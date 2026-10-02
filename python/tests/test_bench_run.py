"""Benchmark runs: placeholders resolved at run time, dated run directories, unrated tries."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from spellbench.arena import cli
from spellbench.arena.config import DeckSpec, TournamentConfig
from spellbench.bench import definition
from spellbench.bench.definition import BenchmarkError
from spellbench.bench.run import run_benchmark

from arena_helpers import FAKE_ENGINE, roomy_machine

REPO = Path(__file__).resolve().parents[2]
ENVIRON = {"PY": sys.executable, "FAKE_ENGINE": str(FAKE_ENGINE)}
PUBLISHED = ("COMMITMENT.json", "manifest.json", "config.json", "registry.json", "matches.jsonl", "leaderboard.json",
             "LEADERBOARD.md")
KERNEL_MODEL_STATES = {
    "g115": "8139016ca561961714f25e22a9d6f7fc888548fc332e45b6bce402dfc43159f2",
    "a48": "774e936da26468358257774fe41ae94578265b331d2edb49d017c0835b08699a",
    "c12": "5c14c025e3cc87fb2c3eea28e1dbd770d7d257344174296d6259020f720da9de",
}


@pytest.fixture(autouse=True)
def _roomy_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every benchmark run is a guarded launch (Decision 10): the tests fake the disk it checks."""
    roomy_machine(monkeypatch)


def _bot(name: str, label: str, tag: str, **extra: Any) -> dict[str, Any]:
    return {
        "name": name, "version": "2.0.0", "type": "builtin", "training_style_tags": [tag], **extra,
        "display": {"label": label, "author": "Spellbench", "description": f"{label} bot", "url": None},
    }


def _write_benchmark(root: Path, **extra: Any) -> Path:
    """A v2 definition of three builtins on the fake v2 engine; ``extra`` fields are merged into it."""
    directory = root / "fake-pool"
    directory.mkdir(parents=True)
    value = {
        "schema": "spellbench-benchmark/v2",
        "id": "fake-pool",
        "title": "Fake pool",
        "summary": "Three decks on the fake v2 engine.",
        "format": "pauper-bo1",
        "engine": {"name": "fake-v2-engine", "command": ["${PY}", "${FAKE_ENGINE}"]},
        "deck_pool": ["Burn", "Elves", "Faeries"],
        "pairs_per_deck": 1,
        "stats_seed": 99,
        "bootstrap_replicates": 1000,
        "bots": [_bot("uniform", "random", "baseline", seed=11), _bot("heuristic", "heuristic", "heuristic"),
                 _bot("first", "first", "baseline")],
        **extra,
    }
    (directory / "benchmark.json").write_text(json.dumps(value, indent=2), encoding="utf-8")
    return directory


def test_a_run_publishes_a_dated_validated_directory(tmp_path: Path) -> None:
    result = run_benchmark(_write_benchmark(tmp_path), unrated=True, date="2026-09-26", environ=ENVIRON)
    assert result.run_dir == tmp_path / "fake-pool" / "runs" / "2026-09-26"
    assert result.failures == ()
    assert result.summary.games_total == 3 * 3 * 2  # 3 matchups x 3 pairs (one per deck) x 2 games
    assert sorted(path.name for path in result.run_dir.iterdir()) == sorted(PUBLISHED)
    manifest = json.loads((result.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["run"] == {"benchmark_id": "fake-pool", "label": "2026-09-26", "status": "complete", "rated": False}
    assert manifest["secrets"]["commitment_proof"] is None  # an unrated try proves nothing


def test_the_run_records_placeholders_and_no_local_paths(tmp_path: Path) -> None:
    result = run_benchmark(_write_benchmark(tmp_path), unrated=True, date="2026-09-26", environ=ENVIRON)
    recorded = json.loads((result.run_dir / "config.json").read_text(encoding="utf-8"))
    assert recorded["engine"]["command"] == ["${PY}", "${FAKE_ENGINE}"]
    assert recorded["tournament_dir"] == "runs/2026-09-26"
    for name in PUBLISHED:
        text = (result.run_dir / name).read_text(encoding="utf-8")
        for value in ENVIRON.values():
            assert value not in text and json.dumps(value)[1:-1] not in text, name


def test_a_second_run_the_same_day_gets_the_next_suffix(tmp_path: Path) -> None:
    directory = _write_benchmark(tmp_path)
    first = run_benchmark(directory, unrated=True, date="2026-09-26", environ=ENVIRON)
    second = run_benchmark(directory, unrated=True, date="2026-09-26", environ=ENVIRON)
    assert first.run_dir.name == "2026-09-26" and second.run_dir.name == "2026-09-26-2"
    assert definition.latest_run_dir(directory) == second.run_dir


def test_unresolved_placeholders_fail_before_any_process(tmp_path: Path) -> None:
    directory = _write_benchmark(tmp_path)
    with pytest.raises(BenchmarkError) as caught:
        run_benchmark(directory, unrated=True, date="2026-09-26", environ={})
    assert "FAKE_ENGINE" in str(caught.value) and "PY" in str(caught.value)
    assert not (directory / "runs").exists()


def test_local_json_supplies_values_and_the_environment_wins(tmp_path: Path) -> None:
    directory = _write_benchmark(tmp_path)
    (tmp_path / "local.json").write_text(json.dumps({"PY": "no-such-python", "FAKE_ENGINE": str(FAKE_ENGINE)}), encoding="utf-8")
    result = run_benchmark(directory, unrated=True, date="2026-09-26", environ={"PY": sys.executable})
    assert result.failures == ()


@pytest.mark.parametrize("arguments", [
    {},                                                          # neither committed nor unrated
    {"run": "2026-09-26", "unrated": True, "proof": "https://example.org/i/1"},
    {"run": "2026-09-26"},                                       # no proof
    {"run": "2026-09-26", "proof": " "},
    {"run": "2026-09-26", "proof": "https://example.org/i/1", "date": "2026-09-26"},
    {"run": "2026-09-26", "proof": "https://example.org/i/1", "placement": "main-pc=used: x"},
    {"run": "../elsewhere", "proof": "https://example.org/i/1"},  # a run name, never a path
    {"unrated": True, "proof": "https://example.org/i/1"},
])
def test_a_run_is_committed_or_unrated(tmp_path: Path, arguments: dict[str, Any]) -> None:
    directory = _write_benchmark(tmp_path)
    with pytest.raises(BenchmarkError):
        run_benchmark(directory, environ=ENVIRON, **arguments)
    assert not (directory / "runs").exists()


def test_an_unrated_placement_note_is_checked_before_any_process(tmp_path: Path) -> None:
    directory = _write_benchmark(tmp_path)
    with pytest.raises(BenchmarkError, match="placement"):
        run_benchmark(directory, unrated=True, date="2026-09-26", placement="this PC only", environ=ENVIRON)
    assert not (directory / "runs").exists()


def test_the_cli_runs_a_benchmark(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    for name, value in ENVIRON.items():
        monkeypatch.setenv(name, value)
    directory = _write_benchmark(tmp_path)
    assert cli.main(["bench", "run", str(directory), "--unrated", "--date", "2026-09-26"]) == 0
    assert "validate: OK" in capsys.readouterr().out


def test_cli_usage_and_input_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    directory = _write_benchmark(tmp_path)
    for argv in (["bench"], ["bench", "run"], ["bench", "run", str(directory)],  # neither --run nor --unrated
                 ["bench", "run", str(directory), "--unrated", "--date"],
                 ["bench", "run", str(directory), "--unrated", "--unrated"],
                 ["bench", "run", str(directory), "--run", "2026-09-26"],     # no --proof
                 ["bench", "run", str(directory), "--run", "2026-09-26", "--proof", "p", "--unrated"],
                 ["bench", "run", str(directory), "--run", "2026-09-26", "--proof", "p", "--date", "2026-09-26"],
                 ["bench", "run", str(directory), "--unrated", "--proof", "p"],
                 ["bench", "run", "--unrated"], ["bench", "launch", str(directory)],
                 ["bench", "commit", str(directory)], ["bench", "commit", str(directory), "--placement"],
                 ["bench", "reveal", str(directory)], ["bench", "reveal", str(directory), "--run", "a", "--run", "b"],
                 ["bench", "reveal", str(directory), "--run", "2026-09-26", "--reason", "OSError: disk full"],
                 ["bench", "reveal", str(directory), "--run", "2026-09-26", "--reason", "error", "--withheld"],
                 ["bench", "rerun", str(directory), "--game", "x"], ["bench", "rerun", str(directory), "--game"]):
        assert cli.main(argv) == 2, argv
        assert "usage:" in capsys.readouterr().err
    assert not (directory / "runs").exists()
    assert cli.main(["bench", "run", str(directory), "--unrated", "--date", "not-a-date"]) == 1
    assert "error:" in capsys.readouterr().err


def test_the_launch_definitions_parse() -> None:
    benchmark = definition.load_benchmark(REPO / "benchmarks" / "pauper-kernel")
    TournamentConfig.from_json(benchmark.tournament_config("runs/check"))
    assert definition.placeholder_names(benchmark) == (
        "A48_CHECKPOINT", "A48_SCORER_CONFIG", "C12_CHECKPOINT", "C12_SCORER_CONFIG", "G115_CHECKPOINT",
        "G115_SCORER_CONFIG", "MTG_KERNEL_BRIDGE", "MTG_KERNEL_FLAT_BOT", "MTG_KERNEL_SCORER", "PYTHON",
    )
    assert benchmark.engine_command == ("${MTG_KERNEL_BRIDGE}", "--x-kernel-flat-v4")
    assert benchmark.deck_pool == tuple(
        DeckSpec(catalog_id=name) for name in ("Wildfire", "Rally", "Affinity", "Elves", "Spy", "Burn", "CawGates", "Faeries")
    )
    assert [bot.name for bot in benchmark.bots] == ["uniform", "heuristic", "first", "g115", "a48", "c12"]
    assert benchmark.bot("uniform").display.label == "random"
    # A rated run is not replayed: the expected model state is what ties each kernel bot's name to its model.
    for name, state in KERNEL_MODEL_STATES.items():
        command = benchmark.bot(name).entry["command"]
        assert command[command.index("--expect-model-state") + 1] == state, name
    assert [item.title for item in definition.load_proposed(REPO / "benchmarks")] == ["FDN Limited", "Standard 2022-25"]


@pytest.mark.parametrize(
    "path", ["benchmarks/local.json", "benchmarks/pauper-kernel/runs/2026-09-26/diagnostics.jsonl", "site/index.html"]
)
def test_local_values_diagnostics_and_site_output_are_git_ignored(path: str) -> None:
    result = subprocess.run(["git", "check-ignore", "--no-index", "-q", path], cwd=REPO)
    assert result.returncode == 0, path


# "." has no folder name, and its parent is not the folder that holds local.json.
@pytest.mark.parametrize("cwd,given", [(".", "fake-pool"), ("fake-pool", ".")])
def test_a_relative_benchmark_path_resolves_from_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cwd: str, given: str
) -> None:
    directory = _write_benchmark(tmp_path)
    (tmp_path / "local.json").write_text(json.dumps({"FAKE_ENGINE": str(FAKE_ENGINE)}), encoding="utf-8")
    monkeypatch.chdir(tmp_path / cwd)
    result = run_benchmark(Path(given), unrated=True, date="2026-09-26", environ={"PY": sys.executable})
    assert result.run_dir == directory / "runs" / "2026-09-26"
    assert result.failures == ()
    for name in PUBLISHED:
        text = (result.run_dir / name).read_text(encoding="utf-8")
        for value in (str(tmp_path), tmp_path.as_posix()):
            assert value not in text and json.dumps(value)[1:-1] not in text, name


# With every placeholder resolved, the date is the error, and "" is not today.
@pytest.mark.parametrize("date", ["2026-02-30", ""])
def test_a_bad_date_stops_the_run_before_its_directory_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], date: str
) -> None:
    for name, value in ENVIRON.items():
        monkeypatch.setenv(name, value)
    directory = _write_benchmark(tmp_path)
    assert cli.main(["bench", "run", str(directory), "--unrated", "--date", date]) == 1
    assert "error: run date" in capsys.readouterr().err
    assert not (directory / "runs").exists()


def test_the_cli_prints_the_run_and_each_validate_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for name, value in ENVIRON.items():
        monkeypatch.setenv(name, value)
    failures = ["digest mismatch: matches.jsonl", "manifest games does not match the tournament data"]
    monkeypatch.setattr("spellbench.bench.run.validate_tournament_dir", lambda directory: list(failures))
    directory = _write_benchmark(tmp_path)
    assert cli.main(["bench", "run", str(directory), "--unrated", "--date", "2026-09-26"]) == 1
    out, err = capsys.readouterr()
    assert out.splitlines()[:3] == [
        f"benchmark run published: {directory / 'runs' / '2026-09-26'}",
        "games: 18 total, 18 rated, 0 truncated, 0 halted, 0 forfeit",
        "leaderboard status: ok",
    ]
    assert err.splitlines() == [f"FAIL {failure}" for failure in failures]
