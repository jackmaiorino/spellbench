"""Shared strict validators and the closed name sets of protocol v2 (spec 4.4, 5, 6.9, 7).

The name sets here are the single source of truth; ``candidates`` and
``observation`` re-export them. Every validator checks the Python type first
(``type(value) is int``, so ``True`` is never an integer, and nothing is
tested for membership before it is known to be a string) and raises
``errors.ValidationError("<context>: <detail>")``, which strict receivers
answer with ``malformed_request``.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Callable, Collection, Iterable, Mapping, NoReturn, TypeVar

from .errors import ValidationError
from .wire import MAX_JSON_INT

_T = TypeVar("_T")

# Spec 7.2, table order.
PRIORITY_KINDS = ("pass", "play_land", "cast_spell", "activate_mana_ability", "activate_ability", "special_action")
# Spec 7.3, table order.
CHOICE_KINDS = (
    "choose_target",
    "finish_target_selection",
    "choose_cost_target",
    "choose_cast_method",
    "choose_spell_mode",
    "choose_option",
    "choose_color",
    "choose_number",
    "choose_boolean",
    "choose_name",
    "select_object",
    "finish_selection",
    "optional_cost",
    "choose_cost_option",
    "optional_cast",
    "mulligan",
    "order_pick",
    "arrange_card",
    "choose_replacement",
    "choose_starting_player",
    "declare_attack",
    "declare_block",
    "distribute",
    "choose_pile",
)
V2_KINDS = frozenset(PRIORITY_KINDS + CHOICE_KINDS)
# Spec 7.7: specified for a later minor version; v2.0 engines never emit them.
RESERVED_KINDS = frozenset({"pay_mana", "narrow_name", "narrow_number"})
# Spec 9.1: every engine's hello_ok.decision_kinds includes these.
REQUIRED_KINDS = frozenset({"pass", "play_land", "cast_spell", "declare_attack", "declare_block"})
# Spec 6.9, table order.
OBSERVATION_FLAGS = (
    "poison",
    "player_counters",
    "designations",
    "player_progress",
    "day_night",
    "passed_seats",
    "pending_triggers",
    "keywords",
    "full_name",
    "exiled_by",
    "stack_text",
    "permanent_details",
    "known_cards",
)

# Spec 4.4.
U32_MAX = (1 << 32) - 1
I32_MIN = -(1 << 31)
I32_MAX = (1 << 31) - 1
SAFE_INT_MAX = MAX_JSON_INT
SEATS = ("p0", "p1")
# Spec 5.1.
ZONES = ("library", "hand", "battlefield", "graveyard", "stack", "exile", "command")
REFERENCE_FIELDS = ("object_id", "card_name", "owner_seat", "controller_seat", "zone")
# Anchored with \A and \Z, not ^ and $ (which also matches before a trailing
# newline), so match(), search() and fullmatch() all check the whole string.
SNAKE_CASE_RE = re.compile(r"\A[a-z][a-z0-9_]*\Z")
EXTENSION_KEY_RE = re.compile(r"\Ax_[a-z0-9_]+\Z")


def fail(context: str, detail: str) -> NoReturn:
    raise ValidationError(f"{context}: {detail}")


def as_object(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(context, f"must be an object, got {type(value).__name__}")
    return value


def exact_keys(value: Mapping[str, Any], expected: Iterable[str], context: str) -> None:
    """Every listed field is present and no other (spec 4.2)."""
    expected_set = set(expected)
    actual = set(value)
    missing = expected_set - actual
    extra = actual - expected_set
    if missing or extra:
        fail(context, f"fields mismatch: missing={sorted(missing)} extra={sorted(extra)}")


def _integer(value: Any, context: str, minimum: int, maximum: int) -> int:
    if type(value) is not int:
        fail(context, f"must be an integer, got {type(value).__name__}")
    if not minimum <= value <= maximum:
        fail(context, f"must be an integer in [{minimum}, {maximum}]")
    return value


def safe_int(value: Any, context: str) -> int:
    """A non-negative counter or identifier: an integer in [0, 2^53 - 1] (spec 4.4)."""
    return _integer(value, context, 0, SAFE_INT_MAX)


def u32(value: Any, context: str) -> int:
    """An index, count or amount (spec 4.4)."""
    return _integer(value, context, 0, U32_MAX)


def i32(value: Any, context: str) -> int:
    """A life total, power, toughness or choose_number value (spec 4.4)."""
    return _integer(value, context, I32_MIN, I32_MAX)


def boolean(value: Any, context: str) -> bool:
    if type(value) is not bool:
        fail(context, f"must be a boolean, got {type(value).__name__}")
    return value


def text(value: Any, context: str) -> str:
    if type(value) is not str:
        fail(context, f"must be a string, got {type(value).__name__}")
    return value


def nonempty(value: Any, context: str) -> str:
    if not text(value, context):
        fail(context, "must be a nonempty string")
    return value


def nullable(value: Any, check: Callable[[Any, str], _T], context: str) -> _T | None:
    """``None``, or a value ``check`` accepts (spec 4.2: a nullable field is an explicit null)."""
    return None if value is None else check(value, context)


def array(value: Any, context: str, *, min_length: int = 0, max_length: int | None = None) -> list[Any]:
    if not isinstance(value, list):
        fail(context, f"must be an array, got {type(value).__name__}")
    if len(value) < min_length:
        fail(context, f"must have at least {min_length} entries")
    if max_length is not None and len(value) > max_length:
        fail(context, f"must have at most {max_length} entries")
    return value


def seat(value: Any, context: str) -> str:
    if text(value, context) not in SEATS:
        fail(context, f"must be p0 or p1, got {value!r}")
    return value


def vocab(value: Any, allowed: Collection[str], context: str) -> str:
    """A string from a closed vocabulary (the message lists it sorted, so it is deterministic)."""
    if text(value, context) not in allowed:
        fail(context, f"{value!r} is not one of {', '.join(sorted(allowed))}")
    return value


def snake(value: Any, context: str) -> str:
    """A lowercase snake_case value, ``[a-z][a-z0-9_]*`` (spec 4.4)."""
    if not SNAKE_CASE_RE.fullmatch(text(value, context)):
        fail(context, f"{value!r} is not lowercase snake_case")
    return value


def card_name(value: Any, context: str) -> str:
    """A nonempty card name in Unicode NFC (spec 4.4)."""
    if not unicodedata.is_normalized("NFC", nonempty(value, context)):
        fail(context, f"card name {value!r} is not in Unicode NFC")
    return value


def object_ref(value: Any, context: str) -> dict[str, Any]:
    """An object reference (spec 5.1); returns the input dict."""
    reference = as_object(value, context)
    exact_keys(reference, REFERENCE_FIELDS, context)
    nonempty(reference["object_id"], f"{context}.object_id")
    nullable(reference["card_name"], card_name, f"{context}.card_name")
    seat(reference["owner_seat"], f"{context}.owner_seat")
    seat(reference["controller_seat"], f"{context}.controller_seat")
    vocab(reference["zone"], ZONES, f"{context}.zone")
    return reference


def target_ref(value: Any, context: str) -> dict[str, Any]:
    """Exactly ``{"player": seat}`` or ``{"object": object reference}`` (spec 5.2); returns the input dict."""
    target = as_object(value, context)
    if target.keys() == {"player"}:
        seat(target["player"], f"{context}.player")
    elif target.keys() == {"object"}:
        object_ref(target["object"], f"{context}.object")
    else:
        fail(context, f"must be exactly one of player or object, got fields {sorted(target)}")
    return target
