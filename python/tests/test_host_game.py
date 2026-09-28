"""One game through the host: routing, canonical forwarding, the digest, halts and forfeits (spec 11)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from spellbench import wire
from spellbench.agent_messages import Choice, OwnDeck
from spellbench.digests import GameDigest, deck_id
from spellbench.errors import PeerTimeoutError
from spellbench.host.engine_process import EngineProcess
from spellbench.host.game import GameSetup, play_game
from spellbench.host.seat import SeatFailure
from spellbench.messages import DeckRow, Limits, Resources, Rules, TimeControl, WireDeck
from spellbench.run_secret import RunSecret

from conftest import ScriptedPeer
from test_messages import HELLO_OK, PROVENANCE, RULES
from v2_sample_semantics import seat_decision

ENGINE = Path(__file__).resolve().parent / "fake_v2_engine.py"
SECRET = RunSecret(bytes(range(32)))
ROWS = (DeckRow("Lightning Bolt", 4), DeckRow("Mountain", 18))
BURN = WireDeck(deck_id=deck_id([row.to_json() for row in ROWS]), catalog_id="Burn")
OWN = OwnDeck(deck_id=BURN.deck_id, name="Burn", decklist=ROWS)


def setup(index: int = 0, **changes) -> GameSetup:
    values = dict(game_index=index, game_id=SECRET.game_id(index), game_secret_hex=SECRET.game_secret(index).hex(),
                  format="pauper-bo1", wire_decks=(BURN, BURN), own_decks=(OWN, OWN), rules=Rules.from_json(RULES),
                  time_control=TimeControl(300000, 60000, 600000, 2000, 60000, 120000),
                  limits=Limits(10000, 100000, 500, 4999, 49999), resources=Resources(1, 4096, False, 1),
                  agent_seeds=(SECRET.agent_seed(index, "p0"), SECRET.agent_seed(index, "p1")))
    values.update(changes)
    return GameSetup(**values)


def fail(exc: BaseException):
    raise exc


class Seat:
    """A scripted SeatDriver: pick(decision) returns a candidate_id or a Choice, or raises."""

    def __init__(self, pick=lambda decision: 0, *, start_error: SeatFailure | None = None, start_delay_s: float = 0.0) -> None:
        self.pick, self.start_error, self.start_delay_s, self.received, self.closed = pick, start_error, start_delay_s, [], False

    def start(self, game_start, *, timeout_s):
        time.sleep(self.start_delay_s)
        self.received.append(("game_start", game_start))
        if self.start_error is not None:
            raise self.start_error

    def choose(self, choose, *, timeout_s):
        self.received.append(("choose", choose))
        result = self.pick(choose["decision"])
        return result if isinstance(result, Choice) else Choice(request_id="r", candidate_id=result, echoes={})

    def game_over(self, game_over, *, timeout_s):
        self.received.append(("game_over", game_over))

    def close(self) -> None:
        self.closed = True


def lands(decision) -> int:
    kinds = [candidate["semantic"]["kind"] for candidate in decision["candidates"]]
    return kinds.index("play_land") if "play_land" in kinds else 0


def real_engine() -> EngineProcess:
    engine = EngineProcess([sys.executable, str(ENGINE)], timeout_s=30)
    engine.hello()
    return engine


def scripted(*answers) -> tuple[EngineProcess, ScriptedPeer]:
    peer = ScriptedPeer([wire.canonical_json_dumps(HELLO_OK), *answers])
    engine = EngineProcess(peer=peer)
    engine.hello()
    return engine, peer


def decision_line(request_id: str, step: int, sd: dict) -> bytes:
    return wire.canonical_json_dumps({"response_type": "decision", "protocol": "spellbench/v2", "request_id": request_id,
                                      "game_id": SECRET.game_id(0), "step": step, "seat_decision": sd, "provenance": PROVENANCE})


FIRST = decision_line("h-2", 0, seat_decision())


def test_a_natural_game_routes_both_seats() -> None:
    engine, p0, p1 = real_engine(), Seat(lands), Seat()
    try:
        result = play_game(setup(), engine=engine, seats={"p0": p0, "p1": p1})
    finally:
        engine.close()
    assert (result.outcome, result.classification, result.reason) == ("p0_win", "natural", "score")
    assert (result.step_count, result.decision_count, result.decisions_checked) == (4, 4, 4)
    assert result.adjudication is None and result.violation is None and result.last_selection_seat is None
    assert [kind for kind, _ in p0.received] == ["game_start", "choose", "choose", "game_over"]
    start = p0.received[0][1]
    assert set(start) == {"game_id", "seat", "format", "own_deck", "opponent_deck", "rules", "engine", "engine_profile",
                          "time_control", "limits", "resources", "agent_seed"}
    assert start["agent_seed"] == SECRET.agent_seed(0, "p0") and start["opponent_deck"] == start["own_deck"]
    assert set(p0.received[1][1]) == {"game_id", "decision", "clock"}
    assert p0.received[-1][1]["terminal"] == {"outcome": "p0_win", "classification": "natural", "winner": "p0",
                                              "reason": "score", "seat_step_count": 2}


def test_the_digest_is_reproducible_and_depends_on_the_secret() -> None:
    digests = []
    for index in (0, 0, 1):
        engine = real_engine()
        try:
            digests.append(play_game(setup(index), engine=engine, seats={"p0": Seat(lands), "p1": Seat()}).game_digest)
        finally:
            engine.close()
    assert digests[0] == digests[1] != digests[2]


@pytest.mark.parametrize(
    ("answer", "reason"),
    [
        (PeerTimeoutError("slow"), "host_engine_fault:timeout"),
        (b"{broken", "host_engine_fault:malformed"),
        (wire.canonical_json_dumps({"response_type": "error", "protocol": "spellbench/v2", "request_id": "h-3",
                                    "error": {"code": "game_id_mismatch", "message": "x"}}), "host_engine_fault:error"),
        (wire.canonical_json_dumps({"response_type": "terminal", "protocol": "spellbench/v2", "request_id": "h-3",
                                    "game_id": SECRET.game_id(0), "outcome": "draw", "classification": "natural", "winner": None,
                                    "reason": "x", "step_count": 1, "decision_count": 7, "provenance": PROVENANCE}),
         "host_engine_fault:terminal_counts"),
        (wire.canonical_json_dumps({"response_type": "terminal", "protocol": "spellbench/v2", "request_id": "h-3",
                                    "game_id": SECRET.game_id(0), "outcome": "draw", "classification": "natural", "winner": None,
                                    "reason": "x", "step_count": 5, "decision_count": 1, "provenance": PROVENANCE}),
         "host_engine_fault:terminal_counts"),                                    # the engine client's TerminalCountError (R2-3)
    ],
)
def test_engine_faults_halt_after_the_last_selection(answer, reason: str) -> None:
    engine, _ = scripted(FIRST, answer)
    p1 = Seat()
    result = play_game(setup(), engine=engine, seats={"p0": Seat(), "p1": p1})
    assert (result.classification, result.outcome, result.reason, result.winner) == ("halted", "halted", reason, None)
    assert result.adjudication["kind"] == "halt" and result.last_selection_seat == "p0"
    assert p1.received[-1][0] == "game_over"


def test_a_terminal_reason_impersonating_the_host_halts() -> None:
    """Controller note 1: engine_process's TerminalReasonError becomes a host_engine_fault:terminal_reason halt.

    An engine terminal whose reason starts with host_validator:, host_engine_fault: or forfeit: impersonates
    the host (engine_process._HOST_REASON_PREFIXES); the host never lets that stand as the game's own reason.
    """
    terminal = {"response_type": "terminal", "protocol": "spellbench/v2", "request_id": "h-3", "game_id": SECRET.game_id(0),
                "outcome": "draw", "classification": "natural", "winner": None, "reason": "host_validator:V9",
                "step_count": 1, "decision_count": 1, "provenance": PROVENANCE}
    engine, _ = scripted(FIRST, wire.canonical_json_dumps(terminal))
    p1 = Seat()
    result = play_game(setup(), engine=engine, seats={"p0": Seat(), "p1": p1})
    assert (result.classification, result.outcome, result.reason, result.winner) == (
        "halted", "halted", "host_engine_fault:terminal_reason", None)
    assert result.adjudication["kind"] == "halt" and result.last_selection_seat == "p0"
    assert p1.received[-1][0] == "game_over"


def test_a_terminal_count_halt_names_both_counts() -> None:
    terminal = {"response_type": "terminal", "protocol": "spellbench/v2", "request_id": "h-3", "game_id": SECRET.game_id(0),
                "outcome": "draw", "classification": "natural", "winner": None, "reason": "x", "step_count": 1,
                "decision_count": 7, "provenance": PROVENANCE}
    engine, _ = scripted(FIRST, wire.canonical_json_dumps(terminal))
    result = play_game(setup(), engine=engine, seats={"p0": Seat(), "p1": Seat()})
    assert result.adjudication["detail"] == "terminal step_count 1, decision_count 7; host counted 1, 1"   # R2-23


def test_a_validator_violation_halts_and_the_digest_records_it() -> None:
    engine, peer = scripted(decision_line("h-2", 0, seat_decision(acting_seat="p1")))
    result = play_game(setup(), engine=engine, seats={"p0": Seat(), "p1": Seat()})
    assert (result.reason, result.violation["rule"], result.last_selection_seat) == ("host_validator:V2", "V2", None)
    digest = GameDigest(wire.strict_json_loads(peer.sent[1]))
    digest.add_response(wire.strict_json_loads(decision_line("h-2", 0, seat_decision(acting_seat="p1"))))
    digest.add_adjudication(classification="halted", outcome="halted", reason="host_validator:V2", winner=None)
    assert result.game_digest == digest.value()


def test_a_seat_that_cannot_start_forfeits_before_any_reset() -> None:
    engine, peer = scripted()
    failing, other = Seat(start_error=SeatFailure("timeout", "no answer to game_start within 60000 ms")), Seat()
    result = play_game(setup(), engine=engine, seats={"p0": failing, "p1": other})
    assert (result.classification, result.winner, result.reason, result.step_count) == ("forfeit", "p1", "forfeit:timeout", 0)
    assert result.adjudication == {"kind": "forfeit", "cause": "timeout", "loser_seat": "p0",
                                   "detail": "no answer to game_start within 60000 ms"}
    assert len(peer.sent) == 1                                           # only hello: no reset was sent
    assert [kind for kind, _ in failing.received] == ["game_start"] and failing.closed   # timed out: closed, nothing more (R2-4)
    assert [kind for kind, _ in other.received] == ["game_start", "game_over"]


def test_a_seat_that_times_out_on_choose_gets_no_game_over() -> None:
    engine, _ = scripted(FIRST)
    slow, other = Seat(lambda d: fail(SeatFailure("timeout", "no answer to choose within 60000 ms"))), Seat()
    result = play_game(setup(), engine=engine, seats={"p0": slow, "p1": other})
    assert result.reason == "forfeit:timeout" and slow.closed                        # its request is still outstanding
    assert [kind for kind, _ in slow.received] == ["game_start", "choose"]         # spec 2: never pipelined (R2-4)
    assert other.received[-1][0] == "game_over"


def test_both_seats_start_at_once() -> None:
    engine, _ = scripted(FIRST, PeerTimeoutError("stop here"))
    started = time.monotonic()
    play_game(setup(), engine=engine, seats={"p0": Seat(start_delay_s=1.5), "p1": Seat(start_delay_s=1.5)})
    assert time.monotonic() - started < 2.8                                         # not 3 s in series (R2-26)


def test_a_hidden_opponent_decklist_is_sent_as_null() -> None:
    engine, p0, p1 = real_engine(), Seat(lands), Seat()
    try:
        play_game(setup(rules=Rules.from_json({**RULES, "opponent_decklist": "hidden"})), engine=engine, seats={"p0": p0, "p1": p1})
    finally:
        engine.close()
    for seat in (p0, p1):
        start = seat.received[0][1]
        assert "opponent_deck" in start and start["opponent_deck"] is None           # spec 10.2 (R1-19)


def test_a_game_setup_never_prints_its_secret() -> None:
    assert SECRET.game_secret(0).hex() not in repr(setup())                           # R3-28


@pytest.mark.parametrize(
    ("pick", "cause"),
    [
        (lambda d: fail(SeatFailure("agent_error", "choose was answered with an error (internal_error)")), "agent_error"),
        (lambda d: 7, "invalid_selection"),
        (lambda d: -1, "invalid_selection"),                                        # never the last candidate (R2-16)
        (lambda d: Choice(request_id="r", candidate_id=0, echoes={"seat_step": 5}), "invalid_selection"),
        (lambda d: Choice(request_id="r", candidate_id=0, echoes={"seat_step": False}), "invalid_selection"),
        (lambda d: Choice(request_id="r", candidate_id=0, echoes={"semantic_echo": {"kind": "cast_spell"}}), "invalid_selection"),
    ],
)
def test_a_bad_answer_forfeits_the_acting_seat(pick, cause: str) -> None:
    engine, _ = scripted(FIRST)
    result = play_game(setup(), engine=engine, seats={"p0": Seat(pick), "p1": Seat()})
    assert (result.classification, result.winner, result.reason) == ("forfeit", "p1", f"forfeit:{cause}")
    assert (result.step_count, result.decisions_checked) == (0, 1)


def test_matching_echoes_are_accepted() -> None:
    engine, _ = scripted(FIRST, PeerTimeoutError("stop here"))
    echo = Choice(request_id="r", candidate_id=0, echoes={"seat_step": 0, "semantic_echo": {"kind": "pass"}})
    result = play_game(setup(), engine=engine, seats={"p0": Seat(lambda d: echo), "p1": Seat()})
    assert result.reason == "host_engine_fault:timeout"                 # the answer was valid; the engine then stalled
