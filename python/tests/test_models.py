from __future__ import annotations

import copy
from typing import Any

import pytest

from spellbench.errors import ENGINE_ERROR_CODES, ValidationError
from spellbench.models import (
    SEMANTIC_KINDS,
    Candidate,
    Decision,
    Deck,
    ErrorResponse,
    GameStartRequest,
    HelloRequest,
    ObjectRef,
    ResetRequest,
    Selection,
    TargetRef,
    TerminalResult,
    validate_semantic,
)

from conftest import OBJ, OBJ2, TEST_ENGINE, VALID_SEMANTICS, make_decision


def test_semantic_kinds_cover_the_spec_table() -> None:
    # spec section 6 lists 27 rows; nothing more, nothing less may validate.
    assert len(SEMANTIC_KINDS) == 27
    assert set(VALID_SEMANTICS) == set(SEMANTIC_KINDS)


@pytest.mark.parametrize("kind", sorted(VALID_SEMANTICS))
def test_valid_semantics_accepted(kind: str) -> None:
    semantic = copy.deepcopy(VALID_SEMANTICS[kind])
    assert validate_semantic(semantic) is semantic
    candidate = Candidate(candidate_id=0, semantic=copy.deepcopy(semantic), display_text="text")
    candidate2 = Candidate.from_json(candidate.to_json())
    assert candidate2.to_json() == candidate.to_json()


def _broken(kind: str, mutate) -> dict[str, Any]:
    semantic = copy.deepcopy(VALID_SEMANTICS[kind])
    mutate(semantic)
    return semantic


@pytest.mark.parametrize("kind", sorted(VALID_SEMANTICS))
def test_semantic_missing_field_rejected(kind: str) -> None:
    fields = [key for key in VALID_SEMANTICS[kind] if key != "kind"]
    if not fields:
        pytest.skip("kind has no extra fields")
    semantic = _broken(kind, lambda s: s.pop(fields[0]))
    with pytest.raises(ValidationError):
        validate_semantic(semantic)


@pytest.mark.parametrize("kind", sorted(VALID_SEMANTICS))
def test_semantic_extra_field_rejected(kind: str) -> None:
    semantic = _broken(kind, lambda s: s.update({"bogus": 1}))
    with pytest.raises(ValidationError):
        validate_semantic(semantic)


@pytest.mark.parametrize(
    "semantic",
    [
        {"kind": "nope"},
        {"kind": "pass", "source": OBJ},
        {"kind": "Pass"},
        {"kind": 1},
        {},
        {"kind": "choose_color", "source": OBJ, "color": "colorless"},
        {"kind": "choose_cast_mode", "source": OBJ, "mode": "weird"},
        {"kind": "activate_mana_ability", "source": OBJ, "mana_choice": "X", "cost_target": None},
        {"kind": "choose_kicker", "source": OBJ, "pay": 1},
        {"kind": "choose_spell_mode", "source": OBJ, "mode_index": 2, "mode_count": 2},
        {"kind": "choose_option", "source": OBJ, "option_index": 3, "option_count": 3},
        {"kind": "choose_number", "source": OBJ, "value": 6, "minimum": 0, "maximum": 5},
        {"kind": "choose_effect_target", "source": OBJ, "target": {"player": "p1"}, "selected_count": 0, "min_targets": 3, "max_targets": 2},
        {"kind": "order_triggers", "pending_sources": [OBJ, OBJ2], "order": [0, 0]},
        {"kind": "order_triggers", "pending_sources": [OBJ, OBJ2], "order": [0, 2]},
        {"kind": "discard", "cards": [OBJ, OBJ2]},
        {"kind": "discard", "cards": []},
        {"kind": "choose_optional_cost_which", "choice": "Discard"},
        {"kind": "choose_optional_cost_which", "choice": ""},
        {"kind": "activate_ability", "source": OBJ, "ability_index": -1},
        {"kind": "choose_number", "source": OBJ, "value": 2**31, "minimum": 0, "maximum": 2**31},
        {"kind": "choose_cost_target", "source": OBJ, "cost_kind": "", "remaining": 0, "candidate": OBJ2},
        {"kind": "choose_target", "source": OBJ, "remaining": 0, "target": {"player": "p2"}},
    ],
)
def test_invalid_semantics_rejected(semantic: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        validate_semantic(semantic)


@pytest.mark.parametrize("bad", [[], {}], ids=["list", "dict"])
@pytest.mark.parametrize(
    ("kind", "name"),
    [("activate_mana_ability", "mana_choice"), ("choose_cast_mode", "mode"), ("choose_color", "color")],
)
def test_enum_fields_reject_unhashable_values(kind: str, name: str, bad: Any) -> None:
    # A JSON list or object is unhashable: a set membership test on it raises
    # TypeError, which the clients do not map to a protocol error.
    semantic = _broken(kind, lambda s: s.update({name: bad}))
    with pytest.raises(ValidationError, match=name):
        validate_semantic(semantic)
    with pytest.raises(ValidationError, match=name):
        Selection.from_json({"candidate_id": 0, "semantic_echo": semantic})


def test_mana_choice_may_be_null() -> None:
    semantic = _broken("activate_mana_ability", lambda s: s.update({"mana_choice": None}))
    assert validate_semantic(semantic) is semantic


def test_object_ref_round_trip() -> None:
    ref = ObjectRef.from_json(OBJ)
    assert ref.to_json() == OBJ
    hidden = {**OBJ, "card_name": None}
    assert ObjectRef.from_json(hidden).card_name is None


@pytest.mark.parametrize(
    "value",
    [
        {**OBJ, "zone": "sideboard"},
        {**OBJ, "extra": 1},
        {k: v for k, v in OBJ.items() if k != "zone"},
        {**OBJ, "object_id": ""},
        {**OBJ, "owner_seat": "p2"},
        {**OBJ, "card_name": 7},
    ],
)
def test_object_ref_rejected(value: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ObjectRef.from_json(value)


def test_target_ref_exactly_one_kind() -> None:
    assert TargetRef.from_json({"player": "p1"}).player == "p1"
    assert TargetRef.from_json({"object": OBJ}).object is not None
    with pytest.raises(ValidationError):
        TargetRef.from_json({})
    with pytest.raises(ValidationError):
        TargetRef.from_json({"player": "p1", "object": OBJ})


def _decision_json(**overrides: Any) -> dict[str, Any]:
    message = make_decision("h-2").to_json()
    message.update(overrides)
    return message


def test_decision_round_trip_and_hash_verified() -> None:
    decision = Decision.from_json(_decision_json())
    assert decision.to_json() == _decision_json()
    assert decision.raw is not None


def test_decision_sha_tamper_rejected() -> None:
    message = _decision_json(candidates_sha256="0" * 64)
    with pytest.raises(ValidationError):
        Decision.from_json(message)


def test_decision_non_dense_candidates_rejected() -> None:
    message = _decision_json(
        candidates=[{"candidate_id": 1, "semantic": {"kind": "pass"}, "display_text": None}],
        candidates_sha256="0" * 64,
    )
    with pytest.raises(ValidationError):
        Decision.from_json(message)


def test_decision_empty_candidates_rejected() -> None:
    message = _decision_json(candidates=[], candidates_sha256="0" * 64)
    with pytest.raises(ValidationError):
        Decision.from_json(message)


def test_decision_extensions_key_pattern() -> None:
    good = make_decision("h-2", extensions={"x_kernel_v5": {"raw": 1}}).to_json()
    assert Decision.from_json(good).extensions == {"x_kernel_v5": {"raw": 1}}
    bad = _decision_json(extensions={"not_an_extension": 1})
    with pytest.raises(ValidationError):
        Decision.from_json(bad)


def test_decision_unknown_top_level_field_rejected() -> None:
    message = _decision_json(unknown_field=1)
    with pytest.raises(ValidationError):
        Decision.from_json(message)


@pytest.mark.parametrize(
    "result",
    [
        TerminalResult(outcome="p0_win", classification="natural", winner="p0", reason="r", step_count=1, decision_count=1),
        TerminalResult(outcome="draw", classification="natural", winner=None, reason="r", step_count=0, decision_count=0),
        TerminalResult(outcome="truncated", classification="truncated", winner=None, reason="r", step_count=9, decision_count=9),
        TerminalResult(outcome="halted", classification="halted", winner="p1", reason="r", step_count=9, decision_count=9),
    ],
)
def test_terminal_result_consistency_ok(result: TerminalResult) -> None:
    assert TerminalResult.from_json(result.to_json()) == result


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(outcome="p0_win", classification="natural", winner=None),
        dict(outcome="p0_win", classification="natural", winner="p1"),
        dict(outcome="draw", classification="natural", winner="p0"),
        dict(outcome="p0_win", classification="truncated", winner="p0"),
        dict(outcome="truncated", classification="natural", winner=None),
        dict(outcome="halted", classification="truncated", winner=None),
        dict(outcome="p2_win", classification="natural", winner=None),
        dict(outcome="draw", classification="natural", winner=None, reason=""),
    ],
)
def test_terminal_result_inconsistent_rejected(kwargs: dict[str, Any]) -> None:
    base = dict(outcome="draw", classification="natural", winner=None, reason="r", step_count=0, decision_count=0)
    base.update(kwargs)
    with pytest.raises(ValidationError):
        TerminalResult(**base)


def test_deck_exactly_one_form() -> None:
    assert Deck.from_json({"catalog_id": "Burn"}).catalog_id == "Burn"
    rows = {"decklist": [{"name": "Island", "count": 20}]}
    assert Deck.from_json(rows).decklist is not None
    for bad in ({}, {"catalog_id": "Burn", "decklist": []}, {"decklist": []}, {"catalog_id": ""}, {"decklist": [{"name": "Island", "count": 0}]}):
        with pytest.raises(ValidationError):
            Deck.from_json(bad)


def test_reset_request_round_trip_and_seats() -> None:
    request = ResetRequest(
        request_id="h-2",
        game_id="g",
        format="pauper-bo1",
        seats=make_seats(),
        game_seed=1,
        max_decisions=10,
        max_steps=100,
    )
    assert ResetRequest.from_json(request.to_json()) == request
    bad = request.to_json()
    bad["seats"] = [bad["seats"][0], bad["seats"][0]]
    with pytest.raises(ValidationError):
        ResetRequest.from_json(bad)


def make_seats():
    from spellbench.models import SeatDeck

    return (
        SeatDeck(seat="p0", deck=Deck(catalog_id="Burn")),
        SeatDeck(seat="p1", deck=Deck(catalog_id="Burn")),
    )


def test_game_start_round_trip() -> None:
    from spellbench.models import GameStartRequest as GSR

    request = GSR(
        request_id="h-2",
        game_id="g",
        seat="p0",
        format="pauper-bo1",
        decks=(Deck(catalog_id="Burn"), Deck(catalog_id="Burn")),
        engine=TEST_ENGINE,
    )
    assert GSR.from_json(request.to_json()) == request


def test_hello_request_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        HelloRequest.from_json({"request_type": "hello", "protocol": "spellbench/v1", "request_id": "h-1", "extra": 1})


def test_hello_request_protocol_checked() -> None:
    with pytest.raises(ValidationError):
        HelloRequest.from_json({"request_type": "hello", "protocol": "spellbench/v2", "request_id": "h-1"})


def test_selection_requires_valid_semantic_echo() -> None:
    with pytest.raises(ValidationError):
        Selection(candidate_id=0, semantic_echo={"kind": "bogus"})


def test_error_response_closed_code_set() -> None:
    error = ErrorResponse(request_id="h-1", code="malformed_json", message="bad")
    parsed = ErrorResponse.from_json(error.to_json(), codes=ENGINE_ERROR_CODES)
    assert parsed.code == "malformed_json"
    bad = error.to_json()
    bad["error"] = {"code": "not_a_code", "message": "m"}
    with pytest.raises(ValidationError):
        ErrorResponse.from_json(bad, codes=ENGINE_ERROR_CODES)


def test_models_reject_x_keys_outside_extension_points() -> None:
    message = make_decision("h-2").to_json()
    message["state_summary"]["x_sneaky"] = 1
    with pytest.raises(ValidationError):
        Decision.from_json(message)
    message = make_decision("h-2").to_json()
    message["x_top"] = 1
    with pytest.raises(ValidationError):
        Decision.from_json(message)
