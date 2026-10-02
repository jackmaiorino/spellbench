"""Real SQLite admission and usage accounting shared across worker processes."""

from __future__ import annotations

import sqlite3
import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from spellbench.llm.prompt import Prompt
from spellbench.llm.provider import Completion, ProviderError
from spellbench.llm.run_budget import BudgetedProvider, RunBudget, LIMIT_NAMES

PROMPT = Prompt(({"role": "user", "content": "choose"},), "a" * 64, 10)


def budget(tmp_path, **changes):
    path = tmp_path / "run.sqlite3"
    settings = {"model": "luna", "requests": 8, "tokens": 8000, "wall_seconds": 60, **changes}
    RunBudget.create(path, **settings)
    return RunBudget(path, model="luna")


class Provider:
    def __init__(self, result):
        self.result, self.calls = result, 0

    def complete(self, prompt, *, timeout_s):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_workers_cannot_create_reset_or_change_a_budget(tmp_path):
    with pytest.raises(ProviderError, match="run_budget_unavailable"):
        RunBudget(tmp_path / "absent.sqlite3", model="luna")
    state = budget(tmp_path)
    with pytest.raises(FileExistsError):
        RunBudget.create(state.path, model="luna", requests=900, tokens=9000, wall_seconds=900)
    with pytest.raises(ProviderError, match="run_budget_model_mismatch"):
        RunBudget(state.path, model="different-model")


def test_concurrent_connections_reserve_exactly_the_shared_request_limit(tmp_path):
    state = budget(tmp_path, requests=4, tokens=100_000, max_inflight=8)

    def reserve(_):
        try:
            return RunBudget(state.path, model="luna").reserve(PROMPT, output_tokens=1024)[0]
        except ProviderError as exc:
            assert exc.code == "run_budget_requests_exhausted"
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(reserve, range(20)))
    assert sorted(value for value in results if value is not None) == [1, 2, 3, 4]
    assert state.summary()["requests"] == 4


def test_inflight_tokens_and_concurrency_are_admitted_before_the_request(tmp_path):
    state = budget(tmp_path, tokens=1500, max_inflight=2)
    state.reserve(PROMPT, output_tokens=1024)
    with pytest.raises(ProviderError, match="run_budget_tokens_exhausted"):
        state.reserve(PROMPT, output_tokens=1024)


def test_concurrency_limit_is_shared(tmp_path):
    state = budget(tmp_path, max_inflight=1)
    state.reserve(PROMPT, output_tokens=1024)
    with pytest.raises(ProviderError, match="run_budget_concurrency_exhausted"):
        state.reserve(PROMPT, output_tokens=1024)


def test_reported_usage_replaces_reservation_and_is_not_double_counted(tmp_path):
    state = budget(tmp_path, requests=2, tokens=2500)
    provider = Provider(Completion('{"candidate_id":0}', "luna", 100, 20, "response-1"))
    wrapped = BudgetedProvider(provider, state)
    wrapped.complete(PROMPT, timeout_s=2)
    wrapped.complete(PROMPT, timeout_s=2)
    with pytest.raises(ProviderError, match="run_budget_requests_exhausted"):
        wrapped.complete(PROMPT, timeout_s=2)
    summary = state.summary()
    assert provider.calls == summary["completed"] == 2
    assert summary["reported_input_tokens"] == 200 and summary["reported_output_tokens"] == 40
    assert summary["unknown_usage"] == summary["pending"] == summary["failed"] == 0


def test_host_failure_preserves_inflight_usage_and_cannot_be_cleared_by_another_worker(tmp_path):
    state = budget(tmp_path)
    request, _ = state.reserve(PROMPT, output_tokens=1024)
    other = RunBudget(state.path, model="luna")
    other.fail("profile_renewal_failed")
    state.finish(request, result=Completion("choice", "luna", 100, 20), elapsed_ms=1)
    state.fail("later_host_failure")
    summary = RunBudget(state.path, model="luna").summary()
    assert summary["policy"]["terminal_error"] == "profile_renewal_failed"
    assert summary["requests"] == summary["completed"] == 1
    assert summary["reported_input_tokens"] == 100 and summary["reported_output_tokens"] == 20
    assert summary["unknown_usage"] == summary["pending"] == 0
    with pytest.raises(ProviderError, match="run_budget_already_failed"):
        other.reserve(PROMPT, output_tokens=1024)


@pytest.mark.parametrize("result,code,unknown", [
    (ProviderError("transport_error"), "transport_error", 1),
    (RuntimeError("never log this provider detail"), "provider_internal_error", 1),
    (Completion("{}", "luna", None, 1), "invalid_provider_usage", 1),
    (Completion("{}", "other-model", 100, 1), "run_budget_model_mismatch", 0),
    (Completion("{}", "luna", 100, 2048), "output_token_limit_exceeded", 0),
    (Completion("{}", "luna", 3000, 1), "run_budget_tokens_exceeded", 0),
])
def test_failed_request_stops_every_worker_and_preserves_usage(tmp_path, result, code, unknown):
    state = budget(tmp_path, tokens=2500)
    provider = Provider(result)
    with pytest.raises(ProviderError, match=code):
        BudgetedProvider(provider, state).complete(PROMPT, timeout_s=2)
    with pytest.raises(ProviderError, match="run_budget_already_failed"):
        RunBudget(state.path, model="luna").reserve(PROMPT, output_tokens=1024)
    assert state.summary()["unknown_usage"] == unknown
    assert state.summary()["failed"] == provider.calls == 1


def test_a_killed_workers_unresolved_request_stops_admission(tmp_path):
    state = budget(tmp_path)
    request, _ = state.reserve(PROMPT, output_tokens=1024)
    with sqlite3.connect(state.path) as database:
        database.execute("UPDATE requests SET lease_deadline=0 WHERE id=?", (request,))
    with pytest.raises(ProviderError, match="run_budget_unresolved_request"):
        state.reserve(PROMPT, output_tokens=1024)
    assert state.summary()["pending"] == state.summary()["unknown_usage"] == 1


def test_entry_limits_must_match_the_shared_ledger(tmp_path):
    state = budget(tmp_path)
    with pytest.raises(ProviderError, match="run_budget_limits_mismatch"):
        RunBudget(state.path, model="luna", expected_limits={"max_requests": 9})


def test_expired_budget_stops_before_any_provider_request(tmp_path, monkeypatch):
    state = budget(tmp_path)
    import spellbench.llm.run_budget as module
    now = module.time.time()
    monkeypatch.setattr(module.time, "time", lambda: now + 61)
    provider = Provider(Completion("{}", "luna", 1, 1))
    with pytest.raises(ProviderError, match="run_budget_deadline_exhausted"):
        BudgetedProvider(provider, state).complete(PROMPT, timeout_s=2)
    assert provider.calls == 0


def failed_budget(tmp_path, **changes):
    state = budget(tmp_path, **changes)
    BudgetedProvider(Provider(Completion("{}", "luna", 100, 20)), state).complete(PROMPT, timeout_s=2)
    with pytest.raises(ProviderError, match="timeout"):
        BudgetedProvider(Provider(ProviderError("timeout")), state).complete(PROMPT, timeout_s=2)
    return state


def continuation_arguments(state):
    policy = state.summary()["policy"]
    return {"model": "luna", "parent_sha256": hashlib.sha256(state.path.read_bytes()).hexdigest(),
            "expected_limits": {name: policy[name] for name in LIMIT_NAMES}}


def continue_budget(state, path):
    RunBudget.continue_qualification(state.path, path, **continuation_arguments(state))
    return RunBudget(path, model="luna")


def test_continuation_preserves_original_bytes_deadline_failures_and_uncertain_reservation(tmp_path):
    parent = failed_budget(tmp_path)
    original = parent.path.read_bytes()
    policy = parent.summary()["policy"]
    successor = continue_budget(parent, tmp_path / "successor.sqlite3")
    successor.check()
    summary = successor.summary()
    assert summary["requests"] == 2 and summary["completed"] == summary["failed"] == summary["unknown_usage"] == 1
    assert summary["active_failed"] == summary["active_unknown_usage"] == summary["pending"] == 0
    assert summary["reported_input_tokens"] == 100 and summary["reported_output_tokens"] == 20
    assert summary["uncertain_reserved_tokens"] == 1034 and summary["accounted_tokens"] == 1154
    for name in (*LIMIT_NAMES, "created_at", "deadline"):
        assert summary["policy"][name] == policy[name]
    BudgetedProvider(Provider(Completion("{}", "luna", 50, 10)), successor).complete(PROMPT, timeout_s=2)
    assert successor.summary()["requests"] == 3 and successor.summary()["accounted_tokens"] == 1214
    assert parent.path.read_bytes() == original
    with sqlite3.connect(parent.path.as_uri() + "?mode=ro", uri=True) as database:
        assert database.execute("SELECT status,error FROM requests ORDER BY id").fetchall() == [
            ("completed", None), ("failed", "timeout")]
    with pytest.raises(ProviderError, match="run_budget_attempt_continued"):
        parent.reserve(PROMPT, output_tokens=1024)
    with pytest.raises(ProviderError, match="run_budget_attempt_continued"):
        RunBudget(parent.path, model="luna")


@pytest.mark.parametrize("problem,code", [
    ("healthy", "parent_not_failed"), ("pending", "unresolved_request"),
    ("model", "model_mismatch"), ("limits", "limits_mismatch"),
    ("hash", "parent_changed"), ("expired", "deadline_exhausted"),
])
def test_continuation_rejects_unsettled_or_changed_parent_and_wrong_original_policy(tmp_path, monkeypatch, problem, code):
    parent = budget(tmp_path) if problem in {"healthy", "pending"} else failed_budget(tmp_path)
    if problem == "pending":
        parent.reserve(PROMPT, output_tokens=1024)
        parent.fail("profile_renewal_failed")
    arguments = continuation_arguments(parent)
    if problem == "model":
        arguments["model"] = "different-model"
    elif problem == "limits":
        arguments["expected_limits"]["max_requests"] += 1
    elif problem == "hash":
        arguments["parent_sha256"] = "0" * 64
    elif problem == "expired":
        import spellbench.llm.run_budget as module
        now = module.time.time()
        monkeypatch.setattr(module.time, "time", lambda: now + 61)
    with pytest.raises(ProviderError, match=code):
        RunBudget.continue_qualification(parent.path, tmp_path / "refused.sqlite3", **arguments)
    assert not (tmp_path / "refused.sqlite3").exists()


@pytest.mark.parametrize("mutation", ["deadline", "created_at", "max_requests", "model", "offset",
                                      "unknown", "uncertain", "downgrade", "parent", "claim", "origin"])
def test_every_transaction_rejects_continuation_and_retained_parent_tampering(tmp_path, mutation):
    parent = failed_budget(tmp_path)
    child = continue_budget(parent, tmp_path / "child.sqlite3")
    if mutation == "parent":
        with parent.path.open("ab") as stream:
            stream.write(b"changed retained bytes")
    elif mutation == "claim":
        claim = parent.path.with_name(parent.path.name + ".continuation.json")
        data = json.loads(claim.read_bytes())
        data["successor"] = str(tmp_path / "different.sqlite3")
        claim.write_text(json.dumps(data))
    elif mutation == "origin":
        child.path.with_name(child.path.name + ".continuation-origin.json").unlink()
    else:
        with sqlite3.connect(child.path) as database:
            policy = json.loads(database.execute("SELECT json FROM policy WHERE id=1").fetchone()[0])
            if mutation in {"deadline", "created_at", "max_requests"}:
                policy[mutation] += 1
            elif mutation == "model":
                policy["model"] = "another-model"
            elif mutation == "downgrade":
                policy["schema"] = "spellbench-llm-run-budget/v1"
                del policy["continuation"]
            else:
                field = {"offset": "requests", "unknown": "unknown_usage", "uncertain": "uncertain_reserved_tokens"}[mutation]
                policy["continuation"]["inherited"][field] = 0
            database.execute("UPDATE policy SET json=? WHERE id=1", (json.dumps(policy),))
    with pytest.raises(ProviderError):
        child.reserve(PROMPT, output_tokens=1024)


def test_concurrent_creators_select_exactly_one_successor_without_changing_parent(tmp_path):
    parent = failed_budget(tmp_path)
    original = parent.path.read_bytes()
    arguments = continuation_arguments(parent)

    def create(index):
        target = tmp_path / f"child-{index}.sqlite3"
        try:
            RunBudget.continue_qualification(parent.path, target, **arguments)
            return target
        except ProviderError as exc:
            assert exc.code == "run_budget_attempt_continued"
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(create, range(8)))
    children = [path for path in results if path is not None]
    assert len(children) == 1 and len(list(tmp_path.glob("child-*.sqlite3"))) == 1
    assert parent.path.read_bytes() == original
    with pytest.raises(ProviderError, match="run_budget_attempt_continued"):
        RunBudget.continue_qualification(parent.path, tmp_path / "fork.sqlite3", **arguments)
    RunBudget(children[0], model="luna").check()


@pytest.mark.parametrize("suffix", ["-journal", "-wal", "-shm"])
def test_parent_with_unsealed_sqlite_pages_is_refused_without_modifying_original(tmp_path, suffix):
    parent = failed_budget(tmp_path)
    arguments = continuation_arguments(parent)
    original = parent.path.read_bytes()
    parent.path.with_name(parent.path.name + suffix).write_bytes(b"unsealed pages")
    with pytest.raises(ProviderError, match="run_budget_parent_unsealed"):
        RunBudget.continue_qualification(parent.path, tmp_path / "child.sqlite3", **arguments)
    assert parent.path.read_bytes() == original


def test_successor_workers_share_only_the_remaining_original_request_allowance(tmp_path):
    parent = failed_budget(tmp_path, requests=5, tokens=100_000, max_inflight=8)
    child = continue_budget(parent, tmp_path / "child.sqlite3")

    def reserve(_):
        try:
            return RunBudget(child.path, model="luna").reserve(PROMPT, output_tokens=100)[0]
        except ProviderError as exc:
            assert exc.code == "run_budget_requests_exhausted"
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(reserve, range(16)))
    assert sorted(result for result in results if result is not None) == [1, 2, 3]
    assert child.summary()["requests"] == 5


def test_uncertain_parent_reservation_remains_charged_at_admission_and_completion(tmp_path):
    parent = failed_budget(tmp_path, tokens=1300)
    child = continue_budget(parent, tmp_path / "child.sqlite3")
    with pytest.raises(ProviderError, match="run_budget_tokens_exhausted"):
        child.reserve(PROMPT, output_tokens=1000)
    request, _ = child.reserve(PROMPT, output_tokens=100)
    assert child.finish(request, result=Completion("{}", "luna", 200, 0), elapsed_ms=1) == "run_budget_tokens_exceeded"
    assert child.summary()["accounted_tokens"] == 1354
    with pytest.raises(ProviderError, match="run_budget_already_failed"):
        RunBudget(child.path, model="luna").check()


def test_another_failure_stops_successor_workers_and_a_later_attempt_carries_all_ancestors(tmp_path):
    parent = failed_budget(tmp_path)
    child = continue_budget(parent, tmp_path / "child.sqlite3")
    with pytest.raises(ProviderError, match="timeout"):
        BudgetedProvider(Provider(ProviderError("timeout")), child).complete(PROMPT, timeout_s=2)
    with pytest.raises(ProviderError, match="run_budget_already_failed"):
        RunBudget(child.path, model="luna").reserve(PROMPT, output_tokens=1024)
    original_child = child.path.read_bytes()
    grandchild = continue_budget(child, tmp_path / "grandchild.sqlite3")
    summary = grandchild.summary()
    assert summary["requests"] == 3 and summary["failed"] == summary["unknown_usage"] == 2
    assert summary["uncertain_reserved_tokens"] == 2068 and summary["accounted_tokens"] == 2188
    grandchild.check()
    assert child.path.read_bytes() == original_child
    with pytest.raises(ProviderError, match="run_budget_attempt_continued"):
        child.check()


def test_host_only_failure_is_visible_without_inventing_inherited_requests(tmp_path):
    parent = budget(tmp_path)
    parent.fail("profile_renewal_failed")
    child = continue_budget(parent, tmp_path / "child.sqlite3")
    summary = child.summary()
    assert summary["host_failures"] == 1 and summary["requests"] == summary["failed"] == summary["unknown_usage"] == 0
    child.check()


def test_explicit_qualification_continuation_cli_keeps_original_deadline(tmp_path, monkeypatch):
    import spellbench.llm.run_budget as module
    parent = failed_budget(tmp_path)
    arguments = continuation_arguments(parent)
    deadline = parent.summary()["policy"]["deadline"]
    target = tmp_path / "cli.sqlite3"
    monkeypatch.setattr(sys, "argv", ["run_budget", "continue-qualification", str(parent.path), str(target),
                                    "--model", "luna", "--parent-sha256", arguments["parent_sha256"],
                                    "--max-requests", "8", "--max-tokens", "8000",
                                    "--max-wall-seconds", "60", "--max-inflight", "4"])
    assert module.main() == 0
    assert RunBudget(target, model="luna").summary()["policy"]["deadline"] == deadline
