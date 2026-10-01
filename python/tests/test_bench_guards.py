"""COMPUTE-POLICY and ARTIFACT-LAW guards on the launch paths (Decision 10).

The disk the reserve check reads, the memory and the GPUs are faked (``arena_helpers.roomy_machine``), so no test
needs 60 GiB free; every git command acts on a throwaway repository under ``tmp_path`` whose ``origin`` is a local
bare repository (``test_bench_commit.git_guard``).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from spellbench.arena import cli, qualification, runner, throughput
from spellbench.arena.config import TournamentConfig
from spellbench.arena.schedule import schedule
from spellbench.bench.commit import check_definition, commit_run
from spellbench.bench.definition import BenchmarkError
from spellbench.bench.run import EVIDENCE_NAME, rerun_games, run_benchmark, run_files
from spellbench.run_secret import RunSecret

from arena_helpers import (
    MINIMAL_BOT, ROOMY_FREE_BYTES, builtin, make_config, roomy_machine, run, small_allocation, subprocess_bot,
)
from test_bench_commit import PLACEMENT, env, git, git_guard, repo  # noqa: F401  (fixtures this module reuses)
from test_bench_run import ENVIRON, _write_benchmark

PROOF = "https://example.org/i/1"


@pytest.fixture(autouse=True)
def _roomy_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    roomy_machine(monkeypatch)


def _cores(monkeypatch: pytest.MonkeyPatch, count: int = 4) -> None:
    """This many usable CPUs, for the plan and for the runner's cap alike, whatever machine runs the tests."""
    for module in (qualification, runner):
        monkeypatch.setattr(module, "usable_cpus", lambda cpu_count=None: count if cpu_count is None else cpu_count)


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
        "    json.dump(known, open(rows, 'w'))\n", encoding="utf-8", newline="\n")
    return script, log


def _calls(log: Path) -> list[list[str]]:
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []


def _statuses(calls: list[list[str]]) -> list[tuple[str, str]]:
    """The catalog status each add or update of the register script set, in order."""
    return [(call[0], call[call.index("--status") + 1]) for call in calls if call[0] in ("add", "update")]


def _committed(repo: Path, environ: dict) -> str:
    """bench commit commits and pushes the commitment itself (Task 41)."""
    return commit_run(repo / "benchmarks" / "fake-pool", date="2026-10-01", placement=PLACEMENT, environ=environ).run_dir.name


def _manifest(directory: Path) -> dict:
    return json.loads((directory / "manifest.json").read_text(encoding="utf-8"))


def _config_file(tmp_path: Path, directory: Path, bots: list, *, engine_command: list | None = None, **extra) -> Path:
    value = make_config(directory, bots, **extra)
    if engine_command is not None:
        value["engine"] = {"command": engine_command}
    path = tmp_path / f"{directory.name}.json"
    path.write_text(json.dumps(value), encoding="utf-8", newline="\n")
    return path


def test_a_rated_run_is_measured_pinned_and_registered(repo: Path, tmp_path: Path, monkeypatch) -> None:
    script, log = _register_script(tmp_path)
    environ = {**env(tmp_path), "SPELLBENCH_ARTIFACT_REGISTER": str(script)}
    name = _committed(repo, environ)
    before_the_run = []
    real_run = runner.run_tournament

    def spy(config, **kwargs):                        # what exists when the run's first game is about to start
        before_the_run.append(([path.name for path in (tmp_path / "pins").rglob("*") if path.is_file()], _calls(log)))
        return real_run(config, **kwargs)

    monkeypatch.setattr(runner, "run_tournament", spy)
    result = run_benchmark(repo / "benchmarks" / "fake-pool", run=name, proof=PROOF, environ=environ)
    manifest = _manifest(result.run_dir)
    allocation = manifest["allocation"]
    assert allocation["kind"] == "small" and manifest["run"]["rated"] is True
    assert allocation["spot_check"] == {**allocation["spot_check"], "game_index": allocation["games_total"] // 2,
                                        "passed": True}               # a small run is rated once spot-checked
    assert allocation["budget"]["projected_bytes"] > allocation["budget"]["pinned_bytes"] > 0
    assert allocation["host"] == "local" and allocation["machine"]["free_bytes"] == {"pin_root": ROOMY_FREE_BYTES,
                                                                                    "run_dir": ROOMY_FREE_BYTES}
    engine_file = next(entry for entry in manifest["engine_files"] if entry["file_name"] == "fake_v2_engine.py")
    assert (tmp_path / "pins" / engine_file["sha256"] / "fake_v2_engine.py").is_file()
    [(pinned, registered)] = before_the_run                             # pinned and catalogued live first (R3-7)
    assert "fake_v2_engine.py" in pinned and _statuses(registered)[0] == ("add", "live")
    calls = _calls(log)
    statuses = _statuses(calls)
    assert statuses[0] == ("add", "live") and ("update", "frozen") in statuses       # live at pinning, frozen at closure
    tree = [call for call in calls if call[0] == "add" and Path(call[2]) == result.run_dir]    # the run directory itself
    assert len(tree) == 1 and tree[0][tree[0].index("--status") + 1] == "closed"
    assert tree[0][tree[0].index("--retention") + 1] == "keep-full" and Path(tree[0][tree[0].index("--doc") + 1]).name == "manifest.json"
    assert result.failures == ()
    assert (repo / "benchmarks" / "fake-pool" / EVIDENCE_NAME).is_file()          # the local evidence (R1-6)
    assert git(repo, "status", "--porcelain", "--untracked-files=all", "--", "benchmarks/fake-pool/throughput-evidence.jsonl") == ""
    trials = tuple((repo / "benchmarks/fake-pool/.qualification-records").glob("qualification-*/*.jsonl"))
    assert trials and all(path.stat().st_size > 0 for path in trials)
    check_definition(repo / "benchmarks/fake-pool", manifest["secrets"]["commitment_proof"]["commit"])


def test_a_rated_run_without_pin_values_stops_and_is_revealed(repo: Path, tmp_path: Path) -> None:
    name = _committed(repo, env(tmp_path))
    environ = {key: value for key, value in env(tmp_path).items() if key != "SPELLBENCH_PIN_ROOT"}
    with pytest.raises(BenchmarkError, match="SPELLBENCH_PIN_ROOT"):
        run_benchmark(repo / "benchmarks" / "fake-pool", run=name, proof=PROOF, environ=environ)
    run_dir = repo / "benchmarks" / "fake-pool" / "runs" / name
    assert json.loads((run_dir / "REVEAL.json").read_text(encoding="utf-8"))["reason"] == "guard"
    assert not (run_dir / "matches.jsonl").exists()


def test_a_committed_run_the_reserve_refuses_is_revealed_before_its_first_game(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    name = _committed(repo, env(tmp_path))
    roomy_machine(monkeypatch, free=lambda path: throughput.RESERVE_BYTES - 1)     # a full disk (ARTIFACT-LAW clause 1)
    with pytest.raises(throughput.ThroughputError, match="60 GiB"):
        run_benchmark(repo / "benchmarks" / "fake-pool", run=name, proof=PROOF, environ=env(tmp_path))
    run_dir = repo / "benchmarks" / "fake-pool" / "runs" / name
    assert json.loads((run_dir / "REVEAL.json").read_text(encoding="utf-8"))["reason"] == "guard"
    assert not (tmp_path / "pins").exists()                                        # planned before anything is pinned


def test_a_substantial_run_needs_a_placement_and_compares_worker_counts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(qualification, "SUBSTANTIAL_RUN_SECONDS", 0)
    monkeypatch.setattr(qualification, "QUALIFY_BUDGET_PERCENT", 100)      # the comparison fits an 18-game schedule
    _cores(monkeypatch)
    bench = _write_benchmark(tmp_path / "benchmarks", workers=2)
    with pytest.raises(throughput.ThroughputError, match="placement"):
        run_benchmark(bench, unrated=True, date="2026-10-01", environ=ENVIRON)
    assert not (bench / "runs").exists()
    result = run_benchmark(bench, unrated=True, date="2026-10-02", placement=PLACEMENT, environ=ENVIRON)
    allocation = _manifest(result.run_dir)["allocation"]
    assert allocation["kind"] == "substantial" and allocation["outputs_identical"] is True
    trials = allocation["trials"]
    assert [trial["workers"] for trial in trials] == [1, 2] and len({tuple(trial["indices"]) for trial in trials}) == 1
    assert allocation["placement"] == throughput.Placement.parse(PLACEMENT).to_json() and allocation["machine"]["free_bytes"]
    assert result.failures == ()


def test_a_run_below_the_60_gib_reserve_is_refused(tmp_path: Path, monkeypatch) -> None:
    roomy_machine(monkeypatch, free=lambda path: throughput.RESERVE_BYTES)     # nothing to spare
    bench = _write_benchmark(tmp_path / "benchmarks")
    with pytest.raises(throughput.ThroughputError, match="60 GiB"):
        run_benchmark(bench, unrated=True, date="2026-10-01", environ=ENVIRON)              # ARTIFACT-LAW clause 1 (R3-7)
    assert not (bench / "runs").exists()


def test_the_reserve_is_checked_again_once_the_plan_is_done(tmp_path: Path, monkeypatch) -> None:
    """The disk may fill while the qualification plays: the reserve is read afresh before the first game."""
    filled = []
    real_plan = qualification.plan_allocation

    def plan_then_fill(**kwargs):
        allocation = real_plan(**kwargs)
        filled.append(True)
        return allocation

    monkeypatch.setattr("spellbench.bench.run.plan_allocation", plan_then_fill)
    roomy_machine(monkeypatch, free=lambda path: throughput.RESERVE_BYTES - 1 if filled else ROOMY_FREE_BYTES)
    bench = _write_benchmark(tmp_path / "benchmarks")
    with pytest.raises(throughput.ThroughputError, match="60 GiB"):
        run_benchmark(bench, unrated=True, date="2026-10-01", environ=ENVIRON)
    assert filled and not (bench / "runs").exists()


def test_bot_commands_and_checkpoints_are_pinned_with_the_engine(tmp_path: Path) -> None:
    checkpoint = tmp_path / "model.ckpt"
    checkpoint.write_bytes(b"weights")
    bots = [builtin("uniform"), subprocess_bot("minimal", [sys.executable, str(MINIMAL_BOT)], checkpoint=str(checkpoint))]
    files = run_files(TournamentConfig.from_json(make_config(tmp_path / "t", bots)))
    names = [file.file_name for file in files]
    assert names.index("fake_v2_engine.py") < names.index("minimal_bot.py") < names.index("model.ckpt")   # R3-7
    assert len({(file.file_name, file.sha256) for file in files}) == len(files)    # the shared interpreter once


def test_a_rerun_is_planned_like_a_run(tmp_path: Path, monkeypatch) -> None:
    result = run_benchmark(_write_benchmark(tmp_path / "benchmarks", workers=2), unrated=True, date="2026-10-01",
                           environ=ENVIRON)
    planned, played = [], []
    monkeypatch.setattr("spellbench.bench.run.plan_for", lambda config, **kwargs: planned.append(kwargs) or small_allocation())
    real_play = runner.play_games
    monkeypatch.setattr(runner, "play_games", lambda *args, **kwargs: played.append(kwargs["workers"]) or real_play(*args, **kwargs))
    assert rerun_games(result.run_dir, games=[0], environ=ENVIRON) == []                  # a guarded launch path (R3-6)
    assert [kwargs["games"] for kwargs in planned] == [[0]] and played == [1]          # the planned workers, not 2


def test_spellbench_run_is_guarded_too(tmp_path: Path, monkeypatch, capsys) -> None:
    _cores(monkeypatch)
    bots = [builtin("uniform"), builtin("first")]
    first = _config_file(tmp_path, tmp_path / "t", bots, pairs=1, include_self_play=False, workers=4)
    assert cli.main(["run", str(first)]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == "allocation: small (2 workers)"    # two games, never 4 workers
    allocation = _manifest(tmp_path / "t")["allocation"]
    assert allocation["kind"] == "small" and allocation["reused"] is False and (tmp_path / EVIDENCE_NAME).is_file()
    second = _config_file(tmp_path, tmp_path / "u", bots, pairs=1, include_self_play=False, workers=4)
    assert cli.main(["run", str(second)]) == 0                                             # unchanged conditions (R1-6)
    assert _manifest(tmp_path / "u")["allocation"]["reused"] is True


def test_qualification_samples_across_the_matchups(tmp_path: Path, capsys) -> None:
    """The probe plays each matchup's first game before any matchup's second, whatever the schedule opens with (R3-6)."""
    bots = [builtin("first"), builtin("uniform"), builtin("heuristic")]
    path = _config_file(tmp_path, tmp_path / "t", bots, pairs=2, include_self_play=False)
    assert cli.main(["run", str(path)]) == 0
    contexts = schedule(TournamentConfig.from_json(make_config(tmp_path / "t", bots, pairs=2, include_self_play=False)),
                        RunSecret.generate())
    firsts = [next(context.game_index for context in contexts if context.matchup_index == matchup) for matchup in range(3)]
    probe = _manifest(tmp_path / "t")["allocation"]["probe"]
    assert probe["indices"] == firsts[: probe["games"]] and probe["games"] >= 2 and firsts[1] > 1


def test_guard_errors_are_cli_errors(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(qualification, "SUBSTANTIAL_RUN_SECONDS", 0)
    monkeypatch.setattr(qualification, "QUALIFY_BUDGET_PERCENT", 10**6)    # the comparison fits a 2-game schedule
    path = _config_file(tmp_path, tmp_path / "t", [builtin("uniform"), builtin("first")], pairs=1, include_self_play=False)
    assert cli.main(["run", str(path)]) == 1                                                 # substantial, no --placement
    assert "error:" in capsys.readouterr().err and not (tmp_path / "t").exists()           # not a traceback (R3-29)
    engine = _config_file(tmp_path, tmp_path / "u", [builtin("uniform"), builtin("first")], pairs=1,
                          engine_command=["no-such-engine-program-43"])
    assert cli.main(["run", str(engine)]) == 1                                               # a PinningError
    assert "error: the program 'no-such-engine-program-43' is not on the PATH" in capsys.readouterr().err


def test_bench_run_prints_its_allocation_last(tmp_path: Path, monkeypatch, capsys) -> None:
    for name, value in ENVIRON.items():
        monkeypatch.setenv(name, value)
    directory = _write_benchmark(tmp_path)
    assert cli.main(["bench", "run", str(directory), "--unrated", "--date", "2026-10-01"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[-2:] == ["validate: OK", "allocation: small (1 workers)"]


def test_idle_warnings_go_to_an_unhashed_file(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(throughput.IdleMonitor, "tick", lambda self, *, running, queued, completed=0: "idle capacity: test")
    monkeypatch.setattr(throughput.CpuSampler, "sample", lambda self: 0.5)
    run(make_config(tmp_path / "t", [builtin("uniform"), builtin("first")], pairs=2, workers=2))
    assert "idle capacity: test" in (tmp_path / "t" / "throughput.jsonl").read_text(encoding="utf-8")
    assert "idle capacity: test" in capsys.readouterr().err                                # as it happens (R3-6)
    files = [entry["path"] for entry in _manifest(tmp_path / "t")["files"]]
    assert "throughput.jsonl" not in files
