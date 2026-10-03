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
            retirement = root / self.value["retirement"]
            if any(path.relative_to(root).as_posix() not in self.value["immutable"]
                   for path in (self.snapshot, retirement)):
                raise ValueError("unbound transfer")
            proof = json.loads(retirement.read_bytes())
            if (proof["schema"] != SCHEMA or proof["source_logical"] != self.value["active"]
                    or proof["source_sha256"] != digest(self.snapshot)
                    or proof["destination"] != str(self.active)
                    or proof["host_identity"] != self.value["host_identity"]
                    or proof["host_identity_file"] != self.value["host_identity_file"]
                    or Path(proof["host_identity_file"]).read_text(encoding="utf-8").strip() != proof["host_identity"]):
                raise ValueError("transfer destination changed")
            self.proof = proof
        except (OSError, ValueError, KeyError, TypeError):
            raise ProviderError("run_budget_transfer_changed") from None

    def validate_prefix(self, database, policy: dict) -> None:
        if self.manifest is None:
            return
        from .run_budget import _retained_file, _static_policy_digest
        try:
            _retained_file(self.snapshot)
            with sqlite3.connect(self.snapshot.resolve().as_uri() + "?mode=ro", uri=True) as retained:
                retained.row_factory = sqlite3.Row
                prior = json.loads(retained.execute("SELECT json FROM policy WHERE id=1").fetchone()[0])
                if (retained.execute("PRAGMA journal_mode").fetchone()[0] != "delete"
                        or _static_policy_digest(policy) != _static_policy_digest(prior)
                        or _static_policy_digest(prior) != self.proof["policy_sha256"]):
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
    parser.add_argument("--destination", required=True)
    parser.add_argument("--host-identity-file", required=True)
    parser.add_argument("--host-identity", required=True)
    parser.add_argument("--source-map", type=Path)
    parser.add_argument("--source-map-sha256")
    args = parser.parse_args()
    budget = RunBudget(args.source, model=args.model, path_map=args.source_map,
                       path_map_sha256=args.source_map_sha256)
    manifest = export_budget(budget, args.bundle, destination=args.destination,
                             host_identity_file=args.host_identity_file, host_identity=args.host_identity)
    print(json.dumps({"map": str(manifest), "sha256": digest(manifest), "source_retired": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
