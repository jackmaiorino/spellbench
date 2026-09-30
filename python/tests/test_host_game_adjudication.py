"""Clocks, caps, stalling, the mandatory-loop draw, and forfeits through real processes (spec 11.4, 11.5)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

from spellbench import wire
from spellbench.arena.config import BotSpec
from spellbench.arena.drivers import SubprocessDriver
from spellbench.host.engine_process import EngineProcess
from spellbench.host.game import play_game
from spellbench.host.seat import SeatFailure
from spellbench.messages import Limits, TimeControl, WireDeck

from conftest import ScriptedPeer
from test_host_game import (
    BURN, DRIFTED, FIRST, HELLO_LINE, OWN, Seat, chain, chained, decision_line, halted, lands, recorded, scripted,
    setup, terminal_line, two_attackers,
)

TESTS = Path(__file__).resolve().parent
TIGHT = Limits(max_decisions=10000, max_steps=100000, max_seat_decisions_per_turn=20,
               max_seat_decisions_per_game=4999, max_seat_steps_per_game=49999)


def play(*, deck: str = "Burn", seats=None, engine: str = "fake_v2_engine.py", engine_args=(), clock_ns=None, **changes):
    wire = WireDeck(deck_id=BURN.deck_id, catalog_id=deck)
    process = EngineProcess([sys.executable, str(TESTS / engine), *engine_args], timeout_s=30)
    process.hello()
    seats = seats or {"p0": Seat(lands), "p1": Seat()}
    try:
        kwargs = {} if clock_ns is None else {"clock_ns": clock_ns}
        return play_game(setup(wire_decks=(wire, wire), **changes), engine=process, seats=seats, **kwargs)
    finally:
        process.close()
        for driver in seats.values():
            driver.close()


def hostile(mode: str) -> SubprocessDriver:
    spec = BotSpec(name="hostile", version="1.0.0", type="subprocess", command=(sys.executable, str(TESTS / "bot_v2_hostile.py"), mode))
    return SubprocessDriver(spec, startup_ms=30_000)


def test_a_loop_of_mandatory_actions_is_a_draw_at_the_cap() -> None:
    result = play(deck="Loop", limits=TIGHT)
    assert (result.outcome, result.classification, result.winner, result.reason) == ("draw", "natural", None, "mandatory_loop")
    assert result.adjudication["kind"] == "mandatory_loop" and result.step_count == 39   # p0's 20th answer is the 39th


def test_the_seat_with_more_real_choices_forfeits_for_stalling() -> None:
    last = lambda decision: len(decision["candidates"]) - 1
    result = play(deck="Stall", seats={"p0": Seat(last), "p1": Seat()}, limits=TIGHT)
    assert (result.classification, result.winner, result.reason) == ("forfeit", "p1", "forfeit:stalling")
    assert result.adjudication["loser_seat"] == "p0"
    assert result.adjudication["detail"] == (
        "p0 reached max_seat_decisions_per_turn (20); real choices in the last 250 decisions: p0 20, p1 0")   # R3-12
    ended = play(deck="Stall", seats={"p0": Seat(), "p1": Seat()}, limits=TIGHT)
    assert (ended.outcome, ended.reason) == ("draw", "stall_ended")


def test_the_bank_drains_and_a_late_answer_is_a_timeout() -> None:
    now = [0]

    def slow(decision):
        now[0] += 700_000_000          # 700 ms of fake wall time
        return 0

    p0 = Seat(slow)
    result = play(seats={"p0": p0, "p1": Seat()}, clock_ns=lambda: now[0],
                  time_control=TimeControl(startup_ms=1000, game_start_ms=1000, bank_ms=1000, increment_ms=0,
                                           max_decision_ms=800, engine_step_ms=30000))
    assert (result.classification, result.winner, result.reason) == ("forfeit", "p1", "forfeit:timeout")
    clocks = [payload["clock"] for kind, payload in p0.received if kind == "choose"]
    assert clocks == [{"remaining_ms": 1000, "max_decision_ms": 800}, {"remaining_ms": 300, "max_decision_ms": 800}]


def test_the_increment_refills_the_bank() -> None:
    now = [0]

    def slow(decision):
        now[0] += 700_000_000
        return lands(decision)

    result = play(seats={"p0": Seat(slow), "p1": Seat()}, clock_ns=lambda: now[0],
                  time_control=TimeControl(1000, 1000, 1000, 500, 800, 30000))
    assert result.reason == "score"                                  # 1000 - 700 + 500 = 800 left for the second answer


def test_real_processes_time_out_and_bad_answers_forfeit() -> None:
    fast = TimeControl(startup_ms=30000, game_start_ms=500, bank_ms=600000, increment_ms=0, max_decision_ms=300, engine_step_ms=30000)
    for mode, cause in (("hang", "timeout"), ("slow-game-start", "timeout"), ("out-of-range", "invalid_selection"),
                        ("wrong-echo-step", "invalid_selection"), ("garbage", "malformed_response"), ("crash", "transport_error")):
        result = play(seats={"p0": hostile(mode), "p1": Seat()}, time_control=fast)
        assert (result.reason, result.winner) == (f"forfeit:{cause}", "p1"), mode


def test_lenient_answers_and_game_over_failures_never_forfeit() -> None:
    for mode in ("extra-fields", "crlf", "crash-on-game-over"):
        result = play(seats={"p0": hostile(mode), "p1": Seat()})
        assert result.classification == "natural", mode


def test_a_slow_engine_halts_the_game() -> None:
    result = play(engine="hostile_v2_engine.py", engine_args=("hang-on-step",),
                  time_control=TimeControl(30000, 30000, 600000, 0, 60000, 500))
    assert (result.classification, result.reason) == ("halted", "host_engine_fault:timeout")


# -- Carried from Task 23's re-review: the start deadline, silencing at start, and two digest paths ----------


class LateStart(Seat):
    """A start that logs its ``game_start`` at once and finishes only after ``delay_s``: a slow launch."""

    def __init__(self, delay_s: float) -> None:
        super().__init__()
        self.delay_s = delay_s

    def start(self, game_start, *, timeout_s):
        self.received.append(("game_start", game_start))
        self.timeouts.append(("game_start", timeout_s))
        time.sleep(self.delay_s)


def test_the_start_deadline_is_startup_plus_game_start_shared_by_both_seats() -> None:
    """Spec 11.4 (R2-26): one deadline of startup_ms + game_start_ms bounds both starts together.

    p0's start takes 1.2 s: past game_start_ms alone (a subprocess driver spends startup_ms on its launch and
    hello before the game_start budget) but within the shared 2 s, so p0 starts. p1's takes 3 s: judged a
    timeout at the 2 s deadline; a fresh deadline per seat would let it finish at 3 s and play on.
    """
    engine, peer = scripted()
    seats = {"p0": LateStart(1.2), "p1": LateStart(3.0)}
    started = time.monotonic()
    result = play_game(setup(time_control=TimeControl(1000, 1000, 600000, 2000, 60000, 120000)), engine=engine, seats=seats)
    assert time.monotonic() - started < 2.8                            # judged at the 2 s deadline, not at p1's 3 s
    assert (result.reason, result.winner) == ("forfeit:timeout", "p0")
    assert result.adjudication == {"kind": "forfeit", "cause": "timeout", "loser_seat": "p1",
                                   "detail": "the seat did not start within 2000 ms (startup_ms plus game_start_ms)"}
    assert seats["p1"].closed and [kind for kind, _ in seats["p1"].received] == ["game_start"]   # closed, nothing more (R2-4)
    assert [kind for kind, _ in seats["p0"].received] == ["game_start", "game_over"]
    assert len(peer.sent) == 1                                           # no reset was sent


def test_a_seat_whose_start_fails_with_transport_error_is_closed() -> None:
    """Its process is gone: the host closes the driver at once and sends it nothing more (R2-4)."""
    engine, peer = scripted()
    gone = Seat(start_error=SeatFailure("transport_error", "the bot process failed during game_start"))
    other = Seat()
    result = play_game(setup(), engine=engine, seats={"p0": gone, "p1": other})
    assert (result.reason, result.winner) == ("forfeit:transport_error", "p1") and gone.closed
    assert [kind for kind, _ in gone.received] == ["game_start"]
    assert [kind for kind, _ in other.received] == ["game_start", "game_over"]
    assert len(peer.sent) == 1                                           # no reset was sent


RESET_ERROR = wire.canonical_json_dumps({"response_type": "error", "protocol": "spellbench/v2", "request_id": "h-2",
                                         "error": {"code": "unsupported_deck", "message": "x"}})


def test_a_reset_answered_with_an_error_is_chained_before_the_halt() -> None:
    """The reset request seeds the digest; its answered error line is chained, then the halt's adjudication (spec 11.8)."""
    engine, peer = recorded(ScriptedPeer([HELLO_LINE, RESET_ERROR]))
    result = play_game(setup(), engine=engine, seats={"p0": Seat(), "p1": Seat()})
    assert result.reason == "host_engine_fault:error"
    assert len(chained(peer.lines)) == 2                                 # the reset request and its error answer
    assert result.game_digest == chain(chained(peer.lines), halted("host_engine_fault:error"))


def test_a_reset_answered_with_a_non_json_line_chains_the_seed_only() -> None:
    """The answer line was not JSON, so nothing but the seeded reset request precedes the adjudication (spec 11.8)."""
    engine, peer = recorded(ScriptedPeer([HELLO_LINE, b"{broken"]))
    result = play_game(setup(), engine=engine, seats={"p0": Seat(), "p1": Seat()})
    assert result.reason == "host_engine_fault:malformed"
    assert len(chained(peer.lines)) == 1                                 # the seeded reset request stands alone
    assert result.game_digest == chain(chained(peer.lines), halted("host_engine_fault:malformed"))


def test_a_refused_terminal_that_drifts_the_identity_is_chained_before_its_v10_halt() -> None:
    """The client refused the terminal (its step_count), then the validator fails it (V10): the answered exchange
    is chained and the digest's adjudication record is the violation's, not the count fault's (spec order)."""
    engine, peer = recorded(ScriptedPeer([HELLO_LINE, FIRST, terminal_line(step_count=5, provenance=DRIFTED)]))
    result = play_game(setup(), engine=engine, seats={"p0": Seat(), "p1": Seat()})
    assert result.reason == "host_validator:V10"
    assert result.game_digest == chain(chained(peer.lines), halted("host_validator:V10"))


def test_a_refused_terminal_inside_a_partial_group_is_chained_before_its_v3_halt() -> None:
    """The same for V3: a refused terminal that ends the game inside p0's partial group chains, then halts as V3."""
    engine, peer = recorded(ScriptedPeer([HELLO_LINE, decision_line("h-2", 0, two_attackers()),
                                          terminal_line(step_count=5, decision_count=0)]))
    result = play_game(setup(), engine=engine, seats={"p0": Seat(), "p1": Seat()})
    assert result.reason == "host_validator:V3"
    assert result.game_digest == chain(chained(peer.lines), halted("host_validator:V3"))
