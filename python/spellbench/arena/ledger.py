"""Match ledger rows v2: ``matches.jsonl``, one row per scheduled game (spec 9.5, 11.5, 11.8).

Published ratings are re-derived from these rows, so a row is checked in full
when it is built, and ``to_json`` writes back exactly the object ``from_json``
read: the same keys, the seats p0 then p1, and each adjudication kind's own
key set.

Rated rows (spec 11.5) are ``natural`` terminals, the host's mandatory-loop
draws included, and ``forfeit`` games. ``truncated`` and ``halted`` rows are
recorded and excluded from ratings; ``last_selection`` names the seat and
entry whose selection preceded the halt or truncation.

Each class takes an init-only ``context``, the path its errors start with.
``from_json`` passes its own, so an error in a parsed ledger names the row and
the field, for example ``ledger[12].adjudication.loser_seat``.
"""

from __future__ import annotations

import re
from dataclasses import InitVar, dataclass
from typing import Any, Iterable

from .. import _schema
from .store import require_keys

LEDGER_SCHEMA = "spellbench-match-ledger/v2"
# Spec 11.5.
FORFEIT_CAUSES = frozenset(
    {"timeout", "stalling", "malformed_response", "invalid_selection", "agent_error", "transport_error"}
)
# The engine faults the host halts a game for, with reason "host_engine_fault:<fault>" (spec 11.5, Decision 4).
ENGINE_FAULTS = ("error", "timeout", "transport", "malformed", "terminal_counts")

_OUTCOMES = ("p0_win", "p1_win", "draw", "truncated", "halted")
_CLASSIFICATIONS = ("natural", "forfeit", "truncated", "halted")
# Spec 9.5: a natural terminal pairs p0_win with p0, p1_win with p1, and draw with null.
_WINNERS = {"p0_win": "p0", "p1_win": "p1", "draw": None}
# R1-14: each adjudication kind has its own exact key set.
_ADJUDICATION_KEYS = {
    "forfeit": ("kind", "cause", "loser_seat", "detail"),
    "halt": ("kind", "detail"),
    "mandatory_loop": ("kind", "detail"),
}
_ADJUDICATION_KINDS = tuple(_ADJUDICATION_KEYS)
# A host halt's reason: a live-validation violation of rule V1 to V10 (spec 11.3), or an engine fault.
_HOST_HALT_REASONS = frozenset(
    [f"host_validator:V{rule}" for rule in range(1, 11)] + [f"host_engine_fault:{fault}" for fault in ENGINE_FAULTS]
)
_GAME_DIGEST_RE = re.compile(r"\Asha256:[0-9a-f]{64}\Z")
_ENGINE_KEYS = ("engine_name", "engine_version", "rules_snapshot_id", "card_pool_identity")
_ROW_KEYS = (
    "schema",
    "game_index",
    "game_id",
    "matchup_index",
    "pair_index",
    "pair_slot",
    "format",
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
    "decisions_checked",
    "last_selection",
    "game_digest",
    "engine",
)


def _check_pair(value: Any, kind: type, context: str) -> None:
    if not isinstance(value, tuple) or len(value) != 2 or not all(isinstance(item, kind) for item in value):
        _schema.fail(context, f"must be a tuple of two {kind.__name__}")


def _check_optional(value: Any, kind: type, context: str) -> None:
    if value is not None and not isinstance(value, kind):
        _schema.fail(context, f"must be a {kind.__name__} or None")


@dataclass(frozen=True)
class LedgerSeat:
    """A seat and the entry that played it."""

    seat: str
    bot_id: str
    name: str
    version: str
    context: InitVar[str] = "ledger_seat"

    def __post_init__(self, context: str) -> None:
        _schema.seat(self.seat, f"{context}.seat")
        _schema.nonempty(self.bot_id, f"{context}.bot_id")
        _schema.nonempty(self.name, f"{context}.name")
        _schema.nonempty(self.version, f"{context}.version")

    def to_json(self) -> dict[str, Any]:
        return {"seat": self.seat, "bot_id": self.bot_id, "name": self.name, "version": self.version}

    @classmethod
    def from_json(cls, value: Any, context: str = "ledger_seat") -> LedgerSeat:
        require_keys(_schema.as_object(value, context), ("seat", "bot_id", "name", "version"), context)
        return cls(
            seat=value["seat"], bot_id=value["bot_id"], name=value["name"], version=value["version"], context=context
        )


@dataclass(frozen=True)
class LedgerDeck:
    """A seat's deck: the host-computed ``deck_id``, its name, and its catalog id (None for a decklist deck)."""

    deck_id: str
    name: str
    catalog_id: str | None
    context: InitVar[str] = "ledger_deck"

    def __post_init__(self, context: str) -> None:
        _schema.nonempty(self.deck_id, f"{context}.deck_id")
        _schema.nonempty(self.name, f"{context}.name")
        _schema.nullable(self.catalog_id, _schema.nonempty, f"{context}.catalog_id")

    def to_json(self) -> dict[str, Any]:
        return {"deck_id": self.deck_id, "name": self.name, "catalog_id": self.catalog_id}

    @classmethod
    def from_json(cls, value: Any, context: str = "ledger_deck") -> LedgerDeck:
        require_keys(_schema.as_object(value, context), ("deck_id", "name", "catalog_id"), context)
        return cls(deck_id=value["deck_id"], name=value["name"], catalog_id=value["catalog_id"], context=context)


@dataclass(frozen=True)
class Adjudication:
    """An ending the host records itself (spec 11.5), which the game digest also chains (spec 11.8).

    ``forfeit`` (in a ``forfeit`` row) names its ``cause`` and the ``loser_seat``.
    ``halt`` (in a ``halted`` row: a live-validation violation or an engine
    fault) and ``mandatory_loop`` (a ``natural`` draw at a seat cap, spec 11.4)
    carry only the ``detail``: their ``cause`` and ``loser_seat`` are None and
    never written.
    """

    kind: str
    detail: str
    cause: str | None = None
    loser_seat: str | None = None
    context: InitVar[str] = "adjudication"

    def __post_init__(self, context: str) -> None:
        _schema.vocab(self.kind, _ADJUDICATION_KINDS, f"{context}.kind")
        _schema.nonempty(self.detail, f"{context}.detail")
        if self.kind == "forfeit":
            _schema.vocab(self.cause, FORFEIT_CAUSES, f"{context}.cause")
            _schema.seat(self.loser_seat, f"{context}.loser_seat")
        elif self.cause is not None or self.loser_seat is not None:
            _schema.fail(context, f"a {self.kind} adjudication has no cause and no loser_seat")

    def to_json(self) -> dict[str, Any]:
        if self.kind == "forfeit":
            return {"kind": self.kind, "cause": self.cause, "loser_seat": self.loser_seat, "detail": self.detail}
        return {"kind": self.kind, "detail": self.detail}

    @classmethod
    def from_json(cls, value: Any, context: str = "adjudication") -> Adjudication:
        kind = _schema.vocab(_schema.as_object(value, context).get("kind"), _ADJUDICATION_KINDS, f"{context}.kind")
        require_keys(value, _ADJUDICATION_KEYS[kind], context)
        return cls(
            kind=kind,
            detail=value["detail"],
            cause=value.get("cause"),
            loser_seat=value.get("loser_seat"),
            context=context,
        )


@dataclass(frozen=True)
class LastSelection:
    """The seat and entry whose selection immediately preceded a halt or a truncation (spec 11.5)."""

    seat: str
    bot_id: str
    context: InitVar[str] = "last_selection"

    def __post_init__(self, context: str) -> None:
        _schema.seat(self.seat, f"{context}.seat")
        _schema.nonempty(self.bot_id, f"{context}.bot_id")

    def to_json(self) -> dict[str, Any]:
        return {"seat": self.seat, "bot_id": self.bot_id}

    @classmethod
    def from_json(cls, value: Any, context: str = "last_selection") -> LastSelection:
        require_keys(_schema.as_object(value, context), ("seat", "bot_id"), context)
        return cls(seat=value["seat"], bot_id=value["bot_id"], context=context)


@dataclass(frozen=True)
class LedgerRow:
    """One game of the schedule and its result.

    ``game_index`` is the game's 0-based position in the run's schedule (spec
    11.6), and ``pair_slot`` its place, 0 or 1, in its seat-swapped pair. The
    seats are p0 then p1, and ``decks[i]`` is the deck of ``seats[i]``.
    ``step_count`` and ``decision_count`` count the answered decisions and the
    completed groups (spec 8, 9.5; Decisions 4 and 5); ``decisions_checked``
    counts the seat decisions the live validator checked (spec 11.3), which is
    one more than ``step_count`` when the game ended at a decision that was
    checked but never answered. ``game_digest`` is the chain of spec 11.8, and
    ``engine`` the engine's four provenance fields (spec 9.3).
    """

    game_index: int
    game_id: str
    matchup_index: int
    pair_index: int
    pair_slot: int
    format: str
    seats: tuple[LedgerSeat, LedgerSeat]
    decks: tuple[LedgerDeck, LedgerDeck]
    outcome: str
    classification: str
    winner: str | None
    winner_bot_id: str | None
    reason: str
    adjudication: Adjudication | None
    step_count: int
    decision_count: int
    decisions_checked: int
    last_selection: LastSelection | None
    game_digest: str
    engine: dict[str, str]
    context: InitVar[str] = "ledger"

    def __post_init__(self, context: str) -> None:
        _schema.safe_int(self.game_index, f"{context}.game_index")
        _schema.nonempty(self.game_id, f"{context}.game_id")
        _schema.safe_int(self.matchup_index, f"{context}.matchup_index")
        _schema.safe_int(self.pair_index, f"{context}.pair_index")
        if type(self.pair_slot) is not int or self.pair_slot not in (0, 1):
            _schema.fail(f"{context}.pair_slot", "must be 0 or 1")
        _schema.nonempty(self.format, f"{context}.format")
        _check_pair(self.seats, LedgerSeat, f"{context}.seats")
        if tuple(entry.seat for entry in self.seats) != _schema.SEATS:
            _schema.fail(f"{context}.seats", "must be p0 then p1")
        _check_pair(self.decks, LedgerDeck, f"{context}.decks")
        _schema.vocab(self.outcome, _OUTCOMES, f"{context}.outcome")
        _schema.vocab(self.classification, _CLASSIFICATIONS, f"{context}.classification")
        _schema.nullable(self.winner, _schema.seat, f"{context}.winner")
        _schema.nullable(self.winner_bot_id, _schema.nonempty, f"{context}.winner_bot_id")
        _schema.nonempty(self.reason, f"{context}.reason")
        _check_optional(self.adjudication, Adjudication, f"{context}.adjudication")
        for name in ("step_count", "decision_count", "decisions_checked"):
            _schema.safe_int(getattr(self, name), f"{context}.{name}")
        if not self.step_count <= self.decisions_checked <= self.step_count + 1:
            _schema.fail(
                f"{context}.decisions_checked",
                f"must be step_count ({self.step_count}) or one more, got {self.decisions_checked}",
            )
        _check_optional(self.last_selection, LastSelection, f"{context}.last_selection")
        if not _GAME_DIGEST_RE.fullmatch(_schema.text(self.game_digest, f"{context}.game_digest")):
            _schema.fail(f"{context}.game_digest", "must be sha256: followed by 64 lowercase hex digits")
        require_keys(_schema.as_object(self.engine, f"{context}.engine"), _ENGINE_KEYS, f"{context}.engine")
        for key in _ENGINE_KEYS:
            _schema.nonempty(self.engine[key], f"{context}.engine.{key}")
        self._check_result(context)
        self._check_attribution(context)

    def _check_result(self, context: str) -> None:
        """Outcome, winner, adjudication and reason by classification (spec 9.5, 11.3, 11.4, 11.5)."""
        kind = None if self.adjudication is None else self.adjudication.kind
        if self.classification in ("truncated", "halted"):
            if self.outcome != self.classification:
                _schema.fail(f"{context}.outcome", f"a {self.classification} row has outcome {self.classification}")
            if self.winner is not None:
                _schema.fail(f"{context}.winner", f"a {self.classification} row has winner null")
            if kind is None:
                return  # the engine's own terminal, with its own reason
            if self.classification == "truncated":
                _schema.fail(f"{context}.adjudication", "a truncated row has no adjudication")
            if kind != "halt":
                _schema.fail(f"{context}.adjudication", "a halted row's adjudication is a halt")
            if self.reason not in _HOST_HALT_REASONS:
                _schema.fail(
                    f"{context}.reason",
                    f"a host halt is host_validator:V1 to V10 or host_engine_fault:<fault>, got {self.reason!r}",
                )
            return
        # natural or forfeit: outcome and winner paired as in spec 9.5.
        outcomes = ("p0_win", "p1_win", "draw") if self.classification == "natural" else ("p0_win", "p1_win")
        if self.outcome not in outcomes:
            _schema.fail(f"{context}.outcome", f"a {self.classification} row is {' or '.join(outcomes)}")
        if self.winner != _WINNERS[self.outcome]:
            _schema.fail(f"{context}.winner", f"a {self.outcome} row has winner {_WINNERS[self.outcome] or 'null'}")
        if self.classification == "natural":
            if kind not in (None, "mandatory_loop"):
                _schema.fail(f"{context}.adjudication", "a natural row has no adjudication, or a mandatory_loop one")
            if kind == "mandatory_loop" and (self.outcome, self.reason) != ("draw", "mandatory_loop"):
                _schema.fail(f"{context}.adjudication", "a mandatory_loop adjudication ends a draw, reason mandatory_loop")
            return
        if kind != "forfeit":
            _schema.fail(f"{context}.adjudication", "a forfeit row has a forfeit adjudication")
        if self.adjudication.loser_seat == self.winner:
            _schema.fail(f"{context}.adjudication.loser_seat", "must be the seat that did not win")
        if self.reason != f"forfeit:{self.adjudication.cause}":
            _schema.fail(f"{context}.reason", f"must be 'forfeit:{self.adjudication.cause}', got {self.reason!r}")

    def _check_attribution(self, context: str) -> None:
        """``winner_bot_id`` and ``last_selection`` name the entries at their seats (spec 11.5)."""
        expected = None if self.winner is None else self.bot_id_at(self.winner)
        if self.winner_bot_id != expected:
            detail = "must be null without a winner" if expected is None else f"must be the bot at {self.winner}"
            _schema.fail(f"{context}.winner_bot_id", detail)
        if self.last_selection is not None:
            if self.classification not in ("truncated", "halted"):
                _schema.fail(f"{context}.last_selection", "only a truncated or halted row has a last selection")
            if self.last_selection.bot_id != self.bot_id_at(self.last_selection.seat):
                _schema.fail(f"{context}.last_selection.bot_id", f"must be the bot at {self.last_selection.seat}")

    @property
    def rated(self) -> bool:
        """Natural terminals, mandatory-loop draws included, and forfeits enter ratings (spec 11.5)."""
        return self.classification in ("natural", "forfeit")

    def bot_id_at(self, seat: str) -> str:
        for entry in self.seats:
            if entry.seat == seat:
                return entry.bot_id
        raise KeyError(seat)

    def to_json(self) -> dict[str, Any]:
        return {
            "schema": LEDGER_SCHEMA,
            "game_index": self.game_index,
            "game_id": self.game_id,
            "matchup_index": self.matchup_index,
            "pair_index": self.pair_index,
            "pair_slot": self.pair_slot,
            "format": self.format,
            "seats": [entry.to_json() for entry in self.seats],  # p0 then p1, so sorted by seat
            "decks": [deck.to_json() for deck in self.decks],
            "outcome": self.outcome,
            "classification": self.classification,
            "winner": self.winner,
            "winner_bot_id": self.winner_bot_id,
            "reason": self.reason,
            "adjudication": None if self.adjudication is None else self.adjudication.to_json(),
            "step_count": self.step_count,
            "decision_count": self.decision_count,
            "decisions_checked": self.decisions_checked,
            "last_selection": None if self.last_selection is None else self.last_selection.to_json(),
            "game_digest": self.game_digest,
            "engine": dict(self.engine),
        }

    @classmethod
    def from_json(cls, value: Any, context: str = "ledger") -> LedgerRow:
        row = _schema.as_object(value, context)
        require_keys(row, _ROW_KEYS, context)
        if row["schema"] != LEDGER_SCHEMA:
            _schema.fail(f"{context}.schema", f"must be {LEDGER_SCHEMA!r}")
        seats = _schema.array(row["seats"], f"{context}.seats", min_length=2, max_length=2)
        decks = _schema.array(row["decks"], f"{context}.decks", min_length=2, max_length=2)
        return cls(
            game_index=row["game_index"],
            game_id=row["game_id"],
            matchup_index=row["matchup_index"],
            pair_index=row["pair_index"],
            pair_slot=row["pair_slot"],
            format=row["format"],
            seats=tuple(LedgerSeat.from_json(entry, f"{context}.seats[{index}]") for index, entry in enumerate(seats)),
            decks=tuple(LedgerDeck.from_json(entry, f"{context}.decks[{index}]") for index, entry in enumerate(decks)),
            outcome=row["outcome"],
            classification=row["classification"],
            winner=row["winner"],
            winner_bot_id=row["winner_bot_id"],
            reason=row["reason"],
            adjudication=_schema.nullable(row["adjudication"], Adjudication.from_json, f"{context}.adjudication"),
            step_count=row["step_count"],
            decision_count=row["decision_count"],
            decisions_checked=row["decisions_checked"],
            last_selection=_schema.nullable(
                row["last_selection"], LastSelection.from_json, f"{context}.last_selection"
            ),
            game_digest=row["game_digest"],
            engine=dict(_schema.as_object(row["engine"], f"{context}.engine")),
            context=context,
        )


def parse_ledger(rows: Iterable[dict[str, Any]]) -> tuple[LedgerRow, ...]:
    """Parse ledger rows in order; an error names its row as ``ledger[<i>]``."""
    return tuple(LedgerRow.from_json(row, f"ledger[{index}]") for index, row in enumerate(rows))
