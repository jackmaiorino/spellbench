from pathlib import Path
from types import SimpleNamespace
import json
import time

import pytest

from spellbench.arena import executor, job_storage, runner
from spellbench.arena.config import TournamentConfig
from spellbench.arena.ledger import parse_ledger
from spellbench.arena.schedule import schedule
from spellbench.bench import definition, run
from spellbench.run_secret import RunSecret
from spellbench.arena.allocation import ThroughputError
from arena_helpers import builtin, make_config
from test_ledger import VALID


def test_fixed_pauper_probe_covers_decks_opponents_and_model_concurrency():
    bench = definition.load_benchmark(Path(__file__).parents[2] / "benchmarks/pauper-kernel-v2")
    config = TournamentConfig.from_json(bench.tournament_config("check"))
    contexts = schedule(config, RunSecret(bytes(32)))
    sample = [contexts[index] for index in bench.qualification_sample]
    assert len(contexts) == 576
    assert {game.decks[0].catalog_id for game in sample} == {deck.catalog_id for deck in bench.deck_pool}
    luna = "llm-gpt-6-luna"
    assert all(luna in {spec.name for _, spec in game.seat_specs} for game in sample[:4])
    assert {spec.name for game in sample[:4] for _, spec in game.seat_specs} == {luna, "g115", "a48", "c12"}
    assert any(game.decks[0].catalog_id == "Spy" for game in sample[:4])
    assert all(luna not in {spec.name for _, spec in game.seat_specs} for game in sample[4:])


def test_invalid_sample_is_refused_before_any_qualification(tmp_path, monkeypatch):
    config = TournamentConfig.from_json(make_config(tmp_path, [builtin("uniform"), builtin("first")]))
    monkeypatch.setattr(run, "qualification_play", lambda *a, **kw: pytest.fail("started qualification"))
    with pytest.raises(ThroughputError, match="sample"):
        run.plan_for(config, placement=None, evidence=tmp_path / "evidence",
                     volumes={"run_dir": tmp_path}, sample=[9999])


@pytest.mark.parametrize("kind", ["engine halt", "truncated"])
def test_unusable_qualification_terminals_retain_elapsed_and_rows(tmp_path, monkeypatch, kind):
    config = TournamentConfig.from_json(make_config(tmp_path, [builtin("uniform"), builtin("first")]))
    (row,) = parse_ledger([VALID[kind]])
    outcome = runner.TimedOutcome(row=row, diagnostics=(), violation=None, engine=row.engine, seconds=2.0)
    monkeypatch.setattr(run, "preflight", lambda *args: object())
    def play(*args, **kwargs):
        kwargs["on_outcome"](outcome)
        return SimpleNamespace(outcomes=[outcome], error=None)
    monkeypatch.setattr(runner, "play_games", play)
    with pytest.raises(ThroughputError, match="halted or truncated"):
        run.qualification_play(config, storage_dir=tmp_path, files=())(1, (0,))
    summaries = list(tmp_path.rglob("trial-1-summary.json"))
    assert len(summaries) == 1
    summary = json.loads(summaries[0].read_bytes())
    assert summary["useful_completed"] == 0 and summary["requested_games"] == 1
    assert summary["elapsed_seconds"] >= 0
    retained = list(tmp_path.rglob("trial-1-workers-*.jsonl"))
    assert len(retained) == 1
    assert json.loads(retained[0].read_text().splitlines()[0])["classification"] == row.classification


def _roomy_storage(monkeypatch):
    monkeypatch.setattr(job_storage.shutil, "disk_usage", lambda root: SimpleNamespace(free=2**40))


def test_whole_job_guard_counts_logs_staging_recovery_and_growth(tmp_path, monkeypatch):
    _roomy_storage(monkeypatch)
    settings = {"projected_bytes": 2**20, "cap_bytes": 2**21}
    guard = job_storage.JobStorageGuard(settings, environ={job_storage.ROOT_ENV: str(tmp_path)})
    for name in ("broker-logs", "qualification", "staging", "recovery"):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "part").write_bytes(bytes(2**17))
    assert guard.check() >= 4 * 2**17
    with pytest.raises(ThroughputError, match="declared cap"):
        guard.reconcile_game(576, qualification_games=32)


def test_storage_root_must_cover_every_output_path(tmp_path, monkeypatch):
    _roomy_storage(monkeypatch)
    with pytest.raises(ThroughputError, match="inside"):
        job_storage.JobStorageGuard({"projected_bytes": 100, "cap_bytes": 200},
            environ={job_storage.ROOT_ENV: str(tmp_path)}, paths=[tmp_path.parent / "foreign"])


def test_projected_logs_preserve_volume_reserve(tmp_path, monkeypatch):
    monkeypatch.setattr(job_storage.shutil, "disk_usage", lambda root: SimpleNamespace(free=job_storage.RESERVE_BYTES + 50))
    with pytest.raises(ThroughputError, match="reserve"):
        job_storage.JobStorageGuard({"projected_bytes": 100, "cap_bytes": 200},
            environ={job_storage.ROOT_ENV: str(tmp_path)})


def test_sample_order_binds_qualification_evidence(tmp_path, monkeypatch):
    from test_throughput import MACHINE
    bench = definition.load_benchmark(Path(__file__).parents[2] / "benchmarks/pauper-kernel-v2")
    config = TournamentConfig.from_json(bench.tournament_config("check"))
    monkeypatch.setattr(run, "_hosted_budget_guard", lambda *args, **kwargs: None)
    monkeypatch.setattr(run, "_machine_facts", lambda roles: MACHINE)
    monkeypatch.setattr(run, "_free_space", lambda roles: MACHINE)
    monkeypatch.setattr(run, "qualification_play", lambda *args, **kwargs: object())
    captured = []
    def plan(**kwargs):
        captured.append(kwargs)
        return SimpleNamespace(budget=SimpleNamespace(projected_bytes=0))
    monkeypatch.setattr(run, "plan_allocation", plan)
    options = dict(placement=None, evidence=tmp_path / "evidence", volumes={"run_dir":tmp_path})
    run.plan_for(config, sample=bench.qualification_sample, **options)
    run.plan_for(config, sample=tuple(reversed(bench.qualification_sample)), **options)
    storage = SimpleNamespace(settings={"projected_bytes": 100, "cap_bytes": 200}, check=lambda: 0)
    run.plan_for(config, sample=bench.qualification_sample, job_storage=storage, **options)
    assert captured[0]["sample"][:8] == bench.qualification_sample
    assert set(captured[0]["sample"]) == set(range(576))
    assert captured[0]["workload"] != captured[1]["workload"]
    assert captured[0]["workload"] != captured[2]["workload"]


def _write_long_game(path):
    Path(path).write_bytes(bytes(2**17))
    time.sleep(3)
    return executor.GameOutcome(row=None, diagnostics=(), violation=None, engine={})


def test_one_worker_guard_checks_during_the_game(tmp_path, monkeypatch):
    _roomy_storage(monkeypatch)
    monkeypatch.setattr(executor, "WAIT_SLICE_S", .05)
    guard = job_storage.JobStorageGuard({"projected_bytes": 1024, "cap_bytes": 2048},
        environ={job_storage.ROOT_ENV: str(tmp_path)})
    result = executor.execute([str(tmp_path / "growing.log")], _write_long_game, workers=1, guard=guard.check)
    assert result.stopped == "aborted" and isinstance(result.error, ThroughputError)
    assert result.outcomes == ()
