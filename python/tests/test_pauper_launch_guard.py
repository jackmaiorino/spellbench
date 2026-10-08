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
    # The gorge block: each of the six gorge entries plays the three reference models.
    assert len(contexts) == 1152
    assert {game.decks[0].catalog_id for game in sample} == {deck.catalog_id for deck in bench.deck_pool}
    seats = [{spec.name for _, spec in game.seat_specs} for game in sample]
    assert all(any(name.startswith("gorge-") for name in names) for names in seats)
    assert all(names - {name for name in names if name.startswith("gorge-")} <= {"g115", "a48", "c12"} for names in seats)
    assert len({name for names in seats for name in names if name.startswith("gorge-")}) >= 5
    assert any(game.decks[0].catalog_id == "Spy" for game in sample[:4])
    assert all("llm-gpt-6-luna" not in names for names in seats)


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
        return SimpleNamespace(outcomes=[outcome], error=None, stopped=None)
    monkeypatch.setattr(runner, "play_games", play)
    with pytest.raises(ThroughputError, match="halted or truncated"):
        run.qualification_play(config, storage_dir=tmp_path, files=())(1, (0,))
    summaries = list(tmp_path.rglob("trial-1-summary.json"))
    assert len(summaries) == 1
    summary = json.loads(summaries[0].read_bytes())
    assert summary["useful_completed"] == 0 and summary["requested_games"] == 1
    assert summary["elapsed_seconds"] >= 0
    (timing,) = summary["game_timings"]
    assert timing["game_index"] == row.game_index and timing["elapsed_seconds"] == 2.0
    assert timing["bots"] == [seat.name for seat in row.seats]
    assert timing["decks"] == [deck.catalog_id for deck in row.decks]
    assert timing["classification"] == row.classification and timing["ledger_write_seconds"] >= 0
    retained = list(tmp_path.rglob("trial-1-workers-*.jsonl"))
    assert len(retained) == 1
    assert json.loads(retained[0].read_text().splitlines()[0])["classification"] == row.classification


def test_failed_qualification_retains_replay_only_after_cleanup(tmp_path, monkeypatch):
    config = TournamentConfig.from_json(make_config(tmp_path, [builtin("uniform"), builtin("first")],
        decks=("Halt", "Halt"), pairs=1, include_self_play=False))

    def allocation(**kwargs):
        try:
            kwargs["play"](1, (0,))
        finally:
            assert not list(tmp_path.rglob("REPLAY.json"))

    monkeypatch.setattr(run, "plan_allocation", allocation)
    monkeypatch.setattr(run, "_machine_facts", lambda roles: None)
    with pytest.raises(ThroughputError, match="halted or truncated"):
        run.plan_for(config, placement=None, evidence=tmp_path / "evidence", volumes={"run_dir": tmp_path})
    (replay_path,) = list(tmp_path.rglob("REPLAY.json"))
    replay = json.loads(replay_path.read_bytes())
    restored_config = TournamentConfig.from_json(replay["config"])
    secret = RunSecret.from_hex(replay["run_secret"])
    (trial,) = replay_path.parent.glob("trial-1-workers-*.jsonl")
    (row,) = parse_ledger([json.loads(trial.read_text())])
    assert schedule(restored_config, secret)[0].game_id == row.game_id
    (diagnostic_path,) = replay_path.parent.glob("trial-1-diagnostics.jsonl")
    assert "fixture contract halt diagnostic" in diagnostic_path.read_text()
    assert "diagnostic" not in trial.read_text()
    # Replaying with the saved config and secret consumes no hosted inference and preserves the entire row.
    from spellbench.arena.schedule import preflight
    setup = preflight(restored_config, secret)
    entries = {entry.name: entry for entry in runner.registry_entries(config, config)}
    actual = runner.play_one(restored_config, setup, schedule(restored_config, secret)[0], secret.hex(), entries)
    assert actual.row.to_json() == row.to_json()
    assert runner.row_digest(actual.row) == runner.row_digest(row)
    assert replay["trials"] == [{"workers": 1, "schedule_indices": [0]}]
    assert replay["harness_files"] and replay["files"] == []  # This controlled fixture has no pinned inputs.


def test_unused_qualification_reveal_creates_no_artifacts(tmp_path):
    config = TournamentConfig.from_json(make_config(tmp_path, [builtin("uniform"), builtin("first")]))
    measured = run.qualification_play(config, storage_dir=tmp_path, files=())
    measured.finish()
    assert not list(tmp_path.rglob("REPLAY.json"))
    with pytest.raises(ThroughputError, match="already revealed"):
        measured(1, (0,))


def test_aborted_pool_does_not_disclose_replay_secret(tmp_path, monkeypatch):
    config = TournamentConfig.from_json(make_config(tmp_path, [builtin("uniform"), builtin("first")]))
    failure = RuntimeError("worker aborted before descendant cleanup")
    monkeypatch.setattr(run, "preflight", lambda *args: object())
    monkeypatch.setattr(runner, "play_games", lambda *args, **kwargs:
        SimpleNamespace(outcomes=[], error=failure, stopped="aborted"))
    measured = run.qualification_play(config, storage_dir=tmp_path, files=())
    with pytest.raises(RuntimeError) as caught:
        measured(2, (0,))
    assert caught.value is failure
    with pytest.raises(ThroughputError, match="cleanup unconfirmed"):
        measured(2, (0,))
    measured.finish()
    assert not list(tmp_path.rglob("REPLAY.json"))
    (path,) = list(tmp_path.rglob("FINALIZATION.json"))
    assert json.loads(path.read_bytes())["secret_disclosed"] is False


@pytest.mark.parametrize("earlier_failure", [False, True])
def test_finalization_error_preserves_original_failure(tmp_path, monkeypatch, earlier_failure):
    config = TournamentConfig.from_json(make_config(tmp_path, [builtin("uniform"), builtin("first")]))
    primary = ThroughputError("original qualification failure")
    secondary = OSError("metadata cannot be written")
    def plan(**kwargs):
        if earlier_failure:
            raise primary
        return None
    def finish():
        raise secondary
    monkeypatch.setattr(run, "qualification_play", lambda *args, **kwargs: run.QualificationPlay(object(), finish))
    monkeypatch.setattr(run, "plan_allocation", plan)
    monkeypatch.setattr(run, "_machine_facts", lambda roles: None)
    with pytest.raises((ThroughputError, OSError)) as caught:
        run.plan_for(config, placement=None, evidence=tmp_path / "evidence", volumes={"run_dir": tmp_path})
    assert caught.value is (primary if earlier_failure else secondary)
    if earlier_failure:
        assert "OSError: metadata cannot be written" in primary.__notes__[0]


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


def test_pins_written_between_qualification_and_play_are_not_game_growth(tmp_path, monkeypatch):
    # run 2026-10-07-2: 326 MB of pins landed after qualification, and the first formal game was charged for them
    _roomy_storage(monkeypatch)
    guard = job_storage.JobStorageGuard({"projected_bytes": 2**20, "cap_bytes": 2**26},
                                        environ={job_storage.ROOT_ENV: str(tmp_path)})
    (tmp_path / "qualification-game").write_bytes(bytes(2**10))
    guard.reconcile_game(959, qualification_games=1)
    (tmp_path / "pins").mkdir()
    (tmp_path / "pins" / "engine.jar").write_bytes(bytes(2**24))
    assert guard.rebase() >= 2**24
    (tmp_path / "game-1").write_bytes(bytes(2**10))
    guard.reconcile_game(959)
    assert guard.peak_game_growth < 2**14
    assert guard.projected < guard.settings["cap_bytes"]


def test_whole_job_scan_failure_refuses_incomplete_accounting(tmp_path, monkeypatch):
    failure = PermissionError("cannot scan broker logs")
    def failing_walk(root, *, followlinks, onerror):
        yield str(root), [], []
        onerror(failure)
    monkeypatch.setattr(job_storage.os, "walk", failing_walk)
    with pytest.raises(ThroughputError, match="enumerate") as raised:
        job_storage.tree_bytes(tmp_path)
    assert raised.value.__cause__ is failure


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
    monkeypatch.setattr(run, "qualification_play", lambda *args, **kwargs: run.QualificationPlay(object(), lambda: None))
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
    assert set(captured[0]["sample"]) == set(range(1152))
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
