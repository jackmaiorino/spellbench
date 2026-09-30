#!/usr/bin/env python3
"""Author the spellbench/v2 golden transcripts and their index (spec 16; Decision 7).

Writes ``goldens/protocol_v2/*.transcript.jsonl`` and ``goldens/protocol_v2/index.json``
deterministically. Every game golden plays one real game through ``host.game.play_game``
against the fake (or hostile) v2 engine with in-process reference bots, clocks pinned at
``clock_ns=lambda: 0``, game index 0 of the spec 16 vector secret and the game's rules
fitted to the engine's hello (as ``tour_helpers.play_tour`` fits them). Every engine error
golden sends crafted requests to a fresh fake engine through a recording
``EngineProcess`` (``send_raw``, ``send_line``); every agent error golden sends crafted
lines to the reference ``BotSession`` through a recording ``InProcessBot``.

``--check`` byte-verifies the on-disk files against a fresh in-memory render without
rewriting anything, printing ``OK``, ``STALE`` or ``MISSING`` per file.
"""

from __future__ import annotations

import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

TESTS = Path(__file__).resolve().parents[1] / "tests"
sys.path.insert(0, str(TESTS))  # the fake engine, its scenarios and golden_helpers live with the tests

from spellbench import wire
from spellbench._schema import SEATS
from spellbench.agent_messages import OwnDeck
from spellbench.arena.config import BotSpec
from spellbench.arena.drivers import SubprocessDriver
from spellbench.bot import BotSession, Decision
from spellbench.digests import card_name_domain, deck_id
from spellbench.host.agent_process import AgentProcess
from spellbench.host.engine_process import EngineProcess
from spellbench.host.game import GameSetup, play_game
from spellbench.messages import (
    PROTOCOL,
    DeckRow,
    Limits,
    ResetRequest,
    Resources,
    Rules,
    Selection,
    StepRequest,
    TimeControl,
    WireDeck,
)
from spellbench.run_secret import RunSecret

import fake_v2_engine
import fake_v2_scenario_board
import fake_v2_scenario_kinds
import fake_v2_scenario_knowledge
from fake_v2_world import Scenario
from golden_helpers import InProcessBot, RecordingPeer

GOLDENS_DIR = Path(__file__).resolve().parents[2] / "goldens" / "protocol_v2"
ENGINE = TESTS / "fake_v2_engine.py"
HOSTILE = TESTS / "hostile_v2_engine.py"
FORMAT = "pauper-bo1"
GAME_INDEX = 0
SECRET = RunSecret(bytes(range(32)))                 # the spec 16 test-vector run secret
assert SECRET.game_id(GAME_INDEX) == "g-f67d7fe78c792984"     # spec 16, as in the spec's own examples

SCORING_DECKLIST = fake_v2_engine.SCORING_DECKLIST
TIME_CONTROL = TimeControl(300000, 60000, 600000, 2000, 60000, 120000)
DEFAULT_LIMITS = Limits(10000, 100000, 500, 4999, 49999)
CAP_LIMITS = Limits(10000, 100000, 3, 4999, 49999)   # the loop and stall games end at the per-turn cap
RESOURCES = Resources(1, 4096, False, 1)
BOT_NAME = "golden-bot"
BOT_VERSION = "1.0.0"
_ENGINE_ROLE = ("engine",)
_GAME_ROLES = ("host", "engine", "bot_server")

# The readings the goldens follow where the spec leaves room (Decision 7); the Decision 4 reading first (R2-23).
NOTES = [
    "Spec 8 (Decision 4): a rewind abandons the rewound priority action's own group and every group completed "
    "after it; they do not count toward decision_count, and group_id is never reused.",
    "Spec 11.4 (Decision 5): a seat reaches a cap when its count equals the cap; the host adjudicates right "
    "after that answer, before its step is sent, so the cap goldens end with a choose answered and no step.",
]


@dataclass(frozen=True)
class Golden:
    """One transcript's rows and its ``index.json`` entry (Decision 7)."""

    rows: list[tuple[str, Any]]
    engine: str | None
    engine_args: tuple[str, ...]
    game_digest: str | None
    roles: tuple[str, ...]


class _GateAfterStart:
    """A peer wrapper that opens ``gate`` once two answers passed through.

    ``play_game`` starts both seats on their own threads (R2-26), so p1's agent factory
    waits on this gate: p0's whole start (the ``hello`` and ``game_start`` exchanges) is
    recorded before any row of p1's, on every run.
    """

    def __init__(self, inner: RecordingPeer, gate: threading.Event) -> None:
        self.inner, self.gate, self.reads = inner, gate, 0

    def write_line(self, payload: bytes) -> None:
        self.inner.write_line(payload)

    def read_line(self) -> bytes:
        line = self.inner.read_line()
        self.reads += 1
        if self.reads == 2:
            self.gate.set()
        return line

    def set_timeout(self, seconds) -> None:
        self.inner.set_timeout(seconds)

    def close(self) -> None:
        self.inner.close()


class _ScriptedBot:
    """A Peer answering from scripted payloads: a hand-built bot the reference BotSession cannot play.

    The BotSession refuses to send an invalid candidate id, so p0 of
    ``game_forfeit_invalid_selection`` is answered from this script instead.
    """

    def __init__(self, answers: Sequence[bytes]) -> None:
        self.answers = list(answers)

    def write_line(self, payload: bytes) -> None:
        pass

    def read_line(self) -> bytes:
        return self.answers.pop(0)

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# The games
# ---------------------------------------------------------------------------


def _pass(decision: Decision) -> int:
    return 0


def _lands(decision: Decision) -> int:
    kinds = [candidate.semantic["kind"] for candidate in decision.candidates]
    return kinds.index("play_land") if "play_land" in kinds else 0


def _activate(decision: Decision) -> int:
    kinds = [candidate.semantic["kind"] for candidate in decision.candidates]
    return kinds.index("activate_ability") if "activate_ability" in kinds else 0


def _tour_pick(decision: Decision) -> int:
    """The kinds tour's own picker (R2-2), reading the forwarded seat decision."""
    return fake_v2_scenario_kinds.pick(decision.raw["decision"])


def _rules(decklist: Sequence[Mapping[str, Any]], *, london: bool, toss: bool) -> Rules:
    return Rules.from_json({
        "opponent_decklist": "visible",
        "mulligan": "london" if london else "none",
        "starting_player": "toss_winner_chooses" if toss else "host_assigned",
        "starting_seat": None if toss else "p0",
        "card_name_domain": card_name_domain(row["name"] for row in decklist),
        "extensions": [],
        "probe": False,
    })


def _fitted_rules(hello, decklist: Sequence[Mapping[str, Any]]) -> Rules:
    """The game's rules fitted to the engine's hello, as ``tour_helpers.play_tour`` fits them."""
    supported = hello.profile.rules_supported
    return _rules(decklist,
                  london="london" in supported["mulligan"],
                  toss="toss_winner_chooses" in supported["starting_player"])


def _game_setup(catalog_id: str, decklist: Sequence[Mapping[str, Any]], rules: Rules,
                limits: Limits) -> GameSetup:
    wire_deck = WireDeck(deck_id=deck_id(decklist), catalog_id=catalog_id)
    own_deck = OwnDeck(deck_id=wire_deck.deck_id, name=catalog_id,
                       decklist=tuple(DeckRow(row["name"], row["count"]) for row in decklist))
    return GameSetup(game_index=GAME_INDEX, game_id=SECRET.game_id(GAME_INDEX),
                     game_secret_hex=SECRET.game_secret(GAME_INDEX).hex(), format=FORMAT,
                     wire_decks=(wire_deck, wire_deck), own_decks=(own_deck, own_deck), rules=rules,
                     time_control=TIME_CONTROL, limits=limits, resources=RESOURCES,
                     agent_seeds=(SECRET.agent_seed(GAME_INDEX, "p0"), SECRET.agent_seed(GAME_INDEX, "p1")))


def _session_driver(rows: list, gate: threading.Event, seat: str, *,
                    choose: Callable[[Decision], int] | None = None,
                    scripted: Sequence[bytes] | None = None,
                    bot_name: str = BOT_NAME) -> SubprocessDriver:
    """One seat's driver over a recording in-process peer; p1's factory waits for p0's start."""
    if scripted is not None:
        peer = RecordingPeer(_ScriptedBot(scripted), rows, "host_to_agent", "agent_to_host")
    else:
        assert choose is not None
        session = BotSession(choose=choose, name=bot_name, version=BOT_VERSION)
        peer = RecordingPeer(InProcessBot(session), rows, "host_to_agent", "agent_to_host")
    if seat == "p0":
        peer = _GateAfterStart(peer, gate)

    def factory() -> AgentProcess:
        if seat == "p1":
            gate.wait(30)
        return AgentProcess(peer=peer)

    spec = BotSpec(name=bot_name, version=BOT_VERSION, type="subprocess", command=("in-process",))
    return SubprocessDriver(spec, startup_ms=30_000, agent_factory=factory)


def _game(catalog_id: str, decklist: Sequence[Mapping[str, Any]], engine_args: Sequence[str], *,
          choose: Mapping[str, Callable[[Decision], int]] | None = None,
          scripted_p0: Sequence[bytes] | None = None,
          limits: Limits = DEFAULT_LIMITS,
          engine_path: Path = ENGINE,
          expect: tuple[str, str, str]) -> Golden:
    """One recorded game through ``play_game``: all four directions, and its digest."""
    rows: list[tuple[str, Any]] = []
    gate = threading.Event()
    engine = EngineProcess(peer=RecordingPeer(
        wire.SubprocessPeer([sys.executable, str(engine_path), *engine_args], timeout_s=30),
        rows, "host_to_engine", "engine_to_host"))
    drivers = {}
    try:
        hello = engine.hello()
        setup = _game_setup(catalog_id, decklist, _fitted_rules(hello, decklist), limits)
        for seat in SEATS:
            if seat == "p0" and scripted_p0 is not None:
                drivers[seat] = _session_driver(rows, gate, seat, scripted=scripted_p0, bot_name="bad-bot")
            else:
                assert choose is not None
                drivers[seat] = _session_driver(rows, gate, seat, choose=choose[seat])
        result = play_game(setup, engine=engine, seats=drivers, clock_ns=lambda: 0)
    finally:
        engine.close()
        for driver in drivers.values():
            driver.close()
    got = (result.outcome, result.classification, result.reason)
    assert got == expect, f"the game ended {got}, not {expect}"
    roles = tuple(role for role in _GAME_ROLES if scripted_p0 is None or role != "bot_server")
    return Golden(rows, engine_path.name, tuple(engine_args), result.game_digest, roles)


def _scenario(scenario: Scenario, choose: Callable[[Decision], int], *extra_args: str,
              expect: tuple[str, str, str]) -> Golden:
    catalog_id = f"Scenario:{scenario.name}"
    return _game(catalog_id, scenario.decklist, (*scenario.engine_args, *extra_args),
                 choose={seat: choose for seat in SEATS}, expect=expect)


def _bad_bot_script() -> list[bytes]:
    """p0 of ``game_forfeit_invalid_selection``: a well-formed ``choice`` of candidate 9, never offered."""
    messages = [
        {"response_type": "hello_ok", "protocol": PROTOCOL, "request_id": "r-0",
         "bot": {"name": "bad-bot", "version": BOT_VERSION},
         "requires": {"observation": [], "extensions": []}, "extensions_accepted": []},
        {"response_type": "ack", "protocol": PROTOCOL, "request_id": "r-1"},
        {"response_type": "choice", "protocol": PROTOCOL, "request_id": "r-2", "selection": {"candidate_id": 9}},
        {"response_type": "ack", "protocol": PROTOCOL, "request_id": "r-3"},
    ]
    return [wire.canonical_json_dumps(message) for message in messages]


# ---------------------------------------------------------------------------
# The engine error probes (spec 9.8)
# ---------------------------------------------------------------------------


def _wire_deck(catalog_id: str, *, bad_deck_id: bool = False) -> WireDeck:
    value = "sha256:" + "0" * 64 if bad_deck_id else deck_id(SCORING_DECKLIST)
    return WireDeck(value, catalog_id=catalog_id)


def _reset_json(request_id: str, game_id: str, *, format: str = FORMAT,
                p0_deck: WireDeck | None = None, rules: Rules | None = None) -> dict[str, Any]:
    return ResetRequest(request_id=request_id, game_id=game_id, format=format,
                        seats=(p0_deck or _wire_deck("Burn"), _wire_deck("Burn")),
                        rules=rules or _rules(SCORING_DECKLIST, london=False, toss=False),
                        game_secret=SECRET.game_secret(GAME_INDEX).hex(),
                        max_decisions=DEFAULT_LIMITS.max_decisions,
                        max_steps=DEFAULT_LIMITS.max_steps).to_json()


def _step_json(request_id: str, game_id: str, expected_step: int, candidate_id: int,
               semantic: Mapping[str, Any]) -> dict[str, Any]:
    return StepRequest(request_id=request_id, game_id=game_id, expected_step=expected_step,
                       selection=Selection(candidate_id=candidate_id, semantic_echo=dict(semantic))).to_json()


def _validate_deck_json(request_id: str, catalog_id: str) -> dict[str, Any]:
    return {"request_type": "validate_deck", "protocol": PROTOCOL, "request_id": request_id,
            "format": FORMAT, "deck": {"catalog_id": catalog_id}}


def _probe_resample_json(request_id: str, game_id: str) -> dict[str, Any]:
    return {"request_type": "probe_resample", "protocol": PROTOCOL, "request_id": request_id,
            "game_id": game_id, "samples": 1}


def _check(answer: dict[str, Any], code: str) -> None:
    got = answer.get("error", {}).get("code") if isinstance(answer, dict) else None
    assert answer.get("response_type") == "error" and got == code, f"expected the error {code}, got {answer}"


def _engine_golden(engine_args: Sequence[str], probe: Callable[[EngineProcess], None]) -> Golden:
    """One engine golden: crafted requests to a fresh fake engine through a recording EngineProcess."""
    rows: list[tuple[str, Any]] = []
    engine = EngineProcess(peer=RecordingPeer(
        wire.SubprocessPeer([sys.executable, str(ENGINE), *engine_args], timeout_s=30),
        rows, "host_to_engine", "engine_to_host"))
    try:
        probe(engine)
    finally:
        engine.close()
    return Golden(rows, ENGINE.name, tuple(engine_args), None, _ENGINE_ROLE)


def _probe_malformed_json(engine: EngineProcess) -> None:
    _check(engine.send_line(b"{not json"), "malformed_json")


def _probe_malformed_request(engine: EngineProcess) -> None:
    _check(engine.send_raw({"request_type": "hello", "protocol": PROTOCOL, "request_id": "h-1",
                            "protocol_minor": 0, "no_such_field": 1}), "malformed_request")


def _probe_malformed_request_non_object(engine: EngineProcess) -> None:
    """The line ``[1,2]``: valid JSON with a non-object top level, answered ``malformed_request`` (R1-3)."""
    _check(engine.send_line(b"[1,2]"), "malformed_request")


def _probe_protocol_mismatch(engine: EngineProcess) -> None:
    _check(engine.send_raw({"request_type": "hello", "protocol": "spellbench/v1",
                            "request_id": "h-1", "protocol_minor": 0}), "protocol_mismatch")


def _probe_request_id_reuse_mismatch(engine: EngineProcess) -> None:
    first = engine.send_raw(_validate_deck_json("h-1", "Burn"))
    assert first.get("response_type") == "deck_ok", first
    _check(engine.send_raw(_validate_deck_json("h-1", "Storm")), "request_id_reuse_mismatch")


def _probe_step_before_reset(engine: EngineProcess) -> None:
    _check(engine.send_raw(_step_json("h-1", SECRET.game_id(GAME_INDEX), 0, 0, {"kind": "pass"})),
           "step_before_reset")


def _probe_game_already_active(engine: EngineProcess) -> None:
    engine.send_raw(_reset_json("h-1", SECRET.game_id(GAME_INDEX)))
    _check(engine.send_raw(_reset_json("h-2", SECRET.game_id(1))), "game_already_active")


def _probe_game_id_mismatch(engine: EngineProcess) -> None:
    engine.send_raw(_reset_json("h-1", SECRET.game_id(GAME_INDEX)))
    _check(engine.send_raw(_step_json("h-2", SECRET.game_id(1), 0, 0, {"kind": "pass"})), "game_id_mismatch")


def _probe_expected_step_mismatch(engine: EngineProcess) -> None:
    game_id = SECRET.game_id(GAME_INDEX)
    engine.send_raw(_reset_json("h-1", game_id))
    _check(engine.send_raw(_step_json("h-2", game_id, 7, 0, {"kind": "pass"})), "expected_step_mismatch")


def _probe_candidate_id_out_of_range(engine: EngineProcess) -> None:
    game_id = SECRET.game_id(GAME_INDEX)
    decision = engine.send_raw(_reset_json("h-1", game_id))
    out_of_range = len(decision["seat_decision"]["candidates"])
    _check(engine.send_raw(_step_json("h-2", game_id, 0, out_of_range, {"kind": "pass"})),
           "candidate_id_out_of_range")


def _probe_semantic_echo_mismatch(engine: EngineProcess) -> None:
    game_id = SECRET.game_id(GAME_INDEX)
    decision = engine.send_raw(_reset_json("h-1", game_id))
    semantic = decision["seat_decision"]["candidates"][1]["semantic"]   # offered, under another id
    _check(engine.send_raw(_step_json("h-2", game_id, 0, 0, semantic)), "semantic_echo_mismatch")


def _probe_unsupported_format(engine: EngineProcess) -> None:
    _check(engine.send_raw(_reset_json("h-1", SECRET.game_id(GAME_INDEX),
                                       format="spellbench-goldens-no-such-format")), "unsupported_format")


def _probe_unsupported_deck(engine: EngineProcess) -> None:
    _check(engine.send_raw(_reset_json("h-1", SECRET.game_id(GAME_INDEX), p0_deck=_wire_deck("Storm"))),
           "unsupported_deck")


def _probe_deck_id_mismatch(engine: EngineProcess) -> None:
    _check(engine.send_raw(_reset_json("h-1", SECRET.game_id(GAME_INDEX),
                                       p0_deck=_wire_deck("Burn", bad_deck_id=True))), "deck_id_mismatch")


def _probe_unsupported_rule(engine: EngineProcess) -> None:
    rules = _rules(SCORING_DECKLIST, london=True, toss=False)   # this engine supports none but london
    _check(engine.send_raw(_reset_json("h-1", SECRET.game_id(GAME_INDEX), rules=rules)), "unsupported_rule")


def _probe_unsupported_request(engine: EngineProcess) -> None:
    _check(engine.send_raw(_probe_resample_json("h-1", SECRET.game_id(GAME_INDEX))), "unsupported_request")


def _probe_probe_refused(engine: EngineProcess) -> None:
    """A ``--probe`` engine answers ``probe_resample`` in a game not reset with ``rules.probe`` (spec 9.7)."""
    game_id = SECRET.game_id(GAME_INDEX)
    engine.send_raw(_reset_json("h-1", game_id))
    _check(engine.send_raw(_probe_resample_json("h-2", game_id)), "probe_refused")


def _probe_game_already_terminal(engine: EngineProcess) -> None:
    game_id = SECRET.game_id(GAME_INDEX)
    decision = engine.send_raw(_reset_json("h-1", game_id, p0_deck=_wire_deck("Halt")))
    semantic = decision["seat_decision"]["candidates"][0]["semantic"]
    terminal = engine.send_raw(_step_json("h-2", game_id, 0, 0, semantic))   # the Halt hook's halted terminal
    assert terminal.get("response_type") == "terminal", terminal
    _check(engine.send_raw(_step_json("h-3", game_id, 1, 0, semantic)), "game_already_terminal")


def _probe_validate_deck(engine: EngineProcess) -> None:
    first = engine.send_raw(_validate_deck_json("h-1", "Burn"))
    assert first.get("response_type") == "deck_ok", first
    _check(engine.send_raw(_validate_deck_json("h-2", "Storm")), "unsupported_deck")


# ---------------------------------------------------------------------------
# The agent error probes (spec 10.5)
# ---------------------------------------------------------------------------


def _agent_json(request_type: str, request_id: str, **payload: Any) -> dict[str, Any]:
    return {"request_type": request_type, "protocol": PROTOCOL, "request_id": request_id, **payload}


def _game_start_json(request_id: str, game_id: str) -> dict[str, Any]:
    return _agent_json("game_start", request_id, game_id=game_id, seat="p0")


def _choose_json(request_id: str, game_id: str) -> dict[str, Any]:
    decision = {"acting_seat": "p0", "seat_step": 0,
                "candidates": [{"candidate_id": 0, "semantic": {"kind": "pass"}, "display_text": None}]}
    return _agent_json("choose", request_id, game_id=game_id, decision=decision,
                       clock={"remaining_ms": TIME_CONTROL.bank_ms, "max_decision_ms": TIME_CONTROL.max_decision_ms})


def _agent_golden(lines: Sequence[bytes | dict[str, Any]], code: str, *,
                  choose: Callable[[Decision], int] = _pass) -> Golden:
    """One agent golden: crafted lines to the reference BotSession through a recording InProcessBot."""
    rows: list[tuple[str, Any]] = []
    session = BotSession(choose=choose, name=BOT_NAME, version=BOT_VERSION)
    peer = RecordingPeer(InProcessBot(session), rows, "host_to_agent", "agent_to_host")
    for line in lines:
        peer.write_line(line if isinstance(line, bytes) else wire.canonical_json_dumps(line))
        peer.read_line()
    _check(rows[-1][1], code)
    return Golden(rows, None, (), None, ("bot_server",))


def _agent_decision_pending() -> Golden:
    """``decision_pending``: another request arrives while a choose is unanswered.

    The reference server never pipelines, so it cannot produce this answer; its agent row
    is written by hand, and no replay role applies to this transcript.
    """
    game_id = SECRET.game_id(GAME_INDEX)
    rows = [
        ("host_to_agent", _choose_json("r-0", game_id)),        # never answered
        ("host_to_agent", _choose_json("r-1", game_id)),
        ("agent_to_host", {"response_type": "error", "protocol": PROTOCOL, "request_id": "r-1",
                           "error": {"code": "decision_pending",
                                     "message": "another request arrived while a choose was unanswered"}}),
    ]
    return Golden(rows, None, (), None, ())


# ---------------------------------------------------------------------------
# The transcripts, the render and the command line
# ---------------------------------------------------------------------------


def transcripts() -> dict[str, Golden]:
    """Every v2 golden: the games (with digests), the engine errors and the agent errors."""
    game_id = SECRET.game_id(GAME_INDEX)
    goldens = {
        "game_scoring.transcript.jsonl": _game(
            "Burn", SCORING_DECKLIST, (), choose={"p0": _lands, "p1": _pass},
            expect=("p0_win", "natural", "score")),
        "game_kinds_tour.transcript.jsonl": _scenario(
            fake_v2_scenario_kinds.SCENARIO, _tour_pick, expect=("draw", "natural", "scenario_complete")),
        "game_board_tour.transcript.jsonl": _scenario(
            fake_v2_scenario_board.SCENARIO, _pass, "--all-flags", expect=("draw", "natural", "scenario_complete")),
        "game_knowledge_tour.transcript.jsonl": _scenario(
            fake_v2_scenario_knowledge.SCENARIO, _pass, expect=("draw", "natural", "scenario_complete")),
        "game_forfeit_invalid_selection.transcript.jsonl": _game(
            "Burn", SCORING_DECKLIST, (), scripted_p0=_bad_bot_script(), choose={"p1": _pass},
            expect=("p1_win", "forfeit", "forfeit:invalid_selection")),
        "game_halt_host_validator_v4.transcript.jsonl": _game(
            "Burn", SCORING_DECKLIST, ("stale-reference",), engine_path=HOSTILE,
            choose={"p0": _pass, "p1": _pass}, expect=("halted", "halted", "host_validator:V4")),
        "game_mandatory_loop.transcript.jsonl": _game(
            "Loop", SCORING_DECKLIST, (), choose={"p0": _pass, "p1": _pass}, limits=CAP_LIMITS,
            expect=("draw", "natural", "mandatory_loop")),
        "game_stalling_forfeit.transcript.jsonl": _game(
            "Stall", SCORING_DECKLIST, (), choose={"p0": _activate, "p1": _pass}, limits=CAP_LIMITS,
            expect=("p1_win", "forfeit", "forfeit:stalling")),   # p0's real choices are the stalling (spec 11.4)
        "engine_error_malformed_json.transcript.jsonl": _engine_golden((), _probe_malformed_json),
        "engine_error_malformed_request.transcript.jsonl": _engine_golden((), _probe_malformed_request),
        "engine_error_malformed_request_non_object.transcript.jsonl":
            _engine_golden((), _probe_malformed_request_non_object),
        "engine_error_protocol_mismatch.transcript.jsonl": _engine_golden((), _probe_protocol_mismatch),
        "engine_error_request_id_reuse_mismatch.transcript.jsonl":
            _engine_golden((), _probe_request_id_reuse_mismatch),
        "engine_error_step_before_reset.transcript.jsonl": _engine_golden((), _probe_step_before_reset),
        "engine_error_game_already_active.transcript.jsonl": _engine_golden((), _probe_game_already_active),
        "engine_error_game_id_mismatch.transcript.jsonl": _engine_golden((), _probe_game_id_mismatch),
        "engine_error_expected_step_mismatch.transcript.jsonl": _engine_golden((), _probe_expected_step_mismatch),
        "engine_error_candidate_id_out_of_range.transcript.jsonl":
            _engine_golden((), _probe_candidate_id_out_of_range),
        "engine_error_semantic_echo_mismatch.transcript.jsonl": _engine_golden((), _probe_semantic_echo_mismatch),
        "engine_error_unsupported_format.transcript.jsonl": _engine_golden((), _probe_unsupported_format),
        "engine_error_unsupported_deck.transcript.jsonl": _engine_golden((), _probe_unsupported_deck),
        "engine_error_deck_id_mismatch.transcript.jsonl": _engine_golden((), _probe_deck_id_mismatch),
        "engine_error_unsupported_rule.transcript.jsonl": _engine_golden((), _probe_unsupported_rule),
        "engine_error_unsupported_request.transcript.jsonl": _engine_golden((), _probe_unsupported_request),
        "engine_error_probe_refused.transcript.jsonl": _engine_golden(("--probe",), _probe_probe_refused),
        "engine_error_game_already_terminal.transcript.jsonl": _engine_golden((), _probe_game_already_terminal),
        "engine_validate_deck.transcript.jsonl": _engine_golden((), _probe_validate_deck),
        "agent_error_malformed_json.transcript.jsonl": _agent_golden([b"{not json"], "malformed_json"),
        "agent_error_malformed_request.transcript.jsonl": _agent_golden(
            [{"request_type": "hello", "protocol": PROTOCOL}], "malformed_request"),
        "agent_error_protocol_mismatch.transcript.jsonl": _agent_golden(
            [{"request_type": "hello", "protocol": "spellbench/v1", "request_id": "r-0"}], "protocol_mismatch"),
        "agent_error_unknown_game.transcript.jsonl": _agent_golden(
            [_choose_json("r-0", "g-0000000000000000")], "unknown_game"),
        "agent_error_game_already_active.transcript.jsonl": _agent_golden(
            [_game_start_json("r-0", game_id), _game_start_json("r-1", SECRET.game_id(1))], "game_already_active"),
        "agent_error_decision_pending.transcript.jsonl": _agent_decision_pending(),
        "agent_error_internal_error.transcript.jsonl": _agent_golden(
            [_game_start_json("r-0", game_id), _choose_json("r-1", game_id)], "internal_error",
            choose=lambda decision: 99),   # 99 is a candidate_id the decision did not offer (R3-26)
    }
    return goldens


def render(rows: list[tuple[str, Any]]) -> bytes:
    """One canonical line per message (spec 16); a string message (Decision 7) renders as one."""
    return b"".join(wire.canonical_json_line({"dir": direction, "message": message})
                    for direction, message in rows)


def _index(goldens: dict[str, Golden]) -> bytes:
    """``index.json`` (Decision 7) as one canonical line."""
    entries = {name: {"engine": golden.engine, "engine_args": list(golden.engine_args),
                      "game_digest": golden.game_digest, "roles": list(golden.roles)}
               for name, golden in sorted(goldens.items())}
    document = {"schema": "spellbench-goldens/v2", "notes": NOTES, "transcripts": entries}
    return wire.canonical_json_line(document)


def main(argv: list[str]) -> int:
    check = "--check" in argv
    goldens = transcripts()
    built = {name: render(golden.rows) for name, golden in goldens.items()}
    built["index.json"] = _index(goldens)
    failures = 0
    for name in sorted(built):
        path = GOLDENS_DIR / name
        content = built[name]
        if check:
            if not path.is_file():
                print(f"MISSING {name}")
                failures += 1
            elif path.read_bytes() != content:
                print(f"STALE   {name}")
                failures += 1
            else:
                print(f"OK      {name}")
        else:
            GOLDENS_DIR.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            print(f"WROTE   {name} ({len(content)} bytes)")
    if check and failures:
        print(f"{failures} golden(s) out of date; run without --check to rewrite", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
