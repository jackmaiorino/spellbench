"""Shared helpers for the arena tests: config builders and artifact readers."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from spellbench.arena import runner

TESTS_DIR = Path(__file__).resolve().parent
FAKE_ENGINE = TESTS_DIR / "fake_engine.py"
FAKE_ARENA_ENGINE = TESTS_DIR / "fake_arena_engine.py"
BOT_INVALID_CHOICE = TESTS_DIR / "bot_invalid_choice.py"
BOT_HANG = TESTS_DIR / "bot_hang.py"
BOT_SLOW_START = TESTS_DIR / "bot_slow_start.py"


def builtin(name: str, **extra: Any) -> dict[str, Any]:
    return {"name": name, "version": "1.0.0", "type": "builtin", **extra}


def subprocess_bot(name: str, command: list[str], **extra: Any) -> dict[str, Any]:
    return {"name": name, "version": "1.0.0", "type": "subprocess", "command": command, **extra}


def cli_bot(name: str, *args: str) -> list[str]:
    """Command line serving a builtin bot over stdio via ``spellbench bot``."""
    return [sys.executable, "-m", "spellbench.arena.cli", "bot", name, *args]


def make_config(
    directory: Path,
    bots: list[dict[str, Any]],
    *,
    engine: Path = FAKE_ARENA_ENGINE,
    decks: tuple[str, str] = ("Burn", "Burn"),
    deck_pool: tuple[str, ...] | None = None,
    pairs: int = 2,
    **extra: Any,
) -> dict[str, Any]:
    config: dict[str, Any] = {
        "schema": "spellbench-tournament-config/v1",
        "tournament_dir": str(directory),
        "format": "pauper-bo1",
        "decks": [{"catalog_id": decks[0]}, {"catalog_id": decks[1]}],
        "engine": {"command": [sys.executable, str(engine)], "timeout_ms": 30_000},
        "bots": bots,
        "pairs_per_matchup": pairs,
        "base_seed": 12345,
        "bootstrap_replicates": 1000,
    }
    if deck_pool is not None:
        del config["decks"]
        config["deck_pool"] = [{"catalog_id": deck} for deck in deck_pool]
    config.update(extra)
    return config


def run(config: dict[str, Any]) -> runner.TournamentSummary:
    return runner.run_tournament(runner.TournamentConfig.from_json(config))


def ledger_rows(directory: Path) -> list[dict[str, Any]]:
    lines = (directory / "matches.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def leaderboard(directory: Path) -> dict[str, Any]:
    return json.loads((directory / "leaderboard.json").read_text(encoding="utf-8"))


def row_by_name(document: dict[str, Any], name: str) -> dict[str, Any]:
    matches = [row for row in document["rows"] if row["name"] == name]
    assert len(matches) == 1, f"expected one leaderboard row for {name}"
    return matches[0]


def matchup_by_names(document: dict[str, Any], first: str, second: str) -> dict[str, Any]:
    wanted = {first, second}
    matches = [
        matchup
        for matchup in document["matchups"]
        if {matchup["a_name"], matchup["b_name"]} == wanted
    ]
    assert len(matches) == 1, f"expected one matchup for {first} vs {second}"
    return matches[0]


BOT_HOSTILE = TESTS_DIR / "bot_hostile.py"


def hostile_bot(mode: str) -> dict[str, Any]:
    return subprocess_bot("hostile", [sys.executable, str(BOT_HOSTILE), mode])
