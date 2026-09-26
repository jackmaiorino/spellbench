"""How the arena starts engine and bot processes from config commands."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from spellbench.arena import runner

from arena_helpers import BOT_SLOW_START, FAKE_ARENA_ENGINE, builtin, make_config, run, subprocess_bot


def test_bare_program_names_resolve_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Windows' CreateProcess looks in the running interpreter's own directory
    # before PATH, so under `uv run` a bare "python" started the base
    # interpreter, which cannot import spellbench. Bare names resolve on PATH.
    monkeypatch.setenv("PATH", str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", ""))
    config = make_config(tmp_path / "t", [builtin("heuristic"), builtin("first")], pairs=1)
    config["engine"]["command"] = ["python", str(FAKE_ARENA_ENGINE)]
    assert run(config).games_rated == 6


def test_an_engine_that_cannot_start_is_a_tournament_error(tmp_path: Path) -> None:
    config = make_config(tmp_path / "t", [builtin("heuristic"), builtin("first")], pairs=1)
    config["engine"]["command"] = [str(tmp_path / "no-such-engine")]
    with pytest.raises(runner.TournamentError, match="engine failed to start"):
        run(config)


def test_a_bot_that_cannot_start_stops_the_tournament_before_any_game(tmp_path: Path) -> None:
    # A typo in a bot command is a config error, not a record of forfeits.
    ghost = subprocess_bot("ghost", [str(tmp_path / "no-such-bot")])
    directory = tmp_path / "t"
    with pytest.raises(runner.TournamentError, match="ghost"):
        run(make_config(directory, [builtin("heuristic"), ghost], pairs=1))
    assert not directory.exists()


def test_an_engine_that_refuses_the_decks_stops_the_tournament_before_any_game(tmp_path: Path) -> None:
    directory = tmp_path / "t"
    config = make_config(directory, [builtin("heuristic"), builtin("first")], decks=("Refuse", "Burn"), pairs=1)
    with pytest.raises(runner.TournamentError, match="unsupported_deck"):
        run(config)
    assert not directory.exists()


def test_slow_starting_bots_get_the_startup_budget(tmp_path: Path) -> None:
    # Loading a model can take far longer than one decision may.
    slow = subprocess_bot("slow", [sys.executable, str(BOT_SLOW_START), "1.5"])
    config = make_config(
        tmp_path / "t",
        [builtin("first"), slow],
        pairs=1,
        choose_timeout_ms=500,
        startup_timeout_ms=15_000,
    )
    assert run(config).games_forfeit == 0
