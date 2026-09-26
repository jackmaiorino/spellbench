"""Concurrent game execution: same artifacts, genuinely parallel engines."""

from __future__ import annotations

from pathlib import Path

import pytest

from spellbench.arena import runner

from arena_helpers import builtin, ledger_rows, make_config, run

BOTS = [builtin("uniform", seed=11), builtin("heuristic"), builtin("first")]


def test_worker_count_does_not_change_any_artifact(tmp_path: Path) -> None:
    serial, parallel = tmp_path / "serial", tmp_path / "parallel"
    run(make_config(serial, BOTS, pairs=3, workers=1))
    run(make_config(parallel, BOTS, pairs=3, workers=4))
    for name in ("matches.jsonl", "registry.json", "leaderboard.json", "LEADERBOARD.md"):
        assert (serial / name).read_bytes() == (parallel / name).read_bytes(), name


def test_workers_run_engines_concurrently(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Each engine blocks at reset until a second engine has also reached
    # reset; a serial runner leaves the first engine waiting until it dies.
    rendezvous = tmp_path / "rendezvous"
    rendezvous.mkdir()
    monkeypatch.setenv("SPELLBENCH_RENDEZVOUS_DIR", str(rendezvous))
    monkeypatch.setenv("SPELLBENCH_RENDEZVOUS_COUNT", "2")
    directory = tmp_path / "t"
    run(
        make_config(
            directory,
            [builtin("heuristic"), builtin("first")],
            decks=("Rendezvous", "Burn"),
            pairs=1,
            workers=2,
        )
    )
    assert {row["classification"] for row in ledger_rows(directory)} == {"natural"}


@pytest.mark.parametrize("workers", [0, 257, "4"])
def test_worker_count_is_validated(tmp_path: Path, workers: object) -> None:
    config = make_config(tmp_path / "t", BOTS, pairs=1, workers=workers)
    with pytest.raises(runner.TournamentError, match=r"config\.workers: must be an integer in \[1, 256\]"):
        runner.TournamentConfig.from_json(config)
