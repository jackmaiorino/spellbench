"""Engine-role messages: the spec examples parse and round-trip exactly (spec 9)."""

from __future__ import annotations

import copy

import pytest

from spellbench.errors import ValidationError
from spellbench.messages import (
    ENGINE_ERROR_CODES, Decision, EnvHelloOk, ErrorResponse, Limits, ResetRequest, Rules, StepRequest, Terminal, TimeControl,
    CardNameDomain, DeckOk, DeckRow, EngineProfile, HelloRequest, Resources, ValidateDeckRequest, WireDeck,
)

BURN_ID = "sha256:0df0a001e3c4b74b1061b21e319a645f32fbe3173120e432864e14d6d6f2f5d2"
DOMAIN = {"domain_id": "sha256:74f7f4b39eecbed1c039cf4b229fa533069d2cdd8caf3bb6380b832eb40fb697", "names": ["Lightning Bolt", "Mountain"]}
ENGINE = {"name": "mtg-kernel", "version": "0.0.5", "source_revision": None, "rules_snapshot_id": "opaque engine string",
          "card_pool_identity": "opaque engine string"}
PROVENANCE = {"engine_name": "mtg-kernel", "engine_version": "0.0.5", "rules_snapshot_id": "opaque engine string",
              "card_pool_identity": "opaque engine string"}
FLAGS = {"poison": False, "player_counters": False, "designations": True, "player_progress": False, "day_night": False,
         "passed_seats": True, "pending_triggers": True, "keywords": True, "full_name": False, "exiled_by": True,
         "stack_text": False, "permanent_details": True, "known_cards": True}
HELLO_OK = {  # spec 9.1, verbatim
    "response_type": "hello_ok", "protocol": "spellbench/v2", "request_id": "h-1", "protocol_minor": 0, "engine": ENGINE,
    "formats": ["pauper-bo1"], "deck_sources": ["catalog"],
    "catalog": [{"catalog_id": "Burn", "name": "Burn", "decklist": [{"name": "Lightning Bolt", "count": 4}, {"name": "Mountain", "count": 18}]}],
    "rules_supported": {"mulligan": ["none"], "starting_player": ["host_assigned"]}, "observation": FLAGS,
    "decision_kinds": ["pass", "play_land", "cast_spell", "activate_mana_ability", "activate_ability", "special_action",
                       "choose_target", "finish_target_selection", "choose_cost_target", "choose_cast_method", "choose_spell_mode",
                       "choose_option", "choose_color", "choose_number", "choose_boolean", "select_object", "finish_selection",
                       "optional_cost", "choose_cost_option", "optional_cast", "order_pick", "arrange_card", "declare_attack", "declare_block"],
    "engine_defaults": {"trigger_order": None, "replacement_order": None, "combat_damage_assignment": "engine_order", "mana_payment": None},
    "rewind": False, "fairness": {"noninterference_probe": False}, "extensions": [{"name": "x_kernel_v5", "native_ids": True}],
}
RULES = {"opponent_decklist": "visible", "mulligan": "none", "starting_player": "host_assigned", "starting_seat": "p0",
         "card_name_domain": DOMAIN, "extensions": [], "probe": False}
RESET = {  # spec 9.2, verbatim
    "request_type": "reset", "protocol": "spellbench/v2", "request_id": "h-2", "game_id": "g-f67d7fe78c792984", "format": "pauper-bo1",
    "seats": [{"seat": "p0", "deck": {"deck_id": BURN_ID, "catalog_id": "Burn"}}, {"seat": "p1", "deck": {"deck_id": BURN_ID, "catalog_id": "Burn"}}],
    "rules": RULES, "game_secret": "7648831b4ae4148770e13149d5ebbe1c4991168413d4b38e49292cfc5538980e",
    "max_decisions": 10000, "max_steps": 100000,
}
TERMINAL = {"response_type": "terminal", "protocol": "spellbench/v2", "request_id": "h-9", "game_id": "g-f67d7fe78c792984",
            "outcome": "p0_win", "classification": "natural", "winner": "p0", "reason": "p1_life_zero",
            "step_count": 412, "decision_count": 388, "provenance": PROVENANCE}


@pytest.mark.parametrize(("model", "message"), [(EnvHelloOk, HELLO_OK), (ResetRequest, RESET), (Terminal, TERMINAL)])
def test_spec_examples_round_trip(model, message) -> None:
    assert model.from_json(copy.deepcopy(message)).to_json() == message


def test_the_decision_binding_keeps_the_seat_decision_raw() -> None:
    message = {"response_type": "decision", "protocol": "spellbench/v2", "request_id": "h-7", "game_id": "g-f67d7fe78c792984",
               "step": 14, "seat_decision": {"acting_seat": "p0", "anything": "validated later"}, "provenance": PROVENANCE}
    decision = Decision.from_json(copy.deepcopy(message))
    assert decision.acting_seat == "p0" and decision.to_json() == message


def test_step_request_always_carries_the_echo() -> None:
    step = {"request_type": "step", "protocol": "spellbench/v2", "request_id": "h-8", "game_id": "g-1", "expected_step": 14,
            "selection": {"candidate_id": 0, "semantic_echo": {"kind": "pass"}}}
    assert StepRequest.from_json(step).to_json() == step
    with pytest.raises(ValidationError):
        StepRequest.from_json({**step, "selection": {"candidate_id": 0}})


def _hello(**changes) -> dict:
    value = copy.deepcopy(HELLO_OK)
    value.update(changes)
    return value


@pytest.mark.parametrize(
    "hello",
    [
        _hello(decision_kinds=["pass", "play_land", "cast_spell", "declare_attack"]),                 # a required kind missing
        _hello(decision_kinds=HELLO_OK["decision_kinds"] + ["pay_mana"]),                             # a reserved kind
        _hello(observation={**FLAGS, "x_flag": True}),
        _hello(engine_defaults={**HELLO_OK["engine_defaults"], "mana_payment": "engine_order"}),
        _hello(deck_sources=["catalog", "cloud"]),
        _hello(rules_supported={"mulligan": [], "starting_player": ["host_assigned"]}),
        _hello(catalog=[{"catalog_id": "Vault", "name": "Vault", "decklist": [{"name": "Lim-Du\u0302l's Vault", "count": 4}]}]),
        _hello(extensions=[{"name": "kernel", "native_ids": True}]),
        _hello(x_unknown=1),
    ],
)
def test_invalid_hello_ok_is_malformed(hello: dict) -> None:
    with pytest.raises(ValidationError):
        EnvHelloOk.from_json(hello)


def test_an_nfd_catalog_name_is_named_in_the_error() -> None:
    hello = _hello(catalog=[{"catalog_id": "Vault", "name": "Vault", "decklist": [{"name": "Lim-Du\u0302l's Vault", "count": 4}]}])
    with pytest.raises(ValidationError, match="Lim-Du\u0302l's Vault.*NFC"):
        EnvHelloOk.from_json(hello)


@pytest.mark.parametrize(
    "rules",
    [
        {**RULES, "starting_seat": None},                                     # host_assigned needs a seat
        {**RULES, "starting_player": "toss_winner_chooses"},                  # and toss_winner_chooses none
        {**RULES, "card_name_domain": {**DOMAIN, "names": ["Mountain"]}},     # domain_id must match the names
        {**RULES, "opponent_decklist": "secret"},
        {**RULES, "extensions": ["kernel"]},
    ],
)
def test_invalid_rules_are_malformed(rules: dict) -> None:
    with pytest.raises(ValidationError):
        Rules.from_json(rules)


def test_seat_caps_must_stay_below_half_the_game_caps() -> None:
    Limits(max_decisions=10000, max_steps=100000, max_seat_decisions_per_turn=500,
           max_seat_decisions_per_game=4999, max_seat_steps_per_game=49999)
    with pytest.raises(ValidationError, match="half"):
        Limits(max_decisions=10000, max_steps=100000, max_seat_decisions_per_turn=500,
               max_seat_decisions_per_game=5000, max_seat_steps_per_game=49999)


def test_errors_use_the_closed_code_table() -> None:
    assert len(ENGINE_ERROR_CODES) == 17
    error = {"response_type": "error", "protocol": "spellbench/v2", "request_id": "", "error": {"code": "probe_refused", "message": "no"}}
    assert ErrorResponse.from_json(error, codes=ENGINE_ERROR_CODES).code == "probe_refused"
    with pytest.raises(ValidationError):
        ErrorResponse.from_json({**error, "error": {"code": "no_pending_decision", "message": "x"}}, codes=ENGINE_ERROR_CODES)


def test_a_terminal_never_carries_forfeit_or_a_truncated_winner() -> None:
    for changes in ({"classification": "forfeit"}, {"outcome": "truncated", "classification": "truncated"}):
        with pytest.raises(ValidationError):
            Terminal.from_json({**TERMINAL, **changes})


def test_time_control_round_trips() -> None:
    value = {"startup_ms": 300000, "game_start_ms": 60000, "bank_ms": 600000, "increment_ms": 2000,
             "max_decision_ms": 60000, "engine_step_ms": 120000}
    assert TimeControl.from_json(value).to_json() == value


def test_a_reset_never_prints_its_game_secret() -> None:
    assert RESET["game_secret"] not in repr(ResetRequest.from_json(copy.deepcopy(RESET)))     # R3-28


# The shapes and rules the spec examples above do not reach.
PROFILE = {key: HELLO_OK[key] for key in ("rules_supported", "observation", "decision_kinds", "engine_defaults", "rewind",
                                          "fairness", "extensions")}                         # game_start.engine_profile


@pytest.mark.parametrize(
    ("model", "message"),
    [
        (HelloRequest, {"request_type": "hello", "protocol": "spellbench/v2", "request_id": "h-1", "protocol_minor": 0}),
        (ValidateDeckRequest, {"request_type": "validate_deck", "protocol": "spellbench/v2", "request_id": "h-3",
                               "format": "pauper-bo1", "deck": {"catalog_id": "Burn"}}),
        (ValidateDeckRequest, {"request_type": "validate_deck", "protocol": "spellbench/v2", "request_id": "h-3",
                               "format": "pauper-bo1", "deck": {"decklist": [{"name": "Mountain", "count": 20}]}}),
        (DeckOk, {"response_type": "deck_ok", "protocol": "spellbench/v2", "request_id": "h-3"}),
        (EngineProfile, PROFILE),
        (Limits, {"max_decisions": 10000, "max_steps": 100000, "max_seat_decisions_per_turn": 500,
                  "max_seat_decisions_per_game": 4999, "max_seat_steps_per_game": 49999}),
        (Resources, {"cpus": 1, "memory_mb": 4096, "gpu": False, "engine_cpus": 1}),
    ],
)
def test_the_other_shapes_round_trip(model, message) -> None:
    assert model.from_json(copy.deepcopy(message)).to_json() == message


def test_a_reset_deck_is_a_catalog_id_or_a_decklist() -> None:
    listed = {"deck_id": BURN_ID, "decklist": [{"name": "Lightning Bolt", "count": 4}, {"name": "Mountain", "count": 18}]}
    reset = {**copy.deepcopy(RESET), "seats": [{"seat": "p0", "deck": listed}, copy.deepcopy(RESET["seats"][1])]}
    assert ResetRequest.from_json(copy.deepcopy(reset)).to_json() == reset
    for deck in ({**listed, "catalog_id": "Burn"}, {"deck_id": BURN_ID}, {"deck_id": "0df0a001", "catalog_id": "Burn"}):
        with pytest.raises(ValidationError):
            ResetRequest.from_json({**RESET, "seats": [{"seat": "p0", "deck": deck}, RESET["seats"][1]]})
    with pytest.raises(ValidationError, match="p0"):
        ResetRequest.from_json({**RESET, "seats": RESET["seats"][::-1]})                  # p0 then p1


def test_a_bad_game_secret_is_refused_without_quoting_it() -> None:
    secret = RESET["game_secret"].upper()
    with pytest.raises(ValidationError) as caught:
        ResetRequest.from_json({**RESET, "game_secret": secret})
    assert secret not in str(caught.value)


@pytest.mark.parametrize(
    "hello",
    [
        _hello(protocol_minor=1 << 32),                                                       # a u32 (spec 4.2)
        _hello(deck_sources=["decklist"]),                                                     # a catalog needs its source
        _hello(catalog=HELLO_OK["catalog"] * 2),                                               # catalog ids are distinct
        _hello(decision_kinds=HELLO_OK["decision_kinds"] + ["pass"]),                          # kinds are distinct
        _hello(extensions=[{"name": "x_kernel_v5", "native_ids": True}, {"name": "x_kernel_v5", "native_ids": False}]),
        _hello(formats=[]),
    ],
)
def test_more_invalid_hello_ok(hello: dict) -> None:
    with pytest.raises(ValidationError):
        EnvHelloOk.from_json(hello)


def test_a_reserved_kind_is_named_as_reserved() -> None:
    with pytest.raises(ValidationError, match="pay_mana.*reserved"):
        EnvHelloOk.from_json(_hello(decision_kinds=HELLO_OK["decision_kinds"] + ["pay_mana"]))


def test_construction_checks_the_same_rules() -> None:
    assert EnvHelloOk.from_json(copy.deepcopy(HELLO_OK)).engine.provenance().to_json() == PROVENANCE
    for build in (lambda: DeckRow("Mountain", 0), lambda: CardNameDomain(DOMAIN["domain_id"], ("Mountain",)),
                  lambda: WireDeck(deck_id=BURN_ID), lambda: TimeControl(0, 1, 1, 0, 1, 1)):
        with pytest.raises(ValidationError):
            build()


def test_the_acting_seat_is_none_unless_it_is_a_seat() -> None:
    message = {"response_type": "decision", "protocol": "spellbench/v2", "request_id": "h-7", "game_id": "g-1", "step": 0,
               "provenance": PROVENANCE}
    for seat_decision in ({}, {"acting_seat": "p2"}, {"acting_seat": ["p0"]}):
        assert Decision.from_json({**message, "seat_decision": seat_decision}).acting_seat is None
    with pytest.raises(ValidationError):
        Decision.from_json({**message, "seat_decision": []})
