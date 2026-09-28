"""Hostile participants trip exactly the rule or fault they target."""

from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from spellbench import wire
from spellbench.agent_messages import AgentHelloOk, Choice, request
from spellbench.errors import EngineError, PeerTimeoutError, ProtocolError, TransportError
from spellbench.host.agent_process import AgentProcess
from spellbench.host.engine_process import EngineProcess, TerminalCountError
from spellbench.host.seat import SeatFailure
from spellbench.host.validator import LiveValidator
from spellbench.host.violation import ValidatorViolation
from spellbench.messages import PROTOCOL_MINOR, Decision, ResetRequest, Rules

import bot_v2_hostile
import hostile_v2_engine
from test_messages import RESET, RULES

TESTS = Path(__file__).resolve().parent
FAULTS = ((PeerTimeoutError, "timeout"), (TransportError, "transport"), (EngineError, "error"),
          (TerminalCountError, "terminal_counts"), (ProtocolError, "malformed"))   # the subclass before ProtocolError


def _play(engine: EngineProcess) -> tuple[str, str]:
    """The outcome of one scoring game against ``engine``, and the text naming its cause."""
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
        counted, completed = response.result.decision_count, validator.completed_groups
        if counted != completed:                              # the game loop's check (spec 9.5, 11.5)
            return "terminal_counts", f"terminal decision_count {counted} is not the {completed} completed groups"
        return "clean", ""
    except ValidatorViolation as violation:
        return violation.rule, violation.detail
    except (PeerTimeoutError, TransportError, EngineError, ProtocolError) as exc:
        return next(name for kind, name in FAULTS if isinstance(exc, kind)), str(exc)


def outcome_of_engine(mode: str) -> tuple[str, str]:
    """``(outcome, text)``: the rule or fault the host records for ``mode``, and the text naming its cause."""
    engine = EngineProcess([sys.executable, str(TESTS / "hostile_v2_engine.py"), mode], timeout_s=3)
    try:
        outcome, text = _play(engine)
    finally:
        engine.close()
    if outcome == "transport":
        # The EOF can reach the host before the child is reaped, so the host's own "code=" may read None
        # (about half the runs under load); close() waits for the child, so its exit code is known here.
        text += f"; exit code {engine._peer._proc.returncode}"
    return outcome, text


@pytest.mark.parametrize("mode", sorted(hostile_v2_engine.MODES))
def test_each_hostile_engine_mode_is_caught(mode: str) -> None:
    outcome, text = outcome_of_engine(mode)
    assert outcome == hostile_v2_engine.MODES[mode]
    assert hostile_v2_engine.DETAILS[mode] in text             # the injected fault, not another check of that rule


def test_every_rule_has_a_hostile_engine() -> None:
    assert {f"V{number}" for number in range(1, 11)} <= set(hostile_v2_engine.MODES.values())


GAME_START = {"game_id": "g-1", "seat": "p0"}
CHOOSE = {"game_id": "g-1", "clock": {},
          "decision": {"acting_seat": "p0", "seat_step": 0,
                       "candidates": [{"candidate_id": 0, "semantic": {"kind": "pass"}, "display_text": None}]}}
GAME_OVER = {"game_id": "g-1"}


@dataclass
class BotRun:
    """What the host read from one hostile bot: hello, game_start and choose, then game_over after an ok choose."""

    cause: str = "ok"                        # "ok", or the SeatFailure cause of hello, game_start or choose
    failure: SeatFailure | None = None
    hello: AgentHelloOk | None = None
    choice: Choice | None = None
    game_over: SeatFailure | None = None     # a failure after the game, which the game loop ignores
    stderr: str = ""                         # all the bot wrote to stderr, read once close() reaped it


def outcome_of_bot(mode: str) -> BotRun:
    agent = AgentProcess([sys.executable, str(TESTS / "bot_v2_hostile.py"), mode], startup_timeout_s=3)
    run = BotRun()
    try:
        run.hello = agent.hello()
        agent.game_start(GAME_START, timeout_s=3)
        run.choice = agent.choose(CHOOSE, timeout_s=1)
        try:
            agent.game_over(GAME_OVER, timeout_s=3)
        except SeatFailure as failure:
            run.game_over = failure
    except SeatFailure as failure:
        run.cause, run.failure = failure.cause, failure
    finally:
        agent.close()
    run.stderr = agent.stderr_text()
    return run


def raw_answers(mode: str) -> list[bytes]:
    """The bot's stdout lines, terminators kept, answering hello, game_start, choose and game_over sent at once."""
    requests = (("hello", {"protocol_minor": PROTOCOL_MINOR}), ("game_start", GAME_START), ("choose", CHOOSE),
                ("game_over", GAME_OVER))
    lines = b"".join(wire.canonical_json_dumps(request(kind, f"r-{index}", payload)) + b"\n"
                     for index, (kind, payload) in enumerate(requests))
    done = subprocess.run([sys.executable, str(TESTS / "bot_v2_hostile.py"), mode], input=lines,
                          capture_output=True, timeout=30, check=True)
    return done.stdout.splitlines(keepends=True)


def assert_still_misbehaves(mode: str, run: BotRun) -> None:
    """An ``ok`` mode's answers misbehave as its name says.

    This layer reads them as they are, and the game loop, the drivers or preflight judge them, so a mode
    that quietly behaved would otherwise pass as ``ok``.
    """
    assert (run.game_over is not None) == (mode == "crash-on-game-over")    # every other mode acks game_over
    if mode == "wrong-echo-step":
        assert run.choice.echoes == {"seat_step": 1}                           # the decision's seat_step is 0
    elif mode == "wrong-echo-semantic":
        assert run.choice.echoes == {"semantic_echo": {"kind": "play_land"}}   # candidate 0 is pass
    elif mode == "out-of-range":
        assert run.choice.candidate_id == 999                                  # one candidate was offered
    elif mode == "requires-poison":
        assert run.hello.requires_observation == ("poison",)
    elif mode == "wrong-name":
        assert run.hello.bot.name == "impostor"
    elif mode == "crash-on-game-over":
        assert run.game_over.cause == "transport_error" and bot_v2_hostile.PHASES[mode] in run.game_over.detail
    elif mode == "crlf":
        answers = raw_answers(mode)
        assert len(answers) == 4 and all(answer.endswith(b"\r\n") for answer in answers)
    elif mode == "extra-fields":
        answers = raw_answers(mode)
        assert len(answers) == 4
        assert all(bot_v2_hostile.EXTRA_FIELDS.items() <= json.loads(answer).items() for answer in answers)
    else:
        raise AssertionError(f"no check that the ok mode {mode} still misbehaves")


@pytest.mark.parametrize("mode", sorted(bot_v2_hostile.MODES))
def test_each_hostile_bot_mode_maps_to_its_cause(mode: str) -> None:
    run = outcome_of_bot(mode)
    assert run.cause == bot_v2_hostile.MODES[mode]
    if run.failure is not None:
        assert bot_v2_hostile.PHASES[mode] in run.failure.detail              # the request the mode breaks (R3-32)
    else:
        assert_still_misbehaves(mode, run)


def test_a_crashing_bot_s_traceback_and_pid_reach_only_the_diagnostic() -> None:
    run = outcome_of_bot("crash")
    printed = re.search(r"Traceback \(most recent call last\):\nRuntimeError: pid=(\d+)\n", run.stderr)
    assert run.failure is not None and printed is not None                    # the bot did print both
    pid = printed.group(1)
    for text in (str(run.failure), repr(run.failure), run.failure.detail):
        assert "Traceback" not in text and pid not in text                     # R2-15: nothing the peer wrote
    # The diagnostic holds the stderr the host had drained when it read the EOF. Its stderr reader can lose
    # that race (5 of 100 runs under load); the host's EOF report then shows the empty snapshot instead.
    assert f"pid={pid}" in run.failure.diagnostic or "stderr=''" in run.failure.diagnostic


def test_a_deaf_bot_times_out_on_a_large_choose_without_hanging_the_host() -> None:
    agent = AgentProcess([sys.executable, str(TESTS / "bot_v2_hostile.py"), "deaf"], startup_timeout_s=3)
    candidate = {"candidate_id": 0, "semantic": {"kind": "pass"}, "display_text": "x" * 70_000}
    choose = {**CHOOSE, "decision": {**CHOOSE["decision"], "candidates": [candidate]}}   # past a 64 KiB pipe buffer
    try:
        agent.hello()
        agent.game_start(GAME_START, timeout_s=3)
        started = time.monotonic()
        with pytest.raises(SeatFailure) as caught:
            agent.choose(choose, timeout_s=1)
        elapsed = time.monotonic() - started
    finally:
        agent.close()
    assert caught.value.cause == "timeout" and "choose" in caught.value.detail
    # R2-5: the write is bounded by this request's 1 s budget (about 1.1 s). Left on the 3 s startup budget it
    # takes 3 s, and unbounded it lasts until the deaf bot exits (bot_v2_hostile.DEAF_SECONDS).
    assert elapsed < 2.5
