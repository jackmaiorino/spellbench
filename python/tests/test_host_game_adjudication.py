"""Clocks, caps, stalling, the mandatory-loop draw, and forfeits through real processes (spec 11.4, 11.5).

Every game runs against a real engine process behind a line recorder, so a test can check what the engine was
sent (a cap rules before the capping answer's step is sent, Decision 5) and recompute the digest (spec 11.8).
A fake wall clock drives the bank tests; the real-process budgets are tight only where a timeout is the thing
under test, so a loaded machine cannot turn another outcome into a timeout.
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from spellbench import wire
from spellbench.arena.config import BotSpec
from spellbench.arena.drivers import SubprocessDriver
from spellbench.arena.ledger import LedgerRow, parse_ledger
from spellbench.digests import deck_id
from spellbench.host.game import GameResult, play_game
from spellbench.messages import Limits, Rules, TimeControl, WireDeck

import fake_v2_scenario_smoke
from test_host_game import BURN, Seat, chain, chained, decision_line, lands, recorded, scripted, setup
from test_ledger import A, B, row
from test_messages import RULES
from v2_sample_semantics import seat_decision

TESTS = Path(__file__).resolve().parent
TIGHT = Limits(max_decisions=10000, max_steps=100000, max_seat_decisions_per_turn=20,
               max_seat_decisions_per_game=4999, max_seat_steps_per_game=49999)
SMOKE = WireDeck(deck_id=deck_id(fake_v2_scenario_smoke.SCENARIO.decklist), catalog_id="Scenario:smoke")
P1_FIRST = Rules.from_json({**RULES, "starting_seat": "p1"})
# Nothing a well-behaved participant does comes near these, however loaded the machine.
GENEROUS = TimeControl(startup_ms=30000, game_start_ms=30000, bank_ms=600000, increment_ms=0, max_decision_ms=30000,
                       engine_step_ms=30000)
Lines = list[tuple[str, bytes]]


def play(*, deck: str | WireDeck = "Burn", seats=None, engine: str = "fake_v2_engine.py", engine_args=(),
         clock_ns=None, **changes) -> tuple[GameResult, Lines]:
    """One game against a real engine process: the result, and every engine line ("out" or "in") in order."""
    wire_deck = deck if isinstance(deck, WireDeck) else WireDeck(deck_id=BURN.deck_id, catalog_id=deck)
    process, peer = recorded(wire.SubprocessPeer([sys.executable, str(TESTS / engine), *engine_args], timeout_s=30))
    seats = seats or {"p0": Seat(lands), "p1": Seat()}
    try:
        kwargs = {} if clock_ns is None else {"clock_ns": clock_ns}
        result = play_game(setup(wire_decks=(wire_deck, wire_deck), **changes), engine=process, seats=seats, **kwargs)
    finally:
        process.close()
        for driver in seats.values():
            driver.close()
    return result, peer.lines


def hostile(mode: str) -> SubprocessDriver:
    spec = BotSpec(name="hostile", version="1.0.0", type="subprocess",
                   command=(sys.executable, str(TESTS / "bot_v2_hostile.py"), mode))
    return SubprocessDriver(spec, startup_ms=30_000)


def last(decision) -> int:
    return len(decision["candidates"]) - 1


def thinking(now: list[int], *ms: int, answer=lands):
    """A pick that spends ``ms[i]`` of fake wall time (``now[0]``, in ns) on its i-th decision, then answers."""
    spent = iter(ms)

    def pick(decision) -> int:
        now[0] += next(spent) * 1_000_000
        return answer(decision)

    return pick


def steps_sent(lines: Lines) -> list[int]:
    """The ``expected_step`` of every step request the engine was sent, in order."""
    requests = [json.loads(line) for direction, line in lines if direction == "out"]
    return [request["expected_step"] for request in requests if request["request_type"] == "step"]


def last_line(lines: Lines) -> tuple[str, str, int]:
    """The direction, message type and binding step of the last engine line."""
    direction, line = lines[-1]
    message = json.loads(line)
    return direction, message["response_type"], message["step"]


def clocks(seat: Seat) -> list[dict]:
    return [payload["clock"] for kind, payload in seat.received if kind == "choose"]


def terminal(seat: Seat) -> dict:
    kind, payload = seat.received[-1]
    assert kind == "game_over"
    return payload["terminal"]


def ledger_row(result: GameResult) -> LedgerRow:
    """``result`` as the ledger row it becomes, parsed: the ledger's own rules check its shape (spec 11.5)."""
    bot_ids = {"p0": A, "p1": B, None: None}
    (parsed,) = parse_ledger([row(outcome=result.outcome, classification=result.classification, winner=result.winner,
                                  winner_bot_id=bot_ids[result.winner], reason=result.reason,
                                  adjudication=result.adjudication, step_count=result.step_count,
                                  decision_count=result.decision_count, decisions_checked=result.decisions_checked,
                                  game_digest=result.game_digest)])
    return parsed


# -- caps: the mandatory-loop draw and stalling (spec 11.4, 11.5; Decision 5) ----------------------------------


def test_a_loop_of_mandatory_actions_is_a_draw_at_the_cap() -> None:
    """p0's 20th answer in turn 1 is the game's 39th and reaches the per-turn cap. No seat made a real choice, so the
    host records a natural draw before that answer's step is sent, still counts the answer (R3-12), and appends the
    draw to the digest like every ending it records (spec 11.8)."""
    p0, p1 = Seat(), Seat()
    result, lines = play(deck="Loop", seats={"p0": p0, "p1": p1}, limits=TIGHT)
    draw = {"classification": "natural", "outcome": "draw", "reason": "mandatory_loop", "winner": None}
    assert result == GameResult(
        outcome="draw", classification="natural", winner=None, reason="mandatory_loop",
        adjudication={"kind": "mandatory_loop",
                      "detail": "p0 reached max_seat_decisions_per_turn (20); no real choice in the last 250 decisions"},
        step_count=39, decision_count=39, decisions_checked=39, last_selection_seat=None,
        game_digest=chain(chained(lines), draw), violation=None, diagnostics=())
    assert steps_sent(lines) == list(range(38))                          # never the step answering decision 38
    assert last_line(lines) == ("in", "decision", 38)
    assert [terminal(seat) for seat in (p0, p1)] == [
        {"outcome": "draw", "classification": "natural", "winner": None, "reason": "mandatory_loop", "seat_step_count": n}
        for n in (20, 19)]
    assert ledger_row(result).rated                                       # a natural draw, never a forfeit


def test_the_seat_with_more_real_choices_forfeits_for_stalling() -> None:
    """p0 activates its Relic at each of its 20 decisions of turn 1; p1 only ever has a pass (spec 11.4)."""
    p0, p1 = Seat(last), Seat()
    result, lines = play(deck="Stall", seats={"p0": p0, "p1": p1}, limits=TIGHT)
    forfeit = {"classification": "forfeit", "outcome": "p1_win", "reason": "forfeit:stalling", "winner": "p1"}
    assert result == GameResult(
        outcome="p1_win", classification="forfeit", winner="p1", reason="forfeit:stalling",
        adjudication={"kind": "forfeit", "cause": "stalling", "loser_seat": "p0",
                      "detail": "p0 reached max_seat_decisions_per_turn (20); "
                                "real choices in the last 250 decisions: p0 20, p1 0"},                     # R3-12
        step_count=39, decision_count=39, decisions_checked=39, last_selection_seat=None,
        game_digest=chain(chained(lines), forfeit), violation=None, diagnostics=())
    assert steps_sent(lines) == list(range(38)) and last_line(lines) == ("in", "decision", 38)
    assert [terminal(seat) for seat in (p0, p1)] == [
        {"outcome": "p1_win", "classification": "forfeit", "winner": "p1", "reason": "forfeit:stalling",
         "seat_step_count": n} for n in (20, 19)]
    assert ledger_row(result).rated
    ended, _ = play(deck="Stall", seats={"p0": Seat(), "p1": Seat()}, limits=TIGHT)
    assert (ended.outcome, ended.classification, ended.reason, ended.adjudication) == ("draw", "natural", "stall_ended", None)


def test_the_seat_that_reaches_the_cap_wins_when_the_other_stalled() -> None:
    """p1 moves first, so its 20th pass (the 39th answer) reaches the cap while p0 has made 19 real choices: the
    ruling names the seat with more real choices, not the seat that reached the cap (spec 11.4)."""
    result, lines = play(deck="Stall", seats={"p0": Seat(last), "p1": Seat()}, limits=TIGHT, rules=P1_FIRST)
    assert result.adjudication == {"kind": "forfeit", "cause": "stalling", "loser_seat": "p0",
                                   "detail": "p1 reached max_seat_decisions_per_turn (20); "
                                             "real choices in the last 250 decisions: p0 19, p1 0"}
    assert (result.outcome, result.winner, result.reason, result.step_count) == ("p1_win", "p1", "forfeit:stalling", 39)
    assert steps_sent(lines) == list(range(38))


def test_a_tie_forfeits_the_seat_that_reached_the_cap() -> None:
    """Each seat plays a land at its first decision and passes after. p1 moves first, so its second answer (the
    game's third) reaches a steps cap of 2 with the real choices tied 1 to 1: p1 forfeits (spec 11.4)."""
    first_land = lambda decision: lands(decision) if decision["seat_step"] == 0 else 0   # noqa: E731
    limits = Limits(max_decisions=10000, max_steps=100000, max_seat_decisions_per_turn=500,
                    max_seat_decisions_per_game=4999, max_seat_steps_per_game=2)
    result, lines = play(seats={"p0": Seat(first_land), "p1": Seat(first_land)}, limits=limits, rules=P1_FIRST)
    assert result.adjudication == {"kind": "forfeit", "cause": "stalling", "loser_seat": "p1",
                                   "detail": "p1 reached max_seat_steps_per_game (2); "
                                             "real choices in the last 250 decisions: p0 1, p1 1"}
    assert (result.outcome, result.winner, result.step_count, steps_sent(lines)) == ("p0_win", "p0", 3, [0, 1])


def smoke_pick(decision) -> int:
    kinds = [candidate["semantic"]["kind"] for candidate in decision["candidates"]]
    return kinds.index("cast_spell") if "cast_spell" in kinds else len(kinds) - 1


@pytest.mark.parametrize(
    ("limits", "detail", "step_count", "decision_count"),
    [
        (Limits(10000, 100000, 3, 4999, 49999),
         "p0 reached max_seat_decisions_per_turn (3); real choices in the last 250 decisions: p0 2, p1 0", 3, 2),
        (Limits(10000, 100000, 500, 4, 49999),
         "p0 reached max_seat_decisions_per_game (4); real choices in the last 250 decisions: p0 4, p1 0", 6, 2),
        (Limits(10000, 100000, 500, 4999, 5),
         "p0 reached max_seat_steps_per_game (5); real choices in the last 250 decisions: p0 4, p1 0", 5, 3),
    ],
    ids=["decisions per turn", "groups per game", "steps per game"],
)
def test_each_cap_rules_right_after_the_answer_that_reaches_it(limits: Limits, detail: str, step_count: int,
                                                               decision_count: int) -> None:
    """The smoke scenario poses p0 seven decisions in turn 1 (spec 8): the two substeps of a discard group (a real
    choice between two cards, then one card left), a cast, its target, the first substep of a two-sacrifice cost,
    the rewind's lone pass, a mana payment. Only a group's last substep completes it, so the fourth completed group
    is the rewind's pass, the sixth answer; the fifth answer reaches the steps cap inside a partial group, which a
    host adjudication may interrupt. ``decision_count`` is the validator's, after the rewind (Decision 4)."""
    result, lines = play(deck=SMOKE, engine_args=fake_v2_scenario_smoke.SCENARIO.engine_args,
                         seats={"p0": Seat(smoke_pick), "p1": Seat()}, limits=limits)
    assert result.adjudication == {"kind": "forfeit", "cause": "stalling", "loser_seat": "p0", "detail": detail}
    assert (result.reason, result.winner, result.step_count, result.decision_count, result.decisions_checked) == (
        "forfeit:stalling", "p1", step_count, decision_count, step_count)
    assert steps_sent(lines) == list(range(step_count - 1))


def p0_decision(step: int) -> bytes:
    """The engine's ``step``-th decision, p0's too: the sample priority decision ``[pass, play_land, cast_spell]``."""
    sd = seat_decision()
    sd["seat_step"] = sd["group"]["group_id"] = step
    return decision_line(f"h-{step + 2}", step, sd)          # hello was h-1 and reset h-2; each step takes the next


@pytest.mark.parametrize(
    ("cap", "outcome", "detail"),
    [
        (250, "p1_win", "p0 reached max_seat_steps_per_game (250); real choices in the last 250 decisions: p0 1, p1 0"),
        (251, "draw", "p0 reached max_seat_steps_per_game (251); no real choice in the last 250 decisions"),
    ],
    ids=["in the window", "out of it"],
)
def test_the_window_is_the_last_250_answers_the_capping_one_included(cap: int, outcome: str, detail: str) -> None:
    """p0 plays its land at its first decision and passes at every later one: at a steps cap of 250 that real choice
    is the 250th most recent answer, still in the window; at 251 it has left it (Decision 5)."""
    engine, peer = scripted(*[p0_decision(step) for step in range(cap)])
    limits = Limits(max_decisions=10000, max_steps=100000, max_seat_decisions_per_turn=500,
                    max_seat_decisions_per_game=4999, max_seat_steps_per_game=cap)
    first_land = lambda decision: 1 if decision["seat_step"] == 0 else 0   # noqa: E731
    result = play_game(setup(limits=limits), engine=engine, seats={"p0": Seat(first_land), "p1": Seat()})
    assert (result.outcome, result.adjudication["detail"], result.step_count) == (outcome, detail, cap)
    assert len(peer.sent) == 2 + cap - 1                   # hello, reset, and a step for every answer but the last


def test_the_per_turn_count_restarts_each_turn() -> None:
    """The scoring game poses each decision in a turn of its own, so no seat answers twice in a turn and a per-turn
    cap of 2 is never reached (spec 11.4 counts by observation.turn)."""
    result, _ = play(limits=Limits(10000, 100000, 2, 4999, 49999))
    assert (result.classification, result.reason, result.adjudication, result.step_count) == ("natural", "score", None, 4)


# -- the bank clock (spec 10.3, 11.4) ----------------------------------------------------------------------------


def test_the_bank_drains_and_a_late_answer_is_a_timeout() -> None:
    """Each choose shows the bank before that decision and is bounded by the smaller of the bank and max_decision_ms.
    p0's second answer took 700 ms of a 300 ms bank: it arrived, and it is still a timeout."""
    now = [0]
    p0, p1 = Seat(thinking(now, 700, 700, answer=lambda decision: 0)), Seat()
    result, lines = play(seats={"p0": p0, "p1": p1}, clock_ns=lambda: now[0],
                         time_control=TimeControl(startup_ms=1000, game_start_ms=1000, bank_ms=1000, increment_ms=0,
                                                  max_decision_ms=800, engine_step_ms=30000))
    forfeit = {"classification": "forfeit", "outcome": "p1_win", "reason": "forfeit:timeout", "winner": "p1"}
    assert result == GameResult(
        outcome="p1_win", classification="forfeit", winner="p1", reason="forfeit:timeout",
        adjudication={"kind": "forfeit", "cause": "timeout", "loser_seat": "p0",
                      "detail": "the answer to choose at seat step 1 exceeded the seat's clock"},
        step_count=2, decision_count=2, decisions_checked=3, last_selection_seat=None,
        game_digest=chain(chained(lines), forfeit), violation=None, diagnostics=())
    assert clocks(p0) == [{"remaining_ms": 1000, "max_decision_ms": 800}, {"remaining_ms": 300, "max_decision_ms": 800}]
    assert clocks(p1) == [{"remaining_ms": 1000, "max_decision_ms": 800}]
    # choose is bounded by the clock's budget, game_start and game_over by game_start_ms (R2-4).
    assert p0.timeouts == [("game_start", 1.0), ("choose", 0.8), ("choose", 0.3), ("game_over", 1.0)]
    assert p1.timeouts == [("game_start", 1.0), ("choose", 0.8), ("game_over", 1.0)]
    assert steps_sent(lines) == [0, 1]
    assert terminal(p0) == {"outcome": "p1_win", "classification": "forfeit", "winner": "p1", "reason": "forfeit:timeout",
                            "seat_step_count": 1}                         # the late answer was never accepted


def test_a_late_answer_is_a_timeout_whatever_it_says() -> None:
    """801 ms of an 800 ms max_decision_ms, with a full bank: the clock is charged before the answer is read, so a
    late out-of-range candidate is a timeout, not an invalid selection (spec 11.4)."""
    now = [0]
    result, _ = play(seats={"p0": Seat(thinking(now, 801, answer=lambda decision: 99)), "p1": Seat()},
                     clock_ns=lambda: now[0], time_control=TimeControl(1000, 1000, 600000, 0, 800, 30000))
    assert result.adjudication == {"kind": "forfeit", "cause": "timeout", "loser_seat": "p0",
                                   "detail": "the answer to choose at seat step 0 exceeded the seat's clock"}
    assert (result.reason, result.step_count, result.decisions_checked) == ("forfeit:timeout", 0, 1)


def test_an_answer_that_takes_exactly_its_budget_is_in_time() -> None:
    """800 ms of an 800 ms max_decision_ms, then 200 ms of the 200 ms left in the bank: spec 11.4 forfeits only a
    decision that exceeds them."""
    now = [0]
    p0 = Seat(thinking(now, 800, 200))
    result, _ = play(seats={"p0": p0, "p1": Seat()}, clock_ns=lambda: now[0],
                     time_control=TimeControl(1000, 1000, 1000, 0, 800, 30000))
    assert (result.classification, result.reason, result.adjudication) == ("natural", "score", None)
    assert clocks(p0) == [{"remaining_ms": 1000, "max_decision_ms": 800}, {"remaining_ms": 200, "max_decision_ms": 800}]
    assert [timeout_s for kind, timeout_s in p0.timeouts if kind == "choose"] == [0.8, 0.2]


def test_the_increment_refills_the_bank() -> None:
    """Fischer: 1000 - 700 + 500 leaves 800 for p0's second answer, and p1's instant answer grows its bank past
    bank_ms (spec 11.4 adds the increment after every decision)."""
    now = [0]
    p0, p1 = Seat(thinking(now, 700, 700)), Seat()
    result, _ = play(seats={"p0": p0, "p1": p1}, clock_ns=lambda: now[0],
                     time_control=TimeControl(1000, 1000, 1000, 500, 800, 30000))
    assert (result.classification, result.reason, result.adjudication) == ("natural", "score", None)
    assert clocks(p0) == [{"remaining_ms": 1000, "max_decision_ms": 800}, {"remaining_ms": 800, "max_decision_ms": 800}]
    assert clocks(p1) == [{"remaining_ms": 1000, "max_decision_ms": 800}, {"remaining_ms": 1500, "max_decision_ms": 800}]


# -- real processes (spec 11.4, 11.5) ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mode", "time_control", "cause", "detail"),
    [
        ("hang", replace(GENEROUS, max_decision_ms=300), "timeout", "no answer to choose within 300 ms"),
        ("hang", replace(GENEROUS, bank_ms=300), "timeout", "no answer to choose within 300 ms"),
        ("slow-game-start", replace(GENEROUS, game_start_ms=500), "timeout", "no answer to game_start within 500 ms"),
        ("out-of-range", GENEROUS, "invalid_selection", "candidate_id 999 is outside the 2 candidates"),
        ("wrong-echo-step", GENEROUS, "invalid_selection", "seat_step echo does not match the offered decision"),
        ("garbage", GENEROUS, "malformed_response", "the answer to choose was not a valid protocol message"),
        ("crash", GENEROUS, "transport_error", "the bot process failed during choose"),   # fixed text: no stderr in it
    ],
    ids=["hang", "hang past the bank", "slow-game-start", "out-of-range", "wrong-echo-step", "garbage", "crash"],
)
def test_real_processes_time_out_and_bad_answers_forfeit(mode: str, time_control: TimeControl, cause: str,
                                                         detail: str) -> None:
    """Only the budget a timeout mode is meant to break is tight: 300 ms for choose (max_decision_ms, or the bank),
    500 ms for game_start. Every other answer has 30 s, so load can never turn its forfeit into a timeout."""
    result, _ = play(seats={"p0": hostile(mode), "p1": Seat()}, time_control=time_control)
    assert (result.outcome, result.classification, result.winner, result.reason) == (
        "p1_win", "forfeit", "p1", f"forfeit:{cause}")
    assert result.adjudication == {"kind": "forfeit", "cause": cause, "loser_seat": "p0", "detail": detail}


@pytest.mark.parametrize("mode", ["extra-fields", "crlf", "crash-on-game-over"])
def test_lenient_answers_and_game_over_failures_never_forfeit(mode: str) -> None:
    result, _ = play(seats={"p0": hostile(mode), "p1": Seat()})
    assert (result.outcome, result.classification, result.winner, result.reason, result.adjudication,
            result.step_count) == ("draw", "natural", None, "score", None, 4)


def test_a_slow_engine_halts_the_game() -> None:
    """engine_step_ms bounds each engine answer (spec 11.4): the hostile engine never answers the first step. 2 s,
    not less, so the reset it answers at once is never the answer that times out on a loaded machine."""
    result, _ = play(engine="hostile_v2_engine.py", engine_args=("hang-on-step",),
                     time_control=TimeControl(30000, 30000, 600000, 0, 60000, 2000))
    assert (result.classification, result.reason, result.last_selection_seat) == (
        "halted", "host_engine_fault:timeout", "p0")
    assert result.adjudication == {"kind": "halt", "detail": "the engine did not answer step 0 within 2000 ms"}
