"""The v2 fake engine: the environment role, spoken strictly, for the host's tests (spec 4, 8, 9).

Command line (flags and kinds are comma-separated)::

    python fake_v2_engine.py [--flags NAMES | --all-flags] [--rewind] [--probe] [--london] [--toss]
                             [--decklists] [--kinds NAMES] [--name NAME]

By default the engine declares no optional observation flag, all 30 v2.0 kinds, the format ``pauper-bo1``,
``rules_supported`` ``{"mulligan": ["none"], "starting_player": ["host_assigned"]}``, catalog decks only,
every ``engine_defaults`` entry null, no extensions, and the identity ``fake-v2-engine`` 0.2.0. ``--london``
and ``--toss`` add ``london`` and ``toss_winner_chooses``; ``--decklists`` adds the ``decklist`` deck source;
``--probe`` declares the probe, whose every ``probe_resample`` it refuses (spec 9.7 is reserved), so it plays
no game reset with ``rules.probe: true``.

The p0 deck picks the game. ``Burn``, ``Elves`` and ``Faeries`` play the scoring game: each seat holds two
Mountains, and four decisions follow, the starting seat first (p0 under ``toss_winner_chooses``), then
alternating, in turn ``step + 1`` with the acting seat active and holding priority. Each offers
``[pass, play_land]`` for a Mountain in the seat's hand, and each land played scores 1. After the fourth answer
the higher score wins and equal scores draw (reason ``score``). The built-in games pose no pregame decision,
whatever the mulligan and starting-player rules; ``--london`` and ``--toss`` serve the scenarios, which pose
their own. The hooks: ``Crash`` exits with code 3 at the first step; ``Halt`` answers it with a halted terminal
and ``Truncate`` with a truncated one (reason ``engine_cap``); ``Refuse`` is refused, in either seat;
``Rendezvous`` drops a marker named after the game in ``$SPELLBENCH_RENDEZVOUS_DIR`` at the first step and waits
for ``$SPELLBENCH_RENDEZVOUS_COUNT`` markers (exit code 4 after 10 s); ``Loop`` poses ``[pass]`` to alternating
seats forever; ``Stall`` offers p0 ``[pass, activate_ability]`` for its Relic of Progenitus and p1 ``[pass]`` in
alternation, and draws (reason ``stall_ended``) when p0 passes; ``P0Wins`` is the scoring game that p0 always
wins (reason ``p0_wins_hook``); ``Echo`` is the scoring game whose reason is ``secret:`` and the first 8 hex
digits of the SHA-256 of the game secret's 32 bytes. A decklist deck (``--decklists``) of fixture cards plays
the scoring game. ``Scenario:<name>`` plays the ``SCENARIO`` of ``fake_v2_scenario_<name>.py`` beside this file,
and needs each of the scenario's ``engine_args`` on this engine's command line. Every game ends truncated
(reason ``max_steps`` or ``max_decisions``) once the answered decisions reach ``max_steps`` or the counted groups
reach ``max_decisions``, unless the answer that reaches the cap ends it naturally.

Scenario runner (spec 8; Decision 4, as the host's ``GroupTracker`` counts): each ``Posed`` becomes a seat
decision whose ``{"$obj": n}`` references resolve through ``World.reference`` and whose targets resolve through
``World.target``, per viewer. A ``Posed`` at substep index 0 starts the seat's next group (the id after an
abandoned partial group's), any other continues the current one. The engine keeps every completed group of
both seats in completion order, flagged counted, and each seat's last non-pass priority action as a
completion index; a rewind stops counting every group from that index on. The terminal's ``step_count`` is
the answered decisions and its ``decision_count`` the counted groups.

Requests are parsed strictly (spec 4.2). The one-entry retransmission cache (spec 4.1) holds the last request
that parsed, compared as canonical JSON, so a byte-identical line always matches. ``reset`` checks, in order: a
reused ``game_id`` (``malformed_request``), an active game, the format, the decks, their ``deck_id`` values and
the rules. ``step`` checks in the order of spec 9.4.

``serve(argv, stdin=None, stdout=None, mutate=None)`` runs the engine. ``mutate(step, message)`` may rewrite
each outgoing decision or terminal (``step`` is a decision's binding step, or the answered count for a
terminal); a message it returns is written as canonical JSON, and bytes, for what canonical JSON cannot carry,
are written unchanged as the line's content, followed by ``\\n``. It may also sleep or exit.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib
import os
import sys
import time
from collections.abc import Callable, Generator, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from spellbench import wire
from spellbench._schema import CHOICE_KINDS, OBSERVATION_FLAGS, PRIORITY_KINDS, SEATS, exact_keys, nonempty, u32
from spellbench.digests import deck_id, deck_rows
from spellbench.errors import MalformedJsonError, ValidationError
from spellbench.messages import (
    ENGINE_DEFAULT_KEYS,
    ENGINE_ERROR_CODES,
    MULLIGAN_RULES,
    PROTOCOL,
    PROTOCOL_MINOR,
    STARTING_PLAYER_RULES,
    CatalogDeck,
    Decision,
    DeckOk,
    DeckRow,
    EngineIdentity,
    EngineProfile,
    EnvHelloOk,
    ErrorResponse,
    HelloRequest,
    ResetRequest,
    Rules,
    StepRequest,
    Terminal,
    TerminalResult,
    ValidateDeckRequest,
)

from fake_v2_world import CARDS, Posed, Scenario, World

ENGINE_NAME = "fake-v2-engine"
ENGINE_VERSION = "0.2.0"
FORMATS = ("pauper-bo1",)
SCORING_DECKLIST = [{"name": "Lightning Bolt", "count": 4}, {"name": "Mountain", "count": 18}]
SCORING_DECKS = ("Burn", "Elves", "Faeries")
HOOKS = ("Crash", "Echo", "Halt", "Loop", "P0Wins", "Refuse", "Rendezvous", "Stall", "Truncate")
_SCORING_DECISIONS = 4
_RENDEZVOUS_TIMEOUT_S = 10.0
_KINDS = PRIORITY_KINDS + CHOICE_KINDS                     # all 30 v2.0 kinds, in spec table order
_SCENARIO_PREFIX = "fake_v2_scenario_"
_PASS = {"kind": "pass"}
# What a decklist deck may hold: a fixture card, a multi-face card by its full name (spec 4.4).
_PLAYABLE = frozenset(card["full_name"] or name for name, card in CARDS.items())
# Error messages are human-facing only (spec 9.8); keep them short.
_MAX_MESSAGE_CHARS = 240
_PROBE_FIELDS = ("request_type", "protocol", "request_id", "game_id", "samples")


def _other(seat: str) -> str:
    return "p1" if seat == "p0" else "p0"


# ---------------------------------------------------------------------------
# The built-in games: scripts of Posed decisions that return (outcome, winner, reason)
# ---------------------------------------------------------------------------


def _opening(world: World) -> dict[str, list[int]]:
    """Each seat's two-card hand of Mountains."""
    return {seat: [world.add("Mountain", owner=seat, zone="hand") for _ in range(2)] for seat in SEATS}


def _scoring(world: World, first: str, ending: Callable[[dict[str, int]], tuple]) -> Generator[Posed, int, tuple]:
    """The scoring game; ``ending(scores)`` names its result."""
    hands = _opening(world)
    scores = dict.fromkeys(SEATS, 0)
    for step in range(_SCORING_DECISIONS):
        seat = first if step % 2 == 0 else _other(first)
        world.turn, world.active_seat, world.priority_seat = step + 1, seat, seat
        for obj in world.objects.values():                   # the seat's turn began (spec 6.4, CR 302.6)
            if obj.zone == "battlefield" and obj.controller == seat:
                obj.summoning_sick = False
        picked = yield Posed(seat, [_PASS, {"kind": "play_land", "source": {"$obj": hands[seat][0]}, "face": 0}])
        if picked == 1:
            world.move(hands[seat].pop(0), "battlefield")       # a zone change: a fresh id (spec 5.3)
            scores[seat] += 1
    return ending(scores)


def _by_score(reason: str) -> Callable[[dict[str, int]], tuple]:
    def ending(scores: dict[str, int]) -> tuple:
        if scores["p0"] == scores["p1"]:
            return ("draw", None, reason)
        winner = "p0" if scores["p0"] > scores["p1"] else "p1"
        return (f"{winner}_win", winner, reason)

    return ending


def _loop(world: World, first: str) -> Generator[Posed, int, tuple]:
    """Single-candidate decisions to alternating seats, in turn 1, until a cap ends the game."""
    _opening(world)
    world.active_seat = seat = first
    while True:
        world.priority_seat = seat
        yield Posed(seat, [_PASS])
        seat = _other(seat)


def _stall(world: World, first: str) -> Generator[Posed, int, tuple]:
    """p0 may activate its Relic of Progenitus again and again, in turn 1; the game draws once p0 passes."""
    _opening(world)
    relic = world.add("Relic of Progenitus", owner="p0", zone="battlefield")
    world.active_seat = seat = first
    while True:
        world.priority_seat = seat
        if seat == "p0":
            activate = {"kind": "activate_ability", "source": {"$obj": relic}, "ability_index": 0}
            picked = yield Posed(seat, [_PASS, activate])
            if picked == 0:
                return ("draw", None, "stall_ended")
        else:
            yield Posed(seat, [_PASS])
        seat = _other(seat)


def _rendezvous(game_id: str) -> None:
    """Meet the other engines of a test at the first step; preflight resets never step, so they never wait."""
    directory = Path(os.environ["SPELLBENCH_RENDEZVOUS_DIR"])
    count = int(os.environ["SPELLBENCH_RENDEZVOUS_COUNT"])
    (directory / game_id).touch()
    deadline = time.monotonic() + _RENDEZVOUS_TIMEOUT_S
    while sum(1 for _ in directory.iterdir()) < count:
        if time.monotonic() > deadline:
            sys.exit(4)
        time.sleep(0.02)


# ---------------------------------------------------------------------------
# The scenario runner: numbering, counting, rewinds and caps (spec 8, 9.3, 9.5)
# ---------------------------------------------------------------------------


def _resolve(world: World, seat: str, value: Any) -> Any:
    """A Posed value as ``seat`` sees it: ``{"$obj": n}`` references and targets resolved per viewer (spec 5).

    A reference that resolves to None stays None; so does a target whose object the viewer cannot see.
    """
    if isinstance(value, dict):
        if value.keys() == {"$obj"}:
            return world.reference(seat, value["$obj"])
        if value.keys() == {"player"} or (value.keys() == {"object"} and _object_form(value["object"])):
            return world.target(seat, value)
        return {key: _resolve(world, seat, item) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve(world, seat, item) for item in value]
    return value


def _object_form(value: Any) -> bool:
    return value is None or (isinstance(value, dict) and value.keys() == {"$obj"})


def _family(semantics: Sequence[Mapping[str, Any]]) -> str:
    """The context kind the candidates imply (spec 7.1), read from the first candidate."""
    return "priority" if semantics and semantics[0].get("kind") in PRIORITY_KINDS else "choice"


@dataclass(frozen=True)
class _Pending:
    """What the engine keeps of the pending decision to check and account its answer (spec 8, 9.4)."""

    seat: str
    group_id: int
    index: int
    count: int
    priority: bool
    kinds: tuple[Any, ...]
    semantics: tuple[bytes, ...]         # each candidate's semantic as canonical JSON


class _Game:
    """One game: a script of Posed decisions, numbered, counted and capped (spec 8, 9.2 to 9.5; Decision 4)."""

    def __init__(self, game_id: str, script: Generator[Posed, int, Any], world: World, *, hook: str | None,
                 outcome: tuple | None, max_steps: int, max_decisions: int) -> None:
        self.game_id = game_id
        self.over = False
        self.step = 0                                        # answered decisions of both seats
        self.pending: _Pending | None = None
        self._script = script
        self._world = world
        self._hook = hook
        self._outcome = outcome                              # when the script returns None
        self._caps = (max_steps, max_decisions)
        self._seat_steps = dict.fromkeys(SEATS, 0)
        self._next_group = dict.fromkeys(SEATS, 0)
        self._partial: dict[str, int | None] = dict.fromkeys(SEATS)   # the id of a seat's partial group
        # Every completed group of both seats, in completion order; False once a rewind abandons it.
        self._counted: list[bool] = []
        # Per seat, the completion index of the group of its last non-pass priority action, or None.
        self._actions: dict[str, int | None] = dict.fromkeys(SEATS)

    def start(self) -> tuple[int, dict] | TerminalResult:
        return self._advance(None)

    def answer(self, candidate_id: int) -> tuple[int, dict] | TerminalResult:
        """The next decision or the terminal, after the pending decision is answered with ``candidate_id``."""
        first = self.step == 0
        if first and self._hook == "Crash":
            sys.exit(3)
        if first and self._hook == "Rendezvous":
            _rendezvous(self.game_id)
        self._record(candidate_id)
        if first and self._hook == "Halt":
            return self._end("halted", None, "engine_contract_failure:test_hook")
        if first and self._hook == "Truncate":
            return self._end("truncated", None, "engine_cap")
        return self._advance(candidate_id)

    def _advance(self, sent: int | None) -> tuple[int, dict] | TerminalResult:
        try:
            posed = self._script.send(sent)
        except StopIteration as stop:
            return self._end(*(stop.value if stop.value is not None else self._outcome))
        if not isinstance(posed, Posed):
            raise TypeError(f"a game script yields Posed decisions, not {posed!r}")
        max_steps, max_decisions = self._caps
        if self.step >= max_steps:                           # checked before posing, so nothing is accounted
            return self._end("truncated", None, "max_steps")
        if sum(self._counted) >= max_decisions:
            return self._end("truncated", None, "max_decisions")
        return self.step, self._pose(posed)

    def _pose(self, posed: Posed) -> dict:
        seat, (index, count) = posed.seat, posed.substep
        partial = self._partial[seat]
        if index > 0:                                        # the seat's current group continues
            group_id = self._next_group[seat] if partial is None else partial
        else:                                                # the seat's next group; a partial one is abandoned
            group_id = self._next_group[seat] if partial is None else partial + 1
            if posed.rewind:
                self._rewind(seat)
            self._partial[seat] = None
        world = self._world
        semantics = [_resolve(world, seat, candidate) for candidate in posed.candidates]
        kind = posed.kind or _family(semantics)
        self.pending = _Pending(seat, group_id, index, count, kind == "priority",
                                tuple(semantic.get("kind") for semantic in semantics),
                                tuple(wire.canonical_json_dumps(semantic) for semantic in semantics))
        return {
            "acting_seat": seat,
            "seat_step": self._seat_steps[seat],
            "group": {"group_id": group_id, "substep_index": index, "substep_count": count},
            "context": {"kind": kind, "source": _resolve(world, seat, posed.source), "purpose": posed.purpose,
                        "text": posed.text, "rewind": posed.rewind},
            "observation": world.observation(seat),
            "candidates": [{"candidate_id": number, "semantic": semantic, "display_text": None}
                           for number, semantic in enumerate(semantics)],
            "extensions": copy.deepcopy(posed.extensions),
        }

    def _rewind(self, seat: str) -> None:
        """Decision 4: the rewound action's own group and every group completed after it stop counting."""
        start = self._actions[seat]
        if start is not None:
            self._counted[start:] = [False] * (len(self._counted) - start)
            other = _other(seat)
            if self._actions[other] is not None and self._actions[other] >= start:
                self._actions[other] = None                  # the rewind undid the other seat's later action too
        self._actions[seat] = None

    def _record(self, candidate_id: int) -> None:
        pending, self.pending = self.pending, None
        seat = pending.seat
        self.step += 1
        self._seat_steps[seat] += 1
        if pending.priority:                                 # a priority decision is its own group, completed now
            self._actions[seat] = None if pending.kinds[candidate_id] == "pass" else len(self._counted)
        if pending.index + 1 == pending.count:
            self._counted.append(True)
            self._next_group[seat] = pending.group_id + 1
            self._partial[seat] = None
        else:
            self._partial[seat] = pending.group_id

    def _end(self, outcome: str, winner: str | None, reason: str) -> TerminalResult:
        self.over, self.pending = True, None
        self._script.close()
        classification = outcome if outcome in ("truncated", "halted") else "natural"
        return TerminalResult(outcome, classification, winner, reason, self.step, sum(self._counted))


# ---------------------------------------------------------------------------
# The engine: strict requests, the retransmission cache, errors (spec 4.1, 9)
# ---------------------------------------------------------------------------


def _error(request_id: str, code: str, message: str) -> bytes:
    if code not in ENGINE_ERROR_CODES:
        raise ValueError(f"{code!r} is not an engine error code (spec 9.8)")
    # A parser message may quote the request (a duplicate key, say); a lone surrogate in it cannot be UTF-8.
    text = " ".join(message.encode("utf-8", "backslashreplace").decode("utf-8").split())
    return wire.canonical_json_line(ErrorResponse(request_id, code, text[:_MAX_MESSAGE_CHARS]).to_json())


def _probe_request(value: dict[str, Any]) -> dict[str, Any]:
    """``probe_resample`` (spec 9.7), strictly: exactly its fields, a game id and a u32 sample count."""
    exact_keys(value, _PROBE_FIELDS, "probe_resample")
    nonempty(value["game_id"], "probe_resample.game_id")
    u32(value["samples"], "probe_resample.samples")
    return value


def _scenarios() -> dict[str, Scenario]:
    """``Scenario:<name>`` for each ``fake_v2_scenario_<name>.py`` beside this file, by catalog id."""
    found = {}
    for path in sorted(Path(__file__).resolve().parent.glob(f"{_SCENARIO_PREFIX}*.py")):
        name = path.stem[len(_SCENARIO_PREFIX):]
        scenario = getattr(importlib.import_module(path.stem), "SCENARIO", None)
        if not isinstance(scenario, Scenario) or scenario.name != name:
            raise ValueError(f"{path.name} must define SCENARIO, a fake_v2_world.Scenario named {name!r}")
        found[f"Scenario:{name}"] = scenario
    return found


class _Engine:
    """The environment role of one process: at most one game at a time (spec 2)."""

    def __init__(self, options: argparse.Namespace, argv: Sequence[str],
                 mutate: Callable[[int, dict], dict | bytes] | None) -> None:
        self._argv = tuple(argv)
        self._mutate = mutate
        self._scenarios = _scenarios()
        decks = {catalog_id: SCORING_DECKLIST for catalog_id in (*SCORING_DECKS, *HOOKS)}
        decks.update((catalog_id, scenario.decklist) for catalog_id, scenario in self._scenarios.items())
        self._decks = dict(sorted(decks.items()))
        flags = set(OBSERVATION_FLAGS) if options.all_flags else set(options.flags or ())
        self._flags = {flag: flag in flags for flag in OBSERVATION_FLAGS}
        self._probe = options.probe
        identity = EngineIdentity(options.name, ENGINE_VERSION, None, "fake-v2-rules", "fake-v2-cards")
        self._provenance = identity.provenance()
        self._hello = EnvHelloOk(
            request_id="startup",
            protocol_minor=PROTOCOL_MINOR,
            engine=identity,
            formats=FORMATS,
            deck_sources=("catalog", "decklist") if options.decklists else ("catalog",),
            catalog=tuple(CatalogDeck.from_json({"catalog_id": catalog_id, "name": catalog_id, "decklist": rows})
                          for catalog_id, rows in self._decks.items()),
            profile=EngineProfile(
                rules_supported={
                    "mulligan": tuple(rule for rule in MULLIGAN_RULES if rule == "none" or options.london),
                    "starting_player": tuple(rule for rule in STARTING_PLAYER_RULES
                                             if rule == "host_assigned" or options.toss),
                },
                observation=dict(self._flags),
                decision_kinds=tuple(options.kinds or _KINDS),
                engine_defaults=dict.fromkeys(ENGINE_DEFAULT_KEYS),
                rewind=options.rewind,
                fairness={"noninterference_probe": options.probe},
                extensions=(),
            ),
        )
        self._requests: dict[str, tuple[Callable[[dict], Any], Callable[[Any], bytes]]] = {
            "hello": (HelloRequest.from_json, self._answer_hello),
            "reset": (ResetRequest.from_json, self._answer_reset),
            "step": (StepRequest.from_json, self._answer_step),
            "validate_deck": (ValidateDeckRequest.from_json, self._answer_validate_deck),
            "probe_resample": (_probe_request, self._answer_probe_resample),
        }
        self._game: _Game | None = None
        self._used_game_ids: set[str] = set()
        # The last request that parsed: (request_id, its canonical JSON, the answer line) (spec 4.1).
        self._cache: tuple[str, bytes, bytes] | None = None

    def handle(self, line: bytes) -> bytes:
        """Answer one request line with one response line."""
        try:
            value = wire.strict_json_loads(line)
        except wire.NotAnObjectError as exc:                 # valid JSON, but not an object (spec 9.8)
            return _error("", "malformed_request", str(exc))
        except MalformedJsonError as exc:
            return _error("", "malformed_json", str(exc))
        request_id = value.get("request_id")
        if type(request_id) is not str or not request_id:
            return _error("", "malformed_request", "request_id must be a nonempty string (spec 4.1)")
        protocol = value.get("protocol")
        if type(protocol) is not str:
            return _error(request_id, "malformed_request", "protocol must be a string (spec 4.1)")
        if protocol != PROTOCOL:
            return _error(request_id, "protocol_mismatch", f'protocol must be "{PROTOCOL}", got {protocol!r}')
        request_type = value.get("request_type")
        handler = self._requests.get(request_type) if type(request_type) is str else None
        if handler is None:
            return _error(request_id, "malformed_request", f"unknown request_type {request_type!r}")
        parse, answer = handler
        try:
            request = parse(value)
        except ValidationError as exc:                       # never cached (spec 4.1)
            return _error(request_id, "malformed_request", str(exc))
        payload = wire.canonical_json_dumps(value)           # spec 4.1: the identical payload, as canonical JSON
        if self._cache is not None and self._cache[0] == request_id:
            if self._cache[1] == payload:
                return self._cache[2]                        # a retransmission: no side effects
            # Not cached: the entry stays the request the id first answered.
            return _error(request_id, "request_id_reuse_mismatch",
                          f"request_id {request_id!r} was just used with another payload (spec 4.1)")
        response = answer(request)
        self._cache = (request_id, payload, response)
        return response

    def _answer_hello(self, request: HelloRequest) -> bytes:
        minor = min(request.protocol_minor, PROTOCOL_MINOR)  # spec 4.2
        hello = replace(self._hello, request_id=request.request_id, protocol_minor=minor)
        return wire.canonical_json_line(hello.to_json())

    def _answer_reset(self, request: ResetRequest) -> bytes:
        request_id = request.request_id
        if request.game_id in self._used_game_ids:
            return _error(request_id, "malformed_request",
                          f"game_id {request.game_id!r} was used by an earlier reset of this process (spec 9.2)")
        if self._game is not None and not self._game.over:
            return _error(request_id, "game_already_active", f"game {self._game.game_id!r} is still active (spec 9.2)")
        if request.format not in FORMATS:
            return _error(request_id, "unsupported_format",
                          f"format {request.format!r} is not one of {', '.join(FORMATS)}")
        for seat, deck in zip(SEATS, request.seats):
            refusal = self._refusal(deck.catalog_id, deck.decklist)
            if refusal is not None:
                return _error(request_id, "unsupported_deck", f"the {seat} deck: {refusal}")
        for seat, deck in zip(SEATS, request.seats):
            expected = deck_id(self._rows(deck.catalog_id, deck.decklist))
            if deck.deck_id != expected:
                return _error(request_id, "deck_id_mismatch",
                              f"the {seat} deck_id does not match its list, whose deck_id is {expected}")
        refusal = self._unsupported_rule(request.rules)
        if refusal is not None:
            return _error(request_id, "unsupported_rule", refusal)
        self._used_game_ids.add(request.game_id)
        self._game = self._start(request)
        return self._respond(request_id, self._game.start())

    def _start(self, request: ResetRequest) -> _Game:
        world = World(bytes.fromhex(request.game_secret), flags=self._flags)
        hook = request.seats[0].catalog_id                   # the p0 deck picks the game; a decklist deck scores
        first = request.rules.starting_seat or "p0"
        scenario = self._scenarios.get(hook)
        outcome = None
        if scenario is not None:
            script, outcome = scenario.script(world), scenario.outcome
        elif hook == "Loop":
            script = _loop(world, first)
        elif hook == "Stall":
            script = _stall(world, first)
        elif hook == "P0Wins":
            script = _scoring(world, first, lambda scores: ("p0_win", "p0", "p0_wins_hook"))
        elif hook == "Echo":
            digest = hashlib.sha256(bytes.fromhex(request.game_secret)).hexdigest()
            script = _scoring(world, first, _by_score(f"secret:{digest[:8]}"))
        else:
            script = _scoring(world, first, _by_score("score"))
        return _Game(request.game_id, script, world, hook=hook, outcome=outcome,
                     max_steps=request.max_steps, max_decisions=request.max_decisions)

    def _answer_step(self, request: StepRequest) -> bytes:
        request_id, game = request.request_id, self._game
        # Spec 9.4, in order.
        if game is None:
            return _error(request_id, "step_before_reset", "no game has been reset")
        if request.game_id != game.game_id:
            return _error(request_id, "game_id_mismatch", f"this engine's game is {game.game_id!r}")
        if game.over:
            return _error(request_id, "game_already_terminal", f"game {game.game_id!r} has ended")
        if request.expected_step != game.step:
            return _error(request_id, "expected_step_mismatch", f"the pending decision's step is {game.step}")
        pending, candidate_id = game.pending, request.selection.candidate_id
        if candidate_id >= len(pending.semantics):
            return _error(request_id, "candidate_id_out_of_range",
                          f"candidate_id {candidate_id} is outside the {len(pending.semantics)} candidates")
        if wire.canonical_json_dumps(request.selection.semantic_echo) != pending.semantics[candidate_id]:
            return _error(request_id, "semantic_echo_mismatch", f"semantic_echo differs from candidate {candidate_id}")
        return self._respond(request_id, game.answer(candidate_id))

    def _answer_validate_deck(self, request: ValidateDeckRequest) -> bytes:
        if request.format not in FORMATS:
            return _error(request.request_id, "unsupported_format",
                          f"format {request.format!r} is not one of {', '.join(FORMATS)}")
        refusal = self._refusal(request.catalog_id, request.decklist)
        if refusal is not None:
            return _error(request.request_id, "unsupported_deck", refusal)
        return wire.canonical_json_line(DeckOk(request.request_id).to_json())

    def _answer_probe_resample(self, request: dict[str, Any]) -> bytes:
        request_id, game = request["request_id"], self._game
        if not self._probe:
            return _error(request_id, "unsupported_request", "this engine has no probe (spec 9.7)")
        if game is None:
            return _error(request_id, "step_before_reset", "no game has been reset")
        if request["game_id"] != game.game_id:
            return _error(request_id, "game_id_mismatch", f"this engine's game is {game.game_id!r}")
        if game.over:
            return _error(request_id, "game_already_terminal", f"game {game.game_id!r} has ended")
        return _error(request_id, "probe_refused", "the game was not reset with rules.probe: true (spec 9.7)")

    def _refusal(self, catalog_id: str | None, decklist: tuple[DeckRow, ...] | None) -> str | None:
        """Why this engine cannot play a deck (``unsupported_deck``, spec 9.2), or None."""
        if catalog_id is not None:
            if catalog_id not in self._decks:
                return f"catalog_id {catalog_id!r} is not in this engine's catalog"
            if catalog_id == "Refuse":
                return "the Refuse deck is refused (a test hook)"
            scenario = self._scenarios.get(catalog_id)
            if scenario is not None and not all(arg in self._argv for arg in scenario.engine_args):
                return f"{catalog_id} needs the engine arguments {' '.join(scenario.engine_args)}"
            return None
        if "decklist" not in self._hello.deck_sources:
            return "this engine takes catalog decks only (deck_sources)"
        names = [row["name"] for row in deck_rows([row.to_json() for row in decklist])]
        unknown = [name for name in names if name not in _PLAYABLE]
        return f"cards this engine cannot play: {', '.join(unknown)}" if unknown else None

    def _rows(self, catalog_id: str | None, decklist: tuple[DeckRow, ...] | None) -> list[dict[str, Any]]:
        return self._decks[catalog_id] if catalog_id is not None else [row.to_json() for row in decklist]

    def _unsupported_rule(self, rules: Rules) -> str | None:
        """Why this engine cannot play under ``rules`` (``unsupported_rule``, spec 9.2), or None."""
        profile = self._hello.profile
        for name in ("mulligan", "starting_player"):
            value, supported = getattr(rules, name), profile.rules_supported[name]
            if value not in supported:
                return f"rules.{name} {value!r} is not in rules_supported.{name} ({', '.join(supported)})"
        declared = {extension.name for extension in profile.extensions}
        undeclared = [name for name in rules.extensions if name not in declared]
        if undeclared:
            return f"rules.extensions {', '.join(undeclared)} are not declared in hello_ok.extensions"
        if rules.probe:
            return "rules.probe: this engine plays no probe game (spec 9.7 is reserved; --probe only refuses)"
        return None

    def _respond(self, request_id: str, result: tuple[int, dict] | TerminalResult) -> bytes:
        """The decision or terminal message; ``mutate`` sees it last."""
        game = self._game
        if isinstance(result, TerminalResult):
            step = result.step_count
            message = Terminal(request_id, game.game_id, result, self._provenance).to_json()
        else:
            step, seat_decision = result
            message = Decision(request_id, game.game_id, step, seat_decision, self._provenance).to_json()
        if self._mutate is not None:
            changed = self._mutate(step, message)
            if isinstance(changed, bytes):
                return changed + b"\n"
            if not isinstance(changed, dict):
                raise TypeError(f"mutate returns a message or bytes, not {type(changed).__name__}")
            message = changed
        return wire.canonical_json_line(message)


# ---------------------------------------------------------------------------
# The command line and the serving loop
# ---------------------------------------------------------------------------


def _names(text: str) -> tuple[str, ...]:
    names = tuple(text.split(","))
    if not all(names):
        raise argparse.ArgumentTypeError(f"{text!r} is not a comma-separated list of names")
    return names


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fake_v2_engine.py",
                                     description="The spellbench v2 fake engine (tests only).")
    flags = parser.add_mutually_exclusive_group()
    flags.add_argument("--flags", type=_names, metavar="NAMES", help="observation flags to declare (spec 6.9)")
    flags.add_argument("--all-flags", action="store_true", help="declare all thirteen observation flags")
    parser.add_argument("--rewind", action="store_true", help="declare rewind (spec 8)")
    parser.add_argument("--probe", action="store_true", help="declare the probe and refuse every probe_resample")
    parser.add_argument("--london", action="store_true", help="support the london mulligan rule")
    parser.add_argument("--toss", action="store_true", help="support toss_winner_chooses")
    parser.add_argument("--decklists", action="store_true", help="accept decks given as decklists")
    parser.add_argument("--kinds", type=_names, metavar="NAMES", help="decision kinds to declare (default: all 30)")
    parser.add_argument("--name", default=ENGINE_NAME, help=f"the engine name (default {ENGINE_NAME})")
    return parser


def serve(argv: Sequence[str], *, stdin: Any = None, stdout: Any = None,
          mutate: Callable[[int, dict], dict | bytes] | None = None) -> int:
    """Serve the environment role on binary stdin and stdout until EOF; returns the exit code 0."""
    parser = _parser()
    options = parser.parse_args(list(argv))
    unknown = sorted(set(options.flags or ()) - set(OBSERVATION_FLAGS))
    if unknown:
        parser.error(f"unknown observation flags: {', '.join(unknown)}")
    try:
        engine = _Engine(options, argv, mutate)
    except ValidationError as exc:                           # the declarations the arguments make (spec 9.1)
        parser.error(str(exc))
    in_stream = sys.stdin.buffer if stdin is None else stdin
    out_stream = sys.stdout.buffer if stdout is None else stdout
    while True:
        try:
            line = wire.read_line(in_stream)
        except MalformedJsonError as exc:                    # framing: a line over 8 MiB, or no terminator at EOF
            answer = _error("", "malformed_json", str(exc))
        else:
            if line is None:
                return 0
            answer = engine.handle(line)
        out_stream.write(answer)
        out_stream.flush()


if __name__ == "__main__":
    sys.exit(serve(sys.argv[1:]))
