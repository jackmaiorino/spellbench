"""Validators and frozen dataclasses for every spellbench/v1 message.

The authority is ``spec/SPELLBENCH_PROTOCOL_V1.md``. Validation fails closed:
anything the spec does not license is rejected with :class:`ValidationError`
(which an agent-role server maps to ``malformed_request``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .errors import ValidationError
from .wire import MAX_JSON_INT, candidates_sha256

PROTOCOL = "spellbench/v1"

U32_MAX = (1 << 32) - 1
U64_MAX = MAX_JSON_INT  # protocol numbers never exceed the IEEE-754 safe range
I32_MIN = -(1 << 31)
I32_MAX = (1 << 31) - 1

SEATS = ("p0", "p1")
ZONES = frozenset({"library", "hand", "battlefield", "graveyard", "stack", "exile", "command"})
PHASE_STEPS = frozenset(
    {
        "untap",
        "upkeep",
        "draw",
        "precombat_main",
        "beginning_of_combat",
        "declare_attackers",
        "declare_blockers",
        "combat_damage",
        "end_of_combat",
        "postcombat_main",
        "end_step",
        "cleanup",
    }
)
MANA_CHOICES = frozenset({"W", "U", "B", "R", "G", "C"})
COLORS = frozenset({"white", "blue", "black", "red", "green"})
CAST_MODES = frozenset({"normal", "alternative"})
OUTCOMES = frozenset({"p0_win", "p1_win", "draw", "truncated", "halted"})
CLASSIFICATIONS = frozenset({"natural", "truncated", "halted"})

EXTENSION_KEY_RE = re.compile(r"^x_[a-z0-9_]+$")
SNAKE_CASE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


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
    maximum: int = MAX_JSON_INT,
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


def _i32(value: Any, context: str) -> int:
    return _int(value, context, minimum=I32_MIN, maximum=I32_MAX)


def _bool(value: Any, context: str) -> bool:
    if type(value) is not bool:
        _fail(context, "must be a bool")
    return value


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


def _protocol_field(value: Any, context: str) -> None:
    if value != PROTOCOL:
        _fail(context, f'protocol must be "{PROTOCOL}"')


def _request_id_field(value: Any, context: str) -> str:
    return _nonempty_str(value, context)


def _game_id_field(value: Any, context: str) -> str:
    return _nonempty_str(value, context)


def _extension_map(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(context, "must be an object")
    for key in value:
        if not EXTENSION_KEY_RE.match(key):
            _fail(context, f"extension key must match x_[a-z0-9_]+: {key!r}")
    return value


def _extension_name_list(value: Any, context: str) -> tuple[str, ...]:
    items = _list(value, context)
    out = []
    for index, item in enumerate(items):
        text = _str(item, f"{context}[{index}]")
        if not EXTENSION_KEY_RE.match(text):
            _fail(f"{context}[{index}]", f"extension name must match x_[a-z0-9_]+: {text!r}")
        out.append(text)
    return tuple(out)


# ---------------------------------------------------------------------------
# Object and target references (spec section 5)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ObjectRef:
    object_id: str
    card_name: str | None
    owner_seat: str
    controller_seat: str
    zone: str

    def __post_init__(self) -> None:
        _nonempty_str(self.object_id, "object_ref.object_id")
        if self.card_name is not None:
            _nonempty_str(self.card_name, "object_ref.card_name")
        _seat(self.owner_seat, "object_ref.owner_seat")
        _seat(self.controller_seat, "object_ref.controller_seat")
        if self.zone not in ZONES:
            _fail("object_ref.zone", f"must be one of {sorted(ZONES)}")

    def to_json(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id,
            "card_name": self.card_name,
            "owner_seat": self.owner_seat,
            "controller_seat": self.controller_seat,
            "zone": self.zone,
        }

    @classmethod
    def from_json(cls, value: Any, context: str = "object_ref") -> "ObjectRef":
        if not isinstance(value, dict):
            _fail(context, "must be an object")
        _keys(value, ["object_id", "card_name", "owner_seat", "controller_seat", "zone"], context)
        return cls(
            object_id=_nonempty_str(value["object_id"], f"{context}.object_id"),
            card_name=(
                None
                if value["card_name"] is None
                else _nonempty_str(value["card_name"], f"{context}.card_name")
            ),
            owner_seat=_seat(value["owner_seat"], f"{context}.owner_seat"),
            controller_seat=_seat(value["controller_seat"], f"{context}.controller_seat"),
            zone=_str(value["zone"], f"{context}.zone"),
        )


@dataclass(frozen=True)
class TargetRef:
    """Exactly one of ``player`` or ``object`` is set (spec section 5)."""

    player: str | None = None
    object: ObjectRef | None = None

    def __post_init__(self) -> None:
        if (self.player is None) == (self.object is None):
            _fail("target_ref", "exactly one of player/object must be set")
        if self.player is not None:
            _seat(self.player, "target_ref.player")

    def to_json(self) -> dict[str, Any]:
        if self.player is not None:
            return {"player": self.player}
        assert self.object is not None
        return {"object": self.object.to_json()}

    @classmethod
    def from_json(cls, value: Any, context: str = "target_ref") -> "TargetRef":
        if not isinstance(value, dict):
            _fail(context, "must be an object")
        if set(value) == {"player"}:
            return cls(player=_seat(value["player"], f"{context}.player"))
        if set(value) == {"object"}:
            return cls(object=ObjectRef.from_json(value["object"], f"{context}.object"))
        _fail(context, "must have exactly one of player/object")


def _target_ref(value: Any, context: str) -> dict[str, Any]:
    TargetRef.from_json(value, context)
    return value


def _object_ref(value: Any, context: str) -> dict[str, Any]:
    ObjectRef.from_json(value, context)
    return value


# ---------------------------------------------------------------------------
# Candidate semantics (spec section 6)
# ---------------------------------------------------------------------------

# Field-name -> field-kind; "kind" itself is always present and is the tag.
_SEMANTIC_FIELDS: dict[str, dict[str, str]] = {
    "pass": {},
    "play_land": {"source": "object_ref"},
    "cast_spell": {"source": "object_ref"},
    "activate_mana_ability": {
        "source": "object_ref",
        "mana_choice": "mana_choice",
        "cost_target": "optional_target_ref",
    },
    "activate_ability": {"source": "object_ref", "ability_index": "u32"},
    "plot_spell": {"source": "object_ref"},
    "choose_target": {"source": "object_ref", "remaining": "u32", "target": "target_ref"},
    "choose_cost_target": {
        "source": "object_ref",
        "cost_kind": "nonempty_str",
        "remaining": "u32",
        "candidate": "object_ref",
    },
    "choose_cast_mode": {"source": "object_ref", "mode": "cast_mode"},
    "choose_kicker": {"source": "object_ref", "pay": "bool"},
    "choose_spell_mode": {"source": "object_ref", "mode_index": "u32", "mode_count": "u32"},
    "choose_option": {"source": "object_ref", "option_index": "u32", "option_count": "u32"},
    "choose_effect_target": {
        "source": "object_ref",
        "target": "target_ref",
        "selected_count": "u32",
        "min_targets": "u32",
        "max_targets": "u32",
    },
    "finish_effect_selection": {"source": "object_ref", "selected_count": "u32"},
    "choose_color": {"source": "object_ref", "color": "color"},
    "choose_number": {"source": "object_ref", "value": "i32", "minimum": "i32", "maximum": "i32"},
    "choose_boolean": {"source": "object_ref", "value": "bool"},
    "finish_target_selection": {"source": "object_ref", "selected_count": "u32"},
    "choose_optional_cost_use": {"use_cost": "bool"},
    "choose_optional_cost_which": {"choice": "snake_str"},
    "choose_spell_copy_payment": {"source": "object_ref", "pay": "bool"},
    "choose_spell_copy_retarget": {"source": "object_ref", "change_target": "bool"},
    "choose_madness_cast": {"card": "object_ref", "cast_it": "bool"},
    "discard": {"cards": "object_ref_array_exactly_one"},
    "choose_attacker_inclusion": {"attacker": "object_ref", "include": "bool"},
    "choose_blocker_inclusion": {"attacker": "object_ref", "blocker": "object_ref", "include": "bool"},
    "order_triggers": {"pending_sources": "object_ref_array", "order": "u32_array"},
}

SEMANTIC_KINDS = frozenset(_SEMANTIC_FIELDS)


def _validate_semantic_field(field_kind: str, value: Any, context: str) -> None:
    if field_kind == "object_ref":
        _object_ref(value, context)
    elif field_kind == "target_ref":
        _target_ref(value, context)
    elif field_kind == "optional_target_ref":
        if value is not None:
            _target_ref(value, context)
    elif field_kind == "u32":
        _u32(value, context)
    elif field_kind == "i32":
        _i32(value, context)
    elif field_kind == "bool":
        _bool(value, context)
    elif field_kind == "nonempty_str":
        _nonempty_str(value, context)
    elif field_kind == "snake_str":
        text = _str(value, context)
        if not SNAKE_CASE_RE.match(text):
            _fail(context, f"must be lowercase snake_case: {text!r}")
    # Type before membership: a JSON list or object is unhashable, and testing
    # it against a frozenset raises TypeError instead of ValidationError.
    elif field_kind == "mana_choice":
        if value is not None and (type(value) is not str or value not in MANA_CHOICES):
            _fail(context, f"must be one of {sorted(MANA_CHOICES)} or null")
    elif field_kind == "cast_mode":
        if type(value) is not str or value not in CAST_MODES:
            _fail(context, f"must be one of {sorted(CAST_MODES)}")
    elif field_kind == "color":
        if type(value) is not str or value not in COLORS:
            _fail(context, f"must be one of {sorted(COLORS)}")
    elif field_kind == "object_ref_array":
        for index, item in enumerate(_list(value, context)):
            _object_ref(item, f"{context}[{index}]")
    elif field_kind == "object_ref_array_exactly_one":
        for index, item in enumerate(_list(value, context, length=1)):
            _object_ref(item, f"{context}[{index}]")
    elif field_kind == "u32_array":
        for index, item in enumerate(_list(value, context)):
            _u32(item, f"{context}[{index}]")
    else:  # pragma: no cover - table bug guard
        raise AssertionError(f"unknown semantic field kind {field_kind}")


def validate_semantic(semantic: Any, context: str = "semantic") -> dict[str, Any]:
    """Validate a candidate ``semantic`` object (spec section 6); returns it."""
    if not isinstance(semantic, dict):
        _fail(context, "must be an object")
    kind = semantic.get("kind")
    if type(kind) is not str or kind not in _SEMANTIC_FIELDS:
        _fail(f"{context}.kind", f"unknown semantic kind: {kind!r}")
    fields = _SEMANTIC_FIELDS[kind]
    _keys(semantic, ["kind", *fields], context)
    for name, field_kind in fields.items():
        _validate_semantic_field(field_kind, semantic[name], f"{context}.{name}")
    if kind == "choose_spell_mode" and semantic["mode_index"] >= semantic["mode_count"]:
        _fail(context, "mode_index must be < mode_count")
    if kind == "choose_option" and semantic["option_index"] >= semantic["option_count"]:
        _fail(context, "option_index must be < option_count")
    if kind == "choose_number" and not semantic["minimum"] <= semantic["value"] <= semantic["maximum"]:
        _fail(context, "value must lie within [minimum, maximum]")
    if kind == "choose_effect_target" and semantic["min_targets"] > semantic["max_targets"]:
        _fail(context, "min_targets must be <= max_targets")
    if kind == "order_triggers":
        order = semantic["order"]
        if sorted(order) != list(range(len(semantic["pending_sources"]))):
            _fail(context, "order must be a permutation of pending_sources indexes")
    return semantic


@dataclass(frozen=True)
class Candidate:
    candidate_id: int
    semantic: dict[str, Any]
    display_text: str | None

    def __post_init__(self) -> None:
        _u32(self.candidate_id, "candidate.candidate_id")
        validate_semantic(self.semantic, "candidate.semantic")
        if self.display_text is not None:
            _str(self.display_text, "candidate.display_text")

    def to_json(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "semantic": self.semantic,
            "display_text": self.display_text,
        }

    @classmethod
    def from_json(cls, value: Any, context: str = "candidate") -> "Candidate":
        if not isinstance(value, dict):
            _fail(context, "must be an object")
        _keys(value, ["candidate_id", "semantic", "display_text"], context)
        semantic = validate_semantic(value["semantic"], f"{context}.semantic")
        display = value["display_text"]
        return cls(
            candidate_id=_u32(value["candidate_id"], f"{context}.candidate_id"),
            semantic=semantic,
            display_text=None if display is None else _str(display, f"{context}.display_text"),
        )


@dataclass(frozen=True)
class Selection:
    candidate_id: int
    semantic_echo: dict[str, Any]

    def __post_init__(self) -> None:
        _u32(self.candidate_id, "selection.candidate_id")
        validate_semantic(self.semantic_echo, "selection.semantic_echo")

    def to_json(self) -> dict[str, Any]:
        return {"candidate_id": self.candidate_id, "semantic_echo": self.semantic_echo}

    @classmethod
    def from_json(cls, value: Any, context: str = "selection") -> "Selection":
        if not isinstance(value, dict):
            _fail(context, "must be an object")
        _keys(value, ["candidate_id", "semantic_echo"], context)
        return cls(
            candidate_id=_u32(value["candidate_id"], f"{context}.candidate_id"),
            semantic_echo=validate_semantic(value["semantic_echo"], f"{context}.semantic_echo"),
        )


# ---------------------------------------------------------------------------
# Decision payloads (spec sections 7.3, 8)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Group:
    group_id: int
    substep_index: int
    substep_count: int

    def __post_init__(self) -> None:
        _u64(self.group_id, "group.group_id")
        _u32(self.substep_index, "group.substep_index")
        _u32(self.substep_count, "group.substep_count")
        if self.substep_count < 1:
            _fail("group.substep_count", "must be >= 1")
        if self.substep_index >= self.substep_count:
            _fail("group", "substep_index must be < substep_count")

    def to_json(self) -> dict[str, Any]:
        return {
            "group_id": self.group_id,
            "substep_index": self.substep_index,
            "substep_count": self.substep_count,
        }

    @classmethod
    def from_json(cls, value: Any, context: str = "group") -> "Group":
        if not isinstance(value, dict):
            _fail(context, "must be an object")
        _keys(value, ["group_id", "substep_index", "substep_count"], context)
        return cls(
            group_id=_u64(value["group_id"], f"{context}.group_id"),
            substep_index=_u32(value["substep_index"], f"{context}.substep_index"),
            substep_count=_u32(value["substep_count"], f"{context}.substep_count"),
        )


@dataclass(frozen=True)
class SeatSummary:
    seat: str
    life: int
    hand_count: int
    library_count: int
    graveyard_count: int
    battlefield_count: int

    def __post_init__(self) -> None:
        _seat(self.seat, "seat_summary.seat")
        _i32(self.life, "seat_summary.life")
        _u32(self.hand_count, "seat_summary.hand_count")
        _u32(self.library_count, "seat_summary.library_count")
        _u32(self.graveyard_count, "seat_summary.graveyard_count")
        _u32(self.battlefield_count, "seat_summary.battlefield_count")

    def to_json(self) -> dict[str, Any]:
        return {
            "seat": self.seat,
            "life": self.life,
            "hand_count": self.hand_count,
            "library_count": self.library_count,
            "graveyard_count": self.graveyard_count,
            "battlefield_count": self.battlefield_count,
        }

    @classmethod
    def from_json(cls, value: Any, context: str = "seat_summary") -> "SeatSummary":
        if not isinstance(value, dict):
            _fail(context, "must be an object")
        _keys(
            value,
            ["seat", "life", "hand_count", "library_count", "graveyard_count", "battlefield_count"],
            context,
        )
        return cls(
            seat=_seat(value["seat"], f"{context}.seat"),
            life=_i32(value["life"], f"{context}.life"),
            hand_count=_u32(value["hand_count"], f"{context}.hand_count"),
            library_count=_u32(value["library_count"], f"{context}.library_count"),
            graveyard_count=_u32(value["graveyard_count"], f"{context}.graveyard_count"),
            battlefield_count=_u32(value["battlefield_count"], f"{context}.battlefield_count"),
        )


@dataclass(frozen=True)
class StateSummary:
    turn: int
    phase_step: str
    active_seat: str
    priority_seat: str
    seats: tuple[SeatSummary, SeatSummary]
    stack_count: int

    def __post_init__(self) -> None:
        _u64(self.turn, "state_summary.turn")
        if self.phase_step not in PHASE_STEPS:
            _fail("state_summary.phase_step", f"must be one of {sorted(PHASE_STEPS)}")
        _seat(self.active_seat, "state_summary.active_seat")
        _seat(self.priority_seat, "state_summary.priority_seat")
        if len(self.seats) != 2 or {seat.seat for seat in self.seats} != set(SEATS):
            _fail("state_summary.seats", "must cover exactly p0 and p1")
        _u32(self.stack_count, "state_summary.stack_count")

    def to_json(self) -> dict[str, Any]:
        return {
            "turn": self.turn,
            "phase_step": self.phase_step,
            "active_seat": self.active_seat,
            "priority_seat": self.priority_seat,
            "seats": [seat.to_json() for seat in self.seats],
            "stack_count": self.stack_count,
        }

    @classmethod
    def from_json(cls, value: Any, context: str = "state_summary") -> "StateSummary":
        if not isinstance(value, dict):
            _fail(context, "must be an object")
        _keys(
            value,
            ["turn", "phase_step", "active_seat", "priority_seat", "seats", "stack_count"],
            context,
        )
        raw_seats = _list(value["seats"], f"{context}.seats", length=2)
        seats = tuple(
            SeatSummary.from_json(item, f"{context}.seats[{index}]") for index, item in enumerate(raw_seats)
        )
        return cls(
            turn=_u64(value["turn"], f"{context}.turn"),
            phase_step=_str(value["phase_step"], f"{context}.phase_step"),
            active_seat=_seat(value["active_seat"], f"{context}.active_seat"),
            priority_seat=_seat(value["priority_seat"], f"{context}.priority_seat"),
            seats=(seats[0], seats[1]),
            stack_count=_u32(value["stack_count"], f"{context}.stack_count"),
        )


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
class Decision:
    """An env-role ``decision`` response; also embedded verbatim in ``choose``."""

    request_id: str
    game_id: str
    step: int
    acting_seat: str
    group: Group
    state_summary: StateSummary
    candidates: tuple[Candidate, ...]
    candidates_sha256: str
    provenance: Provenance
    extensions: dict[str, Any]
    raw: dict[str, Any] | None = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        _request_id_field(self.request_id, "decision.request_id")
        _game_id_field(self.game_id, "decision.game_id")
        _u64(self.step, "decision.step")
        _seat(self.acting_seat, "decision.acting_seat")
        if not self.candidates:
            _fail("decision.candidates", "must be nonempty")
        for index, candidate in enumerate(self.candidates):
            if candidate.candidate_id != index:
                _fail("decision.candidates", "candidate_id values must be dense and ordered")
        if not SHA256_HEX_RE.match(self.candidates_sha256):
            _fail("decision.candidates_sha256", "must be 64 lowercase hex chars")
        computed = candidates_sha256([candidate.to_json() for candidate in self.candidates])
        if self.candidates_sha256 != computed:
            _fail("decision.candidates_sha256", "does not match the candidates' semantic content")
        _extension_map(self.extensions, "decision.extensions")

    def to_json(self) -> dict[str, Any]:
        return {
            "response_type": "decision",
            "protocol": PROTOCOL,
            "request_id": self.request_id,
            "game_id": self.game_id,
            "step": self.step,
            "acting_seat": self.acting_seat,
            "group": self.group.to_json(),
            "state_summary": self.state_summary.to_json(),
            "candidates": [candidate.to_json() for candidate in self.candidates],
            "candidates_sha256": self.candidates_sha256,
            "provenance": self.provenance.to_json(),
            "extensions": self.extensions,
        }

    @classmethod
    def from_json(cls, value: Any, context: str = "decision") -> "Decision":
        if not isinstance(value, dict):
            _fail(context, "must be an object")
        _keys(
            value,
            [
                "response_type",
                "protocol",
                "request_id",
                "game_id",
                "step",
                "acting_seat",
                "group",
                "state_summary",
                "candidates",
                "candidates_sha256",
                "provenance",
                "extensions",
            ],
            context,
        )
        if value["response_type"] != "decision":
            _fail(f"{context}.response_type", 'must be "decision"')
        _protocol_field(value["protocol"], f"{context}.protocol")
        raw_candidates = _list(value["candidates"], f"{context}.candidates", min_length=1)
        candidates = tuple(
            Candidate.from_json(item, f"{context}.candidates[{index}]")
            for index, item in enumerate(raw_candidates)
        )
        return cls(
            request_id=_request_id_field(value["request_id"], f"{context}.request_id"),
            game_id=_game_id_field(value["game_id"], f"{context}.game_id"),
            step=_u64(value["step"], f"{context}.step"),
            acting_seat=_seat(value["acting_seat"], f"{context}.acting_seat"),
            group=Group.from_json(value["group"], f"{context}.group"),
            state_summary=StateSummary.from_json(value["state_summary"], f"{context}.state_summary"),
            candidates=candidates,
            candidates_sha256=_str(value["candidates_sha256"], f"{context}.candidates_sha256"),
            provenance=Provenance.from_json(value["provenance"], f"{context}.provenance"),
            extensions=_extension_map(value["extensions"], f"{context}.extensions"),
            raw=value,
        )


# ---------------------------------------------------------------------------
# Terminal results (spec sections 7.5, 10.4)
# ---------------------------------------------------------------------------

_NATURAL_WINNERS: dict[str, str | None] = {"p0_win": "p0", "p1_win": "p1", "draw": None}


@dataclass(frozen=True)
class TerminalResult:
    outcome: str
    classification: str
    winner: str | None
    reason: str
    step_count: int
    decision_count: int

    def __post_init__(self) -> None:
        if self.outcome not in OUTCOMES:
            _fail("terminal.outcome", f"must be one of {sorted(OUTCOMES)}")
        if self.classification not in CLASSIFICATIONS:
            _fail("terminal.classification", f"must be one of {sorted(CLASSIFICATIONS)}")
        _optional_seat(self.winner, "terminal.winner")
        _nonempty_str(self.reason, "terminal.reason")
        _u64(self.step_count, "terminal.step_count")
        _u64(self.decision_count, "terminal.decision_count")
        if self.classification == "natural":
            if self.outcome not in _NATURAL_WINNERS:
                _fail("terminal", "a natural terminal has outcome p0_win, p1_win, or draw")
            if self.winner != _NATURAL_WINNERS[self.outcome]:
                _fail("terminal", "natural outcome/winner mismatch")
        elif self.outcome != self.classification:
            _fail("terminal", "truncated/halted classification requires the matching outcome")

    def to_json(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "classification": self.classification,
            "winner": self.winner,
            "reason": self.reason,
            "step_count": self.step_count,
            "decision_count": self.decision_count,
        }

    @classmethod
    def from_json(cls, value: Any, context: str = "terminal") -> "TerminalResult":
        if not isinstance(value, dict):
            _fail(context, "must be an object")
        _keys(
            value,
            ["outcome", "classification", "winner", "reason", "step_count", "decision_count"],
            context,
        )
        return cls(
            outcome=_str(value["outcome"], f"{context}.outcome"),
            classification=_str(value["classification"], f"{context}.classification"),
            winner=_optional_seat(value["winner"], f"{context}.winner"),
            reason=_nonempty_str(value["reason"], f"{context}.reason"),
            step_count=_u64(value["step_count"], f"{context}.step_count"),
            decision_count=_u64(value["decision_count"], f"{context}.decision_count"),
        )


@dataclass(frozen=True)
class Terminal:
    """An env-role ``terminal`` response."""

    request_id: str
    game_id: str
    result: TerminalResult
    provenance: Provenance
    raw: dict[str, Any] | None = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        _request_id_field(self.request_id, "terminal.request_id")
        _game_id_field(self.game_id, "terminal.game_id")

    def to_json(self) -> dict[str, Any]:
        return {
            "response_type": "terminal",
            "protocol": PROTOCOL,
            "request_id": self.request_id,
            "game_id": self.game_id,
            **self.result.to_json(),
            "provenance": self.provenance.to_json(),
        }

    @classmethod
    def from_json(cls, value: Any, context: str = "terminal") -> "Terminal":
        if not isinstance(value, dict):
            _fail(context, "must be an object")
        _keys(
            value,
            [
                "response_type",
                "protocol",
                "request_id",
                "game_id",
                "outcome",
                "classification",
                "winner",
                "reason",
                "step_count",
                "decision_count",
                "provenance",
            ],
            context,
        )
        if value["response_type"] != "terminal":
            _fail(f"{context}.response_type", 'must be "terminal"')
        _protocol_field(value["protocol"], f"{context}.protocol")
        return cls(
            request_id=_request_id_field(value["request_id"], f"{context}.request_id"),
            game_id=_game_id_field(value["game_id"], f"{context}.game_id"),
            result=TerminalResult.from_json(
                {
                    "outcome": value["outcome"],
                    "classification": value["classification"],
                    "winner": value["winner"],
                    "reason": value["reason"],
                    "step_count": value["step_count"],
                    "decision_count": value["decision_count"],
                },
                context,
            ),
            provenance=Provenance.from_json(value["provenance"], f"{context}.provenance"),
            raw=value,
        )


# ---------------------------------------------------------------------------
# Decks (spec sections 7.2, 10.2)
# ---------------------------------------------------------------------------


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


@dataclass(frozen=True)
class SeatDeck:
    seat: str
    deck: Deck

    def __post_init__(self) -> None:
        _seat(self.seat, "seat_deck.seat")

    def to_json(self) -> dict[str, Any]:
        return {"seat": self.seat, "deck": self.deck.to_json()}

    @classmethod
    def from_json(cls, value: Any, context: str = "seat_deck") -> "SeatDeck":
        if not isinstance(value, dict):
            _fail(context, "must be an object")
        _keys(value, ["seat", "deck"], context)
        return cls(
            seat=_seat(value["seat"], f"{context}.seat"),
            deck=Deck.from_json(value["deck"], f"{context}.deck"),
        )


# ---------------------------------------------------------------------------
# Envelope messages, both roles (spec sections 4.1, 7, 10)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HelloRequest:
    request_id: str

    def __post_init__(self) -> None:
        _request_id_field(self.request_id, "hello.request_id")

    def to_json(self) -> dict[str, Any]:
        return {"request_type": "hello", "protocol": PROTOCOL, "request_id": self.request_id}

    @classmethod
    def from_json(cls, value: Any, context: str = "hello") -> "HelloRequest":
        _request_keys(value, ["request_type", "protocol", "request_id"], "hello", context)
        return cls(request_id=_request_id_field(value["request_id"], f"{context}.request_id"))


def _request_keys(value: Any, expected: Sequence[str], request_type: str, context: str) -> None:
    if not isinstance(value, dict):
        _fail(context, "must be an object")
    _keys(value, expected, context)
    if value["request_type"] != request_type:
        _fail(f"{context}.request_type", f'must be "{request_type}"')
    _protocol_field(value["protocol"], f"{context}.protocol")


@dataclass(frozen=True)
class ResetRequest:
    request_id: str
    game_id: str
    format: str
    seats: tuple[SeatDeck, SeatDeck]
    game_seed: int
    max_decisions: int
    max_steps: int

    def __post_init__(self) -> None:
        _request_id_field(self.request_id, "reset.request_id")
        _game_id_field(self.game_id, "reset.game_id")
        _nonempty_str(self.format, "reset.format")
        if len(self.seats) != 2 or {seat.seat for seat in self.seats} != set(SEATS):
            _fail("reset.seats", "must cover exactly p0 and p1")
        _u64(self.game_seed, "reset.game_seed")
        _u64(self.max_decisions, "reset.max_decisions")
        _u64(self.max_steps, "reset.max_steps")

    def to_json(self) -> dict[str, Any]:
        return {
            "request_type": "reset",
            "protocol": PROTOCOL,
            "request_id": self.request_id,
            "game_id": self.game_id,
            "format": self.format,
            "seats": [seat.to_json() for seat in self.seats],
            "game_seed": self.game_seed,
            "max_decisions": self.max_decisions,
            "max_steps": self.max_steps,
        }

    @classmethod
    def from_json(cls, value: Any, context: str = "reset") -> "ResetRequest":
        _request_keys(
            value,
            [
                "request_type",
                "protocol",
                "request_id",
                "game_id",
                "format",
                "seats",
                "game_seed",
                "max_decisions",
                "max_steps",
            ],
            "reset",
            context,
        )
        raw_seats = _list(value["seats"], f"{context}.seats", length=2)
        seats = tuple(
            SeatDeck.from_json(item, f"{context}.seats[{index}]") for index, item in enumerate(raw_seats)
        )
        return cls(
            request_id=_request_id_field(value["request_id"], f"{context}.request_id"),
            game_id=_game_id_field(value["game_id"], f"{context}.game_id"),
            format=_nonempty_str(value["format"], f"{context}.format"),
            seats=(seats[0], seats[1]),
            game_seed=_u64(value["game_seed"], f"{context}.game_seed"),
            max_decisions=_u64(value["max_decisions"], f"{context}.max_decisions"),
            max_steps=_u64(value["max_steps"], f"{context}.max_steps"),
        )


@dataclass(frozen=True)
class StepRequest:
    request_id: str
    game_id: str
    expected_step: int
    selection: Selection

    def __post_init__(self) -> None:
        _request_id_field(self.request_id, "step.request_id")
        _game_id_field(self.game_id, "step.game_id")
        _u64(self.expected_step, "step.expected_step")

    def to_json(self) -> dict[str, Any]:
        return {
            "request_type": "step",
            "protocol": PROTOCOL,
            "request_id": self.request_id,
            "game_id": self.game_id,
            "expected_step": self.expected_step,
            "selection": self.selection.to_json(),
        }

    @classmethod
    def from_json(cls, value: Any, context: str = "step") -> "StepRequest":
        _request_keys(
            value,
            ["request_type", "protocol", "request_id", "game_id", "expected_step", "selection"],
            "step",
            context,
        )
        return cls(
            request_id=_request_id_field(value["request_id"], f"{context}.request_id"),
            game_id=_game_id_field(value["game_id"], f"{context}.game_id"),
            expected_step=_u64(value["expected_step"], f"{context}.expected_step"),
            selection=Selection.from_json(value["selection"], f"{context}.selection"),
        )


@dataclass(frozen=True)
class EnvHelloOk:
    request_id: str
    engine: EngineIdentity
    formats: tuple[str, ...]
    decklists_as_data: bool
    extensions: tuple[str, ...]

    def __post_init__(self) -> None:
        _request_id_field(self.request_id, "hello_ok.request_id")
        for index, fmt in enumerate(self.formats):
            _nonempty_str(fmt, f"hello_ok.formats[{index}]")
        _bool(self.decklists_as_data, "hello_ok.capabilities.decklists_as_data")
        for index, extension in enumerate(self.extensions):
            if not EXTENSION_KEY_RE.match(extension):
                _fail("hello_ok.extensions", f"extension name must match x_[a-z0-9_]+: {extension!r}")

    def to_json(self) -> dict[str, Any]:
        return {
            "response_type": "hello_ok",
            "protocol": PROTOCOL,
            "request_id": self.request_id,
            "engine": self.engine.to_json(),
            "formats": list(self.formats),
            "capabilities": {"decklists_as_data": self.decklists_as_data},
            "extensions": list(self.extensions),
        }

    @classmethod
    def from_json(cls, value: Any, context: str = "hello_ok") -> "EnvHelloOk":
        if not isinstance(value, dict):
            _fail(context, "must be an object")
        _keys(
            value,
            ["response_type", "protocol", "request_id", "engine", "formats", "capabilities", "extensions"],
            context,
        )
        if value["response_type"] != "hello_ok":
            _fail(f"{context}.response_type", 'must be "hello_ok"')
        _protocol_field(value["protocol"], f"{context}.protocol")
        capabilities = value["capabilities"]
        if not isinstance(capabilities, dict):
            _fail(f"{context}.capabilities", "must be an object")
        _keys(capabilities, ["decklists_as_data"], f"{context}.capabilities")
        formats = _list(value["formats"], f"{context}.formats")
        return cls(
            request_id=_request_id_field(value["request_id"], f"{context}.request_id"),
            engine=EngineIdentity.from_json(value["engine"], f"{context}.engine"),
            formats=tuple(_nonempty_str(fmt, f"{context}.formats[{index}]") for index, fmt in enumerate(formats)),
            decklists_as_data=_bool(capabilities["decklists_as_data"], f"{context}.capabilities.decklists_as_data"),
            extensions=_extension_name_list(value["extensions"], f"{context}.extensions"),
        )


@dataclass(frozen=True)
class BotIdentity:
    name: str
    version: str

    def __post_init__(self) -> None:
        _nonempty_str(self.name, "bot.name")
        _nonempty_str(self.version, "bot.version")

    def to_json(self) -> dict[str, Any]:
        return {"name": self.name, "version": self.version}

    @classmethod
    def from_json(cls, value: Any, context: str = "bot") -> "BotIdentity":
        if not isinstance(value, dict):
            _fail(context, "must be an object")
        _keys(value, ["name", "version"], context)
        return cls(
            name=_nonempty_str(value["name"], f"{context}.name"),
            version=_nonempty_str(value["version"], f"{context}.version"),
        )


@dataclass(frozen=True)
class AgentHelloOk:
    request_id: str
    bot: BotIdentity
    extensions_accepted: tuple[str, ...]

    def __post_init__(self) -> None:
        _request_id_field(self.request_id, "hello_ok.request_id")
        for extension in self.extensions_accepted:
            if not EXTENSION_KEY_RE.match(extension):
                _fail("hello_ok.extensions_accepted", f"extension name must match x_[a-z0-9_]+: {extension!r}")

    def to_json(self) -> dict[str, Any]:
        return {
            "response_type": "hello_ok",
            "protocol": PROTOCOL,
            "request_id": self.request_id,
            "bot": self.bot.to_json(),
            "extensions_accepted": list(self.extensions_accepted),
        }

    @classmethod
    def from_json(cls, value: Any, context: str = "hello_ok") -> "AgentHelloOk":
        if not isinstance(value, dict):
            _fail(context, "must be an object")
        _keys(value, ["response_type", "protocol", "request_id", "bot", "extensions_accepted"], context)
        if value["response_type"] != "hello_ok":
            _fail(f"{context}.response_type", 'must be "hello_ok"')
        _protocol_field(value["protocol"], f"{context}.protocol")
        return cls(
            request_id=_request_id_field(value["request_id"], f"{context}.request_id"),
            bot=BotIdentity.from_json(value["bot"], f"{context}.bot"),
            extensions_accepted=_extension_name_list(value["extensions_accepted"], f"{context}.extensions_accepted"),
        )


@dataclass(frozen=True)
class GameStartRequest:
    request_id: str
    game_id: str
    seat: str
    format: str
    decks: tuple[Deck, Deck]
    engine: EngineIdentity

    def __post_init__(self) -> None:
        _request_id_field(self.request_id, "game_start.request_id")
        _game_id_field(self.game_id, "game_start.game_id")
        _seat(self.seat, "game_start.seat")
        _nonempty_str(self.format, "game_start.format")
        if len(self.decks) != 2:
            _fail("game_start.decks", "must have exactly two decks, p0 first")

    def to_json(self) -> dict[str, Any]:
        return {
            "request_type": "game_start",
            "protocol": PROTOCOL,
            "request_id": self.request_id,
            "game_id": self.game_id,
            "seat": self.seat,
            "format": self.format,
            "decks": [deck.to_json() for deck in self.decks],
            "engine": self.engine.to_json(),
        }

    @classmethod
    def from_json(cls, value: Any, context: str = "game_start") -> "GameStartRequest":
        _request_keys(
            value,
            ["request_type", "protocol", "request_id", "game_id", "seat", "format", "decks", "engine"],
            "game_start",
            context,
        )
        raw_decks = _list(value["decks"], f"{context}.decks", length=2)
        decks = tuple(Deck.from_json(item, f"{context}.decks[{index}]") for index, item in enumerate(raw_decks))
        return cls(
            request_id=_request_id_field(value["request_id"], f"{context}.request_id"),
            game_id=_game_id_field(value["game_id"], f"{context}.game_id"),
            seat=_seat(value["seat"], f"{context}.seat"),
            format=_nonempty_str(value["format"], f"{context}.format"),
            decks=(decks[0], decks[1]),
            engine=EngineIdentity.from_json(value["engine"], f"{context}.engine"),
        )


@dataclass(frozen=True)
class ChooseRequest:
    request_id: str
    game_id: str
    decision: Decision

    def __post_init__(self) -> None:
        _request_id_field(self.request_id, "choose.request_id")
        _game_id_field(self.game_id, "choose.game_id")

    def to_json(self) -> dict[str, Any]:
        decision = self.decision.raw if self.decision.raw is not None else self.decision.to_json()
        return {
            "request_type": "choose",
            "protocol": PROTOCOL,
            "request_id": self.request_id,
            "game_id": self.game_id,
            "decision": decision,
        }

    @classmethod
    def from_json(cls, value: Any, context: str = "choose") -> "ChooseRequest":
        _request_keys(
            value,
            ["request_type", "protocol", "request_id", "game_id", "decision"],
            "choose",
            context,
        )
        return cls(
            request_id=_request_id_field(value["request_id"], f"{context}.request_id"),
            game_id=_game_id_field(value["game_id"], f"{context}.game_id"),
            decision=Decision.from_json(value["decision"], f"{context}.decision"),
        )


@dataclass(frozen=True)
class GameOverRequest:
    request_id: str
    game_id: str
    terminal: TerminalResult

    def __post_init__(self) -> None:
        _request_id_field(self.request_id, "game_over.request_id")
        _game_id_field(self.game_id, "game_over.game_id")

    def to_json(self) -> dict[str, Any]:
        return {
            "request_type": "game_over",
            "protocol": PROTOCOL,
            "request_id": self.request_id,
            "game_id": self.game_id,
            "terminal": self.terminal.to_json(),
        }

    @classmethod
    def from_json(cls, value: Any, context: str = "game_over") -> "GameOverRequest":
        _request_keys(
            value,
            ["request_type", "protocol", "request_id", "game_id", "terminal"],
            "game_over",
            context,
        )
        return cls(
            request_id=_request_id_field(value["request_id"], f"{context}.request_id"),
            game_id=_game_id_field(value["game_id"], f"{context}.game_id"),
            terminal=TerminalResult.from_json(value["terminal"], f"{context}.terminal"),
        )


@dataclass(frozen=True)
class Ack:
    request_id: str

    def __post_init__(self) -> None:
        _request_id_field(self.request_id, "ack.request_id")

    def to_json(self) -> dict[str, Any]:
        return {"response_type": "ack", "protocol": PROTOCOL, "request_id": self.request_id}

    @classmethod
    def from_json(cls, value: Any, context: str = "ack") -> "Ack":
        if not isinstance(value, dict):
            _fail(context, "must be an object")
        _keys(value, ["response_type", "protocol", "request_id"], context)
        if value["response_type"] != "ack":
            _fail(f"{context}.response_type", 'must be "ack"')
        _protocol_field(value["protocol"], f"{context}.protocol")
        return cls(request_id=_request_id_field(value["request_id"], f"{context}.request_id"))


@dataclass(frozen=True)
class Choice:
    request_id: str
    selection: Selection

    def __post_init__(self) -> None:
        _request_id_field(self.request_id, "choice.request_id")

    def to_json(self) -> dict[str, Any]:
        return {
            "response_type": "choice",
            "protocol": PROTOCOL,
            "request_id": self.request_id,
            "selection": self.selection.to_json(),
        }

    @classmethod
    def from_json(cls, value: Any, context: str = "choice") -> "Choice":
        if not isinstance(value, dict):
            _fail(context, "must be an object")
        _keys(value, ["response_type", "protocol", "request_id", "selection"], context)
        if value["response_type"] != "choice":
            _fail(f"{context}.response_type", 'must be "choice"')
        _protocol_field(value["protocol"], f"{context}.protocol")
        return cls(
            request_id=_request_id_field(value["request_id"], f"{context}.request_id"),
            selection=Selection.from_json(value["selection"], f"{context}.selection"),
        )


@dataclass(frozen=True)
class ErrorResponse:
    request_id: str
    code: str
    message: str

    def __post_init__(self) -> None:
        _str(self.request_id, "error.request_id")
        _nonempty_str(self.code, "error.code")
        _nonempty_str(self.message, "error.message")

    def to_json(self) -> dict[str, Any]:
        return {
            "response_type": "error",
            "protocol": PROTOCOL,
            "request_id": self.request_id,
            "error": {"code": self.code, "message": self.message},
        }

    @classmethod
    def from_json(
        cls,
        value: Any,
        *,
        codes: frozenset[str],
        context: str = "error",
    ) -> "ErrorResponse":
        if not isinstance(value, dict):
            _fail(context, "must be an object")
        _keys(value, ["response_type", "protocol", "request_id", "error"], context)
        if value["response_type"] != "error":
            _fail(f"{context}.response_type", 'must be "error"')
        _protocol_field(value["protocol"], f"{context}.protocol")
        error = value["error"]
        if not isinstance(error, dict):
            _fail(f"{context}.error", "must be an object")
        _keys(error, ["code", "message"], f"{context}.error")
        code = _nonempty_str(error["code"], f"{context}.error.code")
        if code not in codes:
            _fail(f"{context}.error.code", f"unknown error code: {code!r}")
        return cls(
            request_id=_str(value["request_id"], f"{context}.request_id"),
            code=code,
            message=_nonempty_str(error["message"], f"{context}.error.message"),
        )
