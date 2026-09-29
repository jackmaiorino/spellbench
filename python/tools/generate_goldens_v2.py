#!/usr/bin/env python3
"""Generate the protocol v2 golden transcripts and their index (spec 16; Decision 7).

Writes ``goldens/protocol_v2/<name>.transcript.jsonl``, one canonical JSON line ``{"dir", "message"}`` per
message, and ``goldens/protocol_v2/index.json``, one canonical line holding each golden's engine, engine
arguments, game digest and replay roles, and the readings the goldens follow where the spec leaves room.
``--check`` renders everything afresh and byte-compares it with the files on disk, printing ``OK``,
``STALE`` or ``MISSING`` per file; it never writes, and exits 1 on any difference.

The transcripts are recorded from the reference stack, never written by hand (one agent row excepted, below):

- ``game_*``: one game each through ``host.game.play_game``, against a real fake-engine (or hostile-engine)
  process, with both seats played by ``bot.BotSession`` in process through ``arena.drivers.SubprocessDriver``;
  all four directions, and the game's digest in the index. Game 0 of the spec 16 vector run secret, so the
  game id is ``g-f67d7fe78c792984`` as in the spec's examples.
- ``engine_error_<code>``: one engine process each, sent the requests that draw ``<code>`` (spec 9.8), and
  ``engine_validate_deck``: engine rows only, digest null.
- ``agent_error_<code>``: one ``BotSession`` each, sent the lines that draw ``<code>`` (spec 10.5): agent rows
  only. ``decision_pending`` is the exception: the reference bot server never sees a decision pending, so
  that one agent row is written by hand.

Determinism (the same bytes on every platform and every run): every clock reads 0 (``clock_ns``), rows are the
parsed messages re-serialized as canonical JSON (never a child's raw line, whose terminator a Windows pipe may
change), no path, process id, time or interpreter name is recorded, every iteration is sorted, and files are
written as bytes with ``\\n`` line ends. The two seats start at once on two threads (spec 11.4), so each seat's
agent rows are buffered and a transcript lists p0's start exchanges before p1's (``_GameRows``).

Run from anywhere: ``uv run python python/tools/generate_goldens_v2.py [--check]``.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Sequence

TESTS_DIR = Path(__file__).resolve().parents[1] / "tests"
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))  # golden_helpers, and the scenario modules the kinds tour answers with

from spellbench import wire  # noqa: E402
from spellbench._schema import SEATS  # noqa: E402
from spellbench.agent_messages import OwnDeck, request  # noqa: E402
from spellbench.arena.config import BotSpec  # noqa: E402
from spellbench.arena.drivers import SubprocessDriver  # noqa: E402
from spellbench.bot import BotSession, Decision as BotDecision  # noqa: E402
from spellbench.digests import card_name_domain, deck_id, deck_rows  # noqa: E402
from spellbench.host.agent_process import AgentProcess  # noqa: E402
from spellbench.host.engine_process import EngineProcess  # noqa: E402
from spellbench.host.game import GameSetup, play_game  # noqa: E402
from spellbench.messages import (  # noqa: E402
    PROTOCOL,
    PROTOCOL_MINOR,
    Decision,
    DeckRow,
    EnvHelloOk,
    Limits,
    ResetRequest,
    Resources,
    Rules,
    Selection,
    StepRequest,
    Terminal,
    TimeControl,
    ValidateDeckRequest,
    WireDeck,
)
from spellbench.run_secret import RunSecret  # noqa: E402

import fake_v2_scenario_board  # noqa: E402
import fake_v2_scenario_kinds  # noqa: E402
import fake_v2_scenario_knowledge  # noqa: E402
from golden_helpers import GOLDENS_V2_DIR, InProcessBot, RecordingPeer  # noqa: E402

SCHEMA = "spellbench-goldens/v2"
INDEX_NAME = "index.json"
SUFFIX = ".transcript.jsonl"
FAKE_ENGINE = "fake_v2_engine.py"
HOSTILE_ENGINE = "hostile_v2_engine.py"

# Spec 16: the vector run secret, the bytes 0x00 to 0x1f. Game 0 is g-f67d7fe78c792984, as in the spec's
# examples; game 1 (g-bb341404cf686511) is the other game a request names where one is needed.
SECRET = RunSecret(bytes(range(32)))
FORMAT = "pauper-bo1"
# The spec 11.4 example values (the arena's defaults); the loop and stall games cap a seat's turn at 3.
TIME_CONTROL = TimeControl(startup_ms=300000, game_start_ms=60000, bank_ms=600000, increment_ms=2000,
                           max_decision_ms=60000, engine_step_ms=120000)
LIMITS = Limits(max_decisions=10000, max_steps=100000, max_seat_decisions_per_turn=500,
                max_seat_decisions_per_game=4999, max_seat_steps_per_game=49999)
CAPPED = replace(LIMITS, max_seat_decisions_per_turn=3)
RESOURCES = Resources(cpus=1, memory_mb=4096, gpu=False, engine_cpus=1)
BOT_VERSION = "1.0.0"
# Bounds the generator's own waits (an engine's hello, an error probe); play_game bounds a game's by TIME_CONTROL.
ENGINE_TIMEOUT_S = 60.0
# A catalog id and a card no engine has (the names Task 32's conformance probes use).
NO_SUCH_DECK = "spellbench-conformance-no-such-deck"
NO_SUCH_CARD = "Spellbench Conformance No Such Card"
PASS = {"kind": "pass"}

NOTES = (
    # Decision 4, the reading of spec 8 an adapter comparing counts needs, first (R2-23).
    "a rewind abandons the rewound priority action's own group and every group completed after it; they do not "
    "count toward decision_count, and group_id is never reused",
    # Decision 5.
    "a seat reaches a cap of spec 11.4 when its count equals the cap; the host rules right after that answer, "
    "before sending its step, and the answer still counts toward step_count and the seat's seat_step_count "
    "(game_mandatory_loop, game_stalling_forfeit)",
    # Decision 7.
    "a row's message is a parsed JSON object, except that the offending line of a malformed_json golden or of "
    "engine_error_malformed_request_non_object, which is not a JSON object, is kept as a JSON string holding the "
    "line exactly as sent; digests, engine arguments and replay roles live in this index",
    "error.message is human-facing only (spec 9.8, 10.5): the reference engine and bot server reproduce it, and "
    "another implementation need match only error.code",
    "the games ran on a clock that always reads 0, so every decision took 0 ms and each choose shows the seat's "
    "bank grown by increment_ms per answered decision; a host replaying a game uses the same clock",
    "the spec does not order the two seats' starts, and the host starts both at once: a game transcript lists "
    "p0's hello and game_start exchanges before p1's, and every other row in the order it crossed a pipe",
    "every game and reset uses the spec 16 vector run secret: game 0 (g-f67d7fe78c792984), and game 1 "
    "(g-bb341404cf686511) where a request names another game",
    "agent_error_decision_pending shows the host bug of spec 10.5: the choose is sent again before it is answered, "
    "and the agent answers both in order (spec 2), the choice and then decision_pending; that error row is written "
    "by hand, since the reference bot server reads one line at a time and never sees a decision pending",
    "roles lists the replays that apply: host (the host reproduces every host row and the game digest from the "
    "recorded answers), engine (the listed engine, started with engine_args, reproduces every engine answer) and "
    "bot_server (the reference bot server reproduces every agent answer)",
)


class GenerationError(RuntimeError):
    """A golden did not come out as its definition says; nothing is written."""


@dataclass(frozen=True)
class Golden:
    """One transcript's rows and its index entry (Decision 7)."""

    rows: tuple[tuple[str, Any], ...]
    engine: str | None
    engine_args: tuple[str, ...]
    game_digest: str | None
    roles: tuple[str, ...]

    def index_entry(self) -> dict[str, Any]:
        return {"engine": self.engine, "engine_args": list(self.engine_args), "game_digest": self.game_digest,
                "roles": sorted(self.roles)}


def render(rows: Sequence[tuple[str, Any]]) -> bytes:
    """One canonical line ``{"dir", "message"}`` per row (spec 16), each ending in ``\\n``."""
    return b"".join(wire.canonical_json_line({"dir": direction, "message": message}) for direction, message in rows)


def render_index(goldens: dict[str, Golden]) -> bytes:
    """``index.json``: the notes and every golden's entry, as one canonical line."""
    index = {"schema": SCHEMA, "notes": list(NOTES),
             "transcripts": {name: goldens[name].index_entry() for name in sorted(goldens)}}
    return wire.canonical_json_line(index)


def _expect(condition: bool, name: str, detail: str) -> None:
    if not condition:
        raise GenerationError(f"{name}: {detail}")


# ---------------------------------------------------------------------------
# Engines, decks and setups
# ---------------------------------------------------------------------------


def _engine(script: str, args: Sequence[str], rows: Any) -> EngineProcess:
    """A recorded engine process: ``rows`` gets every line the host writes and reads."""
    peer = wire.SubprocessPeer([sys.executable, str(TESTS_DIR / script), *args], timeout_s=ENGINE_TIMEOUT_S)
    return EngineProcess(peer=RecordingPeer(peer, rows, "host_to_engine", "engine_to_host"))


def _deck(hello: EnvHelloOk, catalog_id: str) -> tuple[WireDeck, OwnDeck]:
    """A catalog deck as preflight resolves it (spec 11.1, 12.1): its rows checked and sorted, and its ``deck_id``."""
    deck = next(entry for entry in hello.catalog if entry.catalog_id == catalog_id)
    rows = deck_rows([row.to_json() for row in deck.decklist], f"catalog deck {catalog_id}")
    identifier = deck_id(rows)
    own = OwnDeck(identifier, deck.name, tuple(DeckRow(row["name"], row["count"]) for row in rows))
    return WireDeck(identifier, catalog_id=catalog_id), own


def _rules(hello: EnvHelloOk, own: OwnDeck) -> Rules:
    """The rules fitted to the engine, as ``tour_helpers.play_tour`` fits them (spec 12.2).

    ``london`` and ``toss_winner_chooses`` when the engine supports them, else ``none`` and ``host_assigned``
    with ``p0``; the decklist visible, no extension, the probe off.
    """
    supported = hello.profile.rules_supported
    toss = "toss_winner_chooses" in supported["starting_player"]
    return Rules.from_json({
        "opponent_decklist": "visible",
        "mulligan": "london" if "london" in supported["mulligan"] else "none",
        "starting_player": "toss_winner_chooses" if toss else "host_assigned",
        "starting_seat": None if toss else "p0",
        "card_name_domain": card_name_domain(row.name for row in own.decklist),
        "extensions": [],
        "probe": False,
    })


def _setup(hello: EnvHelloOk, catalog_id: str, limits: Limits) -> GameSetup:
    """Game 0 of the vector run secret, both seats on ``catalog_id`` (spec 11.6, 16)."""
    wire_deck, own = _deck(hello, catalog_id)
    return GameSetup(game_index=0, game_id=SECRET.game_id(0), game_secret_hex=SECRET.game_secret(0).hex(),
                     format=FORMAT, wire_decks=(wire_deck, wire_deck), own_decks=(own, own), rules=_rules(hello, own),
                     time_control=TIME_CONTROL, limits=limits, resources=RESOURCES,
                     agent_seeds=(SECRET.agent_seed(0, "p0"), SECRET.agent_seed(0, "p1")))


def _reset(engine: EngineProcess, setup: GameSetup, *, game: int = 0, **changes: Any) -> ResetRequest:
    """The reset ``play_game`` would send for ``setup``, as game ``game`` of the vector secret, with ``changes``."""
    fields = dict(request_id=engine.next_request_id(), game_id=SECRET.game_id(game), format=setup.format,
                  seats=setup.wire_decks, rules=setup.rules, game_secret=SECRET.game_secret(game).hex(),
                  max_decisions=setup.limits.max_decisions, max_steps=setup.limits.max_steps)
    fields.update(changes)
    return ResetRequest(**fields)


def _step(engine: EngineProcess, *, expected_step: int, candidate_id: int, echo: dict[str, Any],
          game: int = 0) -> dict[str, Any]:
    """A ``step`` request as the host shapes it (spec 9.4), whatever its binding."""
    return StepRequest(request_id=engine.next_request_id(), game_id=SECRET.game_id(game), expected_step=expected_step,
                       selection=Selection(candidate_id, echo)).to_json()


# ---------------------------------------------------------------------------
# Bots
# ---------------------------------------------------------------------------


class _AnswersNine(InProcessBot):
    """A hand-built bad bot: its session answers ``hello``, ``game_start`` and ``game_over``, and every ``choose`` is
    answered by hand with ``candidate_id`` 9, which the reference bot server would refuse to send (spec 11.5)."""

    def write_line(self, payload: bytes) -> None:
        message = wire.strict_json_loads(payload)
        if message.get("request_type") != "choose":
            super().write_line(payload)
            return
        self.pending.append(wire.canonical_json_line({"response_type": "choice", "protocol": PROTOCOL,
                                                      "request_id": message["request_id"],
                                                      "selection": {"candidate_id": 9}}))


@dataclass(frozen=True)
class _Bot:
    """A seat's bot: a ``BotSession`` answering with ``choose``, or the hand-built ``_AnswersNine``."""

    name: str
    choose: Callable[[BotDecision], int]
    hand_built: bool = False

    def peer(self) -> InProcessBot:
        session = BotSession(choose=self.choose, name=self.name, version=BOT_VERSION)
        return _AnswersNine(session) if self.hand_built else InProcessBot(session)


def _play_land(decision: BotDecision) -> int:
    return next((c.candidate_id for c in decision.candidates if c.semantic.get("kind") == "play_land"), 0)


FIRST = _Bot("golden-first", lambda decision: 0)
LANDS = _Bot("golden-lands", _play_land)
LAST = _Bot("golden-last", lambda decision: decision.candidates[-1].candidate_id)
# The kinds tour's own picker (R2-2), so the tour follows the answers it scripts: the rewind's cast is taken.
TOUR = _Bot("golden-kinds-tour", lambda decision: fake_v2_scenario_kinds.pick(decision.raw["decision"]))
NINE = _Bot("golden-nine", lambda decision: 0, hand_built=True)


# ---------------------------------------------------------------------------
# Games (spec 11): all four directions, and the digest
# ---------------------------------------------------------------------------


class _GameRows:
    """One game's rows in wire order.

    The host starts both seats at once, each on its own thread (spec 11.4), so their ``hello`` and ``game_start``
    exchanges interleave by timing. Each seat's agent rows wait in ``seats[seat]`` and move into ``rows``, p0's
    first, before each engine row and at the end: every exchange made one at a time keeps its true place, and the
    simultaneous start reads as p0's exchanges, then p1's.
    """

    def __init__(self) -> None:
        self.rows: list[tuple[str, Any]] = []
        self.seats: dict[str, list[tuple[str, Any]]] = {seat: [] for seat in SEATS}

    def append(self, row: tuple[str, Any]) -> None:
        """An engine row: the agent rows before it first."""
        self.flush()
        self.rows.append(row)

    def flush(self) -> tuple[tuple[str, Any], ...]:
        for seat in SEATS:
            self.rows.extend(self.seats[seat])
            self.seats[seat].clear()
        return tuple(self.rows)


@dataclass(frozen=True)
class _Game:
    """One game golden: its engine and arguments, the catalog deck both seats play, the p0 and p1 bots, the caps,
    and the ending it must reach (the generator refuses any other)."""

    engine: str
    engine_args: tuple[str, ...]
    deck: str
    bots: tuple[_Bot, _Bot]
    limits: Limits
    ending: tuple[str, str, str]     # outcome, classification, reason


GAMES: dict[str, _Game] = {
    # Burn: p0 plays a land whenever it can and wins on score (the scoring game of the fake engine).
    "game_scoring": _Game(FAKE_ENGINE, (), "Burn", (LANDS, FIRST), LIMITS, ("p0_win", "natural", "score")),
    # Every v2.0 kind and group shape, a full arrangement and a rewind among them (spec 7, 8).
    "game_kinds_tour": _Game(FAKE_ENGINE, fake_v2_scenario_kinds.SCENARIO.engine_args, "Scenario:kinds",
                             (TOUR, TOUR), LIMITS, ("draw", "natural", "scenario_complete")),
    # Every board field of spec 6.2 to 6.6 and every optional field of spec 6.9.
    "game_board_tour": _Game(FAKE_ENGINE, (*fake_v2_scenario_board.SCENARIO.engine_args, "--all-flags"),
                             "Scenario:board", (FIRST, FIRST), LIMITS, ("draw", "natural", "scenario_complete")),
    # Every knowledge update of spec 6.7.
    "game_knowledge_tour": _Game(FAKE_ENGINE, fake_v2_scenario_knowledge.SCENARIO.engine_args, "Scenario:knowledge",
                                 (FIRST, FIRST), LIMITS, ("draw", "natural", "scenario_complete")),
    # p0's first answer names candidate 9 of 2 (spec 11.5).
    "game_forfeit_invalid_selection": _Game(FAKE_ENGINE, (), "Burn", (NINE, FIRST), LIMITS,
                                            ("p1_win", "forfeit", "forfeit:invalid_selection")),
    # The engine's second decision references a Mountain as an Island (spec 11.3 V4).
    "game_halt_host_validator_v4": _Game(HOSTILE_ENGINE, ("stale-reference",), "Burn", (LANDS, FIRST), LIMITS,
                                         ("halted", "halted", "host_validator:V4")),
    # Single-candidate decisions until p0's third answer of the turn reaches the cap: no real choice (spec 11.4).
    "game_mandatory_loop": _Game(FAKE_ENGINE, (), "Loop", (FIRST, FIRST), CAPPED,
                                 ("draw", "natural", "mandatory_loop")),
    # p0 activates its Relic at every chance until it reaches the cap with the only real choices (spec 11.4).
    "game_stalling_forfeit": _Game(FAKE_ENGINE, (), "Stall", (LAST, FIRST), CAPPED,
                                   ("p1_win", "forfeit", "forfeit:stalling")),
}


def _driver(bot: _Bot, rows: list[tuple[str, Any]]) -> SubprocessDriver:
    spec = BotSpec(name=bot.name, version=BOT_VERSION, type="subprocess", command=("in-process",))
    return SubprocessDriver(spec, startup_ms=TIME_CONTROL.startup_ms, agent_factory=lambda: AgentProcess(
        peer=RecordingPeer(bot.peer(), rows, "host_to_agent", "agent_to_host")))


def _play(name: str, game: _Game) -> Golden:
    rows = _GameRows()
    engine = _engine(game.engine, game.engine_args, rows)
    seats: dict[str, SubprocessDriver] = {}
    try:
        setup = _setup(engine.hello(), game.deck, game.limits)
        seats = {seat: _driver(bot, rows.seats[seat]) for seat, bot in zip(SEATS, game.bots)}
        result = play_game(setup, engine=engine, seats=seats, clock_ns=lambda: 0)
    finally:
        for driver in seats.values():
            driver.close()
        engine.close()
    ending = (result.outcome, result.classification, result.reason)
    _expect(ending == game.ending, name, f"ended {ending}, not {game.ending}: {result.adjudication}")
    roles = ("host", "engine") + (() if any(bot.hand_built for bot in game.bots) else ("bot_server",))
    return Golden(rows.flush(), game.engine, game.engine_args, result.game_digest, roles)


# ---------------------------------------------------------------------------
# Engine errors (spec 9.8) and validate_deck (spec 9.6): engine rows only
# ---------------------------------------------------------------------------


class _EngineSession:
    """One recorded fake-engine process, and game 0's setup on Burn once ``hello`` answered."""

    def __init__(self, engine_args: tuple[str, ...] = ()) -> None:
        self.engine_args = engine_args
        self.rows: list[tuple[str, Any]] = []
        self.engine = _engine(FAKE_ENGINE, engine_args, self.rows)
        self.setup: GameSetup | None = None

    def hello(self) -> GameSetup:
        self.setup = _setup(self.engine.hello(), "Burn", LIMITS)
        return self.setup

    def reset(self, **changes: Any) -> dict[str, Any]:
        return _reset(self.engine, self.setup, **changes).to_json()

    def step(self, **fields: Any) -> dict[str, Any]:
        return _step(self.engine, **fields)

    def started(self) -> Decision:
        """``hello``, then game 0's reset, answered with its first decision (step 0)."""
        self.hello()
        decision = self.engine.reset(_reset(self.engine, self.setup))
        assert isinstance(decision, Decision)
        return decision


def _malformed_json(session: _EngineSession) -> None:
    session.hello()
    session.engine.send_line(b"{not json")


def _malformed_request(session: _EngineSession) -> None:
    session.hello()
    session.engine.send_raw({**session.reset(), "game_seed": 12345})       # a v1 field, unknown in v2 (spec 4.2)


def _malformed_request_non_object(session: _EngineSession) -> None:
    session.hello()
    session.engine.send_line(b"[1,2]")                                      # valid JSON, not an object (R1-3)


def _protocol_mismatch(session: _EngineSession) -> None:
    session.engine.send_raw({"request_type": "hello", "protocol": "spellbench/v1",
                             "request_id": session.engine.next_request_id(), "protocol_minor": PROTOCOL_MINOR})


def _request_id_reuse_mismatch(session: _EngineSession) -> None:
    candidates = session.started().seat_decision["candidates"]
    step = session.step(expected_step=0, candidate_id=0, echo=candidates[0]["semantic"])
    session.engine.send_raw(step)
    session.engine.send_raw(step)                                           # retransmitted: the cached answer (spec 4.1)
    other = Selection(1, candidates[1]["semantic"]).to_json()               # the same request_id, the other candidate
    session.engine.send_raw({**step, "selection": other})


def _step_before_reset(session: _EngineSession) -> None:
    session.hello()
    session.engine.send_raw(session.step(expected_step=0, candidate_id=0, echo=PASS))


def _game_already_active(session: _EngineSession) -> None:
    session.started()
    session.engine.send_raw(session.reset(game=1))


def _game_id_mismatch(session: _EngineSession) -> None:
    session.started()
    session.engine.send_raw(session.step(expected_step=0, candidate_id=0, echo=PASS, game=1))


def _expected_step_mismatch(session: _EngineSession) -> None:
    session.started()
    session.engine.send_raw(session.step(expected_step=1, candidate_id=0, echo=PASS))


def _candidate_id_out_of_range(session: _EngineSession) -> None:
    decision = session.started()
    count = len(decision.seat_decision["candidates"])
    session.engine.send_raw(session.step(expected_step=0, candidate_id=count, echo=PASS))


def _semantic_echo_mismatch(session: _EngineSession) -> None:
    session.started()                                                       # candidate 1 plays a Mountain
    session.engine.send_raw(session.step(expected_step=0, candidate_id=1, echo=PASS))


def _unsupported_format(session: _EngineSession) -> None:
    session.hello()
    session.engine.send_raw(session.reset(format="standard-bo1"))


def _unsupported_deck(session: _EngineSession) -> None:
    setup = session.hello()
    burn = setup.wire_decks[0]
    session.engine.send_raw(session.reset(seats=(burn, WireDeck(burn.deck_id, catalog_id=NO_SUCH_DECK))))


def _deck_id_mismatch(session: _EngineSession) -> None:
    setup = session.hello()
    wrong = WireDeck("sha256:" + "00" * 32, catalog_id=setup.wire_decks[0].catalog_id)
    session.engine.send_raw(session.reset(seats=(wrong, setup.wire_decks[1])))


def _unsupported_rule(session: _EngineSession) -> None:
    setup = session.hello()                                                 # the engine supports mulligan none only
    session.engine.send_raw(session.reset(rules=replace(setup.rules, mulligan="london")))


def _probe(session: _EngineSession) -> None:
    session.started()
    session.engine.send_raw({"request_type": "probe_resample", "protocol": PROTOCOL,
                             "request_id": session.engine.next_request_id(), "game_id": SECRET.game_id(0),
                             "samples": 1})


def _game_already_terminal(session: _EngineSession) -> None:
    response: Decision | Terminal = session.started()
    while isinstance(response, Decision):
        response = session.engine.step(candidate_id=0, semantic=response.seat_decision["candidates"][0]["semantic"])
    session.engine.send_raw(session.step(expected_step=response.result.step_count, candidate_id=0, echo=PASS))


# Each golden's requests and the engine arguments it needs: every code of spec 9.8, and the non-object line (R1-3).
ENGINE_ERRORS: dict[str, tuple[Callable[[_EngineSession], None], tuple[str, ...], str]] = {
    "engine_error_malformed_json": (_malformed_json, (), "malformed_json"),
    "engine_error_malformed_request": (_malformed_request, (), "malformed_request"),
    "engine_error_malformed_request_non_object": (_malformed_request_non_object, (), "malformed_request"),
    "engine_error_protocol_mismatch": (_protocol_mismatch, (), "protocol_mismatch"),
    "engine_error_request_id_reuse_mismatch": (_request_id_reuse_mismatch, (), "request_id_reuse_mismatch"),
    "engine_error_step_before_reset": (_step_before_reset, (), "step_before_reset"),
    "engine_error_game_already_active": (_game_already_active, (), "game_already_active"),
    "engine_error_game_id_mismatch": (_game_id_mismatch, (), "game_id_mismatch"),
    "engine_error_expected_step_mismatch": (_expected_step_mismatch, (), "expected_step_mismatch"),
    "engine_error_candidate_id_out_of_range": (_candidate_id_out_of_range, (), "candidate_id_out_of_range"),
    "engine_error_semantic_echo_mismatch": (_semantic_echo_mismatch, (), "semantic_echo_mismatch"),
    "engine_error_unsupported_format": (_unsupported_format, (), "unsupported_format"),
    "engine_error_unsupported_deck": (_unsupported_deck, (), "unsupported_deck"),
    "engine_error_deck_id_mismatch": (_deck_id_mismatch, (), "deck_id_mismatch"),
    "engine_error_unsupported_rule": (_unsupported_rule, (), "unsupported_rule"),
    # Spec 9.7: an engine without the probe answers unsupported_request, one with it probe_refused.
    "engine_error_unsupported_request": (_probe, (), "unsupported_request"),
    "engine_error_probe_refused": (_probe, ("--probe",), "probe_refused"),
    "engine_error_game_already_terminal": (_game_already_terminal, (), "game_already_terminal"),
}


def _engine_golden(requests: Callable[[_EngineSession], None], engine_args: tuple[str, ...]) -> Golden:
    session = _EngineSession(engine_args)
    try:
        requests(session)
    finally:
        session.engine.close()
    return Golden(tuple(session.rows), FAKE_ENGINE, session.engine_args, None, ("engine",))


def _engine_error(name: str, requests: Callable[[_EngineSession], None], engine_args: tuple[str, ...],
                  code: str) -> Golden:
    golden = _engine_golden(requests, engine_args)
    direction, answer = golden.rows[-1]
    _expect(direction == "engine_to_host" and answer["response_type"] == "error" and answer["error"]["code"] == code,
            name, f"the last answer is not a {code} error: {answer}")
    errors = [message for direction, message in golden.rows[:-1]
              if direction == "engine_to_host" and message["response_type"] == "error"]
    _expect(not errors, name, f"an earlier answer is an error: {errors}")
    return golden


def _validate_deck(session: _EngineSession) -> None:
    """``deck_ok`` for a catalog deck and for a playable decklist; ``unsupported_deck`` for a made-up card (spec 9.6)."""
    setup = session.hello()
    engine = session.engine
    engine.validate_deck(format=FORMAT, catalog_id=setup.wire_decks[0].catalog_id)
    engine.validate_deck(format=FORMAT, decklist=[row.to_json() for row in setup.own_decks[0].decklist])
    unplayable = ValidateDeckRequest(engine.next_request_id(), FORMAT, None,
                                     (DeckRow(NO_SUCH_CARD, 1), DeckRow("Mountain", 21)))
    engine.send_raw(unplayable.to_json())


def _validate_deck_golden() -> Golden:
    name = "engine_validate_deck"
    golden = _engine_golden(_validate_deck, ("--decklists",))
    answers = [message["response_type"] if message["response_type"] != "error" else message["error"]["code"]
               for direction, message in golden.rows if direction == "engine_to_host"]
    _expect(answers == ["hello_ok", "deck_ok", "deck_ok", "unsupported_deck"], name, f"answered {answers}")
    return golden


# ---------------------------------------------------------------------------
# Agent errors (spec 10.5): agent rows only
# ---------------------------------------------------------------------------


def _agent_rows(lines: Sequence[bytes], choose: Callable[[BotDecision], int], bot: str) -> list[tuple[str, Any]]:
    """The rows of ``lines`` sent one at a time to a fresh ``BotSession``, each answered before the next is sent."""
    rows: list[tuple[str, Any]] = []
    peer = RecordingPeer(InProcessBot(BotSession(choose=choose, name=bot, version=BOT_VERSION)), rows,
                         "host_to_agent", "agent_to_host")
    for line in lines:
        peer.write_line(line)
        peer.read_line()
    return rows


def _agent_errors(scoring: Golden) -> dict[str, Golden]:
    """Each code of spec 10.5, drawn by the host's own messages to p0 of ``game_scoring`` or by a changed copy."""
    to_p0 = [message for direction, message in scoring.rows if direction == "host_to_agent"
             and (message.get("seat") == "p0" or message.get("decision", {}).get("acting_seat") == "p0")]
    start = next(message for message in to_p0 if message["request_type"] == "game_start")
    choose = next(message for message in to_p0 if message["request_type"] == "choose")
    _expect((start["request_id"], choose["request_id"]) == ("r-1", "r-2"), "agent_error_*",
            "p0's first game_start and choose are not r-1 and r-2")
    hello = wire.canonical_json_dumps(request("hello", "r-0", {"protocol_minor": PROTOCOL_MINOR}))
    game_start, first_choose = wire.canonical_json_dumps(start), wire.canonical_json_dumps(choose)
    other_game = SECRET.game_id(1)

    def changed(message: dict[str, Any], **fields: Any) -> bytes:
        return wire.canonical_json_dumps({**message, **fields})

    without_game_id = wire.canonical_json_dumps({key: value for key, value in start.items() if key != "game_id"})
    second_start = changed(start, request_id="r-2", game_id=other_game, agent_seed=SECRET.agent_seed(1, "p0"))
    wrong_protocol = wire.canonical_json_dumps({**request("hello", "r-0", {"protocol_minor": PROTOCOL_MINOR}),
                                                "protocol": "spellbench/v1"})
    sessions: dict[str, tuple[Sequence[bytes], Callable[[BotDecision], int], str]] = {
        "malformed_json": ((hello, b"{not json"), FIRST.choose, FIRST.name),
        "malformed_request": ((hello, without_game_id), FIRST.choose, FIRST.name),
        "protocol_mismatch": ((wrong_protocol,), FIRST.choose, FIRST.name),
        "unknown_game": ((hello, game_start, changed(choose, game_id=other_game)), FIRST.choose, FIRST.name),
        "game_already_active": ((hello, game_start, second_start), FIRST.choose, FIRST.name),
        # R3-26: choose returns 99, a candidate_id the decision does not offer, as the bot server replay does.
        "internal_error": ((hello, game_start, first_choose), lambda decision: 99, "golden-unoffered"),
    }
    goldens: dict[str, Golden] = {}
    for code, (lines, pick, bot) in sessions.items():
        rows = _agent_rows(lines, pick, bot)
        goldens[f"agent_error_{code}"] = Golden(tuple(rows), None, (), None, ("bot_server",))
    # decision_pending: the choose is sent again before it is answered (a host bug, spec 10.5). The session answers
    # the first copy; the agent's second answer is written by hand, since the reference server never sees it pending.
    answered = _agent_rows((hello, game_start, first_choose), FIRST.choose, FIRST.name)
    pending = {"response_type": "error", "protocol": PROTOCOL, "request_id": choose["request_id"],
               "error": {"code": "decision_pending", "message": "a choose is still unanswered"}}
    rows = [*answered[:-1], ("host_to_agent", choose), answered[-1], ("agent_to_host", pending)]
    goldens["agent_error_decision_pending"] = Golden(tuple(rows), None, (), None, ())
    for name, golden in goldens.items():
        direction, answer = golden.rows[-1]
        code = name[len("agent_error_"):]
        _expect(direction == "agent_to_host" and answer["response_type"] == "error" and answer["error"]["code"] == code,
                name, f"the last answer is not a {code} error: {answer}")
    return goldens


# ---------------------------------------------------------------------------
# All goldens, and the command line
# ---------------------------------------------------------------------------


def transcripts() -> dict[str, Golden]:
    """Every golden, by file name."""
    goldens = {name: _play(name, game) for name, game in sorted(GAMES.items())}
    for name, (requests, engine_args, code) in sorted(ENGINE_ERRORS.items()):
        goldens[name] = _engine_error(name, requests, engine_args, code)
    goldens["engine_validate_deck"] = _validate_deck_golden()
    goldens.update(_agent_errors(goldens["game_scoring"]))
    return {name + SUFFIX: goldens[name] for name in sorted(goldens)}


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="generate_goldens_v2.py", description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="compare with the files on disk; write nothing")
    options = parser.parse_args(list(argv))
    try:
        goldens = transcripts()
    except GenerationError as exc:
        print(f"ERROR   {exc}", file=sys.stderr)
        return 1
    built = {name: render(golden.rows) for name, golden in goldens.items()}
    built[INDEX_NAME] = render_index(goldens)
    # A transcript on disk the generator no longer makes is out of date too.
    extra = sorted(path.name for path in GOLDENS_V2_DIR.glob("*" + SUFFIX) if path.name not in built)
    failures = 0
    for name in sorted(built):
        path, content = GOLDENS_V2_DIR / name, built[name]
        if options.check:
            if not path.is_file():
                print(f"MISSING {name}")
                failures += 1
            elif path.read_bytes() != content:
                print(f"STALE   {name}")
                failures += 1
            else:
                print(f"OK      {name}")
        else:
            GOLDENS_V2_DIR.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            print(f"WROTE   {name} ({len(content)} bytes)")
    for name in extra:
        if options.check:
            print(f"STALE   {name} (no longer generated)")
            failures += 1
        else:
            (GOLDENS_V2_DIR / name).unlink()
            print(f"REMOVED {name}")
    if failures:
        print(f"{failures} golden file(s) out of date; run without --check to rewrite them", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
