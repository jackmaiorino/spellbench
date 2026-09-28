"""Builtin and subprocess seat drivers."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from spellbench.arena.config import BotSpec
from spellbench.arena.drivers import BuiltinDriver, SubprocessDriver
from spellbench.host.seat import SeatFailure

MINIMAL = Path(__file__).resolve().parents[2] / "examples" / "minimal_bot.py"
DECISION = {"acting_seat": "p0", "seat_step": 0, "candidates": [
    {"candidate_id": 0, "semantic": {"kind": "pass"}, "display_text": None},
    {"candidate_id": 1, "semantic": {"kind": "play_land", "face": 0}, "display_text": None}]}
CHOOSE = {"game_id": "g-1", "decision": DECISION, "clock": {"remaining_ms": 1000, "max_decision_ms": 1000}}
START = {"game_id": "g-1", "seat": "p0", "agent_seed": 42}


def builtin(name: str) -> BotSpec:
    return BotSpec(name=name, version="2.0.0", type="builtin")


def test_builtin_bots_play_and_cannot_mutate_the_host_copy() -> None:
    class Mutator:
        def on_game_start(self, game): pass
        def choose(self, decision):
            decision.raw["decision"]["candidates"].clear()
            return 1
        def on_game_over(self, game_over): pass

    driver = BuiltinDriver(builtin("first"), factory=Mutator)
    driver.start(START, timeout_s=5)
    assert driver.choose(CHOOSE, timeout_s=5).candidate_id == 1
    assert len(CHOOSE["decision"]["candidates"]) == 2
    heuristic = BuiltinDriver(builtin("heuristic"))
    heuristic.start(START, timeout_s=5)
    assert heuristic.choose(CHOOSE, timeout_s=5).candidate_id == 1


@pytest.mark.parametrize(
    ("choose", "cause"),
    [(lambda decision: time.sleep(5), "timeout"), (lambda decision: 1 / 0, "agent_error"), (lambda decision: "1", "malformed_response")],
)
def test_builtin_failures(choose, cause: str) -> None:
    class Bot:
        def on_game_start(self, game): pass
        def on_game_over(self, game_over): pass

    Bot.choose = staticmethod(choose)
    driver = BuiltinDriver(builtin("first"), factory=Bot)
    driver.start(START, timeout_s=5)
    with pytest.raises(SeatFailure) as caught:
        driver.choose(CHOOSE, timeout_s=0.3)
    assert caught.value.cause == cause


def test_a_subprocess_bot_per_game() -> None:
    spec = BotSpec(name="minimal", version="1.0.0", type="subprocess", command=(sys.executable, str(MINIMAL)))
    driver = SubprocessDriver(spec, startup_ms=30_000)
    try:
        driver.start(START, timeout_s=30)
        assert driver.choose(CHOOSE, timeout_s=30).candidate_id == 0
        driver.game_over({"game_id": "g-1", "terminal": {}}, timeout_s=30)
    finally:
        driver.close()


def test_a_subprocess_bot_must_name_its_config_entry() -> None:
    spec = BotSpec(name="someone-else", version="1.0.0", type="subprocess", command=(sys.executable, str(MINIMAL)))
    driver = SubprocessDriver(spec, startup_ms=30_000)
    with pytest.raises(SeatFailure, match="different bot"):
        driver.start(START, timeout_s=30)
    driver.close()


def test_a_subprocess_bot_never_sees_spellbench_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPELLBENCH_SECRETS_DIR", str(tmp_path / "secrets"))         # where a committed run keeps its secret
    bot = tmp_path / "env_bot.py"
    bot.write_text("import os, sys\nfrom spellbench.bot import serve\n"
                   "name = 'leaky' if any(key.startswith('SPELLBENCH_') for key in os.environ) else 'clean'\n"
                   "sys.exit(serve(choose=lambda d: 0, name=name, version='1'))\n", encoding="utf-8")
    driver = SubprocessDriver(BotSpec(name="clean", version="1", type="subprocess", command=(sys.executable, str(bot))),
                              startup_ms=30_000)
    try:
        driver.start(START, timeout_s=30)        # a bot that saw SPELLBENCH_* would name itself "leaky" and be refused (R3-9)
    finally:
        driver.close()
