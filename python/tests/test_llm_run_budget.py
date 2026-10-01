"""Real SQLite admission and usage accounting shared across worker processes."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from spellbench.llm.prompt import Prompt
from spellbench.llm.provider import Completion, ProviderError
from spellbench.llm.run_budget import BudgetedProvider, RunBudget

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
