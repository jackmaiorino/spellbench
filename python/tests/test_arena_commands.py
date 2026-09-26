"""How the arena starts engine and bot processes from config commands."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from spellbench.arena import runner

from arena_helpers import FAKE_ARENA_ENGINE, builtin, ledger_rows, make_config, run, subprocess_bot


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


def test_a_bot_that_cannot_start_forfeits(tmp_path: Path) -> None:
    ghost = subprocess_bot("ghost", [str(tmp_path / "no-such-bot")])
    directory = tmp_path / "t"
    run(make_config(directory, [builtin("heuristic"), ghost], pairs=1))
    forfeits = [row for row in ledger_rows(directory) if row["classification"] == "forfeit"]
    assert len(forfeits) == 4
    assert {row["adjudication"]["cause"] for row in forfeits} == {"transport_error"}
