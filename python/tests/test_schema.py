"""Shared strict validators of the v2 modules."""

from __future__ import annotations

import pytest

from spellbench import _schema as s
from spellbench.errors import ValidationError

BOLT = {"object_id": "o-1a7f3c9e5b2d4801", "card_name": "Lightning Bolt", "owner_seat": "p0",
        "controller_seat": "p0", "zone": "hand"}


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


def test_closed_name_sets() -> None:
    assert len(s.PRIORITY_KINDS) == 6 and len(s.CHOICE_KINDS) == 24 and len(s.V2_KINDS) == 30
    assert s.REQUIRED_KINDS <= s.V2_KINDS and not s.RESERVED_KINDS & s.V2_KINDS
    assert s.OBSERVATION_FLAGS[0] == "poison" and s.OBSERVATION_FLAGS[-1] == "known_cards" and len(s.OBSERVATION_FLAGS) == 13


def test_snake_case_and_card_names() -> None:
    assert s.snake("time_lord", "x") == "time_lord"
    with pytest.raises(ValidationError):
        s.snake("Time-Lord", "x")
    assert s.card_name("Lim-D\u00fbl's Vault", "x")
    with pytest.raises(ValidationError, match="NFC"):
        s.card_name("Lim-Du\u0302l's Vault", "x")
