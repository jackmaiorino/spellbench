"""One host-owned usage budget shared by the processes of an LLM benchmark.

SQLite transactions reserve requests before sending them. Usage limits include
in-flight reservations; they are local admission limits, not a provider output
cap. A failed or uncertain request stops further admission across all workers.
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

SCHEMA = "spellbench-llm-run-budget/v1"
CONTINUATION_SCHEMA = "spellbench-llm-run-budget/v2"
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


class RunBudget:
    def __init__(self, path: Path, *, model: str, expected_limits: dict | None = None):
        self.path, self.model = Path(path), model
        self.expected_limits = dict(expected_limits or {})
        with self._transaction() as database:
            policy = self._policy(database)
            if policy["model"] != model:
                raise ProviderError("run_budget_model_mismatch")

    @staticmethod
    def create(path: Path, *, model: str, requests: int, tokens: int,
               wall_seconds: int, max_inflight: int = 4) -> None:
        if not isinstance(model, str) or not model.strip():
            raise ValueError("an explicit model is required")
        for name, value in (("requests", requests), ("tokens", tokens),
                            ("wall_seconds", wall_seconds), ("max_inflight", max_inflight)):
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        created = time.time()
        policy = {"schema": SCHEMA, "model": model, "max_requests": requests,
                  "max_reported_tokens": tokens, "deadline": time.time() + wall_seconds,
                  "created_at": created, "max_wall_seconds": wall_seconds,
                  "max_inflight": max_inflight, "provider_output_cap": False,
                  "terminal_error": None}
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
                               expected_limits: dict) -> None:
        """Explicitly continue repaired pre-commit qualification under the original budget.

        The parent's bytes and failed rows stay unchanged. Its exclusive sidecar
        retires that attempt and selects one successor, including concurrent creators.
        An interrupted creation retains its partial evidence; it never resets a budget.
        """
        if (set(expected_limits) != set(LIMIT_NAMES)
                or any(type(value) is not int or value < 1 for value in expected_limits.values())
                or not isinstance(parent_sha256, str) or len(parent_sha256) != 64
                or any(char not in "0123456789abcdef" for char in parent_sha256)):
            raise ValueError("original policy and parent SHA-256 are required")
        parent, path = Path(parent).resolve(strict=True), Path(path).resolve()
        if parent == path:
            raise ValueError("continuation needs a distinct ledger")
        _retained_file(parent)
        previous = RunBudget(parent, model=model, expected_limits=expected_limits)
        with previous._transaction() as database:
            policy = previous._policy(database)
            if database.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
                raise ProviderError("run_budget_parent_unsealed")
            if _digest(parent) != parent_sha256:
                raise ProviderError("run_budget_parent_changed")
            rows = database.execute("SELECT * FROM requests ORDER BY id").fetchall()
            if any(row["status"] == "pending" for row in rows):
                raise ProviderError("run_budget_unresolved_request")
            if not (policy.get("terminal_error") or any(
                    row["status"] == "failed" or row["input_tokens"] is None or row["output_tokens"] is None
                    for row in rows)):
                raise ProviderError("run_budget_parent_not_failed")
            if policy["deadline"] <= time.time():
                raise ProviderError("run_budget_deadline_exhausted")
            inherited = _totals(policy, rows)
            if inherited["requests"] >= policy["max_requests"]:
                raise ProviderError("run_budget_requests_exhausted")
            if (inherited["reported_input_tokens"] + inherited["reported_output_tokens"]
                    + inherited["uncertain_reserved_tokens"] >= policy["max_reported_tokens"]):
                raise ProviderError("run_budget_tokens_exhausted")
            successor = {**policy, "schema": CONTINUATION_SCHEMA, "terminal_error": None,
                         "continuation": {"kind": "precommit-qualification", "parent": str(parent),
                                          "parent_sha256": parent_sha256, "inherited": inherited}}
            path.parent.mkdir(parents=True, exist_ok=True)
            RunBudget._initialize(path, successor)
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
        current = self.path.resolve()
        origin = _origin(current)
        if origin.exists() or value["schema"] == CONTINUATION_SCHEMA:
            recorded = json.loads(origin.read_bytes())
            if (recorded["successor"] != str(current)
                    or recorded["policy"] != {key: item for key, item in value.items() if key != "terminal_error"}):
                raise ProviderError("run_budget_continuation_changed")
        seen = {current}
        child = value
        while child.get("continuation") is not None:
            continuation = child["continuation"]
            if continuation["kind"] != "precommit-qualification":
                raise ValueError("invalid continuation kind")
            parent = Path(continuation["parent"]).resolve(strict=True)
            _retained_file(parent)
            if parent in seen or _digest(parent) != continuation["parent_sha256"]:
                raise ProviderError("run_budget_parent_changed")
            seen.add(parent)
            claim = json.loads(_successor_claim(parent).read_bytes())
            if (claim["successor"] != str(current) or claim["parent_sha256"] != continuation["parent_sha256"]
                    or claim["policy"] != {key: item for key, item in child.items() if key != "terminal_error"}):
                raise ProviderError("run_budget_continuation_changed")
            retained = sqlite3.connect(parent.as_uri() + "?mode=ro", uri=True, timeout=10)
            retained.row_factory = sqlite3.Row
            try:
                retained.execute("BEGIN")
                if retained.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
                    raise ProviderError("run_budget_parent_unsealed")
                prior = json.loads(retained.execute("SELECT json FROM policy WHERE id=1").fetchone()[0])
                self._validate_policy(prior, self.model, self.expected_limits)
                rows = retained.execute("SELECT * FROM requests ORDER BY id").fetchall()
                if any(row["status"] == "pending" for row in rows):
                    raise ProviderError("run_budget_unresolved_request")
                if (any(child[name] != prior[name] for name in (*LIMIT_NAMES, "created_at", "deadline", "provider_output_cap"))
                        or continuation["inherited"] != _totals(prior, rows)):
                    raise ProviderError("run_budget_continuation_changed")
            finally:
                retained.close()
            current, child = parent, prior
        return value

    @staticmethod
    def _validate_policy(value, model, expected_limits):
        if (value["schema"] not in (SCHEMA, CONTINUATION_SCHEMA)
                or (value["schema"] == CONTINUATION_SCHEMA) != ("continuation" in value)
                or (value["schema"] == CONTINUATION_SCHEMA and not isinstance(value["continuation"], dict))):
            raise ValueError("unknown budget schema")
        if value["model"] != model:
            raise ProviderError("run_budget_model_mismatch")
        for name in LIMIT_NAMES:
            if type(value[name]) is not int or value[name] < 1:
                raise ValueError("invalid budget limits")
        if any(value.get(name) != limit for name, limit in expected_limits.items()):
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
        with self._transaction() as database:
            policy = self._policy(database)
            rows = database.execute("SELECT * FROM requests").fetchall()
            if policy.get("terminal_error") or any(row["status"] == "failed" or (
                    row["status"] != "pending" and (row["input_tokens"] is None or row["output_tokens"] is None))
                    for row in rows):
                raise ProviderError("run_budget_already_failed")
            pending = [row for row in rows if row["status"] == "pending"]
            # Allow cleanup time after the request's own timeout. A worker
            # killed in inference leaves uncertain usage, never a free retry.
            if any(time.time() > row["lease_deadline"] for row in pending):
                raise ProviderError("run_budget_unresolved_request")
            remaining = policy["deadline"] - time.time()
            if remaining <= 0:
                raise ProviderError("run_budget_deadline_exhausted")
            totals = _totals(policy, rows)
            if totals["requests"] >= policy["max_requests"]:
                raise ProviderError("run_budget_requests_exhausted")
            if len(pending) >= policy["max_inflight"]:
                raise ProviderError("run_budget_concurrency_exhausted")
            used = totals["reported_input_tokens"] + totals["reported_output_tokens"] + totals["uncertain_reserved_tokens"]
            reserved = sum(row["reserved_tokens"] for row in pending)
            estimate = prompt.bytes + output_tokens
            if used + reserved + estimate > policy["max_reported_tokens"]:
                raise ProviderError("run_budget_tokens_exhausted")
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
            if result is not None:
                if result.model != self.model:
                    error = "run_budget_model_mismatch"
                totals = _totals(policy, database.execute("SELECT * FROM requests").fetchall())
                used = totals["reported_input_tokens"] + totals["reported_output_tokens"] + totals["uncertain_reserved_tokens"]
                if used + sum(counts) > policy["max_reported_tokens"]:
                    error = "run_budget_tokens_exceeded"
                if time.time() >= policy["deadline"]:
                    error = "run_budget_deadline_exhausted"
            database.execute(
                "UPDATE requests SET status=?,input_tokens=?,output_tokens=?,response_id=?,"
                "returned_model=?,elapsed_ms=?,error=? WHERE id=?",
                ("failed" if error else "completed", *counts,
                 None if result is None else result.response_id,
                 None if result is None else result.model, elapsed_ms, error, request),
            )
            return error

    def summary(self) -> dict:
        with self._transaction() as database:
            policy = self._policy(database)
            rows = database.execute("SELECT * FROM requests ORDER BY id").fetchall()
            totals = _totals(policy, rows)
            return {"policy": policy, **totals,
                    "active_failed": sum(row["status"] == "failed" for row in rows),
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
        if (summary["policy"].get("terminal_error") or summary["active_failed"]
                or (summary["active_unknown_usage"] > summary["pending"])):
            raise ProviderError("run_budget_already_failed")
        if summary["expired_pending"] or (summary["pending"] and not allow_pending):
            raise ProviderError("run_budget_unresolved_request")
        if summary["policy"]["deadline"] <= time.time():
            raise ProviderError("run_budget_deadline_exhausted")
        if summary["requests"] >= summary["policy"]["max_requests"]:
            raise ProviderError("run_budget_requests_exhausted")
        if summary["accounted_tokens"] >= summary["policy"]["max_reported_tokens"]:
            raise ProviderError("run_budget_tokens_exhausted")


class BudgetedProvider:
    def __init__(self, provider, budget: RunBudget, *, output_tokens: int = 1024):
        self.provider, self.budget, self.output_tokens = provider, budget, output_tokens

    def complete(self, prompt: Prompt, *, timeout_s: float) -> Completion:
        if type(timeout_s) not in (float, int) or not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ProviderError("timeout")
        deadline = time.monotonic() + timeout_s
        request, remaining = self.budget.reserve(prompt, output_tokens=self.output_tokens, timeout_s=timeout_s)
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
        error = self.budget.finish(request, result=result,
                                   elapsed_ms=max(0, round((time.monotonic() - started) * 1000)), error=error)
        if error is not None:
            raise ProviderError(error)
        return result


def check_hosted_budgets(config, *, allow_pending: bool = False) -> None:
    """The launcher's phase/row check for the maintainer-owned hosted entry.

    A depleted or failed shared run budget aborts the evaluation; it must not
    turn every remaining Luna game into an immediate budget-related forfeit.
    During parallel play other workers can legitimately have pending requests.
    """
    for bot in config.bots:
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

        budget = RunBudget(Path(option("--run-budget")), model=option("--model"), expected_limits={
            "max_requests": int(option("--max-run-requests", 4096)),
            "max_reported_tokens": int(option("--max-run-tokens", 10_000_000)),
            "max_wall_seconds": int(option("--max-run-wall-seconds", 7200)),
            "max_inflight": int(option("--max-inflight", 4)),
        })
        budget.check(allow_pending=allow_pending)


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
    args = parser.parse_args()
    if args.command == "create":
        RunBudget.create(args.path, model=args.model, requests=args.max_requests, tokens=args.max_tokens,
                         wall_seconds=args.max_wall_seconds, max_inflight=args.max_inflight)
    elif args.command == "continue-qualification":
        RunBudget.continue_qualification(args.parent, args.path, model=args.model, parent_sha256=args.parent_sha256,
                                         expected_limits={"max_requests": args.max_requests, "max_reported_tokens": args.max_tokens,
                                                          "max_wall_seconds": args.max_wall_seconds, "max_inflight": args.max_inflight})
    else:
        print(json.dumps(RunBudget(args.path, model=args.model).summary(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
