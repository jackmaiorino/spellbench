"""The v2 tournament: commitment first, opaque ids, the manifest, invalid and aborted runs."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from spellbench.arena import cli, config as config_module, drivers, leaderboard, ledger, manifest as manifest_module, runner, store
from spellbench.arena.config import DEFAULT_TIME_CONTROL, TournamentConfig
from spellbench.arena.machine import usable_cpus
from spellbench.arena.throughput import MachineFacts, PlayedGame, plan_allocation
from spellbench.errors import ValidationError
from spellbench.run_secret import RunSecret

from arena_helpers import (
    BOT_SLOW_START, HOSTILE_ENGINE, ROOMY_CHILD, TEST_RUN_SECRET, TESTS_DIR, builtin, cli_bot, ledger_rows, make_config,
    manifest, roomy_machine, run, subprocess_bot,
)

BOTS = [builtin("uniform", seed=11), builtin("heuristic"), builtin("first")]
DATA = ("registry.json", "matches.jsonl", "leaderboard.json", "LEADERBOARD.md", "COMMITMENT.json")


@pytest.fixture(autouse=True)
def _roomy_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    """``spellbench run`` is a guarded launch (Decision 10): the tests fake the disk it checks."""
    roomy_machine(monkeypatch)


@pytest.fixture(autouse=True)
def _python_sigint_handler():
    """Each test starts under Python's own SIGINT handler, whatever the shell passed on, and the handler found is
    put back afterwards. A background job of a non-interactive shell, ``nohup`` or ``trap '' INT`` starts pytest
    with SIGINT ignored, and the runner rightly keeps ignoring it, so the interrupt tests would see nothing."""
    previous = signal.signal(signal.SIGINT, signal.default_int_handler)
    yield
    if previous is not None:  # None: a handler not set from Python, which cannot be put back
        signal.signal(signal.SIGINT, previous)


def test_store_schema_constants_match_their_owners() -> None:
    assert store.TOURNAMENT_SCHEMA == manifest_module.TOURNAMENT_SCHEMA_V2
    assert store.LEDGER_SCHEMA == ledger.LEDGER_SCHEMA and store.CONFIG_SCHEMA == config_module.CONFIG_SCHEMA
    assert store.LEADERBOARD_SCHEMA == leaderboard.LEADERBOARD_SCHEMA_V2


def test_a_complete_run_publishes_every_v2_record(tmp_path: Path) -> None:
    directory = tmp_path / "t"
    summary = run(make_config(directory, BOTS, pairs=1, include_self_play=False))
    document = manifest(directory)
    assert set(document) == set(manifest_module.MANIFEST_KEYS)
    assert document["run"] == {"benchmark_id": None, "label": None, "status": "complete", "rated": False}
    assert document["secrets"]["run_secret"] == TEST_RUN_SECRET.hex()
    assert document["secrets"]["commitment"] == TEST_RUN_SECRET.commitment() and document["secrets"]["commitment_proof"] is None
    assert document["information_rules"]["fairness_label"] == "validator only"
    assert document["validator"]["verdict"] == "pass" and document["protocol"] == {"name": "spellbench/v2", "minor": 0}
    assert [entry["path"] for entry in document["files"]] == ["COMMITMENT.json", *store.DATA_FILE_NAMES]
    assert json.loads((directory / "COMMITMENT.json").read_text(encoding="utf-8"))["commitment"] == TEST_RUN_SECRET.commitment()
    rows = ledger_rows(directory)
    assert [row["game_id"] for row in rows] == [TEST_RUN_SECRET.game_id(index) for index in range(len(rows))]
    assert summary.status == "complete" and not summary.rated


def test_a_rated_run(tmp_path: Path) -> None:
    summary = run(make_config(tmp_path / "t", BOTS, pairs=1, include_self_play=False), rated=True)
    assert summary.rated and manifest(tmp_path / "t")["run"]["rated"] is True


def test_serial_and_parallel_runs_publish_the_same_data(tmp_path: Path) -> None:
    for name, workers in (("serial", 1), ("parallel", 3)):
        run(make_config(tmp_path / name, BOTS, pairs=2, workers=workers))
    for name in DATA:
        assert (tmp_path / "serial" / name).read_bytes() == (tmp_path / "parallel" / name).read_bytes(), name


def test_a_validator_violation_invalidates_the_run_at_that_game(tmp_path: Path) -> None:
    directory = tmp_path / "t"
    summary = run(make_config(directory, [builtin("first"), builtin("heuristic")], engine=HOSTILE_ENGINE,
                              engine_args=("stale-reference",), pairs=2))
    rows = ledger_rows(directory)
    assert summary.status == "invalid" and not summary.rated
    assert len(rows) == 1 and rows[0]["reason"] == "host_validator:V4"
    assert manifest(directory)["validator"]["verdict"] == "fail"


def test_an_interrupted_run_is_published_as_aborted_with_its_secret(tmp_path: Path) -> None:
    directory = tmp_path / "t"

    def interrupt(row) -> None:
        if row.game_index == 1:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run(make_config(directory, BOTS, pairs=2), on_game=interrupt)
    document = manifest(directory)
    assert document["run"]["status"] == "aborted" and document["secrets"]["run_secret"] == TEST_RUN_SECRET.hex()
    assert len(ledger_rows(directory)) == 2


def test_a_config_error_writes_nothing(tmp_path: Path) -> None:
    directory = tmp_path / "t"
    with pytest.raises(runner.TournamentError, match="unsupported_deck"):
        run(make_config(directory, BOTS, decks=("Refuse", "Refuse")))
    assert not directory.exists()


def test_the_cli_runs_a_config_and_serves_builtins(tmp_path: Path, capsys) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(make_config(tmp_path / "t", BOTS[:2], pairs=1)), encoding="utf-8")
    assert cli.main(["run", str(path)]) == 0
    assert "status: complete (unrated)" in capsys.readouterr().out
    hello = b'{"request_type":"hello","protocol":"spellbench/v2","request_id":"r-0","protocol_minor":0}\n'
    served = subprocess.run(cli_bot("uniform"), input=hello, capture_output=True, timeout=60)
    assert b'"name":"uniform"' in served.stdout and b'"version":"2.0.0"' in served.stdout


def _wrapped_engine(tmp_path: Path, name: str, body: str) -> Path:
    """A fake v2 engine behind a small script whose behavior changes once the test touches a marker after game 0."""
    script = tmp_path / f"{name}.py"
    script.write_text(f"import os, sys\nsys.path.insert(0, {str(TESTS_DIR)!r})\nimport fake_v2_engine\n{body}", encoding="utf-8")
    return script


def test_an_engine_rebuilt_mid_run_aborts_it(tmp_path: Path) -> None:
    marker = tmp_path / "rebuilt"
    engine = _wrapped_engine(tmp_path, "rebuilt_engine",
                             f"name = 'fake-v2-engine-rebuilt' if os.path.exists({str(marker)!r}) else 'fake-v2-engine'\n"
                             "sys.exit(fake_v2_engine.serve(['--name', name, *sys.argv[1:]]))\n")
    directory = tmp_path / "t"
    with pytest.raises(runner.TournamentError, match="engine identity"):
        run(make_config(directory, BOTS[:2], engine=engine, pairs=1, include_self_play=False), on_game=lambda row: marker.touch())
    assert manifest(directory)["run"]["status"] == "aborted" and len(ledger_rows(directory)) == 1    # R3-5


def test_an_engine_that_fails_to_start_halts_that_game_only(tmp_path: Path) -> None:
    marker = tmp_path / "broken"
    engine = _wrapped_engine(tmp_path, "flaky_engine",
                             f"if os.path.exists({str(marker)!r}):\n    sys.exit(7)\n"
                             "sys.exit(fake_v2_engine.serve(sys.argv[1:]))\n")
    directory = tmp_path / "t"
    summary = run(make_config(directory, BOTS[:2], engine=engine, pairs=1, include_self_play=False),
                  on_game=lambda row: marker.touch())
    rows = ledger_rows(directory)
    assert summary.status == "complete" and (rows[1]["classification"], rows[1]["reason"]) == ("halted", "host_engine_fault:transport")
    assert rows[1]["last_selection"] is None                                                       # R3-23


def test_workers_are_capped_by_the_declared_cores(tmp_path: Path) -> None:
    resources = {"cpus": 1, "memory_mb": 4096, "gpu": False, "engine_cpus": os.cpu_count() or 1}  # one game fills the machine
    run(make_config(tmp_path / "t", BOTS, pairs=1, workers=3, resources=resources))
    assert manifest(tmp_path / "t")["allocation"]["workers"] == 1                                   # spec 11.4 (R3-24)


def test_unvetted_subprocess_bots_are_refused_and_the_isolation_is_published(tmp_path: Path) -> None:
    first = subprocess_bot("first", cli_bot("first"), version="2.0.0")
    with pytest.raises(runner.TournamentError, match="sandbox"):
        run(make_config(tmp_path / "refused", [builtin("uniform"), {**first, "owner": "someone"}]))
    assert not (tmp_path / "refused").exists()
    run(make_config(tmp_path / "t", [builtin("uniform"), first], pairs=1))
    assert manifest(tmp_path / "t")["isolation"] == {"entries": [{"name": "uniform", "isolation": "builtin-in-process"},
                                                                 {"name": "first", "isolation": "unsandboxed"}],
                                                     "self_reported": True}                         # spec 11.7 (R3-9)


def test_a_commitment_made_for_another_run_is_refused(tmp_path: Path) -> None:
    directory = tmp_path / "t"
    directory.mkdir()
    record = manifest_module.commitment_record(run_secret=TEST_RUN_SECRET, benchmark_id="other-bench", run_label="2026-10-01")
    store.write_json_atomic(directory / "COMMITMENT.json", record)
    with pytest.raises(runner.TournamentError, match="benchmark_id"):
        run(make_config(directory, BOTS, pairs=1), benchmark_id="fake-pool", run_label="2026-10-01")   # R3-30


def test_a_second_interrupt_waits_until_the_manifest_is_written() -> None:
    written = []
    with pytest.raises(KeyboardInterrupt):
        with runner.deferred_interrupts():
            signal.raise_signal(signal.SIGINT)             # a second Ctrl+C while the aborted manifest is written
            written.append("manifest")
    assert written == ["manifest"]                         # R3-31


# ---------------------------------------------------------------------------
# Beyond the plan's list: each guarantee above has a test that fails when it breaks
# ---------------------------------------------------------------------------


def test_the_store_names_the_commitment_and_keeps_the_registry_schema() -> None:
    assert store.COMMITMENT_NAME == "COMMITMENT.json" and store.REGISTRY_SCHEMA == "spellbench-bot-registry/v1"


def test_no_arena_module_loads_bench_site_or_v1_protocol_code() -> None:
    """Arena modules import ``bench`` and ``site`` only inside CLI commands (R3-4); the CLI drops its v1 imports (R3-25)."""
    code = (
        "import importlib, pkgutil, sys, spellbench.arena as arena\n"
        "for module in pkgutil.iter_modules(arena.__path__):\n"
        "    if not module.ispkg:\n"
        "        importlib.import_module('spellbench.arena.' + module.name)\n"
        "unwanted = ('spellbench.bench', 'spellbench.site', 'spellbench.agent_server', 'spellbench.agent_client',\n"
        "            'spellbench.engine_client', 'spellbench.arena.bots')\n"
        "print(sorted(name for name in sys.modules if name.startswith(unwanted)))\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True, timeout=60)
    assert result.stdout.strip() == "[]"


def _marking_engine(tmp_path: Path) -> tuple[Path, Path]:
    """A fake engine that leaves a marker file whenever a process of it starts."""
    marker = tmp_path / "engine-started"
    return _wrapped_engine(tmp_path, "marking_engine", f"open({str(marker)!r}, 'w').close()\n"
                                                       "sys.exit(fake_v2_engine.serve(sys.argv[1:]))\n"), marker


def test_unvetted_bots_are_refused_before_any_process_starts(tmp_path: Path) -> None:
    engine, marker = _marking_engine(tmp_path)
    bot = subprocess_bot("first", cli_bot("first"), version="2.0.0", owner="someone")
    with pytest.raises(runner.TournamentError, match="sandbox"):
        run(make_config(tmp_path / "t", [builtin("uniform"), bot], engine=engine))
    assert not marker.exists() and not (tmp_path / "t").exists()                                   # R3-9


def test_an_unreadable_checkpoint_stops_the_run_before_any_process_starts(tmp_path: Path) -> None:
    engine, marker = _marking_engine(tmp_path)
    bot = subprocess_bot("first", cli_bot("first"), version="2.0.0", checkpoint=str(tmp_path / "missing.bin"))
    with pytest.raises(ValidationError, match="checkpoint is not readable"):
        run(make_config(tmp_path / "t", [builtin("uniform"), bot], engine=engine))
    assert not marker.exists() and not (tmp_path / "t").exists()


def test_an_allocation_the_declared_cores_cannot_hold_is_refused_before_any_process_starts(tmp_path: Path) -> None:
    digest = "sha256:" + "0" * 64
    machine = MachineFacts(memory_bytes=2**36, gpus=(), free_bytes=(("pin_root", 2**42), ("run_dir", 2**42)))

    def slow_games(workers: int, indices: tuple[int, ...]) -> tuple[float, tuple[PlayedGame, ...]]:
        return 10.0 * len(indices) / workers, tuple(PlayedGame(index, 10.0, digest, 10) for index in indices)

    placement = ("main-pc=used: fastest measured; computehost=slower: half the speed per game; "
                 "runpod=not_authorized: no spending authority")
    allocation = plan_allocation(games_total=200, cap=4, per_game_cores=1, play=slow_games, placement=placement,
                                 cpu_count=4, host="test-host", machine=machine)
    assert (allocation.kind, allocation.workers) == ("substantial", 4)
    engine, marker = _marking_engine(tmp_path)
    resources = {"cpus": 1, "memory_mb": 4096, "gpu": False, "engine_cpus": usable_cpus()}          # one game fills the machine
    config = TournamentConfig.from_json(make_config(tmp_path / "t", BOTS, engine=engine, pairs=1, workers=4, resources=resources))
    with pytest.raises(runner.TournamentError, match="allocation"):
        runner.run_tournament(config, run_secret=TEST_RUN_SECRET, allocation=allocation)
    assert not marker.exists() and not (tmp_path / "t").exists()                                   # R3-24


def test_a_run_directory_may_already_hold_its_own_commitment(tmp_path: Path) -> None:
    directory = tmp_path / "t"
    directory.mkdir()
    record = manifest_module.commitment_record(run_secret=TEST_RUN_SECRET, benchmark_id="fake-pool", run_label="2026-10-01")
    committed = store.write_json_atomic(directory / "COMMITMENT.json", record)
    summary = run(make_config(directory, BOTS[:2], pairs=1, include_self_play=False), benchmark_id="fake-pool",
                  run_label="2026-10-01")
    document = manifest(directory)
    assert summary.status == "complete" and (directory / "COMMITMENT.json").read_bytes() == committed
    assert document["run"]["benchmark_id"] == "fake-pool" and document["run"]["label"] == "2026-10-01"
    assert document["files"][0] == store.file_entry(directory / "COMMITMENT.json", "COMMITMENT.json")


@pytest.mark.parametrize(
    ("field", "secret", "run_label"),
    [("commitment", RunSecret(bytes(32)), "2026-10-01"), ("run_label", TEST_RUN_SECRET, "2026-10-02")],
)
def test_a_commitment_for_another_secret_or_label_is_refused_and_nothing_is_written(
    tmp_path: Path, field: str, secret: RunSecret, run_label: str
) -> None:
    directory = tmp_path / "t"
    directory.mkdir()
    record = manifest_module.commitment_record(run_secret=secret, benchmark_id="fake-pool", run_label=run_label)
    store.write_json_atomic(directory / "COMMITMENT.json", record)
    with pytest.raises(runner.TournamentError, match=f"its {field} differs"):
        run(make_config(directory, BOTS, pairs=1), benchmark_id="fake-pool", run_label="2026-10-01")
    assert [path.name for path in directory.iterdir()] == ["COMMITMENT.json"]                       # R3-30


def test_a_run_directory_holding_more_than_a_commitment_is_refused(tmp_path: Path) -> None:
    directory = tmp_path / "t"
    directory.mkdir()
    store.write_json_atomic(directory / "COMMITMENT.json",
                            manifest_module.commitment_record(run_secret=TEST_RUN_SECRET, benchmark_id=None, run_label=None))
    (directory / "matches.jsonl").write_bytes(b"")
    with pytest.raises(store.StoreError, match="not empty"):
        run(make_config(directory, BOTS, pairs=1))
    assert sorted(path.name for path in directory.iterdir()) == ["COMMITMENT.json", "matches.jsonl"]


def test_an_engine_that_never_says_hello_halts_that_game_as_a_timeout(tmp_path: Path) -> None:
    marker = tmp_path / "stuck"
    engine = _wrapped_engine(tmp_path, "stuck_engine",
                             f"if os.path.exists({str(marker)!r}):\n    import time\n    time.sleep(60)\n"
                             "sys.exit(fake_v2_engine.serve(sys.argv[1:]))\n")
    time_control = {**DEFAULT_TIME_CONTROL.to_json(), "startup_ms": 5000}   # room for the healthy engines on a slow machine
    directory = tmp_path / "t"
    summary = run(make_config(directory, BOTS[:2], engine=engine, pairs=1, include_self_play=False, time_control=time_control),
                  on_game=lambda row: marker.touch())
    first, second = ledger_rows(directory)
    assert summary.status == "complete" and (second["classification"], second["reason"]) == ("halted", "host_engine_fault:timeout")
    assert (second["step_count"], second["decision_count"], second["last_selection"]) == (0, 0, None)
    assert second["engine"] == first["engine"]                                                     # the preflight identity (R3-23)


def test_an_engine_that_fails_to_start_is_recorded_as_one_that_died_at_its_reset(tmp_path: Path) -> None:
    """R3-23's row for an engine that never started chains what the game loop chains for one that answered hello
    and died before answering its reset: the reset request, then the halt record (spec 11.8)."""
    endings = {
        "dead_at_start": "    sys.exit(7)\n",
        "dead_at_reset": ("    import io\n"
                          "    hello = sys.stdin.buffer.readline()\n"
                          "    fake_v2_engine.serve(sys.argv[1:], stdin=io.BytesIO(hello), stdout=sys.stdout.buffer)\n"
                          "    sys.exit(0)\n"),
    }
    games = {}
    for name, ending in endings.items():
        marker = tmp_path / f"{name}.marker"
        engine = _wrapped_engine(tmp_path, name, f"if os.path.exists({str(marker)!r}):\n{ending}"
                                                 "sys.exit(fake_v2_engine.serve(sys.argv[1:]))\n")
        run(make_config(tmp_path / name, BOTS[:2], engine=engine, pairs=1, include_self_play=False),
            on_game=lambda row, marker=marker: marker.touch())
        games[name] = ledger_rows(tmp_path / name)[1]
    keys = ("game_digest", "classification", "reason", "step_count", "decision_count", "decisions_checked", "last_selection", "engine")
    started, reset = games["dead_at_start"], games["dead_at_reset"]
    assert reset["reason"] == "host_engine_fault:transport"
    assert {key: started[key] for key in keys} == {key: reset[key] for key in keys}


def test_rows_record_the_scheduled_seats_decks_and_ids(tmp_path: Path) -> None:
    directory = tmp_path / "t"
    run(make_config(directory, [builtin("uniform", seed=11), builtin("first")], decks=("Burn", "Elves"), pairs=1,
                    include_self_play=False))
    rows = ledger_rows(directory)
    assert [(row["game_index"], row["matchup_index"], row["pair_index"], row["pair_slot"]) for row in rows] == [(0, 0, 0, 0), (1, 0, 0, 1)]
    assert [[seat["name"] for seat in row["seats"]] for row in rows] == [["uniform", "first"], ["first", "uniform"]]
    assert all([deck["catalog_id"] for deck in row["decks"]] == ["Burn", "Elves"] for row in rows)
    provenance = {"engine_name": "fake-v2-engine", "engine_version": "0.2.0", "rules_snapshot_id": "fake-v2-rules",
                  "card_pool_identity": "fake-v2-cards"}
    assert all(row["engine"] == provenance for row in rows)


def test_a_halted_game_names_the_selection_before_it(tmp_path: Path) -> None:
    directory = tmp_path / "t"
    run(make_config(directory, [builtin("first"), builtin("heuristic")], decks=("Crash", "Crash"), pairs=1,
                    include_self_play=False))
    for row in ledger_rows(directory):                   # the engine dies at the first step, after p0's selection
        assert (row["classification"], row["reason"]) == ("halted", "host_engine_fault:transport")
        assert row["last_selection"] == {"seat": "p0", "bot_id": row["seats"][0]["bot_id"]}         # spec 11.5


def test_an_interrupt_after_the_last_game_still_publishes_a_complete_run(tmp_path: Path) -> None:
    directory = tmp_path / "t"

    def interrupt(row) -> None:
        if row.game_index == 1:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run(make_config(directory, BOTS[:2], pairs=1, include_self_play=False), on_game=interrupt)
    assert manifest(directory)["run"]["status"] == "complete" and len(ledger_rows(directory)) == 2  # R3-13


def test_an_error_in_the_callback_aborts_the_run_and_is_raised(tmp_path: Path) -> None:
    directory = tmp_path / "t"

    def fail(row) -> None:
        raise RuntimeError("the caller's callback failed")

    with pytest.raises(RuntimeError, match="callback failed"):
        run(make_config(directory, BOTS, pairs=2), on_game=fail)
    document = manifest(directory)
    assert document["run"]["status"] == "aborted" and (document["games"]["scheduled"], document["games"]["total"]) == (24, 1)
    assert len(ledger_rows(directory)) == 1


def test_ctrl_c_mid_game_publishes_the_games_finished_before_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    choose = drivers.BuiltinDriver.choose

    def interrupting(self, request, *, timeout_s):
        calls.append(request)
        if len(calls) == 6:                                # game 1's second decision: each scoring game poses four
            raise KeyboardInterrupt
        return choose(self, request, timeout_s=timeout_s)

    monkeypatch.setattr(drivers.BuiltinDriver, "choose", interrupting)
    directory = tmp_path / "t"
    with pytest.raises(KeyboardInterrupt):
        run(make_config(directory, BOTS, pairs=2))
    document = manifest(directory)
    assert document["run"]["status"] == "aborted" and document["secrets"]["run_secret"] == TEST_RUN_SECRET.hex()
    assert [row["game_index"] for row in ledger_rows(directory)] == [0] and document["games"]["total"] == 1


@pytest.mark.parametrize("interrupted", [True, False])
def test_a_ctrl_c_while_the_run_publishes_waits_for_its_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interrupted: bool
) -> None:
    publish = store.publish_manifest

    def publish_under_ctrl_c(directory: Path, document: dict) -> bytes:
        signal.raise_signal(signal.SIGINT)                 # Ctrl+C while the manifest is written
        return publish(directory, document)

    monkeypatch.setattr(store, "publish_manifest", publish_under_ctrl_c)

    def interrupt(row) -> None:
        if interrupted:
            raise KeyboardInterrupt

    directory = tmp_path / "t"
    with pytest.raises(KeyboardInterrupt):
        run(make_config(directory, BOTS[:2], pairs=1, include_self_play=False), on_game=interrupt)
    assert manifest(directory)["run"]["status"] == ("aborted" if interrupted else "complete")      # R3-31


def test_a_ctrl_c_while_a_game_is_recorded_keeps_the_ledger_and_the_manifest_in_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    append = store.append_ledger_row

    def append_under_ctrl_c(path: Path, row: dict) -> None:
        append(path, row)
        if row["game_index"] == 1:
            signal.raise_signal(signal.SIGINT)             # Ctrl+C right after the row reached the file

    monkeypatch.setattr(store, "append_ledger_row", append_under_ctrl_c)
    directory = tmp_path / "t"
    with pytest.raises(KeyboardInterrupt):
        run(make_config(directory, BOTS, pairs=2))
    document = manifest(directory)
    assert document["run"]["status"] == "aborted"
    assert len(ledger_rows(directory)) == document["games"]["total"] == 2                          # R3-13


def test_a_ctrl_c_before_the_first_game_still_publishes_the_committed_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_registry = runner.registry.write_registry

    def write_under_ctrl_c(path: Path, entries) -> bytes:
        signal.raise_signal(signal.SIGINT)                 # Ctrl+C once the commitment is written, before any game
        return write_registry(path, entries)

    monkeypatch.setattr(runner.registry, "write_registry", write_under_ctrl_c)
    directory = tmp_path / "t"
    with pytest.raises(KeyboardInterrupt):
        run(make_config(directory, BOTS, pairs=1))
    document = manifest(directory)
    assert document["run"]["status"] == "aborted" and document["secrets"]["run_secret"] == TEST_RUN_SECRET.hex()
    assert document["games"]["total"] == 0 and ledger_rows(directory) == []                        # spec 11.6


@pytest.mark.parametrize("ending", ["complete", "interrupted"])
def test_every_engine_and_seat_driver_is_closed_however_the_game_ends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ending: str
) -> None:
    opened: list[object] = []
    closed: list[object] = []
    make_driver = runner.make_driver

    def tracked_driver(spec, time_control, **kwargs):
        driver = make_driver(spec, time_control, **kwargs)
        close = driver.close

        def tracked_close() -> None:
            closed.append(driver)
            close()

        driver.close = tracked_close
        opened.append(driver)
        return driver

    class TrackedEngine(runner.EngineProcess):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            opened.append(self)

        def close(self) -> None:
            closed.append(self)
            super().close()

    monkeypatch.setattr(runner, "make_driver", tracked_driver)
    monkeypatch.setattr(runner, "EngineProcess", TrackedEngine)
    if ending == "interrupted":
        def interrupted_game(*args, **kwargs):
            raise KeyboardInterrupt

        monkeypatch.setattr(runner, "play_game", interrupted_game)
    bots = [builtin("uniform", seed=11), subprocess_bot("first", cli_bot("first"), version="2.0.0")]
    config = make_config(tmp_path / "t", bots, pairs=1, include_self_play=False)
    if ending == "complete":
        run(config)
    else:
        with pytest.raises(KeyboardInterrupt):
            run(config)
    assert len(opened) == (6 if ending == "complete" else 3)       # an engine and two seats per game
    assert all(any(item is thing for item in closed) for thing in opened)


def test_a_game_dropped_for_engine_drift_leaves_no_trace_in_the_published_run(tmp_path: Path) -> None:
    """The rebuilt engine's game also breaks a validator rule; neither the row nor its violation is recorded (R3-13)."""
    marker = tmp_path / "rebuilt"
    engine = _wrapped_engine(tmp_path, "rebuilt_hostile_engine",
                             f"if os.path.exists({str(marker)!r}):\n"
                             "    import hostile_v2_engine\n"
                             "    sys.exit(fake_v2_engine.serve(['--name', 'fake-v2-engine-rebuilt', *sys.argv[1:]],\n"
                             "                                  mutate=hostile_v2_engine.MUTATIONS['stale-reference']))\n"
                             "sys.exit(fake_v2_engine.serve(sys.argv[1:]))\n")
    directory = tmp_path / "t"
    with pytest.raises(runner.TournamentError, match="engine identity changed during the run"):
        run(make_config(directory, [builtin("first"), builtin("heuristic")], engine=engine, pairs=1,
                        include_self_play=False), on_game=lambda row: marker.touch())
    document = manifest(directory)
    assert document["run"]["status"] == "aborted" and document["validator"]["violations"] == []
    assert len(ledger_rows(directory)) == document["games"]["total"] == 1


def test_deferred_interrupts_restores_the_handler_and_changes_nothing_off_the_main_thread() -> None:
    before = signal.getsignal(signal.SIGINT)
    with runner.deferred_interrupts():
        assert signal.getsignal(signal.SIGINT) is not before
    assert signal.getsignal(signal.SIGINT) is before
    seen: list[object] = []

    def elsewhere() -> None:
        try:
            with runner.deferred_interrupts():
                seen.append(signal.getsignal(signal.SIGINT))
        except BaseException as exc:  # noqa: BLE001 - reported to the test
            seen.append(exc)

    thread = threading.Thread(target=elsewhere)
    thread.start()
    thread.join()
    assert seen == [before]


def test_a_held_interrupt_is_delivered_to_the_handler_it_found() -> None:
    before = signal.signal(signal.SIGINT, signal.SIG_IGN)            # a run started with Ctrl+C ignored keeps ignoring it
    try:
        with runner.deferred_interrupts():
            signal.raise_signal(signal.SIGINT)
        assert signal.getsignal(signal.SIGINT) is signal.SIG_IGN
    except KeyboardInterrupt:
        pytest.fail("a held Ctrl+C reached a process that ignores SIGINT")    # fail the test, not the session
    finally:
        signal.signal(signal.SIGINT, before)


# ---------------------------------------------------------------------------
# One SIGINT handler for the committed phase: a Ctrl+C on any line (spec 11.6, R3-31)
# ---------------------------------------------------------------------------

SWEEP_BOTS = [builtin("uniform", seed=11), builtin("first")]


@pytest.fixture(scope="module")
def recorded_engine_work(tmp_path_factory: pytest.TempPathFactory) -> tuple[dict, dict]:
    """A two-game config, and one real run's preflight and game outcomes for the sweeps to replay: a sweep plays
    the run once per line it covers, and only the runner's own lines are under test."""
    config = make_config(tmp_path_factory.mktemp("sweep") / "t", SWEEP_BOTS, pairs=1, include_self_play=False, workers=1)
    recorded: dict = {}
    preflight, play_one = runner.preflight, runner.play_one

    def recording_preflight(config, run_secret, *, pin):
        recorded["setup"] = preflight(config, run_secret, pin=pin)
        return recorded["setup"]

    def recording_play_one(config, setup, context, **keywords):
        recorded[context.game_index] = play_one(config, setup, context, **keywords)
        return recorded[context.game_index]

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(runner, "preflight", recording_preflight)
        patch.setattr(runner, "play_one", recording_play_one)
        run(config)
    return config, recorded


class _CtrlC:
    """A Ctrl+C landing on the ``at``-th line the runner executes once ``armed`` (through ``sys.settrace``): SIGINT
    is raised right there, as the operating system could deliver it, and ``where`` names that line. With ``at``
    None it only counts the lines."""

    def __init__(self, at: int | None = None) -> None:
        self.at = at
        self.armed = False
        self.lines = 0
        self.where = ""

    def trace(self, frame, event, arg):
        return self._line if frame.f_code.co_filename == runner.__file__ else None

    def _line(self, frame, event, arg):
        if event == "line" and self.armed:
            self.lines += 1
            if self.lines == self.at:
                self.where = f"runner.py:{frame.f_lineno} in {frame.f_code.co_name}"
                signal.raise_signal(signal.SIGINT)
        return self._line


def _under_ctrl_c(monkeypatch: pytest.MonkeyPatch, work: tuple[dict, dict], directory: Path, ctrl_c: _CtrlC,
                  sweep: str) -> bool:
    """One replayed run of ``work`` into ``directory`` with ``ctrl_c`` armed where ``sweep`` starts; whether it
    raised ``KeyboardInterrupt``.

    ``"preflight"`` arms once preflight is done and disarms at the first game; ``"second"`` arms as a first Ctrl+C
    stops the games after game 0; ``"last"`` arms once the last game is recorded.
    """
    config, recorded = work

    def replayed_preflight(config, run_secret, *, pin):
        pin.check(recorded["setup"].engine)                      # as preflight pins it
        ctrl_c.armed = sweep == "preflight"
        return recorded["setup"]

    def replayed_play_one(config, setup, context, **keywords):
        if sweep == "preflight":
            ctrl_c.armed = False
        return recorded[context.game_index]

    def on_game(row) -> None:
        if sweep == "second" and row.game_index == 0:
            ctrl_c.armed = True
            signal.raise_signal(signal.SIGINT)                   # the first Ctrl+C, while games play
        elif sweep == "last" and row.game_index == 1:
            ctrl_c.armed = True

    monkeypatch.setattr(runner, "preflight", replayed_preflight)
    monkeypatch.setattr(runner, "play_one", replayed_play_one)
    tracing = sys.gettrace()
    sys.settrace(ctrl_c.trace)
    try:
        run(config, output_dir=directory, on_game=on_game)
    except KeyboardInterrupt:
        return True
    finally:
        sys.settrace(tracing)
    return False


def _sweep(monkeypatch: pytest.MonkeyPatch, work: tuple[dict, dict], tmp_path: Path,
           sweep: str) -> list[tuple[str, Path]]:
    """The run once per line the sweep covers, with a Ctrl+C on that line; each must raise ``KeyboardInterrupt``.
    Returns, in line order, where each Ctrl+C landed and the run's directory."""
    counting = _CtrlC()
    _under_ctrl_c(monkeypatch, work, tmp_path / "counted", counting, sweep)
    assert counting.lines > 10                                   # the sweep covers the phase's lines
    runs = []
    for at in range(1, counting.lines + 1):
        ctrl_c, directory = _CtrlC(at), tmp_path / f"line-{at}"
        assert _under_ctrl_c(monkeypatch, work, directory, ctrl_c, sweep), f"Ctrl+C at {ctrl_c.where}: not raised"
        runs.append((ctrl_c.where, directory))
    return runs


def _published(directory: Path, where: str = "") -> dict:
    """The run's manifest, checked against its files: every digest verifies, and the ledger holds exactly the games
    the manifest counts, a prefix of the schedule (spec 11.6, R3-13). ``where`` names the Ctrl+C in a failure."""
    assert (directory / "manifest.json").is_file(), f"Ctrl+C at {where}: a committed run without its manifest"
    document = manifest(directory)
    assert store.verify_file_digests(directory, document) == [], where
    assert [row["game_index"] for row in ledger_rows(directory)] == list(range(document["games"]["total"])), where
    assert document["secrets"]["run_secret"] == TEST_RUN_SECRET.hex()
    return document


def test_a_second_ctrl_c_on_any_line_after_the_first_waits_for_the_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recorded_engine_work: tuple[dict, dict]
) -> None:
    """A first Ctrl+C stops the games after game 0; a second lands on each line from there to the end, the start
    of the publish included, where it used to escape before the manifest (uv delivers every Ctrl+C twice)."""
    for where, directory in _sweep(monkeypatch, recorded_engine_work, tmp_path, "second"):
        document = _published(directory, where)
        assert (document["run"]["status"], document["games"]["total"]) == ("aborted", 1), where


def test_a_single_ctrl_c_on_any_line_after_the_last_game_publishes_the_complete_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recorded_engine_work: tuple[dict, dict]
) -> None:
    """Once the last game is recorded, one Ctrl+C on any line still leaves the complete run's manifest, and is then
    raised (R3-13, R3-31)."""
    for where, directory in _sweep(monkeypatch, recorded_engine_work, tmp_path, "last"):
        document = _published(directory, where)
        assert (document["run"]["status"], document["games"]["total"]) == ("complete", 2), where


def test_a_ctrl_c_on_any_line_before_the_first_game_publishes_every_committed_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recorded_engine_work: tuple[dict, dict]
) -> None:
    """From the end of preflight to the first game: a Ctrl+C before the commitment is written leaves nothing
    committed, and one after it leaves the run published as aborted with no game (spec 11.6)."""
    committed = 0
    for where, directory in _sweep(monkeypatch, recorded_engine_work, tmp_path, "preflight"):
        if (directory / "COMMITMENT.json").exists():
            committed += 1
            document = _published(directory, where)
            assert (document["run"]["status"], document["games"]["total"]) == ("aborted", 0), where
        else:
            assert not (directory / "manifest.json").exists(), where
    assert committed > 0


def test_ctrl_c_held_until_the_manifest_reaches_the_handler_found_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Whatever handler the run found, a Ctrl+C stops the games; the ones that land while the run publishes are
    held and reach that handler once, after the manifest is written (R3-31)."""
    directory = tmp_path / "t"
    deliveries: list[bool] = []
    signal.signal(signal.SIGINT, lambda signum, frame: deliveries.append((directory / "manifest.json").is_file()))
    publish = store.publish_manifest

    def publish_under_ctrl_c(directory: Path, document: dict) -> bytes:
        signal.raise_signal(signal.SIGINT)                 # two more Ctrl+C while the manifest is written
        signal.raise_signal(signal.SIGINT)
        return publish(directory, document)

    monkeypatch.setattr(store, "publish_manifest", publish_under_ctrl_c)

    def interrupt(row) -> None:
        if row.game_index == 0:
            signal.raise_signal(signal.SIGINT)             # the first Ctrl+C stops the games

    with pytest.raises(KeyboardInterrupt):
        run(make_config(directory, SWEEP_BOTS, pairs=1, include_self_play=False), on_game=interrupt)
    assert deliveries == [True]
    assert _published(directory)["run"]["status"] == "aborted"


def test_the_handler_holds_before_it_raises(tmp_path: Path) -> None:
    """A second Ctrl+C right behind the first, before anything has caught the ``KeyboardInterrupt``, is already
    held: it reaches the handler found once, after the manifest (R3-31)."""
    directory = tmp_path / "t"
    deliveries: list[bool] = []
    signal.signal(signal.SIGINT, lambda signum, frame: deliveries.append((directory / "manifest.json").is_file()))

    def interrupt(row) -> None:
        if row.game_index == 0:
            try:
                signal.raise_signal(signal.SIGINT)         # stops the games
            finally:
                signal.raise_signal(signal.SIGINT)         # while the first unwinds

    with pytest.raises(KeyboardInterrupt):
        run(make_config(directory, SWEEP_BOTS, pairs=1, include_self_play=False), on_game=interrupt)
    assert deliveries == [True]
    assert _published(directory)["run"]["status"] == "aborted"


def test_a_run_that_ignores_sigint_keeps_ignoring_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``nohup`` or a background job: Ctrl+C neither stops the games nor reaches the run after its manifest."""
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    seen: list[object] = []
    publish = store.publish_manifest

    def publish_under_ctrl_c(directory: Path, document: dict) -> bytes:
        signal.raise_signal(signal.SIGINT)
        return publish(directory, document)

    def interrupt(row) -> None:
        seen.append(signal.getsignal(signal.SIGINT))
        signal.raise_signal(signal.SIGINT)

    monkeypatch.setattr(store, "publish_manifest", publish_under_ctrl_c)
    try:
        summary = run(make_config(tmp_path / "t", SWEEP_BOTS, pairs=1, include_self_play=False), on_game=interrupt)
    except KeyboardInterrupt:
        pytest.fail("a Ctrl+C reached a run that ignores SIGINT")    # fail the test, not the session
    assert summary.status == "complete" and seen == [signal.SIG_IGN, signal.SIG_IGN]
    assert signal.getsignal(signal.SIGINT) == signal.SIG_IGN


def test_a_run_off_the_main_thread_installs_no_handler_and_publishes(tmp_path: Path) -> None:
    """Signal handlers belong to the main thread: elsewhere the run leaves SIGINT to it, and still publishes."""
    seen: list[object] = []
    summaries: list[runner.TournamentSummary] = []
    config = make_config(tmp_path / "t", SWEEP_BOTS, pairs=1, include_self_play=False)
    thread = threading.Thread(target=lambda: summaries.append(run(config, on_game=lambda row: seen.append(
        signal.getsignal(signal.SIGINT)))))
    thread.start()
    thread.join()
    assert [summary.status for summary in summaries] == ["complete"]
    assert seen == [signal.default_int_handler, signal.default_int_handler]


def test_the_cli_records_the_cores_each_game_declares(tmp_path: Path) -> None:
    resources = {"cpus": 1, "memory_mb": 4096, "gpu": False, "engine_cpus": 2}
    value = make_config(tmp_path / "t", SWEEP_BOTS, pairs=1, include_self_play=False, resources=resources)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    assert cli.main(["run", str(path)]) == 0
    per_game = TournamentConfig.from_json(value).per_game_cores()
    assert manifest(tmp_path / "t")["allocation"]["per_game_cores"] == per_game == 2   # the cap the runner applied (spec 11.4)


def test_no_published_file_names_the_machine_unless_the_alias_is_set_to_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The allocation's host is an alias, ``local`` by default, never ``platform.node()`` (R3-28)."""
    name = "machine-name-7f3a9c"
    monkeypatch.setattr(platform, "node", lambda: name)
    monkeypatch.delenv("SPELLBENCH_HOST_ALIAS", raising=False)
    for label, alias in (("default", None), ("aliased", name)):
        if alias is not None:
            monkeypatch.setenv("SPELLBENCH_HOST_ALIAS", alias)
        directory = tmp_path / label
        path = tmp_path / f"{label}.json"
        path.write_text(json.dumps(make_config(directory, SWEEP_BOTS, pairs=1, include_self_play=False)), encoding="utf-8")
        assert cli.main(["run", str(path)]) == 0
        assert manifest(directory)["allocation"]["host"] == (alias or "local")
        named = sorted(file.name for file in directory.iterdir() if name.encode() in file.read_bytes())
        assert named == ([] if alias is None else ["manifest.json"])


def test_the_ported_one_land_bot_plays_v2(tmp_path: Path) -> None:
    one_land = subprocess_bot("one-land", [sys.executable, str(TESTS_DIR / "bot_one_land.py")])
    directory = tmp_path / "t"
    summary = run(make_config(directory, [one_land, builtin("heuristic"), builtin("first")], pairs=1, include_self_play=False))
    assert (summary.status, summary.games_total, summary.games_rated) == ("complete", 6, 6)
    for row in ledger_rows(directory):
        names = [seat["name"] for seat in row["seats"]]
        if "one-land" in names:
            winner = names[("p0", "p1").index(row["winner"])]
            assert winner == ("heuristic" if "heuristic" in names else "one-land")    # one land: beats first, loses to heuristic


def test_the_ported_slow_start_bot_plays_v2_within_its_startup_budget(tmp_path: Path) -> None:
    slow = subprocess_bot("slow", [sys.executable, str(BOT_SLOW_START), "0.5"])
    summary = run(make_config(tmp_path / "t", [builtin("first"), slow], pairs=1, include_self_play=False))
    assert (summary.status, summary.games_total, summary.games_forfeit) == ("complete", 2, 0)


def _default_sigint() -> None:
    """Run in the CLI child before it starts: SIGINT back to its default disposition, so the child's Python
    installs its KeyboardInterrupt handler even when the shell started the tests with SIGINT ignored."""
    signal.signal(signal.SIGINT, signal.SIG_DFL)


@pytest.mark.skipif(os.name == "nt", reason="POSIX signals; the in-process interrupts above cover Windows")
@pytest.mark.parametrize("workers", [1, 2])
def test_a_real_ctrl_c_publishes_the_run_as_aborted_and_the_command_exits_nonzero(tmp_path: Path, workers: int) -> None:
    """Review Focus 2: SIGINT to ``spellbench run`` mid-run leaves a manifest with status aborted, the games finished
    so far and the revealed run secret, and a nonzero exit."""
    directory = tmp_path / "t"
    path = tmp_path / "config.json"
    path.write_text(json.dumps(make_config(directory, BOTS, pairs=20, workers=workers)), encoding="utf-8")
    # spellbench run, in a child that sees room above the 60 GiB reserve, as the in-process tests do (Decision 10).
    child = ROOMY_CHILD + "import sys\nfrom spellbench.arena import cli\nsys.exit(cli.main(sys.argv[1:]))\n"
    process = subprocess.Popen([sys.executable, "-c", child, "run", str(path)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, preexec_fn=_default_sigint)
    try:
        deadline = time.monotonic() + 120
        ledger_path = directory / "matches.jsonl"
        while not (ledger_path.is_file() and ledger_path.read_bytes().count(b"\n") >= 1):
            assert process.poll() is None, "the run ended before the interrupt"
            assert time.monotonic() < deadline, "no game was recorded in time"
            time.sleep(0.05)
        process.send_signal(signal.SIGINT)
        process.communicate(timeout=120)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()
    assert process.returncode != 0
    document = manifest(directory)
    commitment = json.loads((directory / "COMMITMENT.json").read_text(encoding="utf-8"))["commitment"]
    assert document["run"]["status"] == "aborted" and document["secrets"]["commitment"] == commitment
    assert hashlib.sha256(bytes.fromhex(document["secrets"]["run_secret"])).hexdigest() == commitment
    rows = ledger_rows(directory)
    assert 1 <= len(rows) == document["games"]["total"] < document["games"]["scheduled"]
    assert [row["game_index"] for row in rows] == list(range(len(rows)))
