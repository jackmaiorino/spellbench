"""Explicit relocation of a settled host-owned budget, preserving original bytes."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import uuid
from pathlib import Path, PurePosixPath

from .provider import ProviderError

SCHEMA = "spellbench-llm-budget-transfer/v1"
MAP_SCHEMA = "spellbench-llm-budget-map/v1"


def _policy_schema(policy: dict) -> str:
    from .run_budget import _continuation_schema
    return _continuation_schema(policy)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class BudgetPaths:
    """Translate retained logical filenames, never their measured contents.

    The map hash is explicit in the arena command. A relocated mutable leaf
    also retains its original settled row prefix and policy, an immutable
    snapshot, and the source's exclusive retirement claim.
    """

    def __init__(self, active: Path, manifest: Path | None, sha256: str | None):
        self.active = active.resolve()
        self.manifest = manifest
        self.sha256 = sha256
        self.files = {}
        self.reverse = {}
        if (manifest is None) != (sha256 is None):
            raise ProviderError("run_budget_transfer_changed")
        if manifest is not None:
            try:
                self.manifest = manifest.resolve(strict=True)
                if digest(self.manifest) != sha256:
                    raise ValueError("map changed")
                self.value = json.loads(self.manifest.read_bytes())
                if self.value["schema"] != MAP_SCHEMA:
                    raise ValueError("map schema")
                root = self.manifest.parent
                for entry in self.value["files"]:
                    logical, relative = entry["logical"], entry["file"]
                    part = PurePosixPath(relative)
                    if (not logical or not part.parts or part.is_absolute() or ".." in part.parts
                            or "\\" in relative or ":" in relative):
                        raise ValueError("invalid path")
                    physical = (root / relative).resolve(strict=True)
                    if not physical.is_relative_to(root) or logical in self.files or physical in self.reverse:
                        raise ValueError("conflicting path")
                    self.files[logical], self.reverse[physical] = physical, logical
                if self.files[self.value["active"]] != self.active:
                    raise ValueError("active path")
                self.validate()
            except (OSError, ValueError, KeyError, TypeError):
                raise ProviderError("run_budget_transfer_changed") from None

    def resolve(self, logical: str) -> Path:
        if self.manifest is None:
            return Path(logical).resolve(strict=True)
        try:
            return self.files[logical]
        except KeyError:
            raise ProviderError("run_budget_transfer_changed") from None

    def key(self, physical: Path) -> str:
        if self.manifest is None:
            return str(physical.resolve())
        try:
            return self.reverse[physical.resolve()]
        except KeyError:
            raise ProviderError("run_budget_transfer_changed") from None

    def validate(self) -> None:
        if self.manifest is None:
            return
        try:
            if digest(self.manifest) != self.sha256:
                raise ValueError("map changed")
            root = self.manifest.parent
            for relative, sha256 in self.value["immutable"].items():
                part = PurePosixPath(relative)
                path = (root / relative).resolve(strict=True)
                if (part.is_absolute() or ".." in part.parts or "\\" in relative or ":" in relative
                        or not path.is_relative_to(root) or path == self.active or digest(path) != sha256):
                    raise ValueError("retained file changed")
            for physical in self.files.values():
                if physical != self.active and physical.relative_to(root).as_posix() not in self.value["immutable"]:
                    raise ValueError("unbound retained file")
            self.snapshot = root / self.value["snapshot"]
            self.transfer_snapshot = transferred_snapshot = root / self.value.get("transfer_snapshot", self.value["snapshot"])
            retirement = root / self.value["retirement"]
            if any(path.relative_to(root).as_posix() not in self.value["immutable"]
                   for path in (self.snapshot, transferred_snapshot, retirement)):
                raise ValueError("unbound transfer")
            proof = json.loads(retirement.read_bytes())
            if (proof["schema"] != SCHEMA
                    or proof["source_sha256"] != digest(transferred_snapshot)
                    or proof["destination"] != str(self.resolve(proof["source_logical"]))
                    or proof["host_identity"] != self.value["host_identity"]
                    or proof["host_identity_file"] != self.value["host_identity_file"]
                    or Path(proof["host_identity_file"]).read_text(encoding="utf-8").strip() != proof["host_identity"]):
                raise ValueError("transfer destination changed")
            from .run_budget import _static_policy_digest
            with sqlite3.connect(transferred_snapshot.resolve().as_uri() + "?mode=ro", uri=True) as retained:
                original_policy = json.loads(retained.execute("SELECT json FROM policy WHERE id=1").fetchone()[0])
            if _static_policy_digest(original_policy) != proof["policy_sha256"]:
                raise ValueError("transfer policy changed")
            self.required_ancestor = self.resolve(proof["source_logical"])
            if self.required_ancestor != self.active and self.value.get("destination") != str(self.active):
                raise ValueError("successor destination changed")
            self.proof = proof
        except (OSError, ValueError, KeyError, TypeError):
            raise ProviderError("run_budget_transfer_changed") from None

    def validate_prefix(self, database, policy: dict) -> None:
        self._validate_database_prefix(database, policy, self.snapshot if self.manifest is not None else None)

    def validate_transfer_anchor(self, database, policy: dict) -> None:
        self._validate_database_prefix(database, policy, self.transfer_snapshot,
                                       expected_digest=self.proof["policy_sha256"])

    def _validate_database_prefix(self, database, policy: dict, snapshot: Path | None,
                                  *, expected_digest: str | None = None) -> None:
        if self.manifest is None:
            return
        from .run_budget import _retained_file, _static_policy_digest
        try:
            _retained_file(snapshot)
            with sqlite3.connect(snapshot.resolve().as_uri() + "?mode=ro", uri=True) as retained:
                retained.row_factory = sqlite3.Row
                prior = json.loads(retained.execute("SELECT json FROM policy WHERE id=1").fetchone()[0])
                if (retained.execute("PRAGMA journal_mode").fetchone()[0] != "delete"
                        or _static_policy_digest(policy) != _static_policy_digest(prior)
                        or (expected_digest is not None and _static_policy_digest(policy) != expected_digest)):
                    raise ValueError("policy changed")
                rows = retained.execute("SELECT * FROM requests ORDER BY id").fetchall()
            if any(row["status"] == "pending" for row in rows):
                raise ValueError("unsettled source")
            maximum = max((row["id"] for row in rows), default=0)
            current = database.execute("SELECT * FROM requests WHERE id<=? ORDER BY id", (maximum,)).fetchall()
            if [dict(row) for row in current] != [dict(row) for row in rows]:
                raise ValueError("retained requests changed")
        except (sqlite3.Error, OSError, ValueError, KeyError, TypeError):
            raise ProviderError("run_budget_transfer_changed") from None


def continue_host_preflight(budget, successor: Path, manifest: Path) -> Path:
    """Repair an authorization prerequisite before any inference on this leaf.

    Only a mapped, settled, zero-request leaf with the fixed renewal failure
    can continue. The failed parent and original transfer stay retained; the
    successor inherits all accounting and the effective deadline unchanged.
    """
    from .run_budget import (_origin, _successor_claim, _retained_file, _totals,
                             _write_marker, TIMEOUT_FORFEIT_SCHEMA, CONTINUATION_SCHEMA)
    if budget.paths.manifest is None:
        raise ProviderError("run_budget_transfer_required")
    successor, manifest = successor.resolve(), manifest.resolve()
    root = budget.paths.manifest.parent
    if (not successor.is_relative_to(root) or not manifest.is_relative_to(root)
            or successor.exists() or manifest.exists() or successor == manifest):
        raise ValueError("fresh successor and map in the existing bundle required")
    with budget._transaction() as database:
        policy = budget._policy(database)
        rows = database.execute("SELECT * FROM requests ORDER BY id").fetchall()
        _retained_file(budget.path)
        if (rows or policy.get("terminal_error") != "profile_renewal_failed"
                or database.execute("PRAGMA journal_mode").fetchone()[0] != "delete"):
            raise ProviderError("run_budget_parent_not_host_preflight")
        inherited = _totals(policy, rows)
        cutoff = budget._effective_deadline(policy)
        import time
        if cutoff is not None and cutoff <= time.time():
            raise ProviderError("run_budget_deadline_exhausted")
        if (inherited["requests"] >= policy["max_requests"] or inherited["reported_input_tokens"]
                + inherited["reported_output_tokens"] + inherited["uncertain_reserved_tokens"] >= policy["max_reported_tokens"]):
            raise ProviderError("run_budget_exhausted")
        parent_sha = digest(budget.path)
        child = {**policy, "terminal_error": None,
                 "schema": _policy_schema(policy),
                 "continuation": {"kind": "host-preflight-recovery", "parent": budget.paths.key(budget.path),
                                  "parent_sha256": parent_sha, "inherited": inherited,
                                  "allow_timeout_forfeits": policy.get("allow_timeout_forfeits", False)}}
        if cutoff is None:
            child["continuation"]["no_cutoff"] = True
        elif cutoff != policy["deadline"]:
            raise ProviderError("run_budget_deadline_extension_present")
        from .run_budget import RunBudget
        RunBudget._initialize(successor, child)
        claim = {"successor": str(successor), "parent_sha256": parent_sha,
                 "policy": {key: item for key, item in child.items() if key != "terminal_error"}}
        _write_marker(_origin(successor), claim)
        snapshot = successor.with_name(successor.name + ".initial.sqlite3")
        shutil.copyfile(successor, snapshot)
        snapshot.chmod(0o600)
        value = dict(budget.paths.value)
        value["files"] = [*value["files"], {"logical": str(successor), "file": successor.relative_to(root).as_posix()}]
        value["immutable"] = dict(value["immutable"])
        value.update(active=str(successor), destination=str(successor),
                     transfer_snapshot=value.get("transfer_snapshot", value["snapshot"]),
                     snapshot=snapshot.relative_to(root).as_posix())
        for path in (budget.path, _origin(successor), snapshot):
            value["immutable"][path.resolve().relative_to(root).as_posix()] = digest(path)
        # The failed parent can never admit calls, and its exclusive claim also
        # stops any old controller. Publish the new map only after retirement.
        _write_marker(_successor_claim(budget.path), claim)
        value["immutable"][_successor_claim(budget.path).resolve().relative_to(root).as_posix()] = digest(_successor_claim(budget.path))
        _write_marker(manifest, value)
    return manifest


def increase_failed_run_limits(budget, successor: Path, manifest: Path, *,
                               approved_limits: dict, failure_receipt: Path,
                               failure_receipt_sha256: str, authority: Path,
                               authority_sha256: str) -> Path:
    """Explicit approved fresh-panel accounting, never a reset or in-place edit.

    The failed mapped parent remains byte-identical and exclusively retired.
    Receipt and authority paths must already lie within its retained bundle.
    Only cumulative request/token caps can increase; no cutoff is introduced.
    """
    from .run_budget import (RunBudget, LIMIT_NAMES, _origin, _successor_claim,
                             _retained_file, _totals, _write_marker, TIMEOUT_FORFEIT_SCHEMA,
                             CONTINUATION_SCHEMA, _deadline_extension)
    if budget.paths.manifest is None:
        raise ProviderError("run_budget_transfer_required")
    root = budget.paths.manifest.parent
    successor, manifest = successor.resolve(), manifest.resolve()
    failure_receipt, authority = failure_receipt.resolve(strict=True), authority.resolve(strict=True)
    if (not successor.is_relative_to(root) or not manifest.is_relative_to(root)
            or successor.exists() or manifest.exists() or successor == manifest
            or not failure_receipt.is_relative_to(root) or not authority.is_relative_to(root)
            or set(approved_limits) != set(LIMIT_NAMES)
            or any(type(value) is not int or value < 1 for value in approved_limits.values())):
        raise ValueError("fresh mapped paths and explicit positive limits required")
    with budget._transaction() as database:
        policy = budget._policy(database)
        rows = database.execute("SELECT * FROM requests ORDER BY id").fetchall()
        _retained_file(budget.path)
        if any(row["status"] == "pending" for row in rows):
            raise ProviderError("run_budget_unresolved_request")
        if not policy.get("terminal_error") or database.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
            raise ProviderError("run_budget_parent_not_failed")
        cutoff = budget._effective_deadline(policy)
        if cutoff is not None:
            raise ProviderError("run_budget_deadline_extension_present")
        parent_sha = digest(budget.path)
        recovery = {"receipt": str(failure_receipt), "receipt_sha256": failure_receipt_sha256}
        RunBudget._recovery_receipt(recovery, budget.path.resolve(), parent_sha, cutoff,
                                    parent_logical=budget.paths.key(budget.path))
        retained_manifest = Path(json.loads(failure_receipt.read_bytes())["retained_run_manifest"]).resolve(strict=True)
        if not retained_manifest.is_relative_to(root):
            raise ValueError("retained aborted manifest must be inside bundle")
        inherited = _totals(policy, rows)
        child = {**policy, **approved_limits, "terminal_error": None,
                 "schema": _policy_schema(policy),
                 "continuation": {"kind": "failed-run-recovery", "parent": budget.paths.key(budget.path),
                                  "parent_sha256": parent_sha, "inherited": inherited,
                                  "allow_timeout_forfeits": policy.get("allow_timeout_forfeits", False),
                                  "recovery": recovery, "no_cutoff": True,
                                  "parent_overlay_sha256": (digest(_deadline_extension(budget.path))
                                                            if _deadline_extension(budget.path).exists() else None),
                                  "limit_increase": {"authority": str(authority), "authority_sha256": authority_sha256}}}
        RunBudget._limit_increase(child["continuation"], budget.path.resolve(), policy, child,
                                  parent_logical=budget.paths.key(budget.path))
        if (inherited["requests"] >= child["max_requests"] or inherited["reported_input_tokens"]
                + inherited["reported_output_tokens"] + inherited["uncertain_reserved_tokens"] >= child["max_reported_tokens"]):
            raise ProviderError("run_budget_exhausted")
        RunBudget._initialize(successor, child)
        claim = {"successor": str(successor), "parent_sha256": parent_sha,
                 "policy": {key: item for key, item in child.items() if key != "terminal_error"}}
        _write_marker(_origin(successor), claim)
        snapshot = successor.with_name(successor.name + ".initial.sqlite3")
        shutil.copyfile(successor, snapshot)
        snapshot.chmod(0o600)
        value = dict(budget.paths.value)
        value["files"] = list(value["files"])
        value["immutable"] = dict(value["immutable"])
        for path in (successor, failure_receipt, retained_manifest, authority):
            if str(path) not in budget.paths.files:
                value["files"].append({"logical": str(path), "file": path.relative_to(root).as_posix()})
        value.update(active=str(successor), destination=str(successor),
                     transfer_snapshot=value.get("transfer_snapshot", value["snapshot"]),
                     snapshot=snapshot.relative_to(root).as_posix())
        for path in (budget.path, _origin(successor), snapshot, failure_receipt, retained_manifest, authority):
            value["immutable"][path.resolve().relative_to(root).as_posix()] = digest(path)
        # An interrupted retirement leaves a non-admitting parent and no new map.
        _write_marker(_successor_claim(budget.path), claim)
        value["immutable"][_successor_claim(budget.path).resolve().relative_to(root).as_posix()] = digest(_successor_claim(budget.path))
        _write_marker(manifest, value)
    return manifest


def amend_idle_budget(budget, successor: Path, manifest: Path, *, approved_limits: dict,
                      authority: Path, authority_sha256: str, no_cutoff: bool = False) -> Path:
    """Prospective operator amendment between phases, retaining every prior debit.

    The caller stops all source controllers first. The SQLite admission lock and
    exclusive claim select one successor; no parent bytes or failure are changed.
    The authority must be retained inside the mapped bundle. Only cumulative
    request/token limits and an explicitly approved overall cutoff may change.
    """
    from .run_budget import (RunBudget, LIMIT_NAMES, _origin, _successor_claim, _retained_file,
                             _totals, _terminal_request, _write_marker, TIMEOUT_FORFEIT_SCHEMA,
                             CONTINUATION_SCHEMA, _deadline_extension)
    if budget.paths.manifest is None:
        raise ProviderError("run_budget_transfer_required")
    root = budget.paths.manifest.parent
    successor, manifest = successor.resolve(), manifest.resolve()
    authority = authority.resolve(strict=True)
    snapshot = successor.with_name(successor.name + ".initial.sqlite3")
    outputs = (successor, manifest, _origin(successor), snapshot)
    if (len(set(outputs)) != len(outputs)
            or any(not path.is_relative_to(root) or path.exists() for path in outputs)
            or not authority.is_relative_to(root) or type(no_cutoff) is not bool
            or set(approved_limits) != set(LIMIT_NAMES)
            or any(type(value) is not int or value < 1 for value in approved_limits.values())):
        raise ValueError("fresh mapped paths and explicit positive limits required")
    with budget._transaction() as database:
        policy = budget._policy(database)
        rows = database.execute("SELECT * FROM requests ORDER BY id").fetchall()
        _retained_file(budget.path)
        if any(row["status"] == "pending" for row in rows):
            raise ProviderError("run_budget_unresolved_request")
        if policy.get("terminal_error") or any(_terminal_request(policy, row) for row in rows):
            raise ProviderError("run_budget_already_failed")
        if database.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
            raise ProviderError("run_budget_parent_unsealed")
        if _deadline_extension(budget.path).exists():
            raise ProviderError("run_budget_deadline_extension_present")
        cutoff = budget._effective_deadline(policy)
        import time
        if not no_cutoff and cutoff is not None and cutoff <= time.time():
            raise ProviderError("run_budget_deadline_exhausted")
        inherited, parent_sha = _totals(policy, rows), digest(budget.path)
        child = {**policy, **approved_limits,
                 "schema": _policy_schema(policy),
                 "continuation": {"kind": "healthy-idle-amendment", "parent": budget.paths.key(budget.path),
                                  "parent_sha256": parent_sha, "inherited": inherited,
                                  "allow_timeout_forfeits": policy.get("allow_timeout_forfeits", False),
                                  "no_cutoff": no_cutoff,
                                  "limit_increase": {"authority": str(authority), "authority_sha256": authority_sha256}}}
        RunBudget._idle_amendment(child["continuation"], budget.path.resolve(), policy, child,
                                  parent_logical=budget.paths.key(budget.path))
        if (inherited["requests"] >= child["max_requests"] or inherited["reported_input_tokens"]
                + inherited["reported_output_tokens"] + inherited["uncertain_reserved_tokens"] >= child["max_reported_tokens"]):
            raise ProviderError("run_budget_exhausted")
        RunBudget._initialize(successor, child)
        claim = {"successor": str(successor), "parent_sha256": parent_sha,
                 "policy": {key: item for key, item in child.items() if key != "terminal_error"}}
        _write_marker(_origin(successor), claim)
        # Exclusive creation also refuses a collision arriving after preflight.
        with successor.open("rb") as source, snapshot.open("xb") as target:
            shutil.copyfileobj(source, target)
            target.flush()
            import os
            os.fsync(target.fileno())
        snapshot.chmod(0o600)
        value = dict(budget.paths.value)
        value["files"], value["immutable"] = list(value["files"]), dict(value["immutable"])
        for path in (successor, authority):
            if str(path) not in budget.paths.files:
                value["files"].append({"logical": str(path), "file": path.relative_to(root).as_posix()})
        value.update(active=str(successor), destination=str(successor),
                     transfer_snapshot=value.get("transfer_snapshot", value["snapshot"]),
                     snapshot=snapshot.relative_to(root).as_posix())
        for path in (budget.path, _origin(successor), snapshot, authority):
            value["immutable"][path.resolve().relative_to(root).as_posix()] = digest(path)
        # Publish activation only after the durable retirement of the old writer.
        _write_marker(_successor_claim(budget.path), claim)
        value["immutable"][_successor_claim(budget.path).resolve().relative_to(root).as_posix()] = digest(_successor_claim(budget.path))
        _write_marker(manifest, value)
    return manifest


def continue_stopped_qualification(budget, successor: Path, manifest: Path, *,
                                  receipt: Path, receipt_sha256: str) -> Path:
    """Recover one stopped precommit HTTP503 attempt with unchanged cumulative caps.

    The operator must stop and preserve the old job first. This creates only a
    fresh qualification budget, never resumes its game or resets any charge.
    """
    from .run_budget import (RunBudget, _origin, _successor_claim, _retained_file,
                             _totals, _write_marker, SERVICE_FORFEIT_SCHEMA, _deadline_extension)
    if budget.paths.manifest is None:
        raise ProviderError("run_budget_transfer_required")
    root = budget.paths.manifest.parent
    successor, manifest, receipt = successor.resolve(), manifest.resolve(), receipt.resolve(strict=True)
    snapshot = successor.with_name(successor.name + ".initial.sqlite3")
    outputs = (successor, manifest, _origin(successor), snapshot)
    record = json.loads(receipt.read_bytes())
    retained = (receipt, Path(record["completion"]).resolve(strict=True),
                Path(record["dispatch"]).resolve(strict=True), budget.paths.manifest)
    if (len(set(outputs)) != len(outputs) or any(not path.is_relative_to(root) or path.exists() for path in outputs)
            or any(not path.is_relative_to(root) for path in retained)):
        raise ValueError("fresh distinct outputs and retained actual qualification evidence required")
    if (record["parent_map"] != str(budget.paths.manifest)
            or record["parent_map_sha256"] != budget.paths.sha256):
        raise ProviderError("run_budget_qualification_recovery_changed")
    with budget._transaction() as database:
        policy = budget._policy(database)
        rows = database.execute("SELECT * FROM requests ORDER BY id").fetchall()
        _retained_file(budget.path)
        if database.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
            raise ProviderError("run_budget_parent_unsealed")
        if _deadline_extension(budget.path).exists():
            raise ProviderError("run_budget_deadline_extension_present")
        inherited, parent_sha = _totals(policy, rows), digest(budget.path)
        cutoff = budget._effective_deadline(policy)
        import time
        if cutoff is not None and cutoff <= time.time():
            raise ProviderError("run_budget_deadline_exhausted")
        child = {**policy, "schema": SERVICE_FORFEIT_SCHEMA, "terminal_error": None,
                 "allow_http503_forfeits": True,
                 "continuation": {"kind": "stopped-qualification-recovery", "parent": budget.paths.key(budget.path),
                                  "parent_sha256": parent_sha, "inherited": inherited,
                                  "allow_timeout_forfeits": policy.get("allow_timeout_forfeits", False),
                                  "no_cutoff": cutoff is None,
                                  "qualification_recovery": {"receipt": str(receipt), "receipt_sha256": receipt_sha256}}}
        RunBudget._stopped_qualification_receipt(child["continuation"], budget.path.resolve(), policy, rows, child,
                                               parent_logical=budget.paths.key(budget.path))
        if (inherited["requests"] >= child["max_requests"] or inherited["reported_input_tokens"]
                + inherited["reported_output_tokens"] + inherited["uncertain_reserved_tokens"] >= child["max_reported_tokens"]):
            raise ProviderError("run_budget_exhausted")
        RunBudget._initialize(successor, child)
        claim = {"successor": str(successor), "parent_sha256": parent_sha,
                 "policy": {key: item for key, item in child.items() if key != "terminal_error"}}
        _write_marker(_origin(successor), claim)
        with successor.open("rb") as source, snapshot.open("xb") as target:
            shutil.copyfileobj(source, target)
            target.flush()
            import os
            os.fsync(target.fileno())
        snapshot.chmod(0o600)
        value = dict(budget.paths.value)
        value["files"], value["immutable"] = list(value["files"]), dict(value["immutable"])
        for path in (successor, *retained):
            if str(path) not in budget.paths.files:
                value["files"].append({"logical": str(path), "file": path.relative_to(root).as_posix()})
        value.update(active=str(successor), destination=str(successor),
                     transfer_snapshot=value.get("transfer_snapshot", value["snapshot"]),
                     snapshot=snapshot.relative_to(root).as_posix())
        for path in (budget.path, _origin(successor), snapshot, *retained):
            value["immutable"][path.resolve().relative_to(root).as_posix()] = digest(path)
        _write_marker(_successor_claim(budget.path), claim)
        value["immutable"][_successor_claim(budget.path).resolve().relative_to(root).as_posix()] = digest(_successor_claim(budget.path))
        _write_marker(manifest, value)
    return manifest


def export_budget(budget, bundle: Path, *, destination: str, host_identity_file: str,
                  host_identity: str) -> Path:
    """Retire an idle source and produce one bound destination bundle.

    Stop the source launcher before calling this. Concurrent reservations and
    exports are serialized by its existing SQLite lock. An interruption after
    the exclusive claim leaves source admission stopped, with retained files
    available for completing that same transfer.
    """
    from .run_budget import (_origin, _successor_claim, _deadline_extension,
                             _retained_file, _static_policy_digest, _terminal_request,
                             _totals, _write_marker)
    if not all(isinstance(value, str) and value.strip()
               for value in (destination, host_identity_file, host_identity)):
        raise ValueError("explicit destination and host identity required")
    if destination == str(budget.path.resolve()):
        raise ValueError("transfer needs a distinct destination")
    budget.check()
    bundle = bundle.resolve()
    bundle.mkdir(mode=0o700)  # Never replace a prior transfer's files.
    files, immutable = [], {}
    with budget._transaction() as database:
        policy = budget._policy(database)
        rows = database.execute("SELECT * FROM requests ORDER BY id").fetchall()
        if any(row["status"] == "pending" for row in rows):
            raise ProviderError("run_budget_unresolved_request")
        if policy.get("terminal_error") or any(_terminal_request(policy, row) for row in rows):
            raise ProviderError("run_budget_already_failed")
        totals = _totals(policy, rows)
        cutoff = budget._effective_deadline(policy)
        import time
        if cutoff is not None and cutoff <= time.time():
            raise ProviderError("run_budget_deadline_exhausted")
        if (totals["requests"] >= policy["max_requests"] or totals["reported_input_tokens"]
                + totals["reported_output_tokens"] + totals["uncertain_reserved_tokens"] >= policy["max_reported_tokens"]):
            raise ProviderError("run_budget_exhausted")
        if database.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
            raise ProviderError("run_budget_parent_unsealed")

        copied = set()
        def copy(path, relative, *, mutable=False, logical=None):
            path = path.resolve(strict=True)
            if path in copied:
                return
            copied.add(path)
            target = bundle / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            target.chmod(0o600)
            files.append({"logical": logical or budget.paths.key(path), "file": relative})
            if not mutable:
                immutable[relative] = digest(target)

        current, child, index = budget.path.resolve(), policy, 0
        while True:
            _retained_file(current)
            relative = "active.sqlite3" if index == 0 else f"retained/{index}/budget.sqlite3"
            logical = budget.paths.key(current)
            copy(current, relative, mutable=index == 0)
            for marker in (_origin(current), _deadline_extension(current)):
                if marker.exists():
                    copy(marker, relative + marker.name[len(current.name):],
                         logical=logical + marker.name[len(current.name):])
            if index:
                copy(_successor_claim(current), relative + ".continuation.json",
                     logical=logical + ".continuation.json")
            continuation = child.get("continuation")
            if continuation is None:
                break
            recovery = continuation.get("recovery")
            if recovery is not None:
                receipt = budget.paths.resolve(recovery["receipt"])
                copy(receipt, f"retained/{index}/recovery.json")
                publication = json.loads(receipt.read_bytes())
                copy(budget.paths.resolve(publication["retained_run_manifest"]),
                     f"retained/{index}/aborted-manifest.json")
            qualification = continuation.get("qualification_recovery")
            if qualification is not None:
                receipt = budget.paths.resolve(qualification["receipt"])
                copy(receipt, f"retained/{index}/qualification-recovery.json")
                stopped = json.loads(receipt.read_bytes())
                copy(budget.paths.resolve(stopped["completion"]), f"retained/{index}/qualification-completion.json")
                copy(budget.paths.resolve(stopped["dispatch"]), f"retained/{index}/qualification-dispatch.json")
                copy(budget.paths.resolve(stopped["parent_map"]), f"retained/{index}/qualification-parent-map.json")
            increase = continuation.get("limit_increase")
            if increase is not None:
                copy(budget.paths.resolve(increase["authority"]), f"retained/{index}/authority.json")
            current = budget.paths.resolve(continuation["parent"])
            with sqlite3.connect(current.as_uri() + "?mode=ro", uri=True) as retained:
                child = json.loads(retained.execute("SELECT json FROM policy WHERE id=1").fetchone()[0])
            index += 1
        snapshot = bundle / "initial.sqlite3"
        shutil.copyfile(bundle / "active.sqlite3", snapshot)
        snapshot.chmod(0o600)
        immutable["initial.sqlite3"] = digest(snapshot)
        proof = {"schema": SCHEMA, "transfer_id": uuid.uuid4().hex,
                 "source": str(budget.path.resolve()), "source_logical": budget.paths.key(budget.path),
                 "source_sha256": digest(snapshot), "destination": destination,
                 "host_identity_file": host_identity_file, "host_identity": host_identity,
                 "policy_sha256": _static_policy_digest(policy)}
        _write_marker(bundle / "source-retirement.json", proof)
        immutable["source-retirement.json"] = digest(bundle / "source-retirement.json")
        value = {"schema": MAP_SCHEMA, "active": proof["source_logical"], "files": files,
                 "immutable": immutable, "snapshot": "initial.sqlite3", "retirement": "source-retirement.json",
                 "host_identity_file": host_identity_file, "host_identity": host_identity}
        # Retire first. A prepared proof is not activation authority: publishing
        # the map before this exclusive claim would permit two active copies
        # if the final source write failed.
        _write_marker(_successor_claim(budget.path.resolve()), proof)
        _write_marker(bundle / "map.json", value)
    return bundle / "map.json"


def main() -> int:
    from .run_budget import RunBudget
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--destination")
    parser.add_argument("--host-identity-file")
    parser.add_argument("--host-identity")
    parser.add_argument("--continue-host-preflight", action="store_true")
    parser.add_argument("--successor", type=Path)
    parser.add_argument("--source-map", type=Path)
    parser.add_argument("--source-map-sha256")
    args = parser.parse_args()
    budget = RunBudget(args.source, model=args.model, path_map=args.source_map,
                       path_map_sha256=args.source_map_sha256)
    if args.continue_host_preflight:
        if args.successor is None:
            parser.error("--continue-host-preflight requires --successor")
        manifest = continue_host_preflight(budget, args.successor, args.bundle)
    else:
        manifest = export_budget(budget, args.bundle, destination=args.destination,
                                 host_identity_file=args.host_identity_file, host_identity=args.host_identity)
    print(json.dumps({"map": str(manifest), "sha256": digest(manifest), "source_retired": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
