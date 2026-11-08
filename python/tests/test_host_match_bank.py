"""A per-seat starting bank (``GameSetup.starting_bank_ms``) and the remaining bank a game reports (match mode)."""

from __future__ import annotations

import pytest

from spellbench.host.game import play_game
from spellbench.host.seat import SeatFailure
from spellbench.messages import TimeControl

from test_host_game import FIRST, STOP, Seat, fail, real_engine, scripted, setup

# A match clock: no increment, and the per-decision cap is the whole bank.
MATCH = TimeControl(startup_ms=300000, game_start_ms=60000, bank_ms=10000, increment_ms=0, max_decision_ms=10000,
                    engine_step_ms=120000)


def ticking(spend_ms: int, now: list[int], then=lambda decision: 0):
    """A pick that advances the fake wall clock by ``spend_ms`` before answering (or raising) through ``then``."""
    def pick(decision):
        now[0] += spend_ms * 1_000_000
        return then(decision)
    return pick


def test_without_a_starting_bank_nothing_changes() -> None:
    """The default path: no remaining bank in the result, and choose shows the time control's bank."""
    engine, _ = scripted(FIRST, STOP)
    p0 = Seat()
    result = play_game(setup(time_control=MATCH), engine=engine, seats={"p0": p0, "p1": Seat()})
    assert result.remaining_bank_ms is None
    assert p0.received[1][1]["clock"] == {"remaining_ms": 10000, "max_decision_ms": 10000}


def test_each_seat_starts_at_its_bank_and_reports_what_is_left() -> None:
    now = [0]
    engine, _ = scripted(FIRST, STOP)
    p0 = Seat(ticking(700, now))
    result = play_game(setup(time_control=MATCH, starting_bank_ms=(5000, 7000)), engine=engine,
                       seats={"p0": p0, "p1": Seat()}, clock_ns=lambda: now[0])
    assert p0.received[1][1]["clock"] == {"remaining_ms": 5000, "max_decision_ms": 10000}
    assert p0.timeouts[1] == ("choose", 5.0)                  # the cap is the remaining bank
    assert result.reason == "host_engine_fault:timeout"       # the scripted engine stops after one step
    assert result.remaining_bank_ms == {"p0": 4300, "p1": 7000}


def test_a_natural_game_reports_both_banks() -> None:
    engine = real_engine()
    try:
        result = play_game(setup(time_control=MATCH, starting_bank_ms=(9000, 8000)), engine=engine,
                           seats={"p0": Seat(), "p1": Seat()})
    finally:
        engine.close()
    assert result.classification == "natural"
    assert set(result.remaining_bank_ms) == {"p0", "p1"}
    assert 0 < result.remaining_bank_ms["p0"] <= 9000 and 0 < result.remaining_bank_ms["p1"] <= 8000


def test_an_answer_over_the_remaining_bank_flags_with_zero_left() -> None:
    now = [0]
    engine, _ = scripted(FIRST)
    result = play_game(setup(time_control=MATCH, starting_bank_ms=(500, 10000)), engine=engine,
                       seats={"p0": Seat(ticking(600, now)), "p1": Seat()}, clock_ns=lambda: now[0])
    assert (result.reason, result.adjudication["loser_seat"]) == ("forfeit:timeout", "p0")
    assert result.remaining_bank_ms == {"p0": 0, "p1": 10000}


def test_a_driver_timeout_flags_with_zero_left() -> None:
    """The driver gave up at the budget (the remaining bank): the bank is spent, floored at 0."""
    now = [0]
    engine, _ = scripted(FIRST)
    timeout = SeatFailure("timeout", "no answer to choose within 500 ms")
    p0 = Seat(ticking(501, now, lambda decision: fail(timeout)))
    result = play_game(setup(time_control=MATCH, starting_bank_ms=(500, 10000)), engine=engine,
                       seats={"p0": p0, "p1": Seat()}, clock_ns=lambda: now[0])
    assert (result.reason, result.adjudication["loser_seat"]) == ("forfeit:timeout", "p0") and p0.closed
    assert result.remaining_bank_ms == {"p0": 0, "p1": 10000}


def test_a_start_timeout_leaves_the_bank() -> None:
    engine, _ = scripted()
    failing = Seat(start_error=SeatFailure("timeout", "no answer to game_start within 60000 ms"))
    result = play_game(setup(time_control=MATCH, starting_bank_ms=(4000, 6000)), engine=engine,
                       seats={"p0": failing, "p1": Seat()})
    assert result.reason == "forfeit:timeout"
    assert result.remaining_bank_ms == {"p0": 4000, "p1": 6000}


@pytest.mark.parametrize("bank", [(-1, 10), (10, 1.5), (True, 10)])
def test_a_bad_starting_bank_is_a_host_fault(bank) -> None:
    engine, _ = scripted()
    with pytest.raises(ValueError):
        play_game(setup(time_control=MATCH, starting_bank_ms=bank), engine=engine, seats={"p0": Seat(), "p1": Seat()})
