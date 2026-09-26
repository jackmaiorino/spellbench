"""End-to-end tests against real child processes over stdio."""

from __future__ import annotations

import sys
from pathlib import Path

from spellbench.agent_client import AgentProcess
from spellbench.engine_client import EngineProcess
from spellbench.models import Decision, Terminal, TerminalResult

from conftest import TEST_ENGINE, make_decision

FAKE_ENGINE = Path(__file__).with_name("fake_engine.py")

TERMINAL = TerminalResult(
    outcome="p1_win",
    classification="natural",
    winner="p1",
    reason="p0_life_zero",
    step_count=2,
    decision_count=2,
)


def test_engine_subprocess_happy_path() -> None:
    with EngineProcess([sys.executable, str(FAKE_ENGINE)], timeout_s=30) as engine:
        hello = engine.hello()
        assert hello.engine.name == "fake-engine"
        first = engine.reset(
            game_id="g-e2e",
            format="pauper-bo1",
            decks=[{"catalog_id": "Burn"}, {"catalog_id": "Burn"}],
            game_seed=7,
            max_decisions=100,
            max_steps=100,
        )
        assert isinstance(first, Decision) and first.step == 0
        second = engine.step(0)
        assert isinstance(second, Decision) and second.step == 1
        done = engine.step(0)
        assert isinstance(done, Terminal)
        assert done.result.outcome == "p0_win"
        assert done.result.step_count == 2 and done.result.decision_count == 2


def test_agent_subprocess_happy_path() -> None:
    with AgentProcess([sys.executable, "-m", "spellbench.agent_server"], timeout_s=30) as agent:
        hello = agent.hello()
        assert hello.bot.name == "first-candidate"
        agent.game_start(
            game_id="g-e2e",
            seat="p1",
            format="pauper-bo1",
            decks=[{"catalog_id": "Burn"}, {"catalog_id": "Burn"}],
            engine=TEST_ENGINE,
        )
        selection = agent.choose(make_decision("h-2", step=0, game_id="g-e2e"))
        assert selection.candidate_id == 0
        assert selection.semantic_echo == {"kind": "pass"}
        agent.game_over(TERMINAL)
