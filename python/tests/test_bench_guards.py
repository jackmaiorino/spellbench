"""COMPUTE-POLICY and ARTIFACT-LAW guards on the launch paths."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from spellbench.arena import cli, qualification, throughput
from spellbench.arena.config import TournamentConfig
from spellbench.arena.throughput import MachineFacts
from spellbench.bench.commit import commit_run
from spellbench.bench.definition import BenchmarkError
from spellbench.bench.run import rerun_games, run_benchmark, run_files

from arena_helpers import MINIMAL_BOT, builtin, make_config, run, small_allocation, subprocess_bot
from test_bench_commit import PLACEMENT, env, git, repo  # noqa: F401  (repo is a fixture this module reuses)
from test_bench_run import ENVIRON, _write_benchmark


def _substantial(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the substantial class: a zero threshold, and a comparison budget the ladder always fits.

    The rules are patched where they are read (``arena.qualification``); the merged
    rules also need the scaling comparison to fit the budget for the substantial
    class, which the plan's threshold patch alone does not cover.
    """
    monkeypatch.setattr(qualification, "SUBSTANTIAL_RUN_SECONDS", 0)
    monkeypatch.setattr(qualification, "QUALIFY_BUDGET_PERCENT", 100)


def _register_script(tmp_path: Path) -> tuple[Path, Path]:
    """A stand-in for collab's artifact_register.py: logs every call and remembers added rows for show."""
    log, rows = tmp_path / "register.log", tmp_path / "rows.json"
    script = tmp_path / "register_log.py"
    script.write_text(
        "import json, os, sys\n"
        f"log, rows = {str(log)!r}, {str(rows)!r}\n"
        "open(log, 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "known = json.load(open(rows)) if os.path.exists(rows) else {}\n"
        "command, key = sys.argv[1], sys.argv[3]\n"
        "if command == 'show':\n"
        "    print(json.dumps(known[key]) if key in known else 'not found')\n"
        "elif command == 'add':\n"
        "    known[key] = {'id': key, 'note': sys.argv[sys.argv.index('--note') + 1] if '--note' in sys.argv else ''}\n"
        "    json.dump(known, open(rows, 'w'))\n", encoding="utf-8")
    return script, log


def _committed(repo: Path, environ: dict) -> str:
    """bench commit commits and pushes the commitment itself (Task 41)."""
    return commit_run(repo / "benchmarks" / "fake-pool", date="2026-10-01", placement=PLACEMENT, environ=environ).run_dir.name


def test_a_rated_run_is_measured_pinned_and_registered(repo: Path, tmp_path: Path) -> None:
    script, log = _register_script(tmp_path)
    environ = {**env(tmp_path), "SPELLBENCH_ARTIFACT_REGISTER": str(script)}
    name = _committed(repo, environ)
    result = run_benchmark(repo / "benchmarks" / "fake-pool", run=name, proof="https://example.org/i/1", environ=environ)
    manifest = json.loads((result.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["allocation"]["kind"] == "small" and manifest["run"]["rated"] is True
    assert manifest["allocation"]["budget"]["projected_bytes"] > 0 and manifest["allocation"]["host"] == "local"
    engine_file = next(entry for entry in manifest["engine_files"] if entry["file_name"] == "fake_v2_engine.py")
    assert (tmp_path / "pins" / engine_file["sha256"] / "fake_v2_engine.py").is_file()
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    statuses = [(call[0], call[call.index("--status") + 1]) for call in calls if call[0] in ("add", "update")]
    assert statuses[0] == ("add", "live") and ("update", "frozen") in statuses       # live at pinning, frozen at closure (R3-7)
    assert any(call[0] == "add" and call[2] == str(result.run_dir) for call in calls)  # the run directory itself
    assert result.failures == ()


def test_a_rated_run_without_pin_values_stops_and_is_revealed(repo: Path, tmp_path: Path) -> None:
    name = _committed(repo, env(tmp_path))
    environ = {key: value for key, value in env(tmp_path).items() if key != "SPELLBENCH_PIN_ROOT"}
    with pytest.raises(BenchmarkError, match="SPELLBENCH_PIN_ROOT"):
        run_benchmark(repo / "benchmarks" / "fake-pool", run=name, proof="https://example.org/i/1", environ=environ)
    run_dir = repo / "benchmarks" / "fake-pool" / "runs" / name
    assert json.loads((run_dir / "REVEAL.json").read_text(encoding="utf-8"))["reason"] == "guard"
    assert not (run_dir / "matches.jsonl").exists()


def test_a_substantial_run_needs_a_placement_and_compares_worker_counts(tmp_path: Path, monkeypatch) -> None:
    _substantial(monkeypatch)
    bench = _write_benchmark(tmp_path / "benchmarks", workers=2)
    with pytest.raises(throughput.ThroughputError, match="placement"):
        run_benchmark(bench, unrated=True, date="2026-10-01", environ=ENVIRON)
    result = run_benchmark(bench, unrated=True, date="2026-10-02", placement=PLACEMENT, environ=ENVIRON)
    allocation = json.loads((result.run_dir / "manifest.json").read_text(encoding="utf-8"))["allocation"]
    assert allocation["kind"] == "substantial" and allocation["outputs_identical"] is True
    trials = allocation["trials"]
    assert [trial["workers"] for trial in trials] == [1, 2] and len({trial["games"] for trial in trials}) == 1   # R3-15
    assert allocation["placement"] == throughput.Placement.parse(PLACEMENT).to_json() and allocation["machine"]["free_bytes"]


def test_a_run_below_the_60_gib_reserve_is_refused(tmp_path: Path, monkeypatch) -> None:
    # A full disk: every volume reports exactly the reserve, so the projection crosses it (ARTIFACT-LAW clause 1).
    full = MachineFacts(memory_bytes=None, gpus=(),
                        free_bytes=(("pin_root", throughput.RESERVE_BYTES), ("run_dir", throughput.RESERVE_BYTES)))
    monkeypatch.setattr(qualification, "machine_facts", lambda volumes: full)
    bench = _write_benchmark(tmp_path / "benchmarks")
    with pytest.raises(throughput.ThroughputError, match="60 GiB"):
        run_benchmark(bench, unrated=True, date="2026-10-01", environ=ENVIRON)              # R3-7
    assert not (bench / "runs").exists()


def test_bot_commands_and_checkpoints_are_pinned_with_the_engine(tmp_path: Path) -> None:
    checkpoint = tmp_path / "model.ckpt"
    checkpoint.write_bytes(b"weights")
    bots = [builtin("uniform"), subprocess_bot("minimal", [sys.executable, str(MINIMAL_BOT)], checkpoint=str(checkpoint))]
    names = {file.file_name for file in run_files(TournamentConfig.from_json(make_config(tmp_path / "t", bots)))}
    assert {"fake_v2_engine.py", "minimal_bot.py", "model.ckpt"} <= names                   # ARTIFACT-LAW clause 4 (R3-7)


def test_a_rerun_is_planned_like_a_run(tmp_path: Path, monkeypatch) -> None:
    result = run_benchmark(_write_benchmark(tmp_path / "benchmarks"), unrated=True, date="2026-10-01", environ=ENVIRON)
    planned = []
    monkeypatch.setattr("spellbench.bench.run.plan_for", lambda config, **kwargs: planned.append(config) or small_allocation())
    assert rerun_games(result.run_dir, games=[0], environ=ENVIRON) == [] and planned         # a guarded launch path (R3-6)


def test_spellbench_run_is_guarded_too(tmp_path: Path, capsys) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(make_config(tmp_path / "t", [builtin("uniform"), builtin("first")], pairs=1)), encoding="utf-8")
    assert cli.main(["run", str(path)]) == 0
    assert "allocation: small (" in capsys.readouterr().out
    assert json.loads((tmp_path / "t" / "manifest.json").read_text(encoding="utf-8"))["allocation"]["kind"] == "small"


def test_guard_errors_are_cli_errors(tmp_path: Path, monkeypatch, capsys) -> None:
    _substantial(monkeypatch)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(make_config(tmp_path / "t", [builtin("uniform"), builtin("first")], pairs=1)), encoding="utf-8")
    assert cli.main(["run", str(path)]) == 1                                                 # substantial, no --placement
    assert "error:" in capsys.readouterr().err                                               # not a traceback (R3-29)


def test_idle_warnings_go_to_an_unhashed_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(throughput.IdleMonitor, "tick", lambda self, *, running, queued, completed=0: "idle capacity: test")
    run(make_config(tmp_path / "t", [builtin("uniform"), builtin("first")], pairs=2, workers=2))
    assert "idle capacity: test" in (tmp_path / "t" / "throughput.jsonl").read_text(encoding="utf-8")
    files = [entry["path"] for entry in json.loads((tmp_path / "t" / "manifest.json").read_text(encoding="utf-8"))["files"]]
    assert "throughput.jsonl" not in files
