"""Shared helpers for the arena tests (protocol v2): config builders, fixtures and artifact readers."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from spellbench.arena import runner
from spellbench.arena.config import TournamentConfig
from spellbench.arena.manifest import CommitmentProof, EngineFile
from spellbench.arena.throughput import Allocation, MachineFacts, PlayedGame, plan_allocation, spot_check_game
from spellbench.run_secret import RunSecret

TESTS_DIR = Path(__file__).resolve().parent
FAKE_ENGINE = TESTS_DIR / "fake_v2_engine.py"
HOSTILE_ENGINE = TESTS_DIR / "hostile_v2_engine.py"
BOT_HOSTILE = TESTS_DIR / "bot_v2_hostile.py"
BOT_SLOW_START = TESTS_DIR / "bot_slow_start.py"
MINIMAL_BOT = TESTS_DIR.parents[1] / "examples" / "minimal_bot.py"
TEST_RUN_SECRET = RunSecret(bytes(range(32)))  # the spec 16 vector secret
TEST_PROOF = CommitmentProof(commit="0" * 40, timestamp="test fixture")
# A rated run needs pinned engine files (Decision 3, R3-7); library tests pass this stand-in record.
TEST_ENGINE_FILES = (EngineFile(index=1, file_name="fake_v2_engine.py", sha256="0" * 64, bytes=1),)

_DIGEST = "sha256:" + "0" * 64
# Room above the 60 GiB reserve on both volumes a guarded launch checks (ARTIFACT-LAW clause 1).
_MACHINE = MachineFacts(memory_bytes=2**36, gpus=(), free_bytes=(("pin_root", 2**42), ("run_dir", 2**42)))


def _instant_games(workers: int, indices: tuple[int, ...]) -> tuple[float, tuple[PlayedGame, ...]]:
    """A stand-in qualification where every game takes 10 ms, so every schedule projects small."""
    return 0.01 * len(indices), tuple(PlayedGame(index, 0.01, _DIGEST, 10) for index in indices)


def small_allocation(workers: int = 1) -> Allocation:
    """A measured "small" allocation of ``workers`` workers for tests (named so pytest never collects it).

    Task 5's allocation carries its qualification rules, a machine snapshot, a budget and a spot check, so it is
    built the way a launch builds one, as ``test_arena_manifest._small_allocation`` does: planned, then its spot
    check passed. The cap, the cores and the game count all admit ``workers``, so the plan keeps that many.
    """
    games_total = max(4, workers)
    allocation = plan_allocation(games_total=games_total, cap=workers, per_game_cores=1, play=_instant_games,
                                 placement=None, cpu_count=max(workers, os.cpu_count() or 1), host="test-host",
                                 machine=_MACHINE)
    return allocation.with_spot_check(spot_check_game(games_total), recorded_digest=_DIGEST, replayed_digest=_DIGEST)


def builtin(name: str, **extra: Any) -> dict[str, Any]:
    return {"name": name, "version": "2.0.0", "type": "builtin", **extra}


def subprocess_bot(name: str, command: list[str], **extra: Any) -> dict[str, Any]:
    """The test bots are the project's own: owner spellbench, so the isolation rule admits them unsandboxed."""
    return {"name": name, "version": "1.0.0", "type": "subprocess", "command": command, "owner": "spellbench", **extra}


def cli_bot(name: str, *args: str) -> list[str]:
    """Command line serving a builtin bot over stdio via ``spellbench bot``."""
    return [sys.executable, "-m", "spellbench.arena.cli", "bot", name, *args]


def hostile_bot(mode: str) -> dict[str, Any]:
    return subprocess_bot("hostile", [sys.executable, str(BOT_HOSTILE), mode])


def make_config(directory: Path, bots: list[dict[str, Any]], *, engine: Path = FAKE_ENGINE, engine_args: tuple[str, ...] = (),
                decks: tuple[str, str] = ("Burn", "Burn"), deck_pool: tuple[str, ...] | None = None, pairs: int = 2,
                **extra: Any) -> dict[str, Any]:
    config: dict[str, Any] = {
        "schema": "spellbench-tournament-config/v2", "tournament_dir": str(directory), "format": "pauper-bo1",
        "decks": [{"catalog_id": decks[0]}, {"catalog_id": decks[1]}],
        "engine": {"command": [sys.executable, str(engine), *engine_args]},
        "bots": bots, "pairs_per_matchup": pairs, "stats_seed": 12345, "bootstrap_replicates": 1000,
    }
    if deck_pool is not None:
        del config["decks"]
        config["deck_pool"] = [{"catalog_id": deck} for deck in deck_pool]
    config.update(extra)
    return config


def run(config: dict[str, Any], *, rated: bool = False, secret: RunSecret = TEST_RUN_SECRET, **kwargs: Any) -> runner.TournamentSummary:
    parsed = TournamentConfig.from_json(config)
    return runner.run_tournament(parsed, run_secret=secret, allocation=small_allocation(parsed.workers),
                                 commitment_proof=TEST_PROOF if rated else None,
                                 engine_files=TEST_ENGINE_FILES if rated else (), **kwargs)


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def ledger_rows(directory: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (directory / "matches.jsonl").read_text(encoding="utf-8").splitlines()]


def leaderboard(directory: Path) -> dict[str, Any]:
    return _json(directory / "leaderboard.json")


def manifest(directory: Path) -> dict[str, Any]:
    return _json(directory / "manifest.json")


def row_by_name(document: dict[str, Any], name: str) -> dict[str, Any]:
    matches = [row for row in document["rows"] if row["name"] == name]
    assert len(matches) == 1, f"expected one leaderboard row for {name}"
    return matches[0]


def matchup_by_names(document: dict[str, Any], first: str, second: str) -> dict[str, Any]:
    matches = [m for m in document["matchups"] if {m["a_name"], m["b_name"]} == {first, second}]
    assert len(matches) == 1, f"expected one matchup for {first} vs {second}"
    return matches[0]
