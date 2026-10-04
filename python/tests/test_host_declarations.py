"""V8 declarations and V9 context (spec 6.9, 7.1, 7.6)."""

import pytest

from spellbench._schema import V2_KINDS
from spellbench.host.declarations import check_context, check_declarations
from spellbench.host.violation import ValidatorViolation
from spellbench.messages import EngineProfile, Rules

from v2_sample_semantics import SAMPLES, seat_decision

FLAGS = {"poison": False, "player_counters": False, "designations": True, "player_progress": False, "day_night": False,
         "passed_seats": True, "pending_triggers": True, "keywords": True, "full_name": False, "exiled_by": True,
         "stack_text": False, "permanent_details": True, "known_cards": True}   # the spec 6.1 example's flags
PROFILE_JSON = {"rules_supported": {"mulligan": ["none"], "starting_player": ["host_assigned"]}, "observation": FLAGS,
                "decision_kinds": ["pass", "play_land", "cast_spell", "activate_mana_ability", "activate_ability", "optional_cost",
                                   "choose_target", "declare_attack", "declare_block", "mulligan", "choose_starting_player"],
                "engine_defaults": {"trigger_order": None, "replacement_order": None, "combat_damage_assignment": None, "mana_payment": None},
                "rewind": False, "fairness": {"noninterference_probe": False}, "extensions": [{"name": "x_kernel_v5", "native_ids": True}]}
RULES_JSON = {"opponent_decklist": "visible", "mulligan": "none", "starting_player": "host_assigned", "starting_seat": "p0",
              "card_name_domain": {"domain_id": "sha256:74f7f4b39eecbed1c039cf4b229fa533069d2cdd8caf3bb6380b832eb40fb697",
                                   "names": ["Lightning Bolt", "Mountain"]}, "extensions": [], "probe": False}
PROFILE, RULES = EngineProfile.from_json(PROFILE_JSON), Rules.from_json(RULES_JSON)


def _v8(decision) -> None:
    check_declarations(decision, PROFILE, RULES)


def _swift(decision) -> dict:
    return decision["observation"]["players"][0]["battlefield"][0]


def test_the_spec_example_matches_its_declarations() -> None:
    _v8(seat_decision())


@pytest.mark.parametrize(
    "decision",
    [
        seat_decision([SAMPLES["pass"], SAMPLES["choose_name"]]),                         # an undeclared kind
        seat_decision([SAMPLES["mulligan"]], kind="choice"),                              # mulligan under rules.mulligan none
        seat_decision([SAMPLES["choose_starting_player"]], kind="choice"),                # host_assigned starting player
        seat_decision(rewind=True),                                                       # rewind not declared
        seat_decision(extensions={"x_kernel_v5": {}}),                                    # declared but not enabled
    ],
)
def test_v8_kinds_rules_and_extensions(decision: dict) -> None:
    with pytest.raises(ValidatorViolation) as caught:
        _v8(decision)
    assert caught.value.rule == "V8"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["observation"]["players"][0].update(poison=0),                            # flag off, value present
        lambda d: d["observation"].update(passed_seats=None),                                 # flag on, value missing
        lambda d: d["observation"]["players"][0]["hand"][0]["characteristics"].update(keywords=None),
        lambda d: _swift(d)["permanent"].update(class_level=2),                               # not a Class
        lambda d: (_swift(d)["characteristics"]["subtypes"].append("class"), _swift(d)["permanent"].update(class_level=None)),
        lambda d: _swift(d)["permanent"].update(statuses=None),
    ],
)
def test_v8_optional_fields_follow_the_flags(mutate) -> None:
    decision = seat_decision()
    mutate(decision)
    with pytest.raises(ValidatorViolation) as caught:
        _v8(decision)
    assert caught.value.rule == "V8"


def test_v8_allowed_nulls_with_the_flag_on() -> None:
    decision = seat_decision()
    assert _swift(decision)["exiled_by"] is None     # flag on: null is allowed for exiled_by
    _v8(decision)


def test_v8_without_known_cards_only_current_looks_are_listed() -> None:
    profile = EngineProfile.from_json({**PROFILE_JSON, "observation": {**FLAGS, "known_cards": False}})
    current = seat_decision()
    current["observation"]["known"] = [{"owner_seat": "p0", "zone": "library", "card_name": "Mountain",
                                        "object_id": "o-3c9f5e7a1b2d4c6e", "position_from_top": 0,
                                        "position_from_bottom": None, "how": "looked_at"}]
    check_declarations(current, profile, RULES)                               # a card looked at in this decision
    with pytest.raises(ValidatorViolation) as caught:
        check_declarations(seat_decision(), profile, RULES)                    # the example's persistent entries (R2-6)
    assert caught.value.rule == "V8"


MANA = [{**SAMPLES["optional_cost"], "cost": "unless_payment", "pay": True},
        {**SAMPLES["optional_cost"], "cost": "unless_payment", "pay": False},
        SAMPLES["activate_mana_ability"]]


ALL_KINDS_JSON = {**PROFILE_JSON, "decision_kinds": sorted(V2_KINDS)}


def _defaults(**changes) -> EngineProfile:
    return EngineProfile.from_json({**ALL_KINDS_JSON, "engine_defaults": {**PROFILE_JSON["engine_defaults"], **changes}})


@pytest.mark.parametrize(
    ("default", "value", "decision"),
    [
        ("trigger_order", "engine_order", seat_decision([SAMPLES["order_pick"]], kind="choice")),
        ("replacement_order", "engine_order", seat_decision([SAMPLES["choose_replacement"]], kind="choice")),
        ("combat_damage_assignment", "engine_order",
         seat_decision([{**SAMPLES["distribute"], "purpose": "combat_damage"}], kind="choice")),
        ("mana_payment", "engine_autopay", seat_decision(MANA, kind="choice", purpose="mana_payment")),
    ],
    ids=["trigger_order", "replacement_order", "combat_damage_assignment", "mana_payment"],
)
def test_v8_a_declared_engine_default_answers_its_decision_itself(default: str, value: str, decision: dict) -> None:
    check_declarations(decision, _defaults(), RULES)                                  # null: offered through its kind
    with pytest.raises(ValidatorViolation, match=f"engine_defaults.{default}") as caught:
        check_declarations(decision, _defaults(**{default: value}), RULES)             # spec 7.6 (M7)
    assert caught.value.rule == "V8"


def test_v8_under_its_engine_defaults_the_seat_still_decides_the_rest() -> None:
    engine = _defaults(trigger_order="engine_order", combat_damage_assignment="engine_order", mana_payment="engine_autopay")
    check_declarations(seat_decision(MANA[:2], kind="choice", purpose="mana_payment"), engine, RULES)   # whether to pay
    check_declarations(seat_decision([{**SAMPLES["order_pick"], "purpose": "library_top",
                                       "item": {"object": SAMPLES["arrange_card"]["card"]}}], kind="choice"), engine, RULES)
    check_declarations(seat_decision([SAMPLES["distribute"]], kind="choice"), engine, RULES)          # damage a spell divides


def test_priority_mana_activation_is_distinct_from_automatic_cost_payment() -> None:
    engine = _defaults(mana_payment="engine_autopay")
    priority = seat_decision([SAMPLES["pass"], SAMPLES["activate_mana_ability"]])
    check_declarations(priority, engine, RULES)
    check_context(priority)

    undeclared = EngineProfile.from_json({**engine.to_json(), "decision_kinds": [
        kind for kind in engine.decision_kinds if kind != "activate_mana_ability"
    ]})
    with pytest.raises(ValidatorViolation, match="decision_kinds") as caught:
        check_declarations(priority, undeclared, RULES)
    assert caught.value.rule == "V8"

    payment = seat_decision(MANA, kind="choice", purpose="mana_payment")
    with pytest.raises(ValidatorViolation, match="engine_defaults.mana_payment") as caught:
        check_declarations(payment, engine, RULES)
    assert caught.value.rule == "V8"


def test_v8_an_extension_key_is_declared_and_enabled() -> None:
    rules = Rules.from_json({**RULES_JSON, "extensions": ["x_kernel_v5", "x_other"]})
    check_declarations(seat_decision(extensions={"x_kernel_v5": {}}), PROFILE, rules)
    with pytest.raises(ValidatorViolation, match="hello_ok.extensions") as caught:
        check_declarations(seat_decision(extensions={"x_other": {}}), PROFILE, rules)   # enabled, never declared (M8)
    assert caught.value.rule == "V8"


def test_v9_context_purpose_repeats_the_candidates_shared_purpose() -> None:
    boolean = SAMPLES["choose_boolean"]                                                # purpose may_ability
    check_context(seat_decision([boolean], kind="choice", purpose="may_ability"))
    check_context(seat_decision([boolean], kind="choice"))                             # or is left null
    for decision in (
        seat_decision(purpose="p1_holds_counterspell_and_island"),                     # the audit's input (M1)
        seat_decision([boolean], kind="choice", purpose="reveal"),                     # not the candidates' purpose
        seat_decision([boolean, {**boolean, "purpose": "reveal", "value": True}], kind="choice", purpose="reveal"),
    ):
        with pytest.raises(ValidatorViolation, match="context.purpose") as caught:
            check_context(decision)
        assert caught.value.rule == "V9"


def test_v9_a_mana_payment_pays_one_cost_of_one_source() -> None:
    for payment in ({**MANA[0], "source": SAMPLES["activate_ability"]["source"]}, {**MANA[0], "cost": "kicker"}):
        with pytest.raises(ValidatorViolation, match="one cost") as caught:              # M10
            check_context(seat_decision([payment, *MANA[1:]], kind="choice", purpose="mana_payment"))
        assert caught.value.rule == "V9"


def test_v9_context_matches_the_family_with_the_mana_payment_exception() -> None:
    check_context(seat_decision())
    check_context(seat_decision(MANA, kind="choice", purpose="mana_payment"))
    for decision in (
        seat_decision(kind="choice"),                                                   # priority kinds in a choice decision
        seat_decision([SAMPLES["pass"], SAMPLES["choose_target"]]),                    # mixed families
        seat_decision(MANA, kind="choice"),                                             # mana abilities without the purpose
        seat_decision(MANA[:1] + MANA[2:], kind="choice", purpose="mana_payment"),     # no pay: false
        seat_decision(MANA + [SAMPLES["choose_target"]], kind="choice", purpose="mana_payment"),
        seat_decision(purpose="mana_payment"),                                          # the purpose on a priority decision
        seat_decision(MANA[1:], purpose="mana_payment"),                               # legal mana_payment candidates, wrong kind
    ):
        with pytest.raises(ValidatorViolation) as caught:
            check_context(decision)
        assert caught.value.rule == "V9"
