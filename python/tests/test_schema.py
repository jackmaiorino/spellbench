"""Shared strict validators of the v2 modules."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from spellbench import _schema as s
from spellbench.errors import ValidationError

BOLT = {"object_id": "o-1a7f3c9e5b2d4801", "card_name": "Lightning Bolt", "owner_seat": "p0",
        "controller_seat": "p0", "zone": "hand"}
SPEC = Path(__file__).resolve().parents[2] / "spec" / "SPELLBENCH_PROTOCOL_V2.md"


def test_object_ref_accepts_the_spec_example_and_a_hidden_name() -> None:
    assert s.object_ref(BOLT, "ref") == BOLT
    assert s.object_ref({**BOLT, "card_name": None}, "ref")["card_name"] is None


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        ({"extra": 1}, "fields mismatch"),
        ({"zone": "deck"}, "zone"),
        ({"owner_seat": "p2"}, "p0 or p1"),
        ({"card_name": "Lim-Du\u0302l's Vault"}, "not in Unicode NFC"),
        ({"object_id": ""}, "nonempty"),
    ],
)
def test_object_ref_rejects(edit: dict, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        s.object_ref({**BOLT, **edit}, "ref")


def test_target_ref_is_exactly_one_of_player_or_object() -> None:
    assert s.target_ref({"player": "p1"}, "t") == {"player": "p1"}
    assert s.target_ref({"object": BOLT}, "t") == {"object": BOLT}
    for bad in ({}, {"player": "p1", "object": BOLT}, {"player": None}):
        with pytest.raises(ValidationError):
            s.target_ref(bad, "t")


def test_integers_check_type_before_range() -> None:
    with pytest.raises(ValidationError, match="integer"):
        s.u32(True, "n")
    with pytest.raises(ValidationError):
        s.u32(1 << 32, "n")
    with pytest.raises(ValidationError):
        s.safe_int(1 << 53, "n")
    with pytest.raises(ValidationError):
        s.safe_int(-1, "n")
    assert s.i32(-(1 << 31), "n") == -(1 << 31)


def test_vocab_rejects_unhashable_values_as_validation_errors() -> None:
    with pytest.raises(ValidationError):
        s.vocab([], frozenset({"red"}), "color")


def _spec_table_names(heading: str) -> tuple[str, ...]:
    """The backticked first cells of the table under a heading of the frozen spec, in order."""
    lines = SPEC.read_text(encoding="utf-8").splitlines()
    start = lines.index(heading) + 1
    end = next(index for index in range(start, len(lines)) if lines[index].startswith("#"))
    return tuple(match.group(1) for line in lines[start:end] if (match := re.match(r"\| `([a-z_]+)` \|", line)))


def test_closed_name_sets() -> None:
    assert len(s.PRIORITY_KINDS) == 6 and len(s.CHOICE_KINDS) == 24 and len(s.V2_KINDS) == 30
    assert s.REQUIRED_KINDS <= s.V2_KINDS and not s.RESERVED_KINDS & s.V2_KINDS
    assert s.OBSERVATION_FLAGS[0] == "poison" and s.OBSERVATION_FLAGS[-1] == "known_cards" and len(s.OBSERVATION_FLAGS) == 13
    assert s.V2_KINDS == frozenset(s.PRIORITY_KINDS + s.CHOICE_KINDS)
    assert s.RESERVED_KINDS == frozenset(_spec_table_names("### 7.7 Reserved kinds")) and len(s.RESERVED_KINDS) == 3
    assert s.REQUIRED_KINDS == {"pass", "play_land", "cast_spell", "declare_attack", "declare_block"}
    assert s.SEATS == ("p0", "p1")
    assert s.ZONES == ("library", "hand", "battlefield", "graveyard", "stack", "exile", "command")
    assert s.REFERENCE_FIELDS == ("object_id", "card_name", "owner_seat", "controller_seat", "zone")
    assert (s.U32_MAX, s.I32_MIN, s.I32_MAX, s.SAFE_INT_MAX) == (2**32 - 1, -(2**31), 2**31 - 1, 2**53 - 1)


@pytest.mark.parametrize(
    ("heading", "names"),
    [
        ("### 7.2 Priority kinds", s.PRIORITY_KINDS),
        ("### 7.3 Choice kinds", s.CHOICE_KINDS),
        ("### 6.9 Optional fields", s.OBSERVATION_FLAGS),
    ],
)
def test_ordered_name_sets_are_the_spec_tables(heading: str, names: tuple[str, ...]) -> None:
    assert _spec_table_names(heading) == names


def test_integer_ranges_are_inclusive() -> None:
    for check, low, high in ((s.u32, 0, s.U32_MAX), (s.i32, s.I32_MIN, s.I32_MAX), (s.safe_int, 0, s.SAFE_INT_MAX)):
        assert check(low, "n") == low and check(high, "n") == high
        for bad in (low - 1, high + 1):
            with pytest.raises(ValidationError, match=r"^n: must be an integer in \["):
                check(bad, "n")


def test_boolean_accepts_only_true_and_false() -> None:
    assert s.boolean(True, "b") is True and s.boolean(False, "b") is False
    for bad in (1, 0, "true", None):
        with pytest.raises(ValidationError, match="^b: must be a boolean"):
            s.boolean(bad, "b")


def test_array_checks_type_and_lengths() -> None:
    assert s.array([1, 2], "a", min_length=2, max_length=2) == [1, 2]
    for value, bounds, message in (
        ((1, 2), {}, "must be an array, got tuple"),
        ([], {"min_length": 1}, "must have at least 1 entries"),
        ([1, 2], {"max_length": 1}, "must have at most 1 entries"),
    ):
        with pytest.raises(ValidationError, match=f"^a: {message}$"):
            s.array(value, "a", **bounds)


def test_exact_keys_names_the_missing_and_extra_fields() -> None:
    s.exact_keys({"a": 1, "b": 2}, ("b", "a"), "o")
    with pytest.raises(ValidationError, match=r"^o: fields mismatch: missing=\['c'\] extra=\['b'\]$"):
        s.exact_keys({"a": 1, "b": 2}, ("a", "c"), "o")


def test_nullable_passes_null_through_and_checks_anything_else() -> None:
    assert s.nullable(None, s.u32, "x") is None
    assert s.nullable(7, s.u32, "x") == 7
    with pytest.raises(ValidationError, match="^x: must be an integer"):
        s.nullable("7", s.u32, "x")


@pytest.mark.parametrize(
    ("key", "valid"),
    [("x_kernel_v5", True), ("x_a", True), ("x_", False), ("x_A", False), ("y_a", False), ("x_a-b", False),
     ("x_a\n", False), (" x_a", False)],
)
def test_extension_key_pattern_matches_whole_keys_only(key: str, valid: bool) -> None:
    assert bool(s.EXTENSION_KEY_RE.match(key)) is valid
    assert bool(s.EXTENSION_KEY_RE.search(key)) is valid


def test_strings_must_encode_as_utf8() -> None:
    # A str can hold a lone surrogate, which no UTF-8 line can carry.
    for check in (s.text, s.nonempty, s.card_name):
        with pytest.raises(ValidationError, match="^t: string contains a lone surrogate"):
            check("Bolt\ud800", "t")


def test_snake_case_and_card_names() -> None:
    assert s.snake("time_lord", "x") == "time_lord"
    with pytest.raises(ValidationError):
        s.snake("Time-Lord", "x")
    assert s.card_name("Lim-D\u00fbl's Vault", "x")
    with pytest.raises(ValidationError, match="NFC"):
        s.card_name("Lim-Du\u0302l's Vault", "x")
