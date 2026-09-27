"""Frozen verifier and reader for published protocol v1 tournament runs.

Every committed v1 run (manifest schema ``spellbench-tournament/v1``) stays
checkable byte for byte after the v1 protocol code is deleted. This module is
a move, not a rewrite: its validators, dataclasses, schedule and manifest
rebuild are copied verbatim from commit 7e9e73f (``models.py``,
``arena/store.py``, ``arena/runner.py``, ``arena/bots/uniform.py``), renamed
where names would clash, and it imports none of those modules. From the rest
of the package it uses only the ``store`` IO helpers,
``registry.read_registry``, ``leaderboard.build_leaderboard``, the
``ratings`` bootstrap limits and ``errors.ValidationError``; the v1 integer
bound is frozen here as ``_V1_MAX_JSON_INT``.

Spec section numbers below refer to ``spec/SPELLBENCH_PROTOCOL_V1.md``.

A v1 run is recomputed only when it was made by ``LEGACY_ARENA_VERSION``,
the arena version that produced the v1 runs, never the running package
version: a later release bumps ``spellbench.__version__`` and the committed
runs must keep validating.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from itertools import combinations_with_replacement
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..errors import ValidationError
from . import leaderboard, ratings, registry, store

LEGACY_ARENA_VERSION = "0.2.0"
TOURNAMENT_SCHEMA_V1 = "spellbench-tournament/v1"
LEDGER_SCHEMA_V1 = "spellbench-match-ledger/v1"
CONFIG_SCHEMA_V1 = "spellbench-tournament-config/v1"
LEADERBOARD_SCHEMA_V1 = "spellbench-leaderboard/v1"


# ---------------------------------------------------------------------------
# Field validators (from models.py)
# ---------------------------------------------------------------------------

# wire.MAX_JSON_INT at 7e9e73f (the v1 bound |x| <= 2^53), frozen: protocol v2 lowers it.
_V1_MAX_JSON_INT = 1 << 53

U32_MAX = (1 << 32) - 1
U64_MAX = _V1_MAX_JSON_INT  # protocol numbers never exceed the IEEE-754 safe range

SEATS = ("p0", "p1")


def _fail(context: str, detail: str) -> None:
    raise ValidationError(f"{context}: {detail}")


def _keys(value: Mapping[str, Any], expected: Sequence[str], context: str) -> None:
    expected_set = set(expected)
    actual = set(value)
    missing = expected_set - actual
    extra = actual - expected_set
    if missing or extra:
        _fail(context, f"fields mismatch: missing={sorted(missing)} extra={sorted(extra)}")


def _int(
    value: Any,
    context: str,
    *,
    minimum: int = 0,
    maximum: int = _V1_MAX_JSON_INT,
) -> int:
    if type(value) is not int:
        _fail(context, f"must be an integer, got {type(value).__name__}")
    if value < minimum:
        _fail(context, f"must be >= {minimum}")
    if value > maximum:
        _fail(context, f"must be <= {maximum}")
    return value


def _u32(value: Any, context: str) -> int:
    return _int(value, context, minimum=0, maximum=U32_MAX)


def _u64(value: Any, context: str) -> int:
    return _int(value, context, minimum=0, maximum=U64_MAX)


def _str(value: Any, context: str) -> str:
    if type(value) is not str:
        _fail(context, "must be a string")
    return value


def _nonempty_str(value: Any, context: str) -> str:
    text = _str(value, context)
    if not text:
        _fail(context, "must be nonempty")
    return text


def _list(value: Any, context: str, *, length: int | None = None, min_length: int = 0) -> list[Any]:
    if not isinstance(value, list):
        _fail(context, "must be a list")
    if length is not None and len(value) != length:
        _fail(context, f"must have length {length}")
    if len(value) < min_length:
        _fail(context, f"must have at least {min_length} entries")
    return value


def _seat(value: Any, context: str) -> str:
    seat = _str(value, context)
    if seat not in SEATS:
        _fail(context, "must be p0 or p1")
    return seat


def _optional_seat(value: Any, context: str) -> str | None:
    if value is None:
        return None
    return _seat(value, context)


# ---------------------------------------------------------------------------
# Engine identity and decks (from models.py)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Provenance:
    """The engine identity repeated in decisions and terminals (spec 7.3)."""

    engine_name: str
    engine_version: str
    rules_snapshot_id: str
    card_pool_identity: str

    def __post_init__(self) -> None:
        _nonempty_str(self.engine_name, "provenance.engine_name")
        _nonempty_str(self.engine_version, "provenance.engine_version")
        _nonempty_str(self.rules_snapshot_id, "provenance.rules_snapshot_id")
        _nonempty_str(self.card_pool_identity, "provenance.card_pool_identity")

    def to_json(self) -> dict[str, Any]:
        return {
            "engine_name": self.engine_name,
            "engine_version": self.engine_version,
            "rules_snapshot_id": self.rules_snapshot_id,
            "card_pool_identity": self.card_pool_identity,
        }

    @classmethod
    def from_json(cls, value: Any, context: str = "provenance") -> "Provenance":
        if not isinstance(value, dict):
            _fail(context, "must be an object")
        _keys(
            value,
            ["engine_name", "engine_version", "rules_snapshot_id", "card_pool_identity"],
            context,
        )
        return cls(
            engine_name=_nonempty_str(value["engine_name"], f"{context}.engine_name"),
            engine_version=_nonempty_str(value["engine_version"], f"{context}.engine_version"),
            rules_snapshot_id=_nonempty_str(value["rules_snapshot_id"], f"{context}.rules_snapshot_id"),
            card_pool_identity=_nonempty_str(value["card_pool_identity"], f"{context}.card_pool_identity"),
        )


@dataclass(frozen=True)
class EngineIdentity:
    """The ``engine`` object of env hello_ok and agent game_start."""

    name: str
    version: str
    source_revision: str | None
    rules_snapshot_id: str
    card_pool_identity: str

    def __post_init__(self) -> None:
        _nonempty_str(self.name, "engine.name")
        _nonempty_str(self.version, "engine.version")
        if self.source_revision is not None:
            _nonempty_str(self.source_revision, "engine.source_revision")
        _nonempty_str(self.rules_snapshot_id, "engine.rules_snapshot_id")
        _nonempty_str(self.card_pool_identity, "engine.card_pool_identity")

    def provenance(self) -> Provenance:
        return Provenance(
            engine_name=self.name,
            engine_version=self.version,
            rules_snapshot_id=self.rules_snapshot_id,
            card_pool_identity=self.card_pool_identity,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "source_revision": self.source_revision,
            "rules_snapshot_id": self.rules_snapshot_id,
            "card_pool_identity": self.card_pool_identity,
        }

    @classmethod
    def from_json(cls, value: Any, context: str = "engine") -> "EngineIdentity":
        if not isinstance(value, dict):
            _fail(context, "must be an object")
        _keys(
            value,
            ["name", "version", "source_revision", "rules_snapshot_id", "card_pool_identity"],
            context,
        )
        source_revision = value["source_revision"]
        return cls(
            name=_nonempty_str(value["name"], f"{context}.name"),
            version=_nonempty_str(value["version"], f"{context}.version"),
            source_revision=(
                None if source_revision is None else _nonempty_str(source_revision, f"{context}.source_revision")
            ),
            rules_snapshot_id=_nonempty_str(value["rules_snapshot_id"], f"{context}.rules_snapshot_id"),
            card_pool_identity=_nonempty_str(value["card_pool_identity"], f"{context}.card_pool_identity"),
        )


@dataclass(frozen=True)
class DeckRow:
    name: str
    count: int

    def __post_init__(self) -> None:
        _nonempty_str(self.name, "deck_row.name")
        _int(self.count, "deck_row.count", minimum=1, maximum=U32_MAX)

    def to_json(self) -> dict[str, Any]:
        return {"name": self.name, "count": self.count}

    @classmethod
    def from_json(cls, value: Any, context: str = "deck_row") -> "DeckRow":
        if not isinstance(value, dict):
            _fail(context, "must be an object")
        _keys(value, ["name", "count"], context)
        return cls(
            name=_nonempty_str(value["name"], f"{context}.name"),
            count=_int(value["count"], f"{context}.count", minimum=1, maximum=U32_MAX),
        )


@dataclass(frozen=True)
class Deck:
    """Exactly one of ``catalog_id`` or ``decklist`` (spec section 7.2)."""

    catalog_id: str | None = None
    decklist: tuple[DeckRow, ...] | None = None

    def __post_init__(self) -> None:
        if (self.catalog_id is None) == (self.decklist is None):
            _fail("deck", "exactly one of catalog_id/decklist must be set")
        if self.catalog_id is not None:
            _nonempty_str(self.catalog_id, "deck.catalog_id")
        if self.decklist is not None:
            if not self.decklist:
                _fail("deck.decklist", "must be nonempty")

    def to_json(self) -> dict[str, Any]:
        if self.catalog_id is not None:
            return {"catalog_id": self.catalog_id}
        assert self.decklist is not None
        return {"decklist": [row.to_json() for row in self.decklist]}

    @classmethod
    def from_json(cls, value: Any, context: str = "deck") -> "Deck":
        if not isinstance(value, dict):
            _fail(context, "must be an object")
        if set(value) == {"catalog_id"}:
            return cls(catalog_id=_nonempty_str(value["catalog_id"], f"{context}.catalog_id"))
        if set(value) == {"decklist"}:
            rows = _list(value["decklist"], f"{context}.decklist", min_length=1)
            return cls(
                decklist=tuple(
                    DeckRow.from_json(row, f"{context}.decklist[{index}]") for index, row in enumerate(rows)
                )
            )
        _fail(context, "must have exactly one of catalog_id/decklist")


# ---------------------------------------------------------------------------
# Match ledger rows (from arena/store.py; matches.jsonl, schema spellbench-match-ledger/v1)
# ---------------------------------------------------------------------------

LEDGER_OUTCOMES = frozenset({"p0_win", "p1_win", "draw", "truncated", "halted"})
LEDGER_CLASSIFICATIONS = frozenset({"natural", "truncated", "halted", "forfeit"})
FORFEIT_CAUSES = frozenset(
    {"timeout", "malformed_response", "invalid_selection", "agent_error", "transport_error"}
)

_NATURAL_WINNERS = {"p0_win": "p0", "p1_win": "p1", "draw": None}


def _req_str(value: Any, context: str) -> str:
    if type(value) is not str or not value:
        raise ValidationError(f"{context}: must be a nonempty string")
    return value


def _req_uint(value: Any, context: str) -> int:
    if type(value) is not int or value < 0 or value > _V1_MAX_JSON_INT:
        raise ValidationError(f"{context}: must be an integer in [0, 2^53]")
    return value


def _req_seat(value: Any, context: str) -> str:
    seat = _req_str(value, context)
    if seat not in SEATS:
        raise ValidationError(f"{context}: must be p0 or p1")
    return seat


@dataclass(frozen=True)
class LedgerSeat:
    seat: str
    bot_id: str
    name: str
    version: str

    def to_json(self) -> dict[str, Any]:
        return {"seat": self.seat, "bot_id": self.bot_id, "name": self.name, "version": self.version}

    @classmethod
    def from_json(cls, value: Any, context: str) -> "LedgerSeat":
        if not isinstance(value, dict):
            raise ValidationError(f"{context}: must be an object")
        store.require_keys(value, ["seat", "bot_id", "name", "version"], context)
        return cls(
            seat=_req_seat(value["seat"], f"{context}.seat"),
            bot_id=_req_str(value["bot_id"], f"{context}.bot_id"),
            name=_req_str(value["name"], f"{context}.name"),
            version=_req_str(value["version"], f"{context}.version"),
        )


@dataclass(frozen=True)
class Adjudication:
    """A host-adjudicated result (the engine produced no terminal for it).

    ``kind == "forfeit"`` carries ``cause`` (one of FORFEIT_CAUSES) and
    ``loser_seat``; ``kind == "engine_halt"`` records a host-detected engine
    contract failure with a ``detail`` message only.
    """

    kind: str
    detail: str
    cause: str | None = None
    loser_seat: str | None = None

    def to_json(self) -> dict[str, Any]:
        if self.kind == "forfeit":
            return {
                "kind": "forfeit",
                "cause": self.cause,
                "loser_seat": self.loser_seat,
                "detail": self.detail,
            }
        return {"kind": self.kind, "detail": self.detail}

    @classmethod
    def from_json(cls, value: Any, context: str) -> "Adjudication":
        if not isinstance(value, dict):
            raise ValidationError(f"{context}: must be an object")
        kind = value.get("kind")
        if kind == "forfeit":
            store.require_keys(value, ["kind", "cause", "loser_seat", "detail"], context)
            cause = _req_str(value["cause"], f"{context}.cause")
            if cause not in FORFEIT_CAUSES:
                raise ValidationError(f"{context}.cause: must be one of {sorted(FORFEIT_CAUSES)}")
            return cls(
                kind="forfeit",
                cause=cause,
                loser_seat=_req_seat(value["loser_seat"], f"{context}.loser_seat"),
                detail=_req_str(value["detail"], f"{context}.detail"),
            )
        if kind == "engine_halt":
            store.require_keys(value, ["kind", "detail"], context)
            return cls(kind="engine_halt", detail=_req_str(value["detail"], f"{context}.detail"))
        raise ValidationError(f"{context}.kind: must be forfeit or engine_halt")


@dataclass(frozen=True)
class LegacyLedgerRow:
    """One completed (or adjudicated) game in the match ledger.

    Natural rows (spec section 7.5) and forfeit rows are rated: a forfeit is
    a loss for the seat that forfeited, or a losing bot could erase its
    losses by hanging or answering garbage. Truncated and halted rows are
    recorded and excluded from the rating fit.
    """

    game_id: str
    matchup_index: int
    pair_index: int
    game_index: int
    format: str
    game_seed: int
    seats: tuple[LedgerSeat, LedgerSeat]
    decks: tuple[dict[str, Any], dict[str, Any]]
    outcome: str
    classification: str
    winner: str | None
    winner_bot_id: str | None
    reason: str
    adjudication: Adjudication | None
    step_count: int
    decision_count: int
    engine: Provenance

    def __post_init__(self) -> None:
        _req_str(self.game_id, "ledger.game_id")
        _req_uint(self.matchup_index, "ledger.matchup_index")
        _req_uint(self.pair_index, "ledger.pair_index")
        if self.game_index not in (0, 1):
            raise ValidationError("ledger.game_index: must be 0 or 1")
        _req_str(self.format, "ledger.format")
        _req_uint(self.game_seed, "ledger.game_seed")
        if len(self.seats) != 2 or {seat.seat for seat in self.seats} != set(SEATS):
            raise ValidationError("ledger.seats: must cover exactly p0 and p1")
        for index, deck in enumerate(self.decks):
            Deck.from_json(deck, f"ledger.decks[{index}]")
        if self.outcome not in LEDGER_OUTCOMES:
            raise ValidationError(f"ledger.outcome: must be one of {sorted(LEDGER_OUTCOMES)}")
        if self.classification not in LEDGER_CLASSIFICATIONS:
            raise ValidationError(
                f"ledger.classification: must be one of {sorted(LEDGER_CLASSIFICATIONS)}"
            )
        _req_str(self.reason, "ledger.reason")
        _req_uint(self.step_count, "ledger.step_count")
        _req_uint(self.decision_count, "ledger.decision_count")
        seat_of = {seat.seat: seat for seat in self.seats}
        if self.classification == "natural":
            if self.outcome not in _NATURAL_WINNERS:
                raise ValidationError("ledger: a natural row has outcome p0_win, p1_win, or draw")
            if self.winner != _NATURAL_WINNERS[self.outcome]:
                raise ValidationError("ledger: natural outcome/winner mismatch")
            if self.adjudication is not None:
                raise ValidationError("ledger: a natural row carries no adjudication")
        elif self.classification in ("truncated", "halted"):
            # Spec 7.5: winner is null "when unassigned by rule"; an engine may
            # name one at a cap. Recorded as reported, never rated.
            if self.outcome != self.classification:
                raise ValidationError("ledger: truncated/halted rows carry the matching outcome")
            if self.classification == "truncated" and self.adjudication is not None:
                raise ValidationError("ledger: a truncated row carries no adjudication")
            if self.classification == "halted" and self.adjudication is not None and self.adjudication.kind != "engine_halt":
                raise ValidationError("ledger: a halted row carries at most an engine_halt adjudication")
        else:  # forfeit
            if self.outcome not in ("p0_win", "p1_win"):
                raise ValidationError("ledger: a forfeit row has outcome p0_win or p1_win")
            if self.winner != _NATURAL_WINNERS[self.outcome]:
                raise ValidationError("ledger: forfeit outcome/winner mismatch")
            if self.adjudication is None or self.adjudication.kind != "forfeit":
                raise ValidationError("ledger: a forfeit row requires a forfeit adjudication")
            expected_loser = "p1" if self.winner == "p0" else "p0"
            if self.adjudication.loser_seat != expected_loser:
                raise ValidationError("ledger: forfeit loser_seat must be the non-winning seat")
        if self.winner is None:
            if self.winner_bot_id is not None:
                raise ValidationError("ledger: winner_bot_id requires a winner")
        else:
            expected_bot = seat_of[self.winner].bot_id
            if self.winner_bot_id != expected_bot:
                raise ValidationError("ledger: winner_bot_id does not match the winning seat")

    @property
    def rated(self) -> bool:
        """Natural terminals and forfeits enter ratings."""
        return self.classification in ("natural", "forfeit")

    @property
    def pair_slot(self) -> int:
        """The game's slot in its seat-swapped pair; v1 records it as ``game_index``."""
        return self.game_index

    def bot_id_at(self, seat: str) -> str:
        for entry in self.seats:
            if entry.seat == seat:
                return entry.bot_id
        raise KeyError(seat)

    def to_json(self) -> dict[str, Any]:
        return {
            "schema": LEDGER_SCHEMA_V1,
            "game_id": self.game_id,
            "matchup_index": self.matchup_index,
            "pair_index": self.pair_index,
            "game_index": self.game_index,
            "format": self.format,
            "game_seed": self.game_seed,
            "seats": [seat.to_json() for seat in sorted(self.seats, key=lambda seat: seat.seat)],
            "decks": [self.decks[0], self.decks[1]],
            "outcome": self.outcome,
            "classification": self.classification,
            "winner": self.winner,
            "winner_bot_id": self.winner_bot_id,
            "reason": self.reason,
            "adjudication": None if self.adjudication is None else self.adjudication.to_json(),
            "step_count": self.step_count,
            "decision_count": self.decision_count,
            "engine": self.engine.to_json(),
        }

    @classmethod
    def from_json(cls, value: Any, context: str = "ledger") -> "LegacyLedgerRow":
        if not isinstance(value, dict):
            raise ValidationError(f"{context}: must be an object")
        store.require_keys(
            value,
            [
                "schema",
                "game_id",
                "matchup_index",
                "pair_index",
                "game_index",
                "format",
                "game_seed",
                "seats",
                "decks",
                "outcome",
                "classification",
                "winner",
                "winner_bot_id",
                "reason",
                "adjudication",
                "step_count",
                "decision_count",
                "engine",
            ],
            context,
        )
        if value["schema"] != LEDGER_SCHEMA_V1:
            raise ValidationError(f'{context}.schema: must be "{LEDGER_SCHEMA_V1}"')
        raw_seats = value["seats"]
        if not isinstance(raw_seats, list) or len(raw_seats) != 2:
            raise ValidationError(f"{context}.seats: must be a list of two")
        seats = tuple(
            sorted(
                (LedgerSeat.from_json(item, f"{context}.seats[{i}]") for i, item in enumerate(raw_seats)),
                key=lambda seat: seat.seat,
            )
        )
        raw_decks = value["decks"]
        if not isinstance(raw_decks, list) or len(raw_decks) != 2:
            raise ValidationError(f"{context}.decks: must be a list of two (p0 first)")
        winner = value["winner"]
        adjudication = value["adjudication"]
        return cls(
            game_id=value["game_id"],
            matchup_index=value["matchup_index"],
            pair_index=value["pair_index"],
            game_index=value["game_index"],
            format=value["format"],
            game_seed=value["game_seed"],
            seats=(seats[0], seats[1]),
            decks=(raw_decks[0], raw_decks[1]),
            outcome=value["outcome"],
            classification=value["classification"],
            winner=None if winner is None else _req_seat(winner, f"{context}.winner"),
            winner_bot_id=value["winner_bot_id"],
            reason=value["reason"],
            adjudication=None if adjudication is None else Adjudication.from_json(adjudication, f"{context}.adjudication"),
            step_count=value["step_count"],
            decision_count=value["decision_count"],
            engine=Provenance.from_json(value["engine"], f"{context}.engine"),
        )


def parse_ledger(rows: Iterable[dict[str, Any]]) -> tuple[LegacyLedgerRow, ...]:
    return tuple(LegacyLedgerRow.from_json(row, f"ledger[{index}]") for index, row in enumerate(rows))


# ---------------------------------------------------------------------------
# Config (from arena/runner.py; config.json, schema spellbench-tournament-config/v1)
# ---------------------------------------------------------------------------

DEFAULT_MAX_DECISIONS = 10_000
DEFAULT_MAX_STEPS = 100_000
DEFAULT_CHOOSE_TIMEOUT_MS = 30_000
DEFAULT_ENGINE_TIMEOUT_MS = 120_000
# Spawn, hello and game_start of a subprocess bot: model loading can be slow.
DEFAULT_STARTUP_TIMEOUT_MS = 120_000
DEFAULT_BOOTSTRAP_REPLICATES = 2_000
DEFAULT_WORKERS = 1
# The most worker processes Windows can wait on; one limit keeps configs portable.
MAX_WORKERS = 61

BOT_TYPES = frozenset({"builtin", "subprocess"})

# The builtin bots of arena 0.2.0 (arena/bots at commit 7e9e73f), frozen.
_V1_BUILTIN_VERSIONS = {"first": "1.0.0", "heuristic": "1.0.0", "uniform": "1.0.0"}


class TournamentError(Exception):
    """The tournament cannot proceed (bad config or a broken engine)."""


@dataclass(frozen=True)
class BotSpec:
    name: str
    version: str
    type: str  # "builtin" | "subprocess"
    seed: int = 0
    command: tuple[str, ...] = ()
    checkpoint: str | None = None
    engine: str = "any"
    owner: str = "unspecified"
    training_style_tags: tuple[str, ...] = ()
    registered_at: int = 0

    def to_json(self) -> dict[str, Any]:
        doc: dict[str, Any] = {
            "name": self.name,
            "version": self.version,
            "type": self.type,
            "seed": self.seed,
            "engine": self.engine,
            "owner": self.owner,
            "training_style_tags": list(self.training_style_tags),
            "registered_at": self.registered_at,
        }
        if self.type == "subprocess":
            doc["command"] = list(self.command)
            if self.checkpoint is not None:
                doc["checkpoint"] = self.checkpoint
        return doc


# runner.py's config validators (they raise TournamentError); renamed with a
# _v1 suffix because store.py's ledger validators of the same names are above.
def _req_str_v1(value: Any, context: str) -> str:
    if type(value) is not str or not value:
        raise TournamentError(f"{context}: must be a nonempty string")
    return value


def _req_uint_v1(value: Any, context: str, *, minimum: int = 0, maximum: int = (1 << 53)) -> int:
    if type(value) is not int or value < minimum or value > maximum:
        raise TournamentError(f"{context}: must be an integer in [{minimum}, {maximum}]")
    return value


def _bot_spec_from_json(value: Any, context: str) -> BotSpec:
    if not isinstance(value, dict):
        raise TournamentError(f"{context}: must be an object")
    allowed = {
        "name",
        "version",
        "type",
        "seed",
        "command",
        "checkpoint",
        "engine",
        "owner",
        "training_style_tags",
        "registered_at",
    }
    required = {"name", "version", "type"}
    missing = required - set(value)
    extra = set(value) - allowed
    if missing or extra:
        raise TournamentError(f"{context}: fields mismatch: missing={sorted(missing)} extra={sorted(extra)}")
    name = _req_str_v1(value["name"], f"{context}.name")
    version = _req_str_v1(value["version"], f"{context}.version")
    bot_type = _req_str_v1(value["type"], f"{context}.type")
    if bot_type not in BOT_TYPES:
        raise TournamentError(f"{context}.type: must be one of {sorted(BOT_TYPES)}")
    seed = _req_uint_v1(value.get("seed", 0), f"{context}.seed")
    engine = _req_str_v1(value.get("engine", "any"), f"{context}.engine")
    owner = _req_str_v1(value.get("owner", "unspecified"), f"{context}.owner")
    registered_at = _req_uint_v1(value.get("registered_at", 0), f"{context}.registered_at")
    raw_tags = value.get("training_style_tags", [])
    if not isinstance(raw_tags, list) or any(type(tag) is not str or not tag for tag in raw_tags):
        raise TournamentError(f"{context}.training_style_tags: must be a list of nonempty strings")
    tags = tuple(raw_tags)
    if len(set(tags)) != len(tags):
        raise TournamentError(f"{context}.training_style_tags: duplicate tags")
    command = value.get("command")
    checkpoint = value.get("checkpoint")
    if bot_type == "builtin":
        if name not in _V1_BUILTIN_VERSIONS:
            raise TournamentError(
                f"{context}: unknown builtin bot {name!r} (known: {sorted(_V1_BUILTIN_VERSIONS)})"
            )
        if version != _V1_BUILTIN_VERSIONS[name]:
            raise TournamentError(
                f"{context}: builtin {name!r} is version {_V1_BUILTIN_VERSIONS[name]}, not {version!r}"
            )
        if command is not None or checkpoint is not None:
            raise TournamentError(f"{context}: builtin bots take no command/checkpoint")
        return BotSpec(
            name=name,
            version=version,
            type=bot_type,
            seed=seed,
            engine=engine,
            owner=owner,
            training_style_tags=tags,
            registered_at=registered_at,
        )
    if not isinstance(command, list) or not command or any(type(part) is not str or not part for part in command):
        raise TournamentError(f"{context}.command: subprocess bots require a nonempty command list")
    if checkpoint is not None:
        _req_str_v1(checkpoint, f"{context}.checkpoint")
    return BotSpec(
        name=name,
        version=version,
        type=bot_type,
        seed=seed,
        command=tuple(command),
        checkpoint=checkpoint,
        engine=engine,
        owner=owner,
        training_style_tags=tags,
        registered_at=registered_at,
    )


@dataclass(frozen=True)
class LegacyConfig:
    """The v1 ``TournamentConfig`` (arena/runner.py at 7e9e73f) as ``from_json`` parses it.

    ``from_json`` keeps every check of the original; the dataclass keeps only
    the fields ``manifest_body`` and the schedule read (the tournament
    directory and the engine command are validated, then dropped).
    """

    format: str
    decks: tuple[Deck, Deck] | None  # None when a deck_pool is used
    engine_timeout_ms: int
    bots: tuple[BotSpec, ...]
    pairs_per_matchup: int
    base_seed: int
    max_decisions: int
    max_steps: int
    choose_timeout_ms: int
    bootstrap_replicates: int
    rating_anchor: str  # bot name from the bots list
    workers: int = DEFAULT_WORKERS
    startup_timeout_ms: int = DEFAULT_STARTUP_TIMEOUT_MS
    deck_pool: tuple[Deck, ...] | None = None
    include_self_play: bool = True

    def decks_for_pair(self, pair_index: int) -> tuple[Deck, Deck]:
        """The (p0, p1) decks of both games of pair ``pair_index``."""
        if self.deck_pool is None:
            assert self.decks is not None
            return self.decks
        deck = self.deck_pool[pair_index % len(self.deck_pool)]
        return (deck, deck)

    @classmethod
    def from_json(cls, value: Any) -> "LegacyConfig":
        context = "config"
        if not isinstance(value, dict):
            raise TournamentError("config: must be an object")
        allowed = {
            "schema",
            "tournament_dir",
            "format",
            "decks",
            "engine",
            "bots",
            "pairs_per_matchup",
            "base_seed",
            "max_decisions",
            "max_steps",
            "choose_timeout_ms",
            "bootstrap_replicates",
            "rating_anchor",
            "workers",
            "startup_timeout_ms",
            "deck_pool",
            "include_self_play",
        }
        required = {
            "schema",
            "tournament_dir",
            "format",
            "engine",
            "bots",
            "pairs_per_matchup",
            "base_seed",
        }
        missing = required - set(value)
        extra = set(value) - allowed
        if missing or extra:
            raise TournamentError(
                f"{context}: fields mismatch: missing={sorted(missing)} extra={sorted(extra)}"
            )
        if value["schema"] != CONFIG_SCHEMA_V1:
            raise TournamentError(f'{context}.schema: must be "{CONFIG_SCHEMA_V1}"')
        has_decks, has_pool = "decks" in value, "deck_pool" in value
        if has_decks and has_pool:
            raise TournamentError(f"{context}: give decks or deck_pool, not both")
        if not has_decks and not has_pool:
            raise TournamentError(f"{context}: requires decks (a fixed pair) or deck_pool")
        decks: tuple[Deck, Deck] | None = None
        deck_pool: tuple[Deck, ...] | None = None
        if has_decks:
            raw_decks = value["decks"]
            if not isinstance(raw_decks, list) or len(raw_decks) != 2:
                raise TournamentError(f"{context}.decks: must be a list of two decks (p0 first)")
            try:
                first, second = (
                    Deck.from_json(item, f"{context}.decks[{i}]") for i, item in enumerate(raw_decks)
                )
            except ValidationError as exc:
                raise TournamentError(str(exc)) from exc
            decks = (first, second)
        else:
            raw_pool = value["deck_pool"]
            if not isinstance(raw_pool, list) or not raw_pool:
                raise TournamentError(f"{context}.deck_pool: must be a nonempty list of decks")
            try:
                deck_pool = tuple(
                    Deck.from_json(item, f"{context}.deck_pool[{i}]") for i, item in enumerate(raw_pool)
                )
            except ValidationError as exc:
                raise TournamentError(str(exc)) from exc
            if len(set(deck_pool)) != len(deck_pool):
                raise TournamentError(f"{context}.deck_pool: decks must be distinct")
        _req_str_v1(value["tournament_dir"], f"{context}.tournament_dir")
        format_ = _req_str_v1(value["format"], f"{context}.format")
        raw_engine = value["engine"]
        if not isinstance(raw_engine, dict):
            raise TournamentError(f"{context}.engine: must be an object")
        if set(raw_engine) - {"command", "timeout_ms"} or "command" not in raw_engine:
            raise TournamentError(f"{context}.engine: requires command; optional timeout_ms")
        command = raw_engine["command"]
        if not isinstance(command, list) or not command or any(type(p) is not str or not p for p in command):
            raise TournamentError(f"{context}.engine.command: must be a nonempty list of strings")
        engine_timeout_ms = _req_uint_v1(raw_engine.get("timeout_ms", DEFAULT_ENGINE_TIMEOUT_MS), f"{context}.engine.timeout_ms", minimum=1)
        raw_bots = value["bots"]
        if not isinstance(raw_bots, list) or not raw_bots:
            raise TournamentError(f"{context}.bots: must be a nonempty list")
        bots = tuple(_bot_spec_from_json(item, f"{context}.bots[{i}]") for i, item in enumerate(raw_bots))
        names = [spec.name for spec in bots]
        if len(set(names)) != len(names):
            raise TournamentError(f"{context}.bots: names must be unique, got {names}")
        pairs_per_matchup = _req_uint_v1(value["pairs_per_matchup"], f"{context}.pairs_per_matchup", minimum=1)
        if deck_pool is not None and pairs_per_matchup % len(deck_pool):
            raise TournamentError(
                f"{context}.pairs_per_matchup: {pairs_per_matchup} is not a multiple of the "
                f"{len(deck_pool)} deck_pool decks (every matchup plays every deck equally)"
            )
        include_self_play = value.get("include_self_play", True)
        if type(include_self_play) is not bool:
            raise TournamentError(f"{context}.include_self_play: must be true or false")
        if not include_self_play and len(bots) < 2:
            raise TournamentError(f"{context}.include_self_play: false needs at least two bots")
        base_seed = _req_uint_v1(value["base_seed"], f"{context}.base_seed")
        max_decisions = _req_uint_v1(value.get("max_decisions", DEFAULT_MAX_DECISIONS), f"{context}.max_decisions", minimum=1)
        max_steps = _req_uint_v1(value.get("max_steps", DEFAULT_MAX_STEPS), f"{context}.max_steps", minimum=1)
        choose_timeout_ms = _req_uint_v1(
            value.get("choose_timeout_ms", DEFAULT_CHOOSE_TIMEOUT_MS), f"{context}.choose_timeout_ms", minimum=1
        )
        startup_timeout_ms = _req_uint_v1(
            value.get("startup_timeout_ms", DEFAULT_STARTUP_TIMEOUT_MS), f"{context}.startup_timeout_ms", minimum=1
        )
        bootstrap_replicates = _req_uint_v1(
            value.get("bootstrap_replicates", DEFAULT_BOOTSTRAP_REPLICATES),
            f"{context}.bootstrap_replicates",
            minimum=1_000,
            maximum=100_000,
        )
        rating_anchor = value.get("rating_anchor", bots[0].name)
        _req_str_v1(rating_anchor, f"{context}.rating_anchor")
        if rating_anchor not in names:
            raise TournamentError(f"{context}.rating_anchor: not a configured bot: {rating_anchor!r}")
        workers = _req_uint_v1(
            value.get("workers", DEFAULT_WORKERS), f"{context}.workers", minimum=1, maximum=MAX_WORKERS
        )
        # The leaderboard's bootstraps refuse oversized inputs; refuse such a
        # config now rather than after every game has been played.
        rated_pairs = len(bots) * (len(bots) - 1) // 2 * pairs_per_matchup
        if (
            pairs_per_matchup > ratings.MAX_PAIR_COUNT
            or max(pairs_per_matchup, rated_pairs) * bootstrap_replicates > ratings.MAX_BOOTSTRAP_DRAWS
        ):
            raise TournamentError(
                f"{context}: the bootstrap would draw {max(pairs_per_matchup, rated_pairs) * bootstrap_replicates} "
                f"pairs (limit {ratings.MAX_BOOTSTRAP_DRAWS}, at most {ratings.MAX_PAIR_COUNT} pairs per "
                "matchup); lower bootstrap_replicates or pairs_per_matchup"
            )
        return cls(
            format=format_,
            decks=decks,
            engine_timeout_ms=engine_timeout_ms,
            bots=bots,
            pairs_per_matchup=pairs_per_matchup,
            base_seed=base_seed,
            max_decisions=max_decisions,
            max_steps=max_steps,
            choose_timeout_ms=choose_timeout_ms,
            bootstrap_replicates=bootstrap_replicates,
            rating_anchor=rating_anchor,
            workers=workers,
            startup_timeout_ms=startup_timeout_ms,
            deck_pool=deck_pool,
            include_self_play=include_self_play,
        )


# ---------------------------------------------------------------------------
# Schedule and manifest (from arena/runner.py and arena/bots/uniform.py)
# ---------------------------------------------------------------------------

MASK64 = 0xFFFF_FFFF_FFFF_FFFF
GOLDEN_RATIO_64 = 0x9E37_79B9_7F4A_7C15


class SplitMix64:
    """Ported from mtg-kernel python/mtg_kernel_rl/determinism.py (SplitMix64)."""

    def __init__(self, seed: int) -> None:
        if type(seed) is not int or seed < 0:
            raise ValueError("seed must be a nonnegative integer")
        self.state = seed & MASK64

    def next(self) -> int:
        self.state = (self.state + GOLDEN_RATIO_64) & MASK64
        z = self.state
        z = ((z ^ (z >> 30)) * 0xBF58_476D_1CE4_E5B9) & MASK64
        z = ((z ^ (z >> 27)) * 0x94D0_49BB_1331_11EB) & MASK64
        return (z ^ (z >> 31)) & MASK64


SEED_SCHEDULE_VERSION = "spellbench-arena-seed-v1"
_GAME_SEED_DOMAIN = 0x5350_5F47_414D_4553
_PAIR_SEED_MIXER = 0xD1B5_4A32_D192_ED03


def derive_game_seed(base_seed: int, matchup_index: int, pair_index: int) -> int:
    """The CRN game seed shared by both games of pair (matchup_index, pair_index)."""
    mixed = (
        base_seed
        ^ _GAME_SEED_DOMAIN
        ^ ((matchup_index * GOLDEN_RATIO_64) & MASK64)
        ^ ((pair_index * _PAIR_SEED_MIXER) & MASK64)
    ) & MASK64
    return SplitMix64(mixed).next() & ((1 << 53) - 1)


def matchup_indexes(bot_count: int, *, include_self_play: bool = True) -> list[tuple[int, int]]:
    """Unordered bot-list index pairs in schedule order; mirrors unless self-play is off."""
    return [
        (i, j)
        for i, j in combinations_with_replacement(range(bot_count), 2)
        if include_self_play or i != j
    ]


@dataclass(frozen=True)
class _GameContext:
    game_id: str
    matchup_index: int
    pair_index: int
    game_index: int
    game_seed: int
    seat_specs: tuple[tuple[str, BotSpec], tuple[str, BotSpec]]  # (seat, spec) for p0, p1
    decks: tuple[Deck, Deck]  # (p0, p1)


def _schedule(config: LegacyConfig) -> list[_GameContext]:
    """Every game of the round-robin, in ledger order."""
    schedule: list[_GameContext] = []
    matchups = matchup_indexes(len(config.bots), include_self_play=config.include_self_play)
    for matchup_index, (i, j) in enumerate(matchups):
        for pair_index in range(config.pairs_per_matchup):
            game_seed = derive_game_seed(config.base_seed, matchup_index, pair_index)
            decks = config.decks_for_pair(pair_index)
            for game_index in (0, 1):
                if game_index == 0:
                    seat_specs = (("p0", config.bots[i]), ("p1", config.bots[j]))
                else:
                    seat_specs = (("p0", config.bots[j]), ("p1", config.bots[i]))
                schedule.append(
                    _GameContext(
                        game_id=f"m{matchup_index:04d}p{pair_index:04d}g{game_index}",
                        matchup_index=matchup_index,
                        pair_index=pair_index,
                        game_index=game_index,
                        game_seed=game_seed,
                        seat_specs=seat_specs,
                        decks=decks,
                    )
                )
    return schedule


def manifest_body(
    config: LegacyConfig,
    entries: Sequence[registry.RegistryEntry],
    anchor_bot_id: str,
    engine: dict[str, Any],
    rows: Sequence[LegacyLedgerRow],
    leaderboard_status: str,
) -> dict[str, Any]:
    """Everything in manifest.json except ``files``; ``entries`` in config order.

    ``arena_version`` is ``LEGACY_ARENA_VERSION``, the version that made the
    v1 runs, so the rebuild matches them whatever the package version is.
    """
    counts = {"natural": 0, "truncated": 0, "halted": 0, "forfeit": 0}
    for row in rows:
        counts[row.classification] += 1
    return {
        "schema": TOURNAMENT_SCHEMA_V1,
        "tournament": {
            "format": config.format,
            "base_seed": config.base_seed,
            "pairs_per_matchup": config.pairs_per_matchup,
            "max_decisions": config.max_decisions,
            "max_steps": config.max_steps,
            "choose_timeout_ms": config.choose_timeout_ms,
            "startup_timeout_ms": config.startup_timeout_ms,
            "engine_timeout_ms": config.engine_timeout_ms,
            "bootstrap_replicates": config.bootstrap_replicates,
            "seed_schedule": SEED_SCHEDULE_VERSION,
            "rating_anchor": {"name": config.rating_anchor, "bot_id": anchor_bot_id},
            "arena_version": LEGACY_ARENA_VERSION,
            "workers": config.workers,
            "bots": [entry.to_json() for entry in entries],
        },
        "engine": engine,
        "games": {"total": len(rows), **counts},
        "leaderboard_status": leaderboard_status,
    }


def schedule_mismatches(
    config: LegacyConfig,
    entries_by_name: dict[str, registry.RegistryEntry],
    rows: Sequence[LegacyLedgerRow],
) -> list[str]:
    """Differences between a ledger and the games its config schedules."""
    schedule = _schedule(config)
    if len(rows) != len(schedule):
        return [f"the ledger has {len(rows)} games but the schedule has {len(schedule)}"]
    failures = []
    for index, (ctx, row) in enumerate(zip(schedule, rows)):
        decks = (ctx.decks[0].to_json(), ctx.decks[1].to_json())
        seats = tuple(
            LedgerSeat(
                seat=seat, bot_id=entries_by_name[spec.name].bot_id, name=spec.name, version=spec.version
            )
            for seat, spec in ctx.seat_specs
        )
        scheduled = (ctx.game_id, ctx.matchup_index, ctx.pair_index, ctx.game_index, ctx.game_seed)
        recorded = (row.game_id, row.matchup_index, row.pair_index, row.game_index, row.game_seed)
        if (recorded, row.format, row.seats, row.decks) != (scheduled, config.format, seats, decks):
            failures.append(f"ledger row {index} ({row.game_id}) does not match the schedule")
    return failures


# ---------------------------------------------------------------------------
# Verifying and reading a v1 run
# ---------------------------------------------------------------------------


def _package_version() -> str:
    """The running package version, read at call time (a later release bumps it)."""
    from .. import __version__

    return __version__


def _read_for_comparison(path: Path, failures: list[str]) -> bytes | None:
    """A published file's bytes, or None after recording a failure that names it.

    Not in the 7e9e73f copy: there an unreadable leaderboard file raised
    FileNotFoundError instead of failing closed with a message.
    """
    try:
        return path.read_bytes()
    except OSError:
        failures.append(f"cannot read {path.name} to compare it with a recomputation")
        return None


def validate_v1_run(directory: Path) -> list[str]:
    """Re-verify a published v1 tournament; returns a list of failures (empty = OK).

    Checks (fail closed): manifest presence and schema, the arena version
    that made the run, the sha256/byte count of every data file, ledger row
    schemas, and a byte-exact recomputation of ``leaderboard.json`` and
    ``LEADERBOARD.md`` from the ledger, registry, and config. Leaderboard
    output can change between arena versions, so a run made by any version
    but ``LEGACY_ARENA_VERSION`` gets one failure naming that version and no
    recomputation.
    """
    failures: list[str] = []
    if not store.is_published(directory):
        return [f"{directory} has no manifest.json (not a published tournament)"]
    try:
        manifest = store.read_json(directory / store.MANIFEST_NAME, schema=TOURNAMENT_SCHEMA_V1)
        store.require_keys(
            manifest,
            ["schema", "tournament", "engine", "games", "leaderboard_status", "files"],
            "manifest",
        )
    except (store.StoreError, ValidationError) as exc:
        return [f"manifest: {exc}"]
    # A manifest without a version string fails the manifest checks below.
    tournament = manifest["tournament"]
    made_by = tournament.get("arena_version") if isinstance(tournament, dict) else None
    if type(made_by) is str and made_by != LEGACY_ARENA_VERSION:
        shown = made_by if made_by.isprintable() else repr(made_by)
        return [
            f"this run was made by spellbench arena {shown}; this is {_package_version()}: "
            f"rerun the benchmark, or validate with arena {shown}"
        ]
    files = manifest["files"]
    listed = [entry.get("path") for entry in files if isinstance(entry, dict)] if isinstance(files, list) else None
    if listed != list(store.DATA_FILE_NAMES):
        failures.append(f"manifest files must list exactly {list(store.DATA_FILE_NAMES)}")
    failures.extend(store.verify_file_digests(directory, manifest))
    try:
        # Everything comes from the directory itself: bot ids from the
        # registry (a checkpoint is never re-hashed), the rest re-derived.
        config = LegacyConfig.from_json(
            store.read_json(directory / store.CONFIG_NAME, schema=CONFIG_SCHEMA_V1)
        )
        entries = registry.read_registry(directory / store.REGISTRY_NAME)
        rows = parse_ledger(store.read_jsonl(directory / store.LEDGER_NAME, schema=LEDGER_SCHEMA_V1))
        by_name = {entry.name: entry for entry in entries}
        if sorted(by_name) != sorted(spec.name for spec in config.bots) or len(entries) != len(config.bots):
            return failures + ["registry.json does not hold exactly the configured bots"]
        anchor_bot_id = by_name[config.rating_anchor].bot_id
        failures.extend(schedule_mismatches(config, by_name, rows))
        engine = EngineIdentity.from_json(manifest["engine"], "manifest.engine")
        if any(row.engine != engine.provenance() for row in rows):
            failures.append("ledger engine provenance does not match manifest.engine")
        document, markdown = leaderboard.build_leaderboard(
            rows,
            entries,
            anchor_bot_id=anchor_bot_id,
            base_seed=config.base_seed,
            bootstrap_replicates=config.bootstrap_replicates,
            format=config.format,
        )
        expected_json = store.canonical_bytes(document) + b"\n"
        actual_json = _read_for_comparison(directory / store.LEADERBOARD_JSON_NAME, failures)
        if actual_json is not None and actual_json != expected_json:
            failures.append("leaderboard.json does not match a recomputation from matches.jsonl")
        actual_md = _read_for_comparison(directory / store.LEADERBOARD_MD_NAME, failures)
        if actual_md is not None and actual_md != markdown.encode("utf-8"):
            failures.append("LEADERBOARD.md does not match a recomputation from matches.jsonl")
        expected = manifest_body(
            config,
            [by_name[spec.name] for spec in config.bots],
            anchor_bot_id,
            manifest["engine"],
            rows,
            document["status"],
        )
        for key in ("tournament", "games", "leaderboard_status"):
            if manifest[key] != expected[key]:
                failures.append(f"manifest {key} does not match the tournament data")
    except (store.StoreError, ValidationError, TournamentError, ValueError) as exc:
        failures.append(f"recomputation failed: {exc}")
    return failures


@dataclass(frozen=True)
class LegacyRun:
    """A published v1 run, read for the site."""

    name: str
    config: dict[str, Any]  # config.json as recorded
    engine: dict[str, Any]  # the engine identity from manifest.json
    owners: dict[str, str]  # registry owner by bot name
    board: dict[str, Any]  # leaderboard.json
    deck_labels: tuple[str, ...]  # the pool in order, or the one fixed pairing
    pairs_per_deck: int
    format: str


def _deck_label(deck: Deck) -> str:
    """A deck's catalog id; a decklist gets the leaderboard's label for it."""
    if deck.catalog_id is not None:
        return deck.catalog_id
    return "decklist " + hashlib.sha256(store.canonical_bytes(deck.to_json())).hexdigest()[:12]


def _deck_labels(config: LegacyConfig) -> tuple[str, ...]:
    """The run's decks: the pool in order, or its one fixed pairing ("<p0>" or "<p0> vs <p1>")."""
    if config.deck_pool is not None:
        return tuple(_deck_label(deck) for deck in config.deck_pool)
    assert config.decks is not None
    first, second = config.decks
    return (_deck_label(first) if first == second else f"{_deck_label(first)} vs {_deck_label(second)}",)


def read_v1_run(directory: Path) -> LegacyRun:
    """Read a run that :func:`validate_v1_run` accepted."""
    manifest = store.read_json(directory / store.MANIFEST_NAME, schema=TOURNAMENT_SCHEMA_V1)
    recorded = store.read_json(directory / store.CONFIG_NAME, schema=CONFIG_SCHEMA_V1)
    config = LegacyConfig.from_json(recorded)
    entries = registry.read_registry(directory / store.REGISTRY_NAME)
    return LegacyRun(
        name=directory.name,
        config=recorded,
        engine=manifest["engine"],
        owners={entry.name: entry.owner for entry in entries},
        board=store.read_json(directory / store.LEADERBOARD_JSON_NAME, schema=LEADERBOARD_SCHEMA_V1),
        deck_labels=_deck_labels(config),
        pairs_per_deck=config.pairs_per_matchup // (1 if config.deck_pool is None else len(config.deck_pool)),
        format=config.format,
    )
