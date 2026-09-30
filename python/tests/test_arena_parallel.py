"""Concurrent game execution: same artifacts, genuinely parallel engines."""

from __future__ import annotations

import pytest

pytest.skip("protocol v1 test, migrated in Task 40", allow_module_level=True)

from pathlib import Path

import pytest

from spellbench.arena import runner
from spellbench.arena.validate import validate_tournament_dir

from arena_helpers import builtin, ledger_rows, make_config, run

BOTS = [builtin("uniform", seed=11), builtin("heuristic"), builtin("first")]


def test_worker_count_does_not_change_any_artifact(tmp_path: Path) -> None:
    serial, parallel = tmp_path / "serial", tmp_path / "parallel"
    run(make_config(serial, BOTS, pairs=3, workers=1))
    run(make_config(parallel, BOTS, pairs=3, workers=4))
    for name in ("matches.jsonl", "registry.json", "leaderboard.json", "LEADERBOARD.md"):
        assert (serial / name).read_bytes() == (parallel / name).read_bytes(), name


def test_a_parallel_deck_pool_run_validates_and_matches_a_serial_one(tmp_path: Path) -> None:
    # The benchmark launch shape: a rotating deck pool, no self-play, games in worker processes.
    serial, parallel = tmp_path / "serial", tmp_path / "parallel"
    shape = {"deck_pool": ("Burn", "Elves", "Faeries"), "include_self_play": False, "rating_anchor": "uniform"}
    run(make_config(serial, BOTS, pairs=3, workers=1, **shape))
    run(make_config(parallel, BOTS, pairs=3, workers=2, **shape))
    assert validate_tournament_dir(parallel) == []
    assert (parallel / "matches.jsonl").read_bytes() == (serial / "matches.jsonl").read_bytes()
    assert {row["decks"][0]["catalog_id"] for row in ledger_rows(parallel)} == {"Burn", "Elves", "Faeries"}


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


@pytest.mark.parametrize("workers", [0, 62, "4"])
def test_worker_count_is_validated(tmp_path: Path, workers: object) -> None:
    # 61 is the most worker processes Windows can wait on; one limit keeps
    # configs portable across platforms.
    config = make_config(tmp_path / "t", BOTS, pairs=1, workers=workers)
    with pytest.raises(runner.TournamentError, match=r"config\.workers: must be an integer in \[1, 61\]"):
        runner.TournamentConfig.from_json(config)


def test_errors_survive_the_trip_between_processes() -> None:
    # Worker processes hand exceptions back to the parent by pickling; an
    # exception that cannot unpickle turns into a broken pool.
    import pickle

    from spellbench.errors import AgentError, EngineError, RemoteError

    for error in (
        AgentError("internal_error", "boom"),
        EngineError("unsupported_deck", "no such deck"),
        RemoteError("malformed_request", "bad"),
        runner.ForfeitError("timeout", "the agent did not answer choose in time"),
        runner.TournamentError("engine hello failed"),
    ):
        restored = pickle.loads(pickle.dumps(error))
        assert type(restored) is type(error)
        assert str(restored) == str(error)
