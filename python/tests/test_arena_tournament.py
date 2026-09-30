"""The v2 tournament: commitment first, opaque ids, the manifest, invalid and aborted runs."""

from __future__ import annotations

import json
import os
import signal
import subprocess
from pathlib import Path

import pytest

from spellbench.arena import cli, config as config_module, leaderboard, ledger, manifest as manifest_module, runner, store

from arena_helpers import (
    HOSTILE_ENGINE, TEST_RUN_SECRET, TESTS_DIR, builtin, cli_bot, ledger_rows, make_config, manifest, run, subprocess_bot,
)

BOTS = [builtin("uniform", seed=11), builtin("heuristic"), builtin("first")]
DATA = ("registry.json", "matches.jsonl", "leaderboard.json", "LEADERBOARD.md", "COMMITMENT.json")


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
