"""A short stochastic benchmark measures parallel completion without adding games."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from spellbench.arena.allocation import Allocation, QualificationRules, Trial, fastest_workers
from spellbench.arena.config import BotSpec, TournamentConfig
from spellbench.arena.qualification import plan_allocation
from spellbench.bench.definition import load_benchmark
from spellbench.bench.run import run_files
from spellbench.llm.run_budget import BudgetedProvider, RunBudget, check_hosted_budgets
from spellbench.llm.provider import Completion, ProviderError

from test_throughput import _player, MACHINE, PLACEMENT
from test_llm_run_budget import PROMPT, Provider


def test_luna_schedule_compares_identical_input_indices_at_one_two_four_workers():
    bench = load_benchmark(Path(__file__).parents[2] / "benchmarks/standard-mirror-xmage")
    play, calls = _player(120, {1: 1, 2: 2, 4: 3})
    allocation = plan_allocation(games_total=48, cap=4, per_game_cores=3, cpu_count=24,
                                 play=play, placement=PLACEMENT, machine=MACHINE,
                                 rules=bench.qualification_rules())
    assert allocation.kind == "substantial" and allocation.measured
    assert [workers for workers, _ in calls] == [1, 2, 4]
    assert all(indices == tuple(range(8)) for _, indices in calls)
    assert allocation.workers == 4
    assert allocation.rules.budget_percent == 30 and allocation.rules.worker_selection == "wall"
    assert Allocation.from_json(allocation.to_json()) == allocation


def test_wall_completion_can_choose_a_different_rung_than_busy_time():
    one = Trial(workers=1, games=8, indices=tuple(range(8)), seconds_milli=1000, busy_milli=1000,
                row_bytes=800, outputs_digest="sha256:" + "a" * 64)
    two = replace(one, workers=2, seconds_milli=1500, busy_milli=1200)
    assert fastest_workers((one, two)) == 2
    assert fastest_workers((one, two), method="wall") == 1


def test_legacy_rule_bytes_and_selection_are_preserved():
    rule = QualificationRules(600, 12, 2, 2, (2, 1), 2)
    assert "worker_selection" not in rule.to_json()
    assert QualificationRules.from_json(rule.to_json()) == rule
    wall = replace(rule, worker_selection="wall")
    assert wall.to_json()["worker_selection"] == "wall"
    assert QualificationRules.from_json(wall.to_json()) == wall


def test_mutable_usage_ledger_is_not_pinned_as_an_agent_input(tmp_path):
    ledger = tmp_path / "budget.sqlite3"
    RunBudget.create(ledger, model="luna", requests=4096, tokens=10_000_000, wall_seconds=7200)
    root = Path(__file__).parents[2]
    bench = load_benchmark(root / "benchmarks/standard-mirror-xmage")
    doc = bench.tournament_config("out/test")
    import sys
    doc["engine"]["command"] = [sys.executable]
    bot = next(bot for bot in doc["bots"] if bot["name"] == "llm-gpt-6-luna")
    bot["command"] = [sys.executable, str(root / "python/tools/llm_hosted_bot.py"),
                       "--run-budget=" + str(ledger)]
    files = run_files(TournamentConfig.from_json(doc))
    assert all(file.path != ledger for file in files)


def test_failed_or_unresolved_budget_refuses_the_next_phase_but_not_live_peers(tmp_path):
    ledger = tmp_path / "budget.sqlite3"
    RunBudget.create(ledger, model="luna", requests=4096, tokens=10_000_000, wall_seconds=7200)
    budget = RunBudget(ledger, model="luna")
    bot = BotSpec("luna", "0.1", "subprocess", command=("python", "llm_hosted_bot.py", "--model", "luna",
                                                         "--run-budget=" + str(ledger)))
    config = SimpleNamespace(bots=(bot,))
    budget.reserve(PROMPT, output_tokens=1024)
    with pytest.raises(ProviderError, match="run_budget_unresolved_request"):
        check_hosted_budgets(config)
    check_hosted_budgets(config, allow_pending=True)
    with pytest.raises(ProviderError):
        BudgetedProvider(Provider(ProviderError("transport_error")), budget).complete(PROMPT, timeout_s=1)
    with pytest.raises(ProviderError, match="run_budget_already_failed"):
        check_hosted_budgets(config, allow_pending=True)


@pytest.mark.parametrize("limit,code", [("requests", "requests_exhausted"), ("tokens", "tokens_exhausted")])
def test_exhausted_shared_budget_stops_before_another_game(tmp_path, limit, code):
    ledger = tmp_path / "budget.sqlite3"
    requests, tokens = (1, 10_000_000) if limit == "requests" else (4096, PROMPT.bytes + 1024)
    RunBudget.create(ledger, model="luna", requests=requests, tokens=tokens, wall_seconds=7200)
    budget = RunBudget(ledger, model="luna")
    request, _ = budget.reserve(PROMPT, output_tokens=1024)
    used = 2 if limit == "requests" else tokens
    budget.finish(request, result=Completion("choice", "luna", used - 1, 1), elapsed_ms=1)
    bot = BotSpec("luna", "0.1", "subprocess", command=("python", "llm_hosted_bot.py", "--model", "luna",
                 "--run-budget=" + str(ledger), "--max-run-requests", str(requests), "--max-run-tokens", str(tokens)))
    with pytest.raises(ProviderError, match=code):
        check_hosted_budgets(SimpleNamespace(bots=(bot,)))


def test_abandoned_pending_request_stops_parallel_evaluation(tmp_path, monkeypatch):
    ledger = tmp_path / "budget.sqlite3"
    RunBudget.create(ledger, model="luna", requests=4096, tokens=10_000_000, wall_seconds=7200)
    budget = RunBudget(ledger, model="luna")
    budget.reserve(PROMPT, output_tokens=1024, timeout_s=1)
    from spellbench.llm import run_budget
    now = run_budget.time.time()
    monkeypatch.setattr(run_budget.time, "time", lambda: now + 62)
    bot = BotSpec("luna", "0.1", "subprocess", command=("python", "llm_hosted_bot.py", "--model", "luna",
                                                         "--run-budget=" + str(ledger)))
    with pytest.raises(ProviderError, match="run_budget_unresolved_request"):
        check_hosted_budgets(SimpleNamespace(bots=(bot,)), allow_pending=True)
