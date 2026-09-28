"""One game through the host: routing, canonical forwarding, the digest, halts and forfeits (spec 11)."""

from __future__ import annotations

import hashlib
import json
import sys
import threading
import time
from pathlib import Path

import pytest

from spellbench import wire
from spellbench.agent_messages import Choice, OwnDeck
from spellbench.arena.config import BotSpec
from spellbench.arena.drivers import SubprocessDriver
from spellbench.arena.ledger import parse_ledger
from spellbench.digests import GameDigest, deck_id
from spellbench.errors import PeerTimeoutError, TransportError
from spellbench.host import game as host_game
from spellbench.host.engine_process import EngineProcess, HostMisuseError
from spellbench.host.game import GameSetup, play_game
from spellbench.host.seat import SeatFailure
from spellbench.messages import DeckRow, Limits, ResetRequest, Resources, Rules, TimeControl, WireDeck
from spellbench.run_secret import RunSecret

import fake_v2_scenario_smoke
from conftest import ScriptedPeer
from test_ledger import A, row
from test_messages import HELLO_OK, PROVENANCE, RULES
from v2_sample_semantics import SAMPLES, seat_decision

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
    """A scripted SeatDriver: pick(decision) returns a candidate_id or a Choice, or raises; ``timeouts`` logs each bound."""

    def __init__(self, pick=lambda decision: 0, *, start_error: BaseException | None = None, start_delay_s: float = 0.0) -> None:
        self.pick, self.start_error, self.start_delay_s, self.received, self.closed = pick, start_error, start_delay_s, [], False
        self.timeouts: list[tuple[str, float]] = []

    def start(self, game_start, *, timeout_s):
        time.sleep(self.start_delay_s)
        self.received.append(("game_start", game_start))
        self.timeouts.append(("game_start", timeout_s))
        if self.start_error is not None:
            raise self.start_error

    def choose(self, choose, *, timeout_s):
        self.received.append(("choose", choose))
        self.timeouts.append(("choose", timeout_s))
        result = self.pick(choose["decision"])
        return result if isinstance(result, Choice) else Choice(request_id="r", candidate_id=result, echoes={})

    def game_over(self, game_over, *, timeout_s):
        self.received.append(("game_over", game_over))
        self.timeouts.append(("game_over", timeout_s))

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


# -- Fix round 1 (the review of 62cb1e9) ------------------------------------------------------------

HELLO_LINE = wire.canonical_json_dumps(HELLO_OK)
ERROR = wire.canonical_json_dumps({"response_type": "error", "protocol": "spellbench/v2", "request_id": "h-3",
                                   "error": {"code": "game_id_mismatch", "message": "x"}})
DRIFTED = {**PROVENANCE, "engine_version": "9.9.9"}
STOP = PeerTimeoutError("stop here")


def terminal_line(**changes) -> bytes:
    """The engine's answer to the first step: a natural draw whose counts match one answered, completed decision."""
    terminal = {"response_type": "terminal", "protocol": "spellbench/v2", "request_id": "h-3", "game_id": SECRET.game_id(0),
                "outcome": "draw", "classification": "natural", "winner": None, "reason": "x", "step_count": 1,
                "decision_count": 1, "provenance": PROVENANCE}
    return wire.canonical_json_dumps({**terminal, **changes})


def halted(reason: str) -> dict:
    return {"classification": "halted", "outcome": "halted", "reason": reason, "winner": None}


class Recorder:
    """A peer that logs each line it wrote ("out") and read ("in"), in order; a write or read that fails logs nothing."""

    def __init__(self, inner) -> None:
        self.inner, self.lines = inner, []

    def write_line(self, data: bytes) -> None:
        self.inner.write_line(data)
        self.lines.append(("out", data))

    def read_line(self) -> bytes:
        data = self.inner.read_line()
        self.lines.append(("in", data))
        return data

    def set_timeout(self, seconds) -> None:
        getattr(self.inner, "set_timeout", lambda seconds: None)(seconds)

    def stderr_text(self) -> str:
        return getattr(self.inner, "stderr_text", lambda: "")()

    def close(self) -> None:
        self.inner.close()


def recorded(inner) -> tuple[EngineProcess, Recorder]:
    peer = Recorder(inner)
    engine = EngineProcess(peer=peer)
    engine.hello()
    return engine, peer


def canon(value) -> bytes:
    """RFC 8785 for these messages without ``wire``: their keys are ASCII, so code point order is UTF-16 order."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def chain(messages: list[dict], adjudication: dict | None = None) -> str:
    """Spec 11.8 over explicit messages, without ``wire`` or ``GameDigest``: the reset request, then the rest in order."""
    def minus_id(message: dict) -> dict:
        return {key: value for key, value in message.items() if key != "request_id"}

    d = hashlib.sha256(b"spellbench/v2/game-digest" + canon(minus_id(messages[0]))).digest()
    for message in messages[1:]:
        d = hashlib.sha256(d + canon(minus_id(message))).digest()
    if adjudication is not None:
        d = hashlib.sha256(d + canon({"adjudication": adjudication})).digest()
    return "sha256:" + d.hex()


def chained(lines: list[tuple[str, bytes]]) -> list[dict]:
    """What a game digest chains, read off a peer's log: the reset request, then every step that was written and
    answered, with its answer when that line is JSON (spec 11.8, as ruled for fix round 1)."""
    messages: list[dict] = []
    for index, (direction, line) in enumerate(lines):
        if direction != "out":
            continue
        request = json.loads(line)
        answer = lines[index + 1][1] if index + 1 < len(lines) and lines[index + 1][0] == "in" else None
        if request["request_type"] == "reset":
            messages.append(request)                       # the seed, whatever became of it
        elif request["request_type"] == "step" and answer is not None:
            messages.append(request)
        else:
            continue                                       # hello, or a step that was never answered
        if answer is not None:
            try:
                messages.append(json.loads(answer))
            except ValueError:
                pass                                       # answered, but not JSON: the request alone
    return messages


def test_the_digest_of_a_natural_game_is_the_spec_11_8_chain() -> None:
    """Every step request and every answer in order, and no adjudication record for the engine's own terminal."""
    engine, peer = recorded(wire.SubprocessPeer([sys.executable, str(ENGINE)], timeout_s=30))
    try:
        result = play_game(setup(), engine=engine, seats={"p0": Seat(lands), "p1": Seat()})
    finally:
        engine.close()
    assert result.reason == "score" and len(chained(peer.lines)) == 10    # the reset, four steps, five answers
    assert result.game_digest == chain(chained(peer.lines))


@pytest.mark.parametrize(
    ("answer", "reason"),
    [
        (ERROR, "host_engine_fault:error"),
        (terminal_line(decision_count=7), "host_engine_fault:terminal_counts"),
        (terminal_line(step_count=5), "host_engine_fault:terminal_counts"),
        (terminal_line(reason="forfeit:timeout"), "host_engine_fault:terminal_reason"),
        (decision_line("h-9", 1, seat_decision()), "host_engine_fault:malformed"),         # a binding failure
        (b"{broken", "host_engine_fault:malformed"),                                       # answered, but not JSON
    ],
    ids=["error", "decision_count", "step_count", "host reason", "binding", "not JSON"],
)
def test_an_answered_fault_is_chained_before_its_halt(answer: bytes, reason: str) -> None:
    engine, peer = recorded(ScriptedPeer([HELLO_LINE, FIRST, answer]))
    result = play_game(setup(), engine=engine, seats={"p0": Seat(), "p1": Seat()})
    assert result.reason == reason
    assert result.game_digest == chain(chained(peer.lines), halted(reason))


def test_a_step_never_answered_is_never_chained_whatever_the_timing() -> None:
    """Spec 11.8 as ruled: only exchanges written and answered are chained, so an engine that died while the bot
    thought (the write fails) and one that died reading the step (EOF) give one digest."""
    inner = ScriptedPeer([HELLO_LINE, FIRST])

    def think(decision) -> int:
        inner.closed = True                        # the engine exits while the bot thinks
        return 0

    died_thinking, peer = recorded(inner)
    first = play_game(setup(), engine=died_thinking, seats={"p0": Seat(think), "p1": Seat()})
    died_reading, _ = recorded(ScriptedPeer([HELLO_LINE, FIRST, TransportError("peer EOF")]))
    second = play_game(setup(), engine=died_reading, seats={"p0": Seat(), "p1": Seat()})
    stalled, stalled_peer = recorded(ScriptedPeer([HELLO_LINE, FIRST, STOP]))
    third = play_game(setup(), engine=stalled, seats={"p0": Seat(), "p1": Seat()})
    assert first.reason == second.reason == "host_engine_fault:transport"
    assert first.game_digest == second.game_digest == chain(chained(peer.lines), halted(first.reason))
    assert len(chained(stalled_peer.lines)) == 2 and stalled_peer.lines[-1][0] == "out"     # the step was written
    assert third.game_digest == chain(chained(stalled_peer.lines), halted("host_engine_fault:timeout"))


def test_a_reset_never_written_chains_nothing_more() -> None:
    inner = ScriptedPeer([HELLO_LINE])
    engine, _ = recorded(inner)
    inner.closed = True                            # the engine exited after hello
    game = setup()
    result = play_game(game, engine=engine, seats={"p0": Seat(), "p1": Seat()})
    reset = ResetRequest(request_id="h-2", game_id=game.game_id, format=game.format, seats=game.wire_decks, rules=game.rules,
                         game_secret=game.game_secret_hex, max_decisions=game.limits.max_decisions,
                         max_steps=game.limits.max_steps).to_json()
    assert result.reason == "host_engine_fault:transport"
    assert result.game_digest == chain([reset], halted(result.reason))       # never the stale hello_ok


# An engine that answers hello and reset from a file of lines, then exits after a delay (never reading its step).
REPLAY_THEN_EXIT = """
import os
import sys
import time

answers = open(sys.argv[1], "rb").read().splitlines(keepends=True)
for answer in answers:
    sys.stdin.buffer.readline()
    sys.stdout.buffer.write(answer)
    sys.stdout.buffer.flush()
time.sleep(float(sys.argv[2]))
os._exit(3)
"""


def test_a_crashed_engine_gives_one_digest_whatever_the_bots_think_time(tmp_path: Path) -> None:
    """A real engine exits 0.5 s after its first decision: a fast bot's step is written and meets EOF, a bot thinking
    for 1.5 s writes to a process already gone. Both halt as transport faults with one digest (spec 11.8)."""
    answers = tmp_path / "answers.ndjson"
    answers.write_bytes(wire.canonical_json_line(HELLO_OK) + wire.canonical_json_line(wire.strict_json_loads(FIRST)))
    script = tmp_path / "replay_then_exit.py"
    script.write_text(REPLAY_THEN_EXIT, encoding="utf-8")
    results = {}
    for name, pick in (("fast", lambda decision: 0), ("slow", lambda decision: time.sleep(1.5) or 0)):
        engine = EngineProcess([sys.executable, str(script), str(answers), "0.5"], timeout_s=30)
        engine.hello()
        try:
            results[name] = play_game(setup(), engine=engine, seats={"p0": Seat(pick), "p1": Seat()})
        finally:
            engine.close()
    fast, slow = results["fast"], results["slow"]
    assert "peer EOF" in fast.diagnostics[0] and "exited before request" in slow.diagnostics[0]   # both paths ran
    assert fast.reason == slow.reason == "host_engine_fault:transport"
    assert fast.game_digest == slow.game_digest


def test_diagnostics_hold_the_engines_stderr_once() -> None:
    """A transport failure's text already quotes the engine's stderr (wire.SubprocessPeer); other faults add it."""
    class Noisy(ScriptedPeer):
        def stderr_text(self) -> str:
            return "engine stderr"

    diagnostics = []
    for answer in (TransportError("peer EOF; stderr='engine stderr'"), ERROR):
        engine = EngineProcess(peer=Noisy([HELLO_LINE, FIRST, answer]))
        engine.hello()
        diagnostics.append(play_game(setup(), engine=engine, seats={"p0": Seat(), "p1": Seat()}).diagnostics)
    assert diagnostics == [("peer EOF; stderr='engine stderr'",), ("game_id_mismatch: x", "engine stderr")]


def test_reusing_an_engine_whose_game_is_still_active_is_a_host_fault() -> None:
    """Spec 2: one active game per engine process, restarted after a forfeit; misuse is never an engine halt."""
    engine, peer = scripted(FIRST)
    first = play_game(setup(), engine=engine, seats={"p0": Seat(lambda d: 9), "p1": Seat()})
    assert first.reason == "forfeit:invalid_selection"
    with pytest.raises(HostMisuseError, match="already active"):
        play_game(setup(1), engine=engine, seats={"p0": Seat(), "p1": Seat()})
    assert len(peer.sent) == 2                                          # hello and the first reset: nothing more


@pytest.mark.parametrize(
    "answer",
    [STOP, TransportError("peer EOF"), b"{broken", ERROR, terminal_line(decision_count=7),
     terminal_line(reason="host_validator:V9"), terminal_line(provenance=DRIFTED)],
    ids=["timeout", "transport", "malformed", "error", "terminal_counts", "terminal_reason", "V10"],
)
def test_every_halt_the_loop_records_is_a_ledger_row(answer) -> None:
    engine, _ = scripted(FIRST, answer)
    result = play_game(setup(), engine=engine, seats={"p0": Seat(), "p1": Seat()})
    (parsed,) = parse_ledger([row(outcome=result.outcome, classification=result.classification, winner=result.winner,
                                  winner_bot_id=None, reason=result.reason, adjudication=result.adjudication,
                                  step_count=result.step_count, decision_count=result.decision_count,
                                  decisions_checked=result.decisions_checked, game_digest=result.game_digest,
                                  last_selection={"seat": result.last_selection_seat, "bot_id": A})])
    assert parsed.classification == "halted" and parsed.last_selection.seat == "p0" and not parsed.rated


def two_attackers() -> dict:
    """The first substep of a two-substep group: p0 declares the first of two attackers (spec 8)."""
    sd = seat_decision([SAMPLES["declare_attack"]], kind="choice")
    sd["group"]["substep_count"] = 2
    return sd


@pytest.mark.parametrize(
    ("first", "terminal", "rule"),
    [(FIRST, terminal_line(provenance=DRIFTED), "V10"),
     (decision_line("h-2", 0, two_attackers()), terminal_line(decision_count=0), "V3")],   # a natural end inside a group
    ids=["V10", "V3"],
)
def test_an_engine_terminal_is_validated_before_it_is_accepted(first: bytes, terminal: bytes, rule: str) -> None:
    engine, _ = scripted(first, terminal)
    result = play_game(setup(), engine=engine, seats={"p0": Seat(), "p1": Seat()})
    assert (result.reason, result.violation["rule"], result.last_selection_seat) == (f"host_validator:{rule}", rule, "p0")


@pytest.mark.parametrize("fault", [{"step_count": 5}, {"reason": "forfeit:timeout"}], ids=["step_count", "host reason"])
def test_a_validator_violation_outranks_a_count_or_reason_fault(fault: dict) -> None:
    """Spec order: a terminal's V3 and V10 checks come first, so a drifted engine identity is V10 however else its
    terminal is wrong, even where the engine client refuses the terminal first (a count, or a host reason)."""
    engine, _ = scripted(FIRST, terminal_line(provenance=DRIFTED, **fault))
    result = play_game(setup(), engine=engine, seats={"p0": Seat(), "p1": Seat()})
    assert result.reason == "host_validator:V10"
    assert result.violation == {"rule": "V10", "detail": "the engine identity drifted from its hello"}


def test_each_seat_is_sent_the_other_seats_deck() -> None:
    """R2-24: a visible opponent_deck is the other seat's own deck."""
    elves = OwnDeck(deck_id=BURN.deck_id, name="Elves", decklist=ROWS)
    engine, _ = scripted(FIRST, STOP)
    p0, p1 = Seat(), Seat()
    play_game(setup(own_decks=(OWN, elves)), engine=engine, seats={"p0": p0, "p1": p1})
    starts = [seat.received[0][1] for seat in (p0, p1)]
    assert [(start["own_deck"]["name"], start["opponent_deck"]["name"]) for start in starts] == [
        ("Burn", "Elves"), ("Elves", "Burn")]


def test_game_over_carries_each_seats_own_step_count() -> None:
    """Spec 10.4: the fake engine's Halt hook ends the game at its first step, which p0 answered and p1 never saw."""
    halt = WireDeck(deck_id=BURN.deck_id, catalog_id="Halt")
    engine, p0, p1 = real_engine(), Seat(), Seat()
    try:
        result = play_game(setup(wire_decks=(halt, BURN)), engine=engine, seats={"p0": p0, "p1": p1})
    finally:
        engine.close()
    assert (result.classification, result.reason, result.adjudication, result.last_selection_seat) == (
        "halted", "engine_contract_failure:test_hook", None, "p0")
    assert [seat.received[-1][1]["terminal"]["seat_step_count"] for seat in (p0, p1)] == [1, 0]


def test_a_seat_whose_process_failed_on_choose_gets_no_game_over() -> None:
    engine, _ = scripted(FIRST)
    gone, other = Seat(lambda d: fail(SeatFailure("transport_error", "the bot process failed during choose"))), Seat()
    result = play_game(setup(), engine=engine, seats={"p0": gone, "p1": other})
    assert result.reason == "forfeit:transport_error" and gone.closed               # its process is gone (R2-4)
    assert [kind for kind, _ in gone.received] == ["game_start", "choose"]
    assert other.received[-1][0] == "game_over"


def test_each_request_is_bounded_and_the_clock_shows_the_bank() -> None:
    """choose is bounded by the decision budget and shows the seat's bank (spec 10.3, 11.4; it never drains before
    Part B); game_start and game_over are bounded by game_start_ms."""
    clocks = TimeControl(startup_ms=300000, game_start_ms=50000, bank_ms=600000, increment_ms=2000, max_decision_ms=40000,
                         engine_step_ms=120000)
    engine, _ = scripted(FIRST, STOP)
    p0 = Seat()
    play_game(setup(time_control=clocks), engine=engine, seats={"p0": p0, "p1": Seat()})
    assert p0.timeouts == [("game_start", 50.0), ("choose", 40.0), ("game_over", 50.0)]
    assert p0.received[1][1]["clock"] == {"remaining_ms": 600000, "max_decision_ms": 40000}


def test_a_driver_that_edits_its_decision_cannot_reach_the_hosts_copy() -> None:
    """A driver gets the canonical re-serialization of the validated decision (spec 11.2), never the host's own objects."""
    class Vandal(Seat):
        def choose(self, choose, *, timeout_s):
            choose["decision"]["candidates"][0]["semantic"]["kind"] = "tampered"
            return super().choose(choose, timeout_s=timeout_s)

    engine, peer = scripted(FIRST, STOP)
    play_game(setup(), engine=engine, seats={"p0": Vandal(), "p1": Seat()})
    assert wire.strict_json_loads(peer.sent[-1])["selection"]["semantic_echo"] == {"kind": "pass"}


def test_the_charge_hook_gets_whole_milliseconds_rounded_up(monkeypatch: pytest.MonkeyPatch) -> None:
    """Part B charges the bank in integer milliseconds (host/clock.py); a partial millisecond is charged in full."""
    charged: list[int] = []
    monkeypatch.setattr(host_game._Game, "_charge", lambda self, seat, sd, elapsed_ms: charged.append(elapsed_ms))
    now = [0]

    def slow(decision) -> int:
        now[0] += 700_000_001                      # 700 ms and 1 ns of fake wall time
        return 0

    engine, _ = scripted(FIRST, STOP)
    play_game(setup(), engine=engine, seats={"p0": Seat(slow), "p1": Seat()}, clock_ns=lambda: now[0])
    assert charged == [701] and type(charged[0]) is int


# Starting both seats: classified failures, one judgment (R2-26), p0 first.


@pytest.mark.parametrize("fault", [RuntimeError("a driver bug"), TransportError("a raw transport error")], ids=["bug", "raw"])
@pytest.mark.parametrize("seat", ["p0", "p1"])
def test_a_host_fault_at_start_halts_the_game_and_forfeits_no_one(fault: BaseException, seat: str) -> None:
    """Only a SeatFailure is the bot's (host/seat.py): anything else a start raises is the host's, raised once both
    starts are judged, p0's first, even beside the other seat's own failure. No reset, no forfeit, no game_over."""
    engine, peer = scripted()
    if seat == "p0":
        seats = {"p0": Seat(start_error=fault), "p1": Seat(start_error=RuntimeError("p1's own host fault"))}
    else:
        seats = {"p0": Seat(start_error=SeatFailure("agent_error", "game_start was answered with an error")),
                 "p1": Seat(start_error=fault)}
    with pytest.raises(type(fault)) as caught:
        play_game(setup(), engine=engine, seats=seats)
    assert caught.value is fault and len(peer.sent) == 1
    assert [kind for driver in seats.values() for kind, _ in driver.received] == ["game_start", "game_start"]


def test_a_bot_that_cannot_be_launched_forfeits_transport_error(tmp_path: Path) -> None:
    """Spec 11.4: a start failure during a run is a forfeit; the subprocess driver reports it as transport_error."""
    ghost = SubprocessDriver(BotSpec(name="ghost", version="1", type="subprocess", command=(str(tmp_path / "no-such-bot.exe"),)),
                             startup_ms=5_000)
    engine, peer = scripted()
    other = Seat()
    try:
        result = play_game(setup(), engine=engine, seats={"p0": ghost, "p1": other})
    finally:
        ghost.close()
    assert (result.reason, result.winner, result.adjudication["detail"]) == (
        "forfeit:transport_error", "p1", "the bot process could not be started")
    assert len(peer.sent) == 1 and [kind for kind, _ in other.received] == ["game_start", "game_over"]


def test_a_game_start_the_host_cannot_build_raises_before_any_seat_starts() -> None:
    engine, peer = scripted()
    p0, p1 = Seat(), Seat()
    with pytest.raises(AttributeError):
        play_game(setup(own_decks=(OWN, None)), engine=engine, seats={"p0": p0, "p1": p1})
    assert p0.received == p1.received == [] and len(peer.sent) == 1


def test_when_both_seats_fail_to_start_p0_forfeits() -> None:
    """R2-26: both starts are judged p0 first, so p0's own failure decides the game; neither seat is silenced."""
    engine, _ = scripted()
    p0 = Seat(start_error=SeatFailure("agent_error", "game_start was answered with an error"))
    p1 = Seat(start_error=SeatFailure("malformed_response", "the answer to game_start was not a valid protocol message"))
    result = play_game(setup(), engine=engine, seats={"p0": p0, "p1": p1})
    assert (result.reason, result.winner, result.adjudication["loser_seat"]) == ("forfeit:agent_error", "p1", "p0")
    assert [kind for kind, _ in p0.received] == [kind for kind, _ in p1.received] == ["game_start", "game_over"]


class Stuck(Seat):
    """A start that ends only when the host closes the seat, as a bot process whose read sees EOF once it is killed."""

    def __init__(self, late: BaseException | None) -> None:
        super().__init__()
        self.late, self.release = late, threading.Event()

    def start(self, game_start, *, timeout_s):
        self.received.append(("game_start", game_start))
        self.release.wait(10)
        if self.late is not None:
            raise self.late

    def close(self) -> None:
        super().close()
        self.release.set()
        time.sleep(0.1)                            # the released start reports while the host is still closing the seat


@pytest.mark.parametrize(
    "late", [None, SeatFailure("transport_error", "the bot process failed during game_start"), RuntimeError("late")],
    ids=["returns", "transport_error", "raises"],
)
def test_a_start_that_overruns_the_deadline_is_judged_once(late: BaseException | None) -> None:
    """A start still running at startup_ms + game_start_ms is a timeout, judged once under a lock: what its thread
    reports after the host closed the seat changes nothing, and the closed seat is sent nothing more (R2-4)."""
    engine, peer = scripted(FIRST, STOP)
    stuck, other = Stuck(late), Seat()
    result = play_game(setup(time_control=TimeControl(100, 100, 600000, 2000, 60000, 120000)), engine=engine,
                       seats={"p0": stuck, "p1": other})
    assert result.adjudication == {"kind": "forfeit", "cause": "timeout", "loser_seat": "p0",
                                   "detail": "the seat did not start within 200 ms (startup_ms plus game_start_ms)"}
    assert stuck.closed and [kind for kind, _ in stuck.received] == ["game_start"]
    assert len(peer.sent) == 1 and [kind for kind, _ in other.received] == ["game_start", "game_over"]


def test_the_smoke_scenario_counts_groups_and_its_rewind_like_the_engine() -> None:
    """A two-substep group, a completed choice group, an abandoned partial group and a rewind, through the loop
    (spec 8, Decision 4): the engine's terminal counts equal the host's own."""
    deck = WireDeck(deck_id=deck_id(fake_v2_scenario_smoke.SCENARIO.decklist), catalog_id="Scenario:smoke")
    engine = EngineProcess([sys.executable, str(ENGINE), *fake_v2_scenario_smoke.SCENARIO.engine_args], timeout_s=30)
    engine.hello()

    def pick(decision) -> int:
        kinds = [candidate["semantic"]["kind"] for candidate in decision["candidates"]]
        return kinds.index("cast_spell") if "cast_spell" in kinds else len(kinds) - 1

    try:
        result = play_game(setup(wire_decks=(deck, deck)), engine=engine, seats={"p0": Seat(pick), "p1": Seat()})
    finally:
        engine.close()
    assert (result.classification, result.violation, result.adjudication) == ("natural", None, None)
    assert (result.step_count, result.decision_count) == (7, 3)
