"""One host-owned usage budget shared by the processes of an LLM benchmark.

SQLite transactions reserve requests before sending them. Usage limits include
in-flight reservations; they are local admission limits, not a provider output
cap. Failures stop admission unless a bound policy allows settled timeout
forfeits. Unknown timeout usage keeps its full reservation permanently charged.
The database contains public settings and usage, never account credentials.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from .prompt import Prompt
from .provider import Completion, ProviderError
from .budget_transfer import BudgetPaths

SCHEMA = "spellbench-llm-run-budget/v1"
CONTINUATION_SCHEMA = "spellbench-llm-run-budget/v2"
TIMEOUT_FORFEIT_SCHEMA = "spellbench-llm-run-budget/v3"
SERVICE_FORFEIT_SCHEMA = "spellbench-llm-run-budget/v4"
DEADLINE_EXTENSION_SCHEMA = "spellbench-llm-run-budget-deadline/v1"
LIMIT_INCREASE_SCHEMA = "spellbench-llm-budget-increase/v1"
IDLE_AMENDMENT_SCHEMA = "spellbench-llm-idle-budget-amendment/v1"
ADMISSION_SCOPE_SCHEMA = "spellbench-llm-admission-scope/v1"
STAGE_EXHAUSTED = frozenset(("run_budget_stage_requests_exhausted", "run_budget_stage_tokens_exhausted"))
LIMIT_NAMES = ("max_requests", "max_reported_tokens", "max_wall_seconds", "max_inflight")
INHERITED_NAMES = ("requests", "completed", "failed", "unknown_usage", "reported_input_tokens",
                   "reported_output_tokens", "uncertain_reserved_tokens", "host_failures")


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _successor_claim(path: Path) -> Path:
    return path.with_name(path.name + ".continuation.json")


def _origin(path: Path) -> Path:
    return path.with_name(path.name + ".continuation-origin.json")


def _deadline_extension(path: Path) -> Path:
    return path.with_name(path.name + ".deadline-extension.json")


def _json_digest(value: dict) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _static_policy_digest(policy: dict) -> str:
    return _json_digest({key: value for key, value in policy.items() if key != "terminal_error"})


def _finite_timestamp(value) -> bool:
    try:
        return type(value) in (float, int) and math.isfinite(value)
    except OverflowError:
        return False


def _retained_file(path: Path) -> None:
    # A main-file SHA cannot bind SQLite pages still held in a journal or WAL.
    if any(path.with_name(path.name + suffix).exists() for suffix in ("-journal", "-wal", "-shm")):
        raise ProviderError("run_budget_parent_unsealed")


def _write_marker(path: Path, value: dict) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _totals(policy, rows) -> dict:
    inherited = policy.get("continuation", {}).get("inherited", dict.fromkeys(INHERITED_NAMES, 0))
    if (set(inherited) != set(INHERITED_NAMES)
            or any(type(value) is not int or value < 0 for value in inherited.values())):
        raise ValueError("invalid inherited accounting")
    result = dict(inherited)
    for imported in policy.get("continuation", {}).get("debit_imports", []):
        totals = imported["totals"]
        if (set(totals) != set(INHERITED_NAMES)
                or any(type(value) is not int or value < 0 for value in totals.values())):
            raise ValueError("invalid imported accounting")
        for name in INHERITED_NAMES:
            result[name] += totals[name]
    result["requests"] += len(rows)
    result["completed"] += sum(row["status"] == "completed" for row in rows)
    result["failed"] += sum(row["status"] == "failed" for row in rows)
    result["unknown_usage"] += sum(row["input_tokens"] is None or row["output_tokens"] is None for row in rows)
    result["reported_input_tokens"] += sum(row["input_tokens"] or 0 for row in rows)
    result["reported_output_tokens"] += sum(row["output_tokens"] or 0 for row in rows)
    result["uncertain_reserved_tokens"] += sum(
        row["reserved_tokens"] for row in rows
        if row["status"] != "pending" and (row["input_tokens"] is None or row["output_tokens"] is None))
    result["host_failures"] += int(policy.get("terminal_error") is not None)
    return result


def debit_ancestry_paths(parent: Path, paths: BudgetPaths | None = None) -> list[Path]:
    """The primary chain and its already imported ledgers, without authority/profile contents."""
    result, seen = [], set()
    current = parent.resolve(strict=True)
    while current not in seen:
        seen.add(current)
        result.append(current)
        with sqlite3.connect(current.as_uri() + "?mode=ro", uri=True) as database:
            policy = json.loads(database.execute("SELECT json FROM policy WHERE id=1").fetchone()[0])
        continuation = policy.get("continuation")
        if continuation is None:
            return result
        resolve = paths.resolve if paths else lambda name: Path(name).resolve(strict=True)
        result.extend(resolve(entry["ledger"]) for entry in continuation.get("debit_imports", []))
        current = resolve(continuation["parent"])
    raise ProviderError("run_budget_continuation_changed")


def _request_keys(row) -> set[tuple]:
    keys = {("request", row["started"], row["prompt_sha256"])}
    if row["response_id"] is not None:
        keys.add(("response", row["returned_model"], row["response_id"]))
    return keys


def sealed_debit_imports(paths, *, model: str, forbidden_paths=()) -> list[dict]:
    """Read settled independent, expired/failed ledgers without reopening their allowance."""
    imports, seen, requests = [], set(), set()
    for filename in forbidden_paths:
        path = Path(filename).resolve(strict=True)
        seen.add(_digest(path))
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as database:
            database.row_factory = sqlite3.Row
            for row in database.execute("SELECT * FROM requests"):
                requests.update(_request_keys(row))
    for filename in paths:
        path = Path(filename).resolve(strict=True)
        _retained_file(path)
        # Imports support independent final ledgers only. Ignoring these overlays
        # could import an expired-looking live grant or a retired chain ancestor.
        if any(marker.exists() for marker in
               (_deadline_extension(path), _successor_claim(path), _origin(path))):
            raise ProviderError("run_budget_debit_import_not_independent")
        sha256 = _digest(path)
        if sha256 in seen:
            raise ProviderError("run_budget_duplicate_debit_import")
        seen.add(sha256)
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as database:
            database.row_factory = sqlite3.Row
            if database.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
                raise ProviderError("run_budget_parent_unsealed")
            policy = json.loads(database.execute("SELECT json FROM policy WHERE id=1").fetchone()[0])
            RunBudget._validate_policy(policy, model, {})
            if "continuation" in policy:
                raise ProviderError("run_budget_debit_import_not_independent")
            rows = database.execute("SELECT * FROM requests ORDER BY id").fetchall()
            for row in rows:
                keys = _request_keys(row)
                if requests.intersection(keys):
                    raise ProviderError("run_budget_overlapping_debit_import")
                requests.update(keys)
            if any(row["status"] == "pending" for row in rows):
                raise ProviderError("run_budget_unresolved_request")
            if not policy.get("terminal_error") and policy["deadline"] > time.time():
                raise ProviderError("run_budget_debit_import_still_active")
            totals = _totals(policy, rows)
        if sha256 != _digest(path):
            raise ProviderError("run_budget_debit_import_changed")
        imports.append({"ledger": str(path), "sha256": sha256, "totals": totals})
    return imports


def _timeout_forfeit(policy, row) -> bool:
    return (policy.get("allow_timeout_forfeits", False) is True
            and row["status"] == "failed" and row["error"] == "timeout")


def _http503_forfeit(policy, row) -> bool:
    return (policy.get("allow_http503_forfeits", False) is True
            and row["status"] == "failed" and row["error"] == "http_503")


def _continuation_schema(policy: dict) -> str:
    if policy.get("allow_http503_forfeits", False):
        return SERVICE_FORFEIT_SCHEMA
    return TIMEOUT_FORFEIT_SCHEMA if policy.get("allow_timeout_forfeits", False) else CONTINUATION_SCHEMA


def _terminal_request(policy, row) -> bool:
    if _timeout_forfeit(policy, row) or _http503_forfeit(policy, row):
        return False
    return (row["status"] not in {"pending", "completed"} or (row["status"] != "pending"
            and (row["input_tokens"] is None or row["output_tokens"] is None)))


class RunBudget:
    def __init__(self, path: Path, *, model: str, expected_limits: dict | None = None,
                 path_map: Path | None = None, path_map_sha256: str | None = None,
                 admission_scope: Path | None = None, admission_scope_sha256: str | None = None):
        self.path, self.model = Path(path), model
        self.paths = BudgetPaths(self.path, path_map, path_map_sha256)
        self.expected_limits = dict(expected_limits or {})
        self.admission_scope, self.admission_scope_sha256 = admission_scope, admission_scope_sha256
        if (admission_scope is None) != (admission_scope_sha256 is None):
            raise ProviderError("run_budget_admission_scope_changed")
        with self._transaction() as database:
            policy = self._policy(database)
            if policy["model"] != model:
                raise ProviderError("run_budget_model_mismatch")
            self._admission_limits(policy)

    def _admission_limits(self, policy: dict) -> tuple[int, int]:
        """A hashed stage scope restricts admission without changing cumulative policy."""
        limits = policy["max_requests"], policy["max_reported_tokens"]
        if self.admission_scope is None:
            return limits
        try:
            if self.paths.manifest is None or _digest(self.admission_scope) != self.admission_scope_sha256:
                raise ValueError("scope changed or unmapped budget")
            record = json.loads(self.admission_scope.read_bytes())
            if (set(record) != {"schema", "model", "budget", "budget_map_sha256", "baseline_requests",
                                "baseline_accounted_tokens", "max_additional_requests", "max_additional_tokens",
                                "user_authority"}
                    or record["schema"] != ADMISSION_SCOPE_SCHEMA or record["model"] != self.model
                    or record["budget"] != self.paths.key(self.path)
                    or record["budget_map_sha256"] != self.paths.sha256
                    or any(type(record[name]) is not int or record[name] < 0
                           for name in ("baseline_requests", "baseline_accounted_tokens"))
                    or any(type(record[name]) is not int or record[name] < 1
                           for name in ("max_additional_requests", "max_additional_tokens"))
                    or not isinstance(record["user_authority"], str) or not record["user_authority"].strip()):
                raise ValueError("scope does not bind this mapped stage")
            with sqlite3.connect(self.paths.snapshot.as_uri() + "?mode=ro", uri=True) as retained:
                retained.row_factory = sqlite3.Row
                initial = json.loads(retained.execute("SELECT json FROM policy WHERE id=1").fetchone()[0])
                totals = _totals(initial, retained.execute("SELECT * FROM requests").fetchall())
            tokens = totals["reported_input_tokens"] + totals["reported_output_tokens"] + totals["uncertain_reserved_tokens"]
            if record["baseline_requests"] != totals["requests"] or record["baseline_accounted_tokens"] != tokens:
                raise ValueError("scope baseline is not the immutable initial accounting")
            return (min(limits[0], totals["requests"] + record["max_additional_requests"]),
                    min(limits[1], tokens + record["max_additional_tokens"]))
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
            raise ProviderError("run_budget_admission_scope_changed") from None

    @staticmethod
    def create(path: Path, *, model: str, requests: int, tokens: int,
               wall_seconds: int, max_inflight: int = 4, allow_timeout_forfeits: bool = False,
               allow_http503_forfeits: bool = False) -> None:
        if not isinstance(model, str) or not model.strip():
            raise ValueError("an explicit model is required")
        for name, value in (("requests", requests), ("tokens", tokens),
                            ("wall_seconds", wall_seconds), ("max_inflight", max_inflight)):
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if type(allow_timeout_forfeits) is not bool or type(allow_http503_forfeits) is not bool:
            raise ValueError("availability policy must be boolean")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        created = time.time()
        policy = {"schema": SCHEMA, "model": model, "max_requests": requests,
                  "max_reported_tokens": tokens, "deadline": time.time() + wall_seconds,
                  "created_at": created, "max_wall_seconds": wall_seconds,
                  "max_inflight": max_inflight, "provider_output_cap": False,
                  "terminal_error": None}
        if allow_timeout_forfeits:
            policy.update(schema=TIMEOUT_FORFEIT_SCHEMA, allow_timeout_forfeits=True)
        if allow_http503_forfeits:
            policy.update(schema=SERVICE_FORFEIT_SCHEMA, allow_http503_forfeits=True)
        RunBudget._initialize(path, policy)

    @staticmethod
    def _initialize(path: Path, policy: dict) -> None:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        database = sqlite3.connect(path)
        try:
            database.executescript("""
                CREATE TABLE policy (id INTEGER PRIMARY KEY CHECK(id=1), json TEXT NOT NULL);
                CREATE TABLE requests (
                    id INTEGER PRIMARY KEY, prompt_sha256 TEXT NOT NULL,
                    reserved_tokens INTEGER NOT NULL, started REAL NOT NULL,
                    status TEXT NOT NULL, lease_deadline REAL NOT NULL,
                    input_tokens INTEGER, output_tokens INTEGER,
                    response_id TEXT, returned_model TEXT, elapsed_ms INTEGER, error TEXT
                );
            """)
            database.execute("INSERT INTO policy VALUES (1, ?)", (json.dumps(policy, sort_keys=True),))
            database.commit()
        finally:
            database.close()

    @staticmethod
    def continue_qualification(parent: Path, path: Path, *, model: str, parent_sha256: str,
                               expected_limits: dict, allow_timeout_forfeits: bool = False,
                               extended_wall_seconds: int | None = None) -> None:
        """Explicitly continue repaired pre-commit qualification under the original budget.

        The parent's bytes and failed rows stay unchanged. Its exclusive sidecar
        retires that attempt and selects one successor, including concurrent creators.
        An interrupted creation retains its partial evidence; it never resets a budget.
        An explicitly authorized wall extension uses the original creation time;
        expected_limits still declares the parent's current limits.
        """
        RunBudget._continue_failure(parent, path, model=model, parent_sha256=parent_sha256,
                                    expected_limits=expected_limits, allow_timeout_forfeits=allow_timeout_forfeits,
                                    extended_wall_seconds=extended_wall_seconds)

    @staticmethod
    def continue_failed_run(parent: Path, path: Path, *, model: str, parent_sha256: str,
                            expected_limits: dict, failure_receipt: Path, failure_receipt_sha256: str,
                            allow_timeout_forfeits: bool = False, no_cutoff: bool = False) -> None:
        """Explicit operator recovery, retaining a published abort and cumulative limits.

        This never resumes the aborted commitment or retries a request. A retained
        receipt binds the abort's manifest, parent bytes and effective cutoff.
        Any deadline overlay is retained and copied with a new path binding.
        An explicitly authorized no_cutoff removes only the successor's overall
        deadline; per-request timeouts and all cumulative limits stay intact.
        """
        recovery = {"receipt": str(Path(failure_receipt).resolve(strict=True)),
                    "receipt_sha256": failure_receipt_sha256}
        RunBudget._continue_failure(parent, path, model=model, parent_sha256=parent_sha256,
                                    expected_limits=expected_limits, allow_timeout_forfeits=allow_timeout_forfeits,
                                    recovery=recovery, no_cutoff=no_cutoff)

    @staticmethod
    def _recovery_receipt(recovery: dict, parent: Path, parent_sha256: str, deadline: float | None,
                          paths: BudgetPaths | None = None, *, parent_logical: str | None = None) -> None:
        receipt = paths.resolve(recovery["receipt"]) if paths else Path(recovery["receipt"]).resolve(strict=True)
        if _digest(receipt) != recovery["receipt_sha256"]:
            raise ProviderError("run_budget_recovery_changed")
        value = json.loads(receipt.read_bytes())
        manifest = (paths.resolve(value["retained_run_manifest"]) if paths
                    else Path(value["retained_run_manifest"]).resolve(strict=True))
        publication = json.loads(manifest.read_bytes())
        if (value["schema"] != "spellbench-llm-failed-run-recovery/v1"
                or value["parent"] != (paths.key(parent) if paths else parent_logical or str(parent))
                or value["parent_sha256"] != parent_sha256
                or value["effective_deadline"] != deadline
                or value["purpose"] not in {"provider-diagnostics", "fixed-panel-rerun"}
                or _digest(manifest) != value["retained_run_sha256"]
                or publication.get("schema") != "spellbench-tournament/v2"
                or publication.get("protocol", {}).get("name") != "spellbench/v2"
                or publication.get("run", {}).get("status") != "aborted"
                or publication.get("run", {}).get("rated") is not False):
            raise ProviderError("run_budget_recovery_changed")

    @staticmethod
    def _limit_increase(continuation: dict, parent: Path, prior: dict, child: dict,
                        paths: BudgetPaths | None = None, *, parent_logical: str | None = None) -> dict | None:
        """Validate explicit operator authority for two cumulative caps only."""
        increase = continuation.get("limit_increase")
        if increase is None:
            return None
        try:
            if (continuation["kind"] != "failed-run-recovery"
                    or set(increase) != {"authority", "authority_sha256"}):
                raise ValueError("invalid increase boundary")
            authority = paths.resolve(increase["authority"]) if paths else Path(increase["authority"]).resolve(strict=True)
            if _digest(authority) != increase["authority_sha256"]:
                raise ValueError("authority changed")
            record = json.loads(authority.read_bytes())
            old = {name: prior[name] for name in LIMIT_NAMES}
            new = {name: child[name] for name in LIMIT_NAMES}
            if (set(record) != {"schema", "model", "parent", "parent_sha256", "parent_limits",
                               "approved_limits", "failure_receipt_sha256", "purpose", "user_authority"}
                    or record["schema"] != LIMIT_INCREASE_SCHEMA or record["model"] != child["model"]
                    or record["parent"] != (paths.key(parent) if paths else parent_logical or str(parent))
                    or record["parent_sha256"] != continuation["parent_sha256"]
                    or record["parent_limits"] != old or record["approved_limits"] != new
                    or record["failure_receipt_sha256"] != continuation["recovery"]["receipt_sha256"]
                    or record["purpose"] != "fixed-panel-rerun"
                    or json.loads((paths.resolve(continuation["recovery"]["receipt"]) if paths
                                   else Path(continuation["recovery"]["receipt"])).read_bytes())["purpose"] != "fixed-panel-rerun"
                    or not prior.get("terminal_error")
                    or not isinstance(record["user_authority"], str) or not record["user_authority"].strip()
                    or any(type(value) is not int or value < 1
                           for limits in (record["parent_limits"], record["approved_limits"])
                           for value in limits.values())
                    or any(new[name] != old[name] for name in ("max_inflight", "max_wall_seconds"))
                    or any(new[name] < old[name] for name in ("max_requests", "max_reported_tokens"))
                    or new == old):
                raise ValueError("unauthorized limit change")
            return record
        except (OSError, ValueError, KeyError, TypeError):
            raise ProviderError("run_budget_limit_increase_changed") from None

    @staticmethod
    def _stopped_qualification_receipt(continuation: dict, parent: Path, prior: dict, rows,
                                       child: dict, paths: BudgetPaths | None = None, *, parent_logical: str | None = None) -> None:
        """Bind a real stopped precommit phase, never a fabricated formal abort."""
        try:
            proof = continuation["qualification_recovery"]
            if set(proof) != {"receipt", "receipt_sha256"}:
                raise ValueError("invalid recovery proof")
            resolve = paths.resolve if paths else lambda value: Path(value).resolve(strict=True)
            logical = parent_logical or (paths.key(parent) if paths else str(parent))
            receipt = resolve(proof["receipt"])
            if _digest(receipt) != proof["receipt_sha256"]:
                raise ValueError("changed recovery proof")
            record = json.loads(receipt.read_bytes())
            names = {"schema", "phase", "source", "model", "parent", "parent_sha256",
                     "parent_map", "parent_map_sha256", "completion", "completion_sha256",
                     "dispatch", "dispatch_sha256",
                     "failed_row", "limits", "effective_deadline", "owned_processes_absent",
                     "formal_started", "public_commitment", "allow_http503_forfeits", "user_authority"}
            failed = [row for row in rows if _terminal_request(prior, row)]
            fields = ("id", "status", "error", "reserved_tokens", "input_tokens", "output_tokens")
            completion_path = resolve(record["completion"])
            completion = json.loads(completion_path.read_bytes())
            dispatch_path = resolve(record["dispatch"])
            dispatch = json.loads(dispatch_path.read_bytes())
            totals = _totals(prior, rows)
            if (set(record) != names or record["schema"] != "spellbench-llm-stopped-qualification/v1"
                    or record["phase"] != "precommit-qualification"
                    or not isinstance(record["source"], str) or len(record["source"]) != 40
                    or any(c not in "0123456789abcdef" for c in record["source"])
                    or _digest(dispatch_path) != record["dispatch_sha256"]
                    or dispatch.get("source") != record["source"] or dispatch.get("formal_dispatches") != 0
                    or record["model"] != child["model"]
                    or record["parent"] != logical
                    or record["parent_sha256"] != continuation["parent_sha256"]
                    or _digest(resolve(record["parent_map"])) != record["parent_map_sha256"]
                    or _digest(completion_path) != record["completion_sha256"]
                    or record["limits"] != {name: prior[name] for name in LIMIT_NAMES}
                    or any(child[name] != prior[name] for name in LIMIT_NAMES)
                    or record["effective_deadline"] != RunBudget._effective_deadline_for(parent, prior, logical=logical)
                    or continuation.get("no_cutoff", False) != (record["effective_deadline"] is None)
                    or prior.get("terminal_error") != "hosted_broker_failed"
                    or len(failed) != 1 or failed[0]["status"] != "failed" or failed[0]["error"] != "http_503"
                    or record["failed_row"] != {name: failed[0][name] for name in fields}
                    or any(row["status"] == "pending" for row in rows)
                    or type(completion["exit_code"]) is not int or completion["exit_code"] == 0
                    or completion["formal_dispatches"] != 0
                    or completion["budget_after"].get("pending") != 0
                    or any(completion["budget_after"].get(name) != value for name, value in totals.items())
                    or record["owned_processes_absent"] is not True
                    or record["formal_started"] is not False or record["public_commitment"] is not None
                    or record["allow_http503_forfeits"] is not True or child.get("allow_http503_forfeits") is not True
                    or not isinstance(record["user_authority"], str) or not record["user_authority"].strip()):
                raise ValueError("invalid stopped qualification")
        except (OSError, ValueError, KeyError, TypeError):
            raise ProviderError("run_budget_qualification_recovery_changed") from None

    @staticmethod
    def _idle_amendment(continuation: dict, parent: Path, prior: dict, child: dict,
                        paths: BudgetPaths | None = None, *, parent_logical: str | None = None,
                        parent_paths: BudgetPaths | None = None) -> dict:
        """Bind prospective caps to explicit authority and the unchanged idle parent."""
        try:
            increase = continuation["limit_increase"]
            if set(increase) != {"authority", "authority_sha256"}:
                raise ValueError("invalid amendment boundary")
            authority = paths.resolve(increase["authority"]) if paths else Path(increase["authority"]).resolve(strict=True)
            if _digest(authority) != increase["authority_sha256"]:
                raise ValueError("authority changed")
            record = json.loads(authority.read_bytes())
            old = {name: prior[name] for name in LIMIT_NAMES}
            new = {name: child[name] for name in LIMIT_NAMES}
            imports = continuation.get("debit_imports", [])
            fields = {"schema", "model", "parent", "parent_sha256", "parent_limits",
                      "approved_limits", "no_cutoff", "purpose", "user_authority"}
            if imports:
                fields.add("debit_imports")
                if record.get("debit_imports") != imports:
                    raise ValueError("unapproved debit imports")
                actual = sealed_debit_imports(
                    [paths.resolve(entry["ledger"]) if paths else entry["ledger"] for entry in imports],
                    model=child["model"], forbidden_paths=debit_ancestry_paths(parent, paths or parent_paths))
                for verified in actual:
                    verified["ledger"] = paths.key(Path(verified["ledger"])) if paths else verified["ledger"]
                if actual != imports:
                    raise ValueError("imported ledger changed")
            if (set(record) != fields
                    or record["schema"] != IDLE_AMENDMENT_SCHEMA or record["model"] != child["model"]
                    or record["parent"] != (paths.key(parent) if paths else parent_logical or str(parent))
                    or record["parent_sha256"] != continuation["parent_sha256"]
                    or record["parent_limits"] != old or record["approved_limits"] != new
                    or type(record["no_cutoff"]) is not bool
                    or record["no_cutoff"] != continuation.get("no_cutoff", False)
                    or record["purpose"] != "precommit-evaluation"
                    or not isinstance(record["user_authority"], str) or not record["user_authority"].strip()
                    or prior.get("terminal_error")
                    or any(type(value) is not int or value < 1
                           for limits in (record["parent_limits"], record["approved_limits"])
                           for value in limits.values())
                    or any(new[name] != old[name] for name in ("max_inflight", "max_wall_seconds"))
                    or any(new[name] < old[name] for name in ("max_requests", "max_reported_tokens"))
                    or (new == old and not record["no_cutoff"] and not imports)):
                raise ValueError("unauthorized amendment")
            return record
        except (OSError, ValueError, KeyError, TypeError):
            raise ProviderError("run_budget_idle_amendment_changed") from None

    @staticmethod
    def _continue_failure(parent: Path, path: Path, *, model: str, parent_sha256: str,
                          expected_limits: dict, allow_timeout_forfeits: bool = False,
                          extended_wall_seconds: int | None = None, recovery: dict | None = None,
                          no_cutoff: bool = False) -> None:
        if type(allow_timeout_forfeits) is not bool:
            raise ValueError("allow_timeout_forfeits must be boolean")
        if type(no_cutoff) is not bool or (no_cutoff and recovery is None):
            raise ValueError("no_cutoff requires explicit failed-run recovery")
        if extended_wall_seconds is not None and (type(extended_wall_seconds) is not int or extended_wall_seconds < 1):
            raise ValueError("extended_wall_seconds must be a positive integer")
        if (set(expected_limits) != set(LIMIT_NAMES)
                or any(type(value) is not int or value < 1 for value in expected_limits.values())
                or not isinstance(parent_sha256, str) or len(parent_sha256) != 64
                or any(char not in "0123456789abcdef" for char in parent_sha256)):
            raise ValueError("original policy and parent SHA-256 are required")
        if extended_wall_seconds is not None and extended_wall_seconds <= expected_limits["max_wall_seconds"]:
            raise ValueError("a wall extension must increase the parent's limit")
        parent, path = Path(parent).resolve(strict=True), Path(path).resolve()
        if parent == path:
            raise ValueError("continuation needs a distinct ledger")
        _retained_file(parent)
        if _deadline_extension(parent).exists() and recovery is None:
            raise ProviderError("run_budget_deadline_extension_present")
        previous = RunBudget(parent, model=model, expected_limits=expected_limits)
        with previous._transaction() as database:
            policy = previous._policy(database)
            effective_deadline = previous._effective_deadline(policy)
            if recovery is not None:
                if extended_wall_seconds is not None:
                    raise ValueError("failed-run recovery cannot extend a deadline")
                if policy.get("allow_timeout_forfeits", False) != allow_timeout_forfeits:
                    raise ProviderError("run_budget_limits_mismatch")
                RunBudget._recovery_receipt(recovery, parent, parent_sha256, effective_deadline)
            if database.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
                raise ProviderError("run_budget_parent_unsealed")
            if _digest(parent) != parent_sha256:
                raise ProviderError("run_budget_parent_changed")
            rows = database.execute("SELECT * FROM requests ORDER BY id").fetchall()
            if any(row["status"] == "pending" for row in rows):
                raise ProviderError("run_budget_unresolved_request")
            if policy.get("allow_timeout_forfeits", False) and not allow_timeout_forfeits:
                raise ProviderError("run_budget_limits_mismatch")
            if not (policy.get("terminal_error") or any(_terminal_request(policy, row) for row in rows)):
                raise ProviderError("run_budget_parent_not_failed")
            deadline = policy["deadline"]
            if extended_wall_seconds is not None:
                if extended_wall_seconds <= policy["max_wall_seconds"]:
                    raise ValueError("a wall extension must increase the parent's limit")
                try:
                    deadline = policy["created_at"] + extended_wall_seconds
                except OverflowError:
                    raise ValueError("wall extension deadline must be finite") from None
                if not math.isfinite(deadline) or deadline <= policy["deadline"]:
                    raise ValueError("a wall extension must increase the parent's deadline")
            admission_deadline = effective_deadline if recovery is not None else deadline
            if not no_cutoff and admission_deadline is not None and admission_deadline <= time.time():
                raise ProviderError("run_budget_deadline_exhausted")
            inherited = _totals(policy, rows)
            if inherited["requests"] >= policy["max_requests"]:
                raise ProviderError("run_budget_requests_exhausted")
            if (inherited["reported_input_tokens"] + inherited["reported_output_tokens"]
                    + inherited["uncertain_reserved_tokens"] >= policy["max_reported_tokens"]):
                raise ProviderError("run_budget_tokens_exhausted")
            successor = {**policy, "schema": _continuation_schema({**policy, "allow_timeout_forfeits": allow_timeout_forfeits}),
                         "terminal_error": None,
                         "continuation": {"kind": "precommit-qualification", "parent": str(parent),
                                          "parent_sha256": parent_sha256, "inherited": inherited,
                                          "allow_timeout_forfeits": allow_timeout_forfeits}}
            if allow_timeout_forfeits:
                successor["allow_timeout_forfeits"] = True
            if recovery is not None:
                successor["continuation"].update(kind="failed-run-recovery", recovery=recovery,
                    parent_overlay_sha256=(_digest(_deadline_extension(parent))
                                           if _deadline_extension(parent).exists() else None))
                if no_cutoff or effective_deadline is None:
                    successor["continuation"]["no_cutoff"] = True
            if extended_wall_seconds is not None:
                successor.update(max_wall_seconds=extended_wall_seconds, deadline=deadline)
                successor["continuation"]["wall_extension"] = {
                    "parent_max_wall_seconds": policy["max_wall_seconds"],
                    "parent_deadline": policy["deadline"],
                    "extended_wall_seconds": extended_wall_seconds,
                }
            path.parent.mkdir(parents=True, exist_ok=True)
            RunBudget._initialize(path, successor)
            if recovery is not None and not no_cutoff and effective_deadline is not None and effective_deadline != deadline:
                marker = {"schema": DEADLINE_EXTENSION_SCHEMA, "budget": str(path),
                          "policy_sha256": _static_policy_digest(successor),
                          "original_deadline": deadline, "effective_deadline": effective_deadline}
                marker["sha256"] = _json_digest(marker)
                _write_marker(_deadline_extension(path), marker)
            if _digest(parent) != parent_sha256:
                raise ProviderError("run_budget_parent_changed")
            claim = {"successor": str(path), "parent_sha256": parent_sha256,
                     "policy": {key: value for key, value in successor.items() if key != "terminal_error"}}
            _write_marker(_origin(path), claim)
            _write_marker(_successor_claim(parent), claim)

    @contextmanager
    def _transaction(self):
        database = None
        try:
            if _successor_claim(self.path.resolve()).exists():
                raise ProviderError("run_budget_attempt_continued")
            # mode=rw refuses an absent database; workers cannot create a fresh budget.
            database = sqlite3.connect(self.path.resolve().as_uri() + "?mode=rw", uri=True, timeout=10)
            database.row_factory = sqlite3.Row
            database.execute("BEGIN IMMEDIATE")
            if _successor_claim(self.path.resolve()).exists():
                raise ProviderError("run_budget_attempt_continued")
            self.paths.validate()
            yield database
            database.commit()
        except (sqlite3.Error, OSError, ValueError, KeyError, TypeError):
            raise ProviderError("run_budget_unavailable") from None
        finally:
            if database is not None:
                database.close()

    def _policy(self, database):
        value = json.loads(database.execute("SELECT json FROM policy WHERE id=1").fetchone()[0])
        self._validate_policy(value, self.model, self.expected_limits)
        self.paths.validate_prefix(database, value)
        current = self.path.resolve()
        if self.paths.manifest is not None and current == self.paths.required_ancestor:
            self.paths.validate_transfer_anchor(database, value)
        origin = _origin(current)
        if origin.exists() or "continuation" in value:
            recorded = json.loads(origin.read_bytes())
            if (recorded["successor"] != self.paths.key(current)
                    or recorded["policy"] != {key: item for key, item in value.items() if key != "terminal_error"}):
                raise ProviderError("run_budget_continuation_changed")
        seen = {current}
        child = value
        while child.get("continuation") is not None:
            continuation = child["continuation"]
            if "debit_imports" in continuation and continuation["kind"] != "healthy-idle-amendment":
                raise ProviderError("run_budget_continuation_changed")
            if continuation["kind"] not in {"precommit-qualification", "failed-run-recovery", "host-preflight-recovery", "healthy-idle-amendment", "stopped-qualification-recovery"}:
                raise ValueError("invalid continuation kind")
            no_cutoff = continuation.get("no_cutoff", False)
            if type(no_cutoff) is not bool or (no_cutoff and continuation["kind"] not in {"failed-run-recovery", "host-preflight-recovery", "healthy-idle-amendment", "stopped-qualification-recovery"}):
                raise ProviderError("run_budget_continuation_changed")
            if (type(continuation.get("allow_timeout_forfeits", False)) is not bool
                    or continuation.get("allow_timeout_forfeits", False) != child.get("allow_timeout_forfeits", False)):
                raise ProviderError("run_budget_continuation_changed")
            extension = continuation.get("wall_extension")
            if "wall_extension" in continuation:
                if (not isinstance(extension, dict) or set(extension) != {
                        "parent_max_wall_seconds", "parent_deadline", "extended_wall_seconds"}
                        or any(type(extension[name]) is not int or extension[name] < 1
                               for name in ("parent_max_wall_seconds", "extended_wall_seconds"))
                        or type(extension["parent_deadline"]) not in (int, float)
                        or not math.isfinite(extension["parent_deadline"])):
                    raise ValueError("invalid wall extension")
            parent = self.paths.resolve(continuation["parent"])
            _retained_file(parent)
            recovery = continuation.get("recovery") if continuation["kind"] == "failed-run-recovery" else None
            if continuation["kind"] == "failed-run-recovery" and not isinstance(recovery, dict):
                raise ProviderError("run_budget_recovery_changed")
            if _deadline_extension(parent).exists() and recovery is None:
                raise ProviderError("run_budget_deadline_extension_present")
            if parent in seen or _digest(parent) != continuation["parent_sha256"]:
                raise ProviderError("run_budget_parent_changed")
            seen.add(parent)
            claim = json.loads(_successor_claim(parent).read_bytes())
            if (claim["successor"] != self.paths.key(current) or claim["parent_sha256"] != continuation["parent_sha256"]
                    or claim["policy"] != {key: item for key, item in child.items() if key != "terminal_error"}):
                raise ProviderError("run_budget_continuation_changed")
            retained = sqlite3.connect(parent.as_uri() + "?mode=ro", uri=True, timeout=10)
            retained.row_factory = sqlite3.Row
            try:
                retained.execute("BEGIN")
                if retained.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
                    raise ProviderError("run_budget_parent_unsealed")
                prior = json.loads(retained.execute("SELECT json FROM policy WHERE id=1").fetchone()[0])
                if self.paths.manifest is not None and parent == self.paths.required_ancestor:
                    self.paths.validate_transfer_anchor(retained, prior)
                if recovery is not None:
                    if prior.get("allow_timeout_forfeits", False) != child.get("allow_timeout_forfeits", False):
                        raise ProviderError("run_budget_recovery_changed")
                    if extension is not None:
                        raise ProviderError("run_budget_recovery_changed")
                    overlay = _deadline_extension(parent)
                    if continuation["parent_overlay_sha256"] != (_digest(overlay) if overlay.exists() else None):
                        raise ProviderError("run_budget_recovery_changed")
                    parent_deadline = self._effective_deadline_for(parent, prior, logical=self.paths.key(parent))
                    child_deadline = self._effective_deadline_for(current, child, logical=self.paths.key(current))
                    if child_deadline != (None if no_cutoff else parent_deadline):
                        raise ProviderError("run_budget_recovery_changed")
                    self._recovery_receipt(recovery, parent, continuation["parent_sha256"], parent_deadline, self.paths)
                idle_amendment = continuation["kind"] == "healthy-idle-amendment"
                increase = (self._idle_amendment(continuation, parent, prior, child, self.paths) if idle_amendment
                            else self._limit_increase(continuation, parent, prior, child, self.paths))
                if increase is not None and not idle_amendment and (parent_deadline is not None or child_deadline is not None):
                    raise ProviderError("run_budget_limit_increase_changed")
                # Validate each ancestor against this boundary's retained wall
                # limit, rather than the leaf's prospectively extended limit.
                ancestor_limits = {name: child[name] for name in LIMIT_NAMES}
                if increase is not None:
                    ancestor_limits.update(increase["parent_limits"])
                ancestor_limits["max_wall_seconds"] = (child["max_wall_seconds"] if extension is None
                                                       else extension["parent_max_wall_seconds"])
                self._validate_policy(prior, self.model, ancestor_limits)
                rows = retained.execute("SELECT * FROM requests ORDER BY id").fetchall()
                if continuation["kind"] == "stopped-qualification-recovery":
                    if extension is not None or recovery is not None or increase is not None:
                        raise ProviderError("run_budget_qualification_recovery_changed")
                    self._stopped_qualification_receipt(continuation, parent, prior, rows, child, self.paths)
                elif child.get("allow_http503_forfeits", False) != prior.get("allow_http503_forfeits", False):
                    raise ProviderError("run_budget_continuation_changed")
                if idle_amendment:
                    if (extension is not None or recovery is not None
                            or any(_terminal_request(prior, row) for row in rows)
                            or child.get("allow_timeout_forfeits", False) != prior.get("allow_timeout_forfeits", False)
                            or self._effective_deadline_for(current, child, logical=self.paths.key(current))
                            != (None if no_cutoff else self._effective_deadline_for(parent, prior, logical=self.paths.key(parent)))):
                        raise ProviderError("run_budget_idle_amendment_changed")
                if continuation["kind"] == "host-preflight-recovery":
                    if (rows or prior.get("terminal_error") != "profile_renewal_failed" or extension is not None
                            or child.get("allow_timeout_forfeits", False) != prior.get("allow_timeout_forfeits", False)
                            or self._effective_deadline_for(parent, prior, logical=self.paths.key(parent))
                            != self._effective_deadline_for(current, child, logical=self.paths.key(current))):
                        raise ProviderError("run_budget_continuation_changed")
                if any(row["status"] == "pending" for row in rows):
                    raise ProviderError("run_budget_unresolved_request")
                if (prior.get("allow_timeout_forfeits", False) and not child.get("allow_timeout_forfeits", False)):
                    raise ProviderError("run_budget_continuation_changed")
                if extension is None:
                    wall_matches = child["deadline"] == prior["deadline"]
                else:
                    wall_matches = (extension["parent_deadline"] == prior["deadline"]
                                    and extension["extended_wall_seconds"] == child["max_wall_seconds"]
                                    and child["max_wall_seconds"] > prior["max_wall_seconds"]
                                    and child["deadline"] == prior["created_at"] + child["max_wall_seconds"]
                                    and child["deadline"] > prior["deadline"])
                if (not wall_matches
                        or any(child[name] != prior[name] for name in (*LIMIT_NAMES, "created_at", "provider_output_cap")
                               if name != "max_wall_seconds" and not (increase is not None
                                   and name in {"max_requests", "max_reported_tokens"}))
                        or continuation["inherited"] != _totals(prior, rows)):
                    raise ProviderError("run_budget_continuation_changed")
            finally:
                retained.close()
            current, child = parent, prior
        if self.paths.manifest is not None and self.paths.required_ancestor not in seen:
            raise ProviderError("run_budget_transfer_changed")
        self._effective_deadline(value)
        return value

    def _effective_deadline(self, policy: dict) -> float | None:
        """Validate the host-owned overlay without changing measured policy bytes."""
        return self._effective_deadline_for(self.path.resolve(), policy, logical=self.paths.key(self.path))

    def qualification_origin(self) -> Path:
        """The sealed budget path for the same qualified request configuration.

        Failed-run and host-preflight recovery preserve the request settings.
        Explicit removal of an overall cutoff does not change those settings.
        Precommit continuations can change policy, so traversal stops there.
        The active successor remains the only budget used for admission.
        """
        with self._transaction() as database:
            policy = self._policy(database)  # verifies all ancestor/receipt/overlay bindings
            path = self.path.resolve()
            while (policy.get("continuation", {}).get("kind") in {"failed-run-recovery", "host-preflight-recovery"}
                   and "limit_increase" not in policy["continuation"]):
                path = self.paths.resolve(policy["continuation"]["parent"])
                with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as retained:
                    policy = json.loads(retained.execute("SELECT json FROM policy WHERE id=1").fetchone()[0])
            return path

    @staticmethod
    def _effective_deadline_for(path: Path, policy: dict, *, logical: str | None = None) -> float | None:
        marker = _deadline_extension(path)
        continuation = policy.get("continuation", {})
        no_cutoff = continuation.get("no_cutoff", False)
        if type(no_cutoff) is not bool:
            raise ProviderError("run_budget_continuation_changed")
        if no_cutoff:
            if continuation.get("kind") not in {"failed-run-recovery", "host-preflight-recovery", "healthy-idle-amendment", "stopped-qualification-recovery"} or marker.exists():
                raise ProviderError("run_budget_deadline_extension_conflict")
            return None
        if not marker.exists():
            return policy["deadline"]
        value = json.loads(marker.read_bytes())
        if (not isinstance(value, dict) or set(value) != {
                "schema", "budget", "policy_sha256", "original_deadline", "effective_deadline", "sha256"}
                or value["schema"] != DEADLINE_EXTENSION_SCHEMA
                or value["budget"] != (logical if logical is not None else str(path))
                or value["policy_sha256"] != _static_policy_digest(policy)
                or value["original_deadline"] != policy["deadline"]
                or not _finite_timestamp(value["effective_deadline"])
                or value["effective_deadline"] <= policy["deadline"]
                or value["sha256"] != _json_digest({key: item for key, item in value.items() if key != "sha256"})):
            raise ProviderError("run_budget_deadline_extension_changed")
        return value["effective_deadline"]

    def extend_deadline(self, deadline: float) -> None:
        """Explicitly apply an authorized absolute cutoff between idle phases.

        The single exclusive sidecar changes only the effective deadline. SQLite,
        its static settings and all cumulative accounting remain byte-identical.
        Repeating the same deadline is idempotent; a different overlay refuses.
        """
        if not _finite_timestamp(deadline):
            raise ValueError("an explicit finite absolute deadline is required")
        if self.paths.manifest is not None:
            raise ProviderError("run_budget_transfer_overlay_frozen")
        with self._transaction() as database:
            policy = self._policy(database)
            if self._effective_deadline(policy) is None:
                raise ProviderError("run_budget_deadline_extension_conflict")
            if deadline <= policy["deadline"] or deadline <= time.time():
                raise ProviderError("run_budget_deadline_exhausted")
            rows = database.execute("SELECT * FROM requests").fetchall()
            if any(row["status"] == "pending" for row in rows):
                raise ProviderError("run_budget_unresolved_request")
            if policy.get("terminal_error") or any(_terminal_request(policy, row) for row in rows):
                raise ProviderError("run_budget_already_failed")
            totals = _totals(policy, rows)
            if totals["requests"] >= policy["max_requests"]:
                raise ProviderError("run_budget_requests_exhausted")
            if (totals["reported_input_tokens"] + totals["reported_output_tokens"]
                    + totals["uncertain_reserved_tokens"] >= policy["max_reported_tokens"]):
                raise ProviderError("run_budget_tokens_exhausted")
            marker = _deadline_extension(self.path.resolve())
            if marker.exists():
                if self._effective_deadline(policy) != deadline:
                    raise ProviderError("run_budget_deadline_extension_conflict")
                return
            value = {"schema": DEADLINE_EXTENSION_SCHEMA, "budget": str(self.path.resolve()),
                     "policy_sha256": _static_policy_digest(policy), "original_deadline": policy["deadline"],
                     "effective_deadline": deadline}
            value["sha256"] = _json_digest(value)
            _write_marker(marker, value)

    @staticmethod
    def _validate_policy(value, model, expected_limits):
        allow_timeouts = value.get("allow_timeout_forfeits", False)
        allow_503 = value.get("allow_http503_forfeits", False)
        if (value["schema"] not in (SCHEMA, CONTINUATION_SCHEMA, TIMEOUT_FORFEIT_SCHEMA, SERVICE_FORFEIT_SCHEMA)
                or type(allow_timeouts) is not bool or type(allow_503) is not bool
                or (value["schema"] == SERVICE_FORFEIT_SCHEMA) != allow_503
                or (not allow_503 and (value["schema"] == TIMEOUT_FORFEIT_SCHEMA) != allow_timeouts)
                or (value["schema"] == SCHEMA and "continuation" in value)
                or (value["schema"] == CONTINUATION_SCHEMA and "continuation" not in value)
                or ("continuation" in value and not isinstance(value["continuation"], dict))):
            raise ValueError("unknown budget schema")
        if value["model"] != model:
            raise ProviderError("run_budget_model_mismatch")
        for name in LIMIT_NAMES:
            if type(value[name]) is not int or value[name] < 1:
                raise ValueError("invalid budget limits")
        if any(value.get(name, False if name in {"allow_timeout_forfeits", "allow_http503_forfeits"} else None) != limit
               for name, limit in expected_limits.items()):
            raise ProviderError("run_budget_limits_mismatch")
        if (any(type(value[name]) not in (float, int) or not math.isfinite(value[name])
                for name in ("created_at", "deadline"))
                or not 0 < value["deadline"] - value["created_at"] <= value["max_wall_seconds"] + 1):
            raise ValueError("invalid budget deadline")
        if value.get("provider_output_cap") is not False:
            raise ValueError("invalid provider cap declaration")
        if value.get("terminal_error") is not None and not RunBudget._error_code(value["terminal_error"]):
            raise ValueError("invalid terminal error")

    @staticmethod
    def _error_code(code):
        return (isinstance(code, str) and 0 < len(code) <= 64
                and all(char in "abcdefghijklmnopqrstuvwxyz0123456789_" for char in code))

    def fail(self, code: str) -> None:
        """Stop every worker after a host failure without inventing a request.

        Store only a fixed error category, never provider exception details.
        Existing in-flight requests can still report their actual usage.
        """
        if not self._error_code(code):
            raise ValueError("a fixed error category is required")
        with self._transaction() as database:
            policy = self._policy(database)
            if policy.get("terminal_error") is None:
                policy["terminal_error"] = code
                database.execute("UPDATE policy SET json=? WHERE id=1", (json.dumps(policy, sort_keys=True),))

    def reserve(self, prompt: Prompt, *, output_tokens: int, timeout_s: float = 20) -> tuple[int, float]:
        if type(output_tokens) is not int or output_tokens < 1:
            raise ValueError("output_tokens must be positive")
        if type(timeout_s) not in (float, int) or not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ProviderError("timeout")
        with self._transaction() as database:
            policy = self._policy(database)
            rows = database.execute("SELECT * FROM requests").fetchall()
            if policy.get("terminal_error") or any(_terminal_request(policy, row) for row in rows):
                raise ProviderError("run_budget_already_failed")
            pending = [row for row in rows if row["status"] == "pending"]
            # Allow cleanup time after the request's own timeout. A worker
            # killed in inference leaves uncertain usage, never a free retry.
            if any(time.time() > row["lease_deadline"] for row in pending):
                raise ProviderError("run_budget_unresolved_request")
            cutoff = self._effective_deadline(policy)
            remaining = math.inf if cutoff is None else cutoff - time.time()
            if remaining <= 0:
                raise ProviderError("run_budget_deadline_exhausted")
            totals = _totals(policy, rows)
            request_limit, token_limit = self._admission_limits(policy)
            if totals["requests"] >= request_limit:
                raise ProviderError("run_budget_stage_requests_exhausted" if request_limit < policy["max_requests"]
                                    else "run_budget_requests_exhausted")
            if len(pending) >= policy["max_inflight"]:
                raise ProviderError("run_budget_concurrency_exhausted")
            used = totals["reported_input_tokens"] + totals["reported_output_tokens"] + totals["uncertain_reserved_tokens"]
            reserved = sum(row["reserved_tokens"] for row in pending)
            estimate = prompt.bytes + output_tokens
            if used + reserved + estimate > token_limit:
                raise ProviderError("run_budget_stage_tokens_exhausted" if token_limit < policy["max_reported_tokens"]
                                    else "run_budget_tokens_exhausted")
            cursor = database.execute(
                "INSERT INTO requests (prompt_sha256,reserved_tokens,started,status,lease_deadline) VALUES (?,?,?,?,?)",
                (prompt.sha256, estimate, time.time(), "pending", time.time() + min(timeout_s, remaining) + 60),
            )
            return cursor.lastrowid, remaining

    def finish(self, request: int, *, result: Completion | None, elapsed_ms: int,
               error: str | None = None) -> str | None:
        with self._transaction() as database:
            row = database.execute("SELECT status FROM requests WHERE id=?", (request,)).fetchone()
            if row is None or row["status"] != "pending":
                raise ProviderError("run_budget_request_mismatch")
            policy = self._policy(database)
            counts = (None, None) if result is None else (result.prompt_tokens, result.completion_tokens)
            stage_error = None
            if result is not None:
                if result.model != self.model:
                    error = "run_budget_model_mismatch"
                totals = _totals(policy, database.execute("SELECT * FROM requests").fetchall())
                used = totals["reported_input_tokens"] + totals["reported_output_tokens"] + totals["uncertain_reserved_tokens"]
                if used + sum(counts) > policy["max_reported_tokens"]:
                    error = "run_budget_tokens_exceeded"
                if self.admission_scope is not None:
                    try:
                        _, token_limit = self._admission_limits(policy)
                        if used + sum(counts) > token_limit:
                            stage_error = "run_budget_stage_tokens_exhausted"
                    except ProviderError as exc:
                        stage_error = exc.code
                cutoff = self._effective_deadline(policy)
                if cutoff is not None and time.time() >= cutoff:
                    error = "run_budget_deadline_exhausted"
            database.execute(
                "UPDATE requests SET status=?,input_tokens=?,output_tokens=?,response_id=?,"
                "returned_model=?,elapsed_ms=?,error=? WHERE id=?",
                ("failed" if error else "completed", *counts,
                 None if result is None else result.response_id,
                 None if result is None else result.model, elapsed_ms, error, request),
            )
            # Known provider usage must settle even after a stage boundary.
            # Its request remains completed; the stage refusal is returned to
            # the caller without inventing an active cumulative failure row.
            return error or stage_error

    def summary(self) -> dict:
        with self._transaction() as database:
            policy = self._policy(database)
            rows = database.execute("SELECT * FROM requests ORDER BY id").fetchall()
            totals = _totals(policy, rows)
            return {"policy": policy, **totals,
                    "original_deadline": policy["deadline"], "effective_deadline": self._effective_deadline(policy),
                    "active_failed": sum(row["status"] == "failed" for row in rows),
                    "active_terminal_failures": sum(_terminal_request(policy, row) for row in rows),
                    "active_timeout_forfeits": sum(_timeout_forfeit(policy, row) for row in rows),
                    "active_http503_forfeits": sum(_http503_forfeit(policy, row) for row in rows),
                    "active_unknown_usage": sum(row["input_tokens"] is None or row["output_tokens"] is None for row in rows),
                    "inherited": policy.get("continuation", {}).get("inherited", dict.fromkeys(INHERITED_NAMES, 0)),
                    "pending": sum(row["status"] == "pending" for row in rows),
                    "expired_pending": sum(row["status"] == "pending" and row["lease_deadline"] < time.time()
                                           for row in rows),
                    "accounted_tokens": totals["reported_input_tokens"] + totals["reported_output_tokens"]
                    + totals["uncertain_reserved_tokens"],
                    "pending_reserved_tokens": sum(row["reserved_tokens"] for row in rows if row["status"] == "pending")}

    def check(self, *, allow_pending: bool = False) -> None:
        """Refuse a failed, depleted or unresolved phase without reserving inference."""
        summary = self.summary()
        request_limit, token_limit = self._admission_limits(summary["policy"])
        if summary["policy"].get("terminal_error") or summary["active_terminal_failures"]:
            raise ProviderError("run_budget_already_failed")
        if summary["expired_pending"] or (summary["pending"] and not allow_pending):
            raise ProviderError("run_budget_unresolved_request")
        if summary["effective_deadline"] is not None and summary["effective_deadline"] <= time.time():
            raise ProviderError("run_budget_deadline_exhausted")
        if summary["requests"] >= request_limit:
            raise ProviderError("run_budget_stage_requests_exhausted" if request_limit < summary["policy"]["max_requests"]
                                else "run_budget_requests_exhausted")
        if summary["accounted_tokens"] >= token_limit:
            raise ProviderError("run_budget_stage_tokens_exhausted" if token_limit < summary["policy"]["max_reported_tokens"]
                                else "run_budget_tokens_exhausted")


class BudgetedProvider:
    def __init__(self, provider, budget: RunBudget, *, output_tokens: int = 1024):
        self.provider, self.budget, self.output_tokens = provider, budget, output_tokens
        self._failed = False
        self._settled_error = None
        self._admission_error = None

    @property
    def admission_error(self) -> str | None:
        return self._admission_error

    @property
    def settled_error(self) -> str | None:
        """This instance's failure code, only after its request row was committed."""
        return self._settled_error

    def complete(self, prompt: Prompt, *, timeout_s: float) -> Completion:
        if self._failed:
            raise ProviderError("provider_already_failed")
        if type(timeout_s) not in (float, int) or not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ProviderError("timeout")
        deadline = time.monotonic() + timeout_s
        try:
            request, remaining = self.budget.reserve(prompt, output_tokens=self.output_tokens, timeout_s=timeout_s)
        except ProviderError as exc:
            self._admission_error = exc.code
            raise
        started = time.monotonic()
        result = None
        error = None
        try:
            timeout_s = min(deadline - time.monotonic(), remaining)
            if timeout_s <= 0:
                # No provider request was sent while waiting for admission.
                result = Completion("", self.budget.model, 0, 0)
                raise ProviderError("timeout")
            value = self.provider.complete(prompt, timeout_s=timeout_s)
            if (not isinstance(value, Completion)
                    or any(type(count) is not int or count < 0
                           for count in (value.prompt_tokens, value.completion_tokens))):
                raise ProviderError("invalid_provider_usage")
            result = value
            if result.completion_tokens > self.output_tokens:
                error = "output_token_limit_exceeded"
        except Exception as exc:
            error = exc.code if isinstance(exc, ProviderError) else "provider_internal_error"
        try:
            error = self.budget.finish(request, result=result,
                                       elapsed_ms=max(0, round((time.monotonic() - started) * 1000)), error=error)
        except Exception:
            self._failed = True
            raise
        self._settled_error = error
        if error is not None:
            self._failed = True
            raise ProviderError(error)
        return result


def _hosted_budgets(config):
    for index, bot in enumerate(config.bots):
        command = bot.command
        if not (any(Path(part).name == "llm_hosted_bot.py" for part in command)
                or "spellbench.llm.hosted" in command):
            continue

        def option(name, default=None):
            found = [part.split("=", 1)[1] for part in command if part.startswith(name + "=")]
            found += [command[index + 1] for index, part in enumerate(command[:-1]) if part == name]
            if len(found) > 1:
                raise ProviderError("run_budget_ambiguous_command")
            return found[0] if found else default

        timeout_flags = [part for part in command if part == "--allow-timeout-forfeits"
                         or part.startswith("--allow-timeout-forfeits=")]
        if len(timeout_flags) > 1 or any(part != "--allow-timeout-forfeits" for part in timeout_flags):
            raise ProviderError("run_budget_ambiguous_command")
        service_flags = [part for part in command if part == "--allow-http503-forfeits"
                         or part.startswith("--allow-http503-forfeits=")]
        if len(service_flags) > 1 or any(part != "--allow-http503-forfeits" for part in service_flags):
            raise ProviderError("run_budget_ambiguous_command")

        map_option = option("--run-budget-map")
        scope_option = option("--admission-scope")
        budget = RunBudget(Path(option("--run-budget")), model=option("--model"),
                           path_map=Path(map_option) if map_option else None,
                           admission_scope=Path(scope_option) if scope_option else None,
                           admission_scope_sha256=option("--admission-scope-sha256"),
                           path_map_sha256=option("--run-budget-map-sha256"), expected_limits={
            "max_requests": int(option("--max-run-requests", 4096)),
            "max_reported_tokens": int(option("--max-run-tokens", 10_000_000)),
            "max_wall_seconds": int(option("--max-run-wall-seconds", 7200)),
            "max_inflight": int(option("--max-inflight", 4)),
            "allow_timeout_forfeits": bool(timeout_flags),
            "allow_http503_forfeits": bool(service_flags),
        })
        yield index, budget


def check_hosted_budgets(config, *, allow_pending: bool = False) -> None:
    """Stop the entire evaluation for a failed/depleted hosted budget."""
    for _, budget in _hosted_budgets(config):
        budget.check(allow_pending=allow_pending)


def qualification_config(config) -> dict:
    """Workload identity with only sealed failed-run budget path aliases.

    A recovery ledger preserves the measured request policy. Its pathname
    is bookkeeping, so use the qualification's ancestor path for hashing.
    Every other config value stays hashed, and executed commands stay intact.
    """
    shape = config.to_json()
    for index, budget in _hosted_budgets(config):
        budget.check()
        origin = budget.qualification_origin()
        if origin == budget.path.resolve():
            continue
        command = shape["bots"][index]["command"]
        for position, part in enumerate(command):
            if part.startswith("--run-budget="):
                command[position] = "--run-budget=" + budget.paths.key(origin)
            elif part == "--run-budget":
                command[position + 1] = budget.paths.key(origin)
    return shape


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("path", type=Path)
    create.add_argument("--model", required=True)
    create.add_argument("--max-requests", type=int, required=True)
    create.add_argument("--max-tokens", type=int, required=True)
    create.add_argument("--max-wall-seconds", type=int, required=True)
    create.add_argument("--max-inflight", type=int, default=4)
    create.add_argument("--allow-timeout-forfeits", action="store_true")
    create.add_argument("--allow-http503-forfeits", action="store_true")
    summary = commands.add_parser("summary")
    summary.add_argument("path", type=Path)
    summary.add_argument("--model", required=True)
    continuation = commands.add_parser("continue-qualification", help="explicit repaired pre-commit qualification only")
    continuation.add_argument("parent", type=Path)
    continuation.add_argument("path", type=Path)
    continuation.add_argument("--model", required=True)
    continuation.add_argument("--parent-sha256", required=True)
    continuation.add_argument("--max-requests", type=int, required=True)
    continuation.add_argument("--max-tokens", type=int, required=True)
    continuation.add_argument("--max-wall-seconds", type=int, required=True)
    continuation.add_argument("--max-inflight", type=int, required=True)
    continuation.add_argument("--allow-timeout-forfeits", action="store_true")
    continuation.add_argument("--extended-wall-seconds", type=int,
                              help="explicit authorized extension from the original creation time; other caps remain unchanged")
    extension = commands.add_parser("extend-deadline", help="explicit authorized absolute cutoff between idle phases")
    extension.add_argument("path", type=Path)
    extension.add_argument("--model", required=True)
    extension.add_argument("--deadline", type=float, required=True, help="absolute Unix timestamp; baseline settings stay unchanged")
    extension.add_argument("--max-requests", type=int, required=True)
    extension.add_argument("--max-tokens", type=int, required=True)
    extension.add_argument("--max-wall-seconds", type=int, required=True)
    extension.add_argument("--max-inflight", type=int, required=True)
    args = parser.parse_args()
    if args.command == "create":
        RunBudget.create(args.path, model=args.model, requests=args.max_requests, tokens=args.max_tokens,
                         wall_seconds=args.max_wall_seconds, max_inflight=args.max_inflight,
                         allow_timeout_forfeits=args.allow_timeout_forfeits,
                         allow_http503_forfeits=args.allow_http503_forfeits)
    elif args.command == "continue-qualification":
        RunBudget.continue_qualification(args.parent, args.path, model=args.model, parent_sha256=args.parent_sha256,
                                         allow_timeout_forfeits=args.allow_timeout_forfeits,
                                         extended_wall_seconds=args.extended_wall_seconds,
                                         expected_limits={"max_requests": args.max_requests, "max_reported_tokens": args.max_tokens,
                                                          "max_wall_seconds": args.max_wall_seconds, "max_inflight": args.max_inflight})
    elif args.command == "extend-deadline":
        state = RunBudget(args.path, model=args.model, expected_limits={
            "max_requests": args.max_requests, "max_reported_tokens": args.max_tokens,
            "max_wall_seconds": args.max_wall_seconds, "max_inflight": args.max_inflight})
        state.extend_deadline(args.deadline)
    else:
        print(json.dumps(RunBudget(args.path, model=args.model).summary(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
