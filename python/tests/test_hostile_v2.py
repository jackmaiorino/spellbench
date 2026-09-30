"""Hostile participants trip exactly the rule or fault they target."""

from __future__ import annotations

import copy
import sys
import time
from pathlib import Path

import pytest

from spellbench.errors import EngineError, PeerTimeoutError, ProtocolError, TransportError
from spellbench.host.agent_process import AgentProcess
from spellbench.host.engine_process import EngineProcess, TerminalCountError
from spellbench.host.seat import SeatFailure
from spellbench.host.validator import LiveValidator
from spellbench.host.violation import ValidatorViolation
from spellbench.messages import Decision, ResetRequest, Rules

import bot_v2_hostile
import hostile_v2_engine
from test_messages import RESET, RULES

TESTS = Path(__file__).resolve().parent
FAULTS = ((PeerTimeoutError, "timeout"), (TransportError, "transport"), (EngineError, "error"),
          (TerminalCountError, "terminal_counts"), (ProtocolError, "malformed"))   # the subclass before ProtocolError


def outcome_of_engine(mode: str) -> str:
    engine = EngineProcess([sys.executable, str(TESTS / "hostile_v2_engine.py"), mode], timeout_s=3)
    try:
        # A1 made the caps required constructor arguments; the reset's values are the game's caps (spec 9.2).
        validator = LiveValidator(engine.hello(), Rules.from_json(RULES),
                                  max_decisions=RESET["max_decisions"], max_steps=RESET["max_steps"])
        response = engine.reset(ResetRequest.from_json({**copy.deepcopy(RESET), "request_id": engine.next_request_id()}))
        while isinstance(response, Decision):
            sd = validator.check(response)
            pick = len(sd["candidates"]) - 1                  # play the land whenever one is offered
            validator.answered(sd, pick)
            response = engine.step(candidate_id=pick, semantic=sd["candidates"][pick]["semantic"])
        validator.check_terminal(response)
        if response.result.decision_count != validator.completed_groups:
            return "terminal_counts"
        return "clean"
    except ValidatorViolation as violation:
        return violation.rule
    except (PeerTimeoutError, TransportError, EngineError, ProtocolError) as exc:
        return next(name for kind, name in FAULTS if isinstance(exc, kind))
    finally:
        engine.close()


@pytest.mark.parametrize("mode", sorted(hostile_v2_engine.MODES))
def test_each_hostile_engine_mode_is_caught(mode: str) -> None:
    assert outcome_of_engine(mode) == hostile_v2_engine.MODES[mode]


def test_every_rule_has_a_hostile_engine() -> None:
    assert {f"V{number}" for number in range(1, 11)} <= set(hostile_v2_engine.MODES.values())


def outcome_of_bot(mode: str) -> str:
    agent = AgentProcess([sys.executable, str(TESTS / "bot_v2_hostile.py"), mode], startup_timeout_s=3)
    decision = {"acting_seat": "p0", "seat_step": 0,
                "candidates": [{"candidate_id": 0, "semantic": {"kind": "pass"}, "display_text": None}]}
    try:
        agent.hello()
        agent.game_start({"game_id": "g-1", "seat": "p0"}, timeout_s=3)
        agent.choose({"game_id": "g-1", "decision": decision, "clock": {}}, timeout_s=1)
        return "ok"
    except SeatFailure as failure:
        return failure.cause
    finally:
        agent.close()


@pytest.mark.parametrize("mode", sorted(bot_v2_hostile.MODES))
def test_each_hostile_bot_mode_maps_to_its_cause(mode: str) -> None:
    assert outcome_of_bot(mode) == bot_v2_hostile.MODES[mode]


def test_a_deaf_bot_times_out_on_a_large_choose_without_hanging_the_host() -> None:
    agent = AgentProcess([sys.executable, str(TESTS / "bot_v2_hostile.py"), "deaf"], startup_timeout_s=3)
    decision = {"acting_seat": "p0", "seat_step": 0,
                "candidates": [{"candidate_id": 0, "semantic": {"kind": "pass"}, "display_text": "x" * 70_000}]}
    started = time.monotonic()
    try:
        agent.hello()
        agent.game_start({"game_id": "g-1", "seat": "p0"}, timeout_s=3)
        with pytest.raises(SeatFailure) as caught:
            agent.choose({"game_id": "g-1", "decision": decision, "clock": {}}, timeout_s=1)    # past any pipe buffer
    finally:
        agent.close()
    assert caught.value.cause == "timeout" and time.monotonic() - started < 15                 # R2-5
