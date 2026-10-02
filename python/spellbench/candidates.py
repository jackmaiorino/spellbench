"""Candidate semantics: the 30 v2.0 decision kinds, their vocabularies and constraints (spec 7).

A candidate is ``{"candidate_id", "semantic", "display_text"}`` (spec 7.1). Its ``semantic`` is a
tagged object: ``kind`` plus exactly the fields that kind lists, all required, nullable ones sent
as an explicit ``null`` (spec 4.2, 7.2, 7.3). A kind outside v2.0, a value outside its vocabulary
(spec 6.10, 7.4) or a broken field constraint (spec 7.3) raises ``errors.ValidationError``, which
strict receivers answer with ``malformed_request``. The kind name sets live in ``_schema`` and are
re-exported here.
"""

from __future__ import annotations

import operator
from typing import Any, Callable, Mapping

from ._schema import (  # the kind name sets are re-exported
    CHOICE_KINDS,
    PRIORITY_KINDS,
    REQUIRED_KINDS,
    RESERVED_KINDS,
    V2_KINDS,
    array,
    as_object,
    boolean,
    card_name,
    exact_keys,
    fail,
    i32,
    name_hidden_with_source,
    nonempty,
    nullable,
    object_ref,
    quoted,
    seat,
    snake,
    target_ref,
    text,
    u32,
    vocab,
)

# Spec 7.1: an engine whose decision would exceed this many candidates ends the game halted.
MAX_CANDIDATES = 4096

# Spec 7.4, in table order. Each purpose list ends in "other".
SELECT_PURPOSES = (
    "discard",
    "sacrifice",
    "exile",
    "destroy",
    "return_to_hand",
    "search",
    "reveal",
    "put_onto_battlefield",
    "put_into_hand",
    "put_into_graveyard",
    "legend_rule",
    "tap",
    "untap",
    "delve",
    "convoke",
    "attach",
    "keep",
    "vote",
    "modes",
    "other",
)
BOOLEAN_PURPOSES = ("may_ability", "optional_trigger", "may_cast", "change_copy_targets", "optional_replacement", "reveal", "other")
NUMBER_PURPOSES = ("x_value", "amount", "life_payment", "cost_repetitions", "vote", "other")
OPTION_PURPOSES = ("effect_option", "top_or_bottom", "odd_or_even", "vote", "other")
COLOR_PURPOSES = ("mana", "protection", "effect", "other")
NAME_PURPOSES = ("card_name", "creature_type", "card_type", "land_type", "basic_land_type", "other")
ORDER_PURPOSES = ("triggers", "library_top", "library_bottom", "mulligan_bottom", "arrangement", "other")
ARRANGE_PURPOSES = ("scry", "surveil", "dig", "look_at_top", "pile_split", "other")
ARRANGE_DESTINATIONS = ("top", "bottom", "graveyard", "exile", "hand", "battlefield", "pile_0", "pile_1")
DISTRIBUTE_PURPOSES = ("damage", "combat_damage", "counters", "mana", "life", "other")
PILE_PURPOSES = ("effect", "other")
# The method of cast_spell, choose_cast_method and optional_cast.
CAST_METHODS = (
    "normal",
    "alternative",
    "flashback",
    "escape",
    "evoke",
    "overload",
    "adventure",
    "disturb",
    "foretell",
    "plot",
    "mdfc_back",
    "split_left",
    "split_right",
    "fuse",
    "prototype",
    "morph",
    "disguise",
    "madness",
    "miracle",
    "cascade",
    "discover",
    "rebound",
    "suspend",
    "free",
    "other",
)
OPTIONAL_COSTS = (
    "kicker",
    "buyback",
    "entwine",
    "conspire",
    "casualty",
    "bargain",
    "gift",
    "offspring",
    "copy",
    "unless_payment",
    "additional",
    "other",
)
COST_KINDS = ("sacrifice", "discard", "exile", "tap", "untap", "return_to_hand", "reveal", "remove_counter", "other")
SPECIAL_ACTIONS = ("turn_face_up", "plot", "foretell", "suspend", "unlock_door", "other")
REPLACEMENT_EVENTS = ("zone_change", "damage", "draw", "enter_battlefield", "counters", "life", "other")
# Spec 6.10.
COLORS = ("white", "blue", "black", "red", "green")
MANA_SYMBOLS = ("W", "U", "B", "R", "G", "C")

# The fields of each kind in spec table order (spec 7.2, 7.3), the whole contract. Field kinds:
# "R" an object reference, "T" a target reference, a "?" suffix allowing null; "u32", "i32",
# "bool", "seat"; "str" a nonempty string, "str?" a string or null; "snake" an open snake_case
# value; ("vocab", values) and ("vocab?", values); "item" an order_pick item; "piles" two piles.
_FIELDS: dict[str, dict[str, Any]] = {
    "pass": {},
    "play_land": {"source": "R", "face": "u32"},
    "cast_spell": {"source": "R", "method": ("vocab?", CAST_METHODS)},
    "activate_mana_ability": {"source": "R", "ability_index": "u32", "mana_choice": ("vocab?", MANA_SYMBOLS), "cost_target": "T?"},
    "activate_ability": {"source": "R", "ability_index": "u32"},
    "special_action": {"source": "R", "action": ("vocab", SPECIAL_ACTIONS)},
    "choose_target": {"source": "R", "slot": "u32", "target": "T", "selected_count": "u32", "minimum": "u32", "maximum": "u32"},
    "finish_target_selection": {"source": "R", "slot": "u32", "selected_count": "u32"},
    "choose_cost_target": {"source": "R", "cost_kind": ("vocab", COST_KINDS), "candidate": "R", "selected_count": "u32", "minimum": "u32", "maximum": "u32"},
    "choose_cast_method": {"source": "R", "method": ("vocab", CAST_METHODS)},
    "choose_spell_mode": {"source": "R", "mode_index": "u32", "mode_count": "u32", "selected_count": "u32", "minimum": "u32", "maximum": "u32"},
    "choose_option": {"source": "R?", "purpose": ("vocab", OPTION_PURPOSES), "option_index": "u32", "option_count": "u32", "option_label": "str?"},
    "choose_color": {"source": "R?", "purpose": ("vocab", COLOR_PURPOSES), "color": ("vocab", COLORS)},
    "choose_number": {"source": "R?", "purpose": ("vocab", NUMBER_PURPOSES), "value": "i32", "minimum": "i32", "maximum": "i32"},
    "choose_boolean": {"source": "R?", "purpose": ("vocab", BOOLEAN_PURPOSES), "value": "bool"},
    "choose_name": {"source": "R?", "purpose": ("vocab", NAME_PURPOSES), "value": "str"},
    "select_object": {"source": "R?", "purpose": ("vocab", SELECT_PURPOSES), "choice": "T", "selected_count": "u32", "minimum": "u32", "maximum": "u32"},
    "finish_selection": {"source": "R?", "purpose": ("vocab", SELECT_PURPOSES), "selected_count": "u32"},
    "optional_cost": {"source": "R", "cost": ("vocab", OPTIONAL_COSTS), "pay": "bool"},
    "choose_cost_option": {"source": "R", "choice": "snake"},
    "optional_cast": {"card": "R", "method": ("vocab", CAST_METHODS), "cast_it": "bool"},
    "mulligan": {"hand_size": "u32", "mulligans_taken": "u32", "keep": "bool"},
    "order_pick": {"source": "R?", "purpose": ("vocab", ORDER_PURPOSES), "item": "item", "position": "u32", "count": "u32"},
    "arrange_card": {"source": "R?", "purpose": ("vocab", ARRANGE_PURPOSES), "card": "R", "card_index": "u32", "card_count": "u32", "destination": ("vocab", ARRANGE_DESTINATIONS)},
    "choose_replacement": {"affected": "T", "event": ("vocab", REPLACEMENT_EVENTS), "replacement_source": "R?", "replacement_index": "u32", "replacement_count": "u32"},
    "choose_starting_player": {"player": "seat"},
    "declare_attack": {"attacker": "R", "defender": "T?"},
    "declare_block": {"blocker": "R", "attacker": "R?"},
    "distribute": {"source": "R?", "purpose": ("vocab", DISTRIBUTE_PURPOSES), "recipient": "T", "amount": "u32", "remaining": "u32"},
    "choose_pile": {"source": "R?", "purpose": ("vocab", PILE_PURPOSES), "pile_index": "u32", "piles": "piles"},
}

# Spec 7.3 field constraints as (left, operator, right); an operand is a field name or a constant.
# choose_pile's "piles has exactly two arrays" is part of its "piles" field kind.
_CONSTRAINTS: dict[str, tuple[tuple[str | int, str, str | int], ...]] = {
    "choose_target": (("minimum", "<=", "maximum"), ("selected_count", "<", "maximum")),
    "choose_cost_target": (("minimum", "<=", "maximum"), ("selected_count", "<", "maximum")),
    "select_object": (("minimum", "<=", "maximum"), ("selected_count", "<", "maximum")),
    "choose_spell_mode": (
        ("mode_index", "<", "mode_count"),
        ("minimum", "<=", "maximum"),
        ("maximum", "<=", "mode_count"),
        ("selected_count", "<", "maximum"),
    ),
    "choose_option": (("option_index", "<", "option_count"),),
    "choose_number": (("minimum", "<=", "value"), ("value", "<=", "maximum")),
    "order_pick": (("position", "<", "count"),),
    "arrange_card": (("card_index", "<", "card_count"),),
    "choose_replacement": ((2, "<=", "replacement_count"), ("replacement_index", "<", "replacement_count")),
    "distribute": (("amount", "<=", "remaining"),),
    "choose_pile": (("pile_index", "<=", 1),),   # a u32, so 0 or 1
}
_COMPARE = {"<": operator.lt, "<=": operator.le}

_CANDIDATE_FIELDS = ("candidate_id", "semantic", "display_text")
# Spec 7.3: the trigger form of an order_pick item.
_TRIGGER_FIELDS = ("source", "source_name", "ability_index", "event_objects", "instance", "label")


def _order_item(value: Any, context: str) -> dict[str, Any]:
    """Exactly ``{"object": R}`` or ``{"trigger": {...}}`` (spec 7.3)."""
    item = as_object(value, context)
    if item.keys() == {"object"}:
        object_ref(item["object"], f"{context}.object")
    elif item.keys() == {"trigger"}:
        where = f"{context}.trigger"
        trigger = as_object(item["trigger"], where)
        exact_keys(trigger, _TRIGGER_FIELDS, where)
        source = nullable(trigger["source"], object_ref, f"{where}.source")
        source_name = nullable(trigger["source_name"], card_name, f"{where}.source_name")
        name_hidden_with_source(source, source_name, f"{where}.source_name")   # as a pending trigger (spec 5.1, 6.8)
        nullable(trigger["ability_index"], u32, f"{where}.ability_index")
        for index, event_object in enumerate(array(trigger["event_objects"], f"{where}.event_objects")):
            object_ref(event_object, f"{where}.event_objects[{index}]")
        u32(trigger["instance"], f"{where}.instance")
        nullable(trigger["label"], text, f"{where}.label")
    else:
        fail(context, f"must be exactly one of object or trigger, got fields {sorted(item)}")
    return item


def _piles(value: Any, context: str) -> list[Any]:
    """Exactly two arrays of object references (spec 7.3); a pile may be empty."""
    piles = array(value, context, min_length=2, max_length=2)
    for index, pile in enumerate(piles):
        for position, member in enumerate(array(pile, f"{context}[{index}]")):
            object_ref(member, f"{context}[{index}][{position}]")
    return piles


_CHECKS: dict[str, Callable[[Any, str], Any]] = {
    "R": object_ref,
    "R?": lambda value, context: nullable(value, object_ref, context),
    "T": target_ref,
    "T?": lambda value, context: nullable(value, target_ref, context),
    "u32": u32,
    "i32": i32,
    "bool": boolean,
    "seat": seat,
    "str": nonempty,
    "str?": lambda value, context: nullable(value, text, context),
    "snake": snake,
    "item": _order_item,
    "piles": _piles,
}


def _check_field(value: Any, field_kind: Any, context: str) -> None:
    if isinstance(field_kind, tuple):
        tag, allowed = field_kind
        if not (tag == "vocab?" and value is None):
            vocab(value, allowed, context)
    else:
        _CHECKS[field_kind](value, context)


def _fields(kind: Any, context: str) -> dict[str, Any]:
    """The field table of a v2.0 kind; any other kind fails, and a reserved one says so (spec 7.7)."""
    fields = _FIELDS.get(text(kind, context))
    if fields is None:
        if kind in RESERVED_KINDS:
            fail(context, f"{quoted(kind)} is a reserved kind (not in v2.0)")
        fail(context, f"{quoted(kind)} is an unknown kind")
    return fields


def validate_semantic(semantic: Any, context: str = "semantic") -> dict:
    """Check a candidate semantic and return it unchanged (spec 6.10, 7.2 to 7.4).

    Checks ``kind`` and exactly its fields, each field's type and vocabulary in spec table order,
    then the spec 7.3 field constraints. ``context`` starts every error message, for example
    ``"seat_decision.candidates[3].semantic"``.
    """
    value = as_object(semantic, context)
    if "kind" not in value:
        fail(context, "missing field kind")
    kind = value["kind"]
    fields = _fields(kind, f"{context}.kind")
    exact_keys(value, ("kind", *fields), context)
    for name, field_kind in fields.items():
        _check_field(value[name], field_kind, f"{context}.{name}")
    for left, op, right in _CONSTRAINTS.get(kind, ()):
        left_value = value[left] if isinstance(left, str) else left
        right_value = value[right] if isinstance(right, str) else right
        if not _COMPARE[op](left_value, right_value):
            fail(context, f"{kind} requires {left} {op} {right}, but {left_value} {op} {right_value} is false")
    return value


def validate_candidate(value: Any, context: str = "candidate") -> dict:
    """Check ``{"candidate_id", "semantic", "display_text"}`` and return it unchanged (spec 7.1).

    That ``candidate_id`` equals the candidate's index is a property of the whole list, which the
    host's V1 check enforces.
    """
    candidate = as_object(value, context)
    exact_keys(candidate, _CANDIDATE_FIELDS, context)
    u32(candidate["candidate_id"], f"{context}.candidate_id")
    validate_semantic(candidate["semantic"], f"{context}.semantic")
    nullable(candidate["display_text"], text, f"{context}.display_text")
    return candidate


def family(kind: str) -> str:
    """The family of a v2.0 kind, which is the ``context.kind`` of a decision offering it.

    ``"priority"`` for the spec 7.2 kinds, ``"choice"`` for the spec 7.3 kinds.
    """
    _fields(kind, "kind")
    return "priority" if kind in PRIORITY_KINDS else "choice"


def object_references(semantic: Mapping[str, Any]) -> list[tuple[str, dict]]:
    """Every non-null object reference of a valid semantic with its path, depth first in sorted key order.

    Paths are relative to the semantic, for example ``"source"``, ``"target.object"``,
    ``"item.trigger.event_objects[0]"`` or ``"piles[1][0]"``. The host checks each reference
    against the observation (spec 5.1) and orders hidden-zone candidates by them (spec 7.1).
    """
    fields = _fields(semantic["kind"], "semantic.kind")
    found: list[tuple[str, dict]] = []
    for name in sorted(fields):
        value, field_kind = semantic[name], fields[name]
        if value is None:
            continue
        if field_kind in ("R", "R?"):
            found.append((name, value))
        elif field_kind in ("T", "T?", "item") and "object" in value:
            found.append((f"{name}.object", value["object"]))
        elif field_kind == "item":
            trigger = value["trigger"]   # its keys in sorted order: event_objects comes before source
            found += [(f"{name}.trigger.event_objects[{index}]", ref) for index, ref in enumerate(trigger["event_objects"])]
            if trigger["source"] is not None:
                found.append((f"{name}.trigger.source", trigger["source"]))
        elif field_kind == "piles":
            found += [(f"{name}[{index}][{position}]", ref) for index, pile in enumerate(value) for position, ref in enumerate(pile)]
    return found
