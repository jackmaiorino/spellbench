"""A stage's relative admission ceiling shares the cumulative ledger lock."""
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from spellbench.arena.config import BotSpec
from spellbench.llm.budget_transfer import digest
from spellbench.llm.provider import Completion, ProviderError
from spellbench.llm.run_budget import (ADMISSION_SCOPE_SCHEMA, BudgetedProvider, RunBudget,
                                      check_hosted_budgets)
from test_llm_budget_transfer import transfer
from test_llm_run_budget import PROMPT, Provider, budget


def setup(tmp_path, *, requests=2, tokens=60):
    original = budget(tmp_path / "before", requests=20, tokens=10_000, allow_timeout_forfeits=True)
    request, _ = original.reserve(PROMPT, output_tokens=20)
    original.finish(request, result=Completion("{}", original.model, 10, 2), elapsed_ms=1)
    source = transfer(tmp_path, original)
    record = {"schema": ADMISSION_SCOPE_SCHEMA, "model": source.model,
              "budget": source.paths.key(source.path), "budget_map_sha256": source.paths.sha256,
              "baseline_requests": 1, "baseline_accounted_tokens": 12,
              "max_additional_requests": requests, "max_additional_tokens": tokens,
              "user_authority": "Authorize this bounded stage, retaining all historical charges"}
    scope = source.path.parent / "stage-scope.json"
    scope.write_text(json.dumps(record), encoding="utf-8")
    return source, scope


def scoped(source, scope):
    return RunBudget(source.path, model=source.model, path_map=source.paths.manifest,
                     path_map_sha256=source.paths.sha256,
                     admission_scope=scope, admission_scope_sha256=digest(scope))


def test_concurrent_brokers_cannot_exceed_stage_request_ceiling(tmp_path):
    source, scope = setup(tmp_path)
    before = source.summary()
    def work(_):
        state = scoped(source, scope)
        provider = BudgetedProvider(Provider(Completion("{}", state.model, 10, 2)), state, output_tokens=20)
        try:
            provider.complete(PROMPT, timeout_s=20)
            return "completed"
        except ProviderError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(work, range(8)))
    assert results.count("completed") == 2
    assert results.count("run_budget_stage_requests_exhausted") == 6
    after = source.summary()
    assert after["requests"] == 3 and after["accounted_tokens"] == 36 and after["pending"] == 0
    assert after["policy"] == before["policy"] and after["policy"]["terminal_error"] is None
    source.check()
    with pytest.raises(ProviderError, match="run_budget_stage_requests_exhausted"):
        scoped(source, scope).check()


def test_pending_full_reservations_and_unknown_usage_consume_stage_tokens(tmp_path):
    source, scope = setup(tmp_path, tokens=50)
    first = scoped(source, scope)
    request, _ = first.reserve(PROMPT, output_tokens=20)
    other = scoped(source, scope)
    with pytest.raises(ProviderError, match="run_budget_stage_tokens_exhausted"):
        other.reserve(PROMPT, output_tokens=20)
    first.finish(request, result=None, elapsed_ms=1, error="timeout")
    summary = source.summary()
    assert summary["requests"] == 2 and summary["unknown_usage"] == 1
    assert summary["accounted_tokens"] == 42 and summary["uncertain_reserved_tokens"] == 30
    with pytest.raises(ProviderError, match="run_budget_stage_tokens_exhausted"):
        other.reserve(PROMPT, output_tokens=20)
    assert source.summary()["policy"]["terminal_error"] is None
    source.check()


def test_concurrent_token_reservations_survive_broker_restart(tmp_path):
    source, scope = setup(tmp_path, requests=8, tokens=60)
    def work(_):
        try:
            return scoped(source, scope).reserve(PROMPT, output_tokens=20)[0]
        except ProviderError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(work, range(8)))
    admitted = [value for value in results if type(value) is int]
    assert len(admitted) == 2 and results.count("run_budget_stage_tokens_exhausted") == 6
    restarted = scoped(source, scope)
    assert source.summary()["pending_reserved_tokens"] == 60
    with pytest.raises(ProviderError, match="run_budget_stage_tokens_exhausted"):
        restarted.reserve(PROMPT, output_tokens=20)
    for request in admitted:
        restarted.finish(request, result=Completion("{}", source.model, 24, 2), elapsed_ms=1)
    assert source.summary()["accounted_tokens"] == 64 and source.summary()["pending"] == 0
    with pytest.raises(ProviderError, match="run_budget_stage_tokens_exhausted"):
        scoped(source, scope).reserve(PROMPT, output_tokens=20)
    source.check()


def test_scope_exhaustion_sends_no_provider_request_and_preserves_broad_allowance(tmp_path):
    source, scope = setup(tmp_path, tokens=20)
    delegate = Provider(Completion("{}", source.model, 10, 2))
    provider = BudgetedProvider(delegate, scoped(source, scope), output_tokens=20)
    with pytest.raises(ProviderError, match="run_budget_stage_tokens_exhausted"):
        provider.complete(PROMPT, timeout_s=20)
    assert delegate.calls == 0 and provider.admission_error == "run_budget_stage_tokens_exhausted"
    assert source.summary()["requests"] == 1 and source.summary()["pending"] == 0
    source.check()


@pytest.mark.parametrize("field,value", [
    ("model", "other"), ("budget", "other.sqlite3"), ("budget_map_sha256", "0" * 64),
    ("baseline_requests", 0), ("baseline_accounted_tokens", 11),
    ("max_additional_requests", True), ("max_additional_tokens", 0), ("user_authority", ""),
])
def test_scope_must_bind_actual_initial_accounting_and_exact_stage(tmp_path, field, value):
    source, scope = setup(tmp_path)
    record = json.loads(scope.read_bytes()); record[field] = value
    scope.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ProviderError, match="run_budget_admission_scope_changed"):
        scoped(source, scope)
    source.check()


def test_every_reservation_rechecks_scope_hash(tmp_path):
    source, scope = setup(tmp_path)
    state = scoped(source, scope)
    scope.write_bytes(scope.read_bytes() + b" ")
    with pytest.raises(ProviderError, match="run_budget_admission_scope_changed"):
        state.reserve(PROMPT, output_tokens=20)
    assert source.summary()["requests"] == 1


def test_hosted_launch_guard_forwards_stage_scope(tmp_path):
    source, scope = setup(tmp_path, requests=1)
    state = scoped(source, scope)
    request, _ = state.reserve(PROMPT, output_tokens=20)
    state.finish(request, result=Completion("{}", state.model, 10, 2), elapsed_ms=1)
    bot = BotSpec("luna", "0.1", "subprocess", command=("python", "llm_hosted_bot.py", "--model", "luna",
        "--run-budget", str(source.path), "--run-budget-map", str(source.paths.manifest),
        "--run-budget-map-sha256", source.paths.sha256, "--admission-scope", str(scope),
        "--admission-scope-sha256", digest(scope), "--max-run-requests", "20", "--max-run-tokens", "10000",
        "--max-run-wall-seconds", "60", "--allow-timeout-forfeits"))
    with pytest.raises(ProviderError, match="run_budget_stage_requests_exhausted"):
        check_hosted_budgets(SimpleNamespace(bots=(bot,)))


@pytest.mark.parametrize("phase", ["inference", "renewal"])
def test_real_hosted_broker_stage_exhaustion_does_not_poison_cumulative_pool(tmp_path, monkeypatch, phase):
    import io
    import sys
    from spellbench import wire
    from spellbench.llm import hosted
    from test_llm_agent import decision
    source, scope = setup(tmp_path, requests=1, tokens=20)
    if phase == "renewal":
        request, _ = source.reserve(PROMPT, output_tokens=20)
        source.finish(request, result=Completion("{}", source.model, 10, 2), elapsed_ms=1)
    delegates = []
    def plan(*args, **kwargs):
        delegate = Provider(Completion('{"candidate_id":"1"}', source.model, 10, 2))
        delegate.renew_before_game = lambda: kwargs["budget"].check()
        delegates.append(delegate)
        return delegate
    monkeypatch.setattr(hosted, "PlanProvider", plan)
    incoming = io.BytesIO(b"".join(wire.canonical_json_line(message) for message in [
        {"protocol": "spellbench/v2", "request_type": "hello", "request_id": "h-1"},
        {"protocol": "spellbench/v2", "request_type": "game_start", "request_id": "g-1",
         "game_id": "g", "seat": "p0", "agent_seed": 1,
         "own_deck": {"decklist": [{"count": 4, "name": "Lightning Bolt"}]}},
        {"protocol": "spellbench/v2", "request_type": "choose", "request_id": "c-1", **decision().raw},
    ]))
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=incoming))
    monkeypatch.setattr(sys, "stdout", SimpleNamespace(buffer=io.BytesIO()))
    monkeypatch.setattr(sys, "argv", ["hosted", "--model", "luna", "--trusted-agent-process",
        "--run-budget", str(source.path), "--run-budget-map", str(source.paths.manifest),
        "--run-budget-map-sha256", source.paths.sha256, "--admission-scope", str(scope),
        "--admission-scope-sha256", digest(scope), "--log-dir", str(tmp_path / "logs"),
        "--max-run-requests", "20", "--max-run-tokens", "10000", "--max-run-wall-seconds", "60",
        "--allow-timeout-forfeits"] + (["--renew-profile-before-game"] if phase == "renewal" else []))
    assert hosted.main() in {1, 2}
    assert delegates[0].calls == 0
    assert source.summary()["requests"] == (2 if phase == "renewal" else 1)
    assert source.summary()["policy"]["terminal_error"] is None
    source.check()
