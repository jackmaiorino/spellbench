"""The live validator: V1 to V10 in rule order, with its counters (spec 11.3)."""

from __future__ import annotations

import copy
import re
import sys
from pathlib import Path

import pytest

from spellbench.errors import ValidationError
from spellbench.host.engine_process import EngineProcess
from spellbench.host.validator import LiveValidator
from spellbench.host.violation import ValidatorViolation
from spellbench.messages import Decision, EnvHelloOk, Provenance, ResetRequest, Rules, Terminal

from test_messages import HELLO_OK, PROVENANCE, RESET, RULES, TERMINAL
from v2_sample_semantics import R_SPRITE, R_STACK, R_SWIFTSPEAR, SAMPLES, seat_decision

ENGINE = Path(__file__).resolve().parent / "fake_v2_engine.py"
CAPS = {"max_decisions": RESET["max_decisions"], "max_steps": RESET["max_steps"]}      # the spec 9.2 reset's caps
# A face-down object as a seat that may not look at it sees it: a nameless, colorless 2/2 creature (spec 6.4).
FACE_DOWN = {"supertypes": [], "types": ["creature"], "subtypes": [], "colors": [], "mana_value": 0, "power": 2,
             "toughness": 2, "keywords": []}


def _validator(*, hello: dict = HELLO_OK, rules: dict = RULES, **caps: int) -> LiveValidator:
    return LiveValidator(EnvHelloOk.from_json(copy.deepcopy(hello)), Rules.from_json(copy.deepcopy(rules)), **{**CAPS, **caps})


def _decision(sd: dict, *, step: int = 0, provenance: dict = PROVENANCE) -> Decision:
    return Decision(request_id=f"h-{step + 2}", game_id="g-1", step=step, seat_decision=sd, provenance=Provenance(**provenance))


def _rule(validator: LiveValidator, sd: dict, **kwargs) -> str:
    with pytest.raises(ValidatorViolation) as caught:
        validator.check(_decision(sd, **kwargs))
    return caught.value.rule


def test_a_fake_engine_game_passes_and_the_counts_match_its_terminal() -> None:
    engine = EngineProcess([sys.executable, str(ENGINE)], timeout_s=30)
    try:
        validator = LiveValidator(engine.hello(), Rules.from_json(RULES), **CAPS)
        response = engine.reset(ResetRequest.from_json({**copy.deepcopy(RESET), "request_id": engine.next_request_id()}))
        while isinstance(response, Decision):
            sd = validator.check(response)
            validator.answered(sd, 0)
            response = engine.step(candidate_id=0, semantic=sd["candidates"][0]["semantic"])
        validator.check_terminal(response)
    finally:
        engine.close()
    assert validator.decisions_checked == validator.answered_steps == response.result.step_count == 4
    assert validator.completed_groups == response.result.decision_count
    assert (validator.answered_by("p0"), validator.answered_by("p1")) == (2, 2)


@pytest.mark.parametrize(
    "sd",
    [
        seat_decision([SAMPLES["pass"], SAMPLES["pass"]]),                                       # duplicate semantics
        seat_decision([SAMPLES["choose_boolean"], SAMPLES["pass"]], kind="choice"),             # pass not first
        {**seat_decision(), "x_extra": 1},                                                       # unknown field
        seat_decision(extensions={"kernel": {}}),                                                # not an x_ key
        seat_decision([{"kind": "pay_mana"}]),                                                    # a reserved kind
        seat_decision([{**SAMPLES["choose_name"], "source": None, "value": "Black Lotus"}], kind="choice"),  # outside the domain
    ],
)
def test_v1_schema(sd: dict) -> None:
    assert _rule(_validator(), sd) == "V1"


def test_v1_dense_ids_and_the_4096_cap() -> None:
    sparse = seat_decision()
    sparse["candidates"][1]["candidate_id"] = 5
    assert _rule(_validator(), sparse) == "V1"
    many = [{**SAMPLES["choose_number"], "source": None, "value": value, "minimum": 0, "maximum": 4096} for value in range(4097)]
    assert _rule(_validator(), seat_decision(many, kind="choice")) == "V1"


def _for_p1(sd: dict) -> None:
    """A decision for p1, which holds priority, carrying p0's view: only V2's viewer rule breaks."""
    sd.update(acting_seat="p1")
    sd["observation"]["priority_seat"] = "p1"


def _named_face_down(sd: dict) -> None:
    """p1's Sprite turned face down with the face-down characteristics, still named: only V6's name rule breaks."""
    sd["observation"]["players"][1]["battlefield"][0].update(face_down=True, characteristics=copy.deepcopy(FACE_DOWN))


@pytest.mark.parametrize(
    ("mutate", "rule"),
    [
        (_for_p1, "V2"),
        (lambda sd: sd.update(seat_step=3), "V3"),
        (lambda sd: sd["candidates"][2]["semantic"]["source"].update(card_name="Chain Lightning"), "V4"),
        (lambda sd: sd["observation"]["players"][1].update(hand=[]), "V5"),
        (_named_face_down, "V6"),
        (lambda sd: sd["observation"]["players"][0].update(poison=0), "V8"),
        (lambda sd: sd["context"].update(kind="choice"), "V9"),
        (lambda sd: (_for_p1(sd), sd["candidates"][2]["semantic"]["source"].update(card_name="x")), "V2"),
    ],
)
def test_each_rule_is_reported_and_the_lowest_wins(mutate, rule: str) -> None:
    sd = seat_decision()
    mutate(sd)
    assert _rule(_validator(), sd) == rule


def test_v7_across_decisions_and_v10_provenance() -> None:
    validator = _validator()
    first = seat_decision()
    validator.check(_decision(first))
    validator.answered(first, 0)
    second = seat_decision([SAMPLES["pass"]])
    second.update(seat_step=1, group={"group_id": 1, "substep_index": 0, "substep_count": 1})
    player = second["observation"]["players"][0]
    bolt = player["hand"].pop(0)
    player["graveyard"].append({**bolt, "zone": "graveyard"})     # the same id in a new zone
    player["hand_count"] = 1
    assert _rule(validator, second, step=1) == "V7"
    assert _rule(_validator(), seat_decision(), provenance={**PROVENANCE, "engine_version": "9.9.9"}) == "V10"


def test_v7_flags_an_id_that_returns_after_leaving_through_a_hidden_zone() -> None:
    """An id that leaves the observation (here as if drawn into a hidden zone) never comes back (spec 5.3).

    V4 alone cannot catch this: the third decision's own references all match its own
    observation record field for field. Only V7's cross-decision history (host.tracking.IdTracker)
    catches the reuse, so this checks that LiveValidator actually wires V7 across decisions.
    """
    validator = _validator()
    first = seat_decision([SAMPLES["pass"]])
    validator.check(_decision(first))
    validator.answered(first, 0)

    second = seat_decision([SAMPLES["pass"]])
    second.update(seat_step=1, group={"group_id": 1, "substep_index": 0, "substep_count": 1})
    player = second["observation"]["players"][0]
    player["hand"].pop(0)                                         # Lightning Bolt leaves to a hidden zone
    player["hand_count"] = 1
    validator.check(_decision(second, step=1))
    validator.answered(second, 0)

    third = seat_decision([SAMPLES["pass"]])                      # the unmodified sample: Lightning Bolt's id is back
    third.update(seat_step=2, group={"group_id": 2, "substep_index": 0, "substep_count": 1})
    assert _rule(validator, third, step=2) == "V7"


def test_v1_a_library_search_may_find_nothing() -> None:
    search = {**SAMPLES["select_object"], "purpose": "search", "minimum": 1}
    finish = {**SAMPLES["finish_selection"], "purpose": "search", "selected_count": 0}       # offered, as M4 requires
    detail = r"candidates\[0\]\.semantic\.minimum: a library search always allows finding nothing"
    with pytest.raises(ValidatorViolation, match=detail) as caught:
        _validator().check(_decision(seat_decision([search, finish], kind="choice")))       # spec 7.5, F3 (R2-7)
    assert caught.value.rule == "V1"


MULLIGAN = {**SAMPLES["mulligan"], "hand_size": 2, "mulligans_taken": 0}                  # the example viewer: 2 cards, 0 taken


@pytest.mark.parametrize(
    ("candidates", "rule"),
    [
        ([SAMPLES["choose_starting_player"]], "V1"),                                        # only one seat offered
        ([{**MULLIGAN, "keep": False}], "V1"),                                              # no keep: true
        ([{**MULLIGAN, "hand_size": 7}], "V1"),                                             # not the viewer's hand_count
        ([{**MULLIGAN, "mulligans_taken": 1}], "V1"),                                       # not the viewer's mulligans_taken
        ([{**SAMPLES["choose_starting_player"], "player": "p0"}, SAMPLES["choose_starting_player"]], "V8"),  # past V1
        ([MULLIGAN, {**MULLIGAN, "keep": False}], "V8"),                                    # past V1; the hello lacks the kind
    ],
)
def test_v1_starting_player_and_mulligan_shapes(candidates: list, rule: str) -> None:
    assert _rule(_validator(), seat_decision(candidates, kind="choice")) == rule            # R2-25


@pytest.mark.parametrize(
    ("semantics", "kind", "count"),
    [
        ([SAMPLES["arrange_card"]], "choice", 2),                  # scry 2 is 2 x 2 - 1 = 3 decisions
        ([SAMPLES["finish_selection"]], "choice", 2),              # a finish candidate ends a one-decision group
        ([SAMPLES["pass"], SAMPLES["play_land"]], "priority", 2),  # a priority decision is never decomposed
    ],
)
def test_v3_group_shapes(semantics: list, kind: str, count: int) -> None:
    sd = seat_decision(semantics, kind=kind)
    sd["group"]["substep_count"] = count
    assert _rule(_validator(), sd) == "V3"                                                   # R2-7


def test_a_check_that_breaks_on_bad_input_reports_v1(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("spellbench.host.validator.check_hidden_zones", lambda sd: [][0])   # an IndexError, not a violation
    assert _rule(_validator(), seat_decision()) == "V1"                                     # R1-8


def _truncated(step_count: int, decision_count: int) -> Terminal:
    return Terminal.from_json({**TERMINAL, "outcome": "truncated", "classification": "truncated", "winner": None,
                               "reason": "max_steps", "step_count": step_count, "decision_count": decision_count})


def _play(validator: LiveValidator, sd: dict, step: int) -> None:
    validator.check(_decision(sd, step=step))
    validator.answered(sd, 0)


def _first_of_two_attackers(*, seat_step: int = 0, group_id: int = 0) -> dict:
    attack = seat_decision([SAMPLES["declare_attack"]], kind="choice")
    attack.update(seat_step=seat_step, group={"group_id": group_id, "substep_index": 0, "substep_count": 2})
    return attack


def test_only_a_halted_or_truncated_terminal_may_interrupt_a_group() -> None:
    validator = _validator(max_steps=1)
    _play(validator, _first_of_two_attackers(), 0)
    with pytest.raises(ValidatorViolation) as caught:
        validator.check_terminal(Terminal.from_json({**TERMINAL, "step_count": 1, "decision_count": 0}))
    assert caught.value.rule == "V3"                                                          # R1-12
    validator.check_terminal(_truncated(1, 0))                  # max_steps reached inside the group (Decision 13)


def test_v3_a_truncated_terminal_needs_a_reached_cap() -> None:
    """Spec 9.2: reaching a cap ends the game truncated, so a truncation below both caps is V3 (I1).

    Only max_steps counts substeps, so only it can fall inside a group (Decision 13); max_decisions
    is reached when a group completes.
    """
    mid_group = _validator()
    _play(mid_group, _first_of_two_attackers(), 0)
    with pytest.raises(ValidatorViolation, match="max_steps 100000") as caught:
        mid_group.check_terminal(_truncated(1, 0))                                  # the audit's reproducing input
    assert caught.value.rule == "V3"
    boundary = _validator()
    _play(boundary, seat_decision(), 0)
    with pytest.raises(ValidatorViolation, match="below max_steps 100000 and max_decisions 10000") as caught:
        boundary.check_terminal(_truncated(1, 1))                                   # one complete decision, no cap
    assert caught.value.rule == "V3"
    groups_capped = _validator(max_decisions=1)
    _play(groups_capped, seat_decision(), 0)
    groups_capped.check_terminal(_truncated(1, 1))                                  # max_decisions reached
    steps_capped = _validator(max_steps=1)
    _play(steps_capped, seat_decision(), 0)
    steps_capped.check_terminal(_truncated(1, 1))                                   # max_steps reached
    past_group_cap = _validator(max_decisions=1)
    _play(past_group_cap, seat_decision(), 0)
    _play(past_group_cap, _first_of_two_attackers(seat_step=1, group_id=1), 1)
    with pytest.raises(ValidatorViolation, match="partial group") as caught:
        past_group_cap.check_terminal(_truncated(2, 1))                             # the group cap never falls inside a group
    assert caught.value.rule == "V3"


def test_the_caps_are_required_counters() -> None:
    hello, rules = EnvHelloOk.from_json(copy.deepcopy(HELLO_OK)), Rules.from_json(RULES)
    with pytest.raises(TypeError):
        LiveValidator(hello, rules)                                                     # no default: a caller passes both
    with pytest.raises(ValidationError, match="max_decisions"):
        LiveValidator(hello, rules, max_decisions=None, max_steps=100000)
    with pytest.raises(ValidationError, match="max_steps"):
        LiveValidator(hello, rules, max_decisions=10000, max_steps="100000")


# The validator-stack audit's findings: C1 to C3, I1 to I3 and the minor ones (M1 to M17).

# C1 (spec 6.4, 6.8; V6): a face-down object the viewer may not look at shows only its face-down characteristics.

R_HIDDEN_SPRITE = {**R_SPRITE, "card_name": None}


def _face_down_sprite(sd: dict) -> dict:
    """p1's Spellstutter Sprite turned face down, as p0 sees it: a nameless, colorless 2/2 creature (spec 6.4)."""
    sprite = sd["observation"]["players"][1]["battlefield"][0]
    sprite.update(face_down=True, card_name=None, full_name=None, characteristics=copy.deepcopy(FACE_DOWN))
    return sprite


def _face_down_spell(**changes) -> dict:
    """A face-down creature spell p1 controls, as p0 sees it (spec 6.5)."""
    return {"object_id": "o-8c1d2e3f4a5b6c7d", "card_name": None, "owner_seat": "p1", "controller_seat": "p1",
            "zone": "stack", "stack_kind": "spell", "source": None, "face_down": True, "copy": False,
            "characteristics": copy.deepcopy(FACE_DOWN), "targets": [], "divided": None, "modes": None, "x_value": None,
            "text": None, **changes}


def test_v6_a_face_down_object_shows_the_face_down_characteristics() -> None:
    sd = seat_decision()
    sprite = _face_down_sprite(sd)
    sprite["characteristics"].update(power=3, toughness=3)            # counters and effects change power and toughness
    sprite["permanent"]["counters"] = {"p1p1": 1}
    sd["observation"]["stack"].append(_face_down_spell())
    _validator().check(_decision(sd))
    disguised = seat_decision()
    _face_down_sprite(disguised)["characteristics"]["keywords"] = ["ward"]       # disguise and cloak give ward 2
    disguised["observation"]["stack"].append(_face_down_spell(characteristics={**FACE_DOWN, "keywords": ["ward"]}))
    _validator().check(_decision(disguised))
    own = seat_decision()
    own["observation"]["players"][0]["battlefield"][0]["face_down"] = True      # the viewer's own: it may look (CR 708.5)
    _validator().check(_decision(own))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("supertypes", ["legendary"]),
        ("types", ["artifact", "creature"]),
        ("subtypes", ["faerie"]),
        ("colors", ["blue"]),
        ("mana_value", 2),
        ("keywords", ["flash", "flying"]),
        ("keywords", ["flying", "ward"]),
    ],
)
def test_v6_a_face_down_permanent_hides_each_printed_characteristic(field: str, value) -> None:
    sd = seat_decision()
    _face_down_sprite(sd)["characteristics"][field] = value
    with pytest.raises(ValidatorViolation, match=rf"players\[1\]\.battlefield\[0\]\.characteristics\.{field} ") as caught:
        _validator().check(_decision(sd))
    assert caught.value.rule == "V6"


@pytest.mark.parametrize(
    ("field", "value"), [("chosen", [{"kind": "card_name", "value": "Lightning Bolt"}]), ("class_level", 2)],
)
def test_v6_a_face_down_permanent_shows_no_chosen_value_or_class_level(field: str, value) -> None:
    sd = seat_decision()
    _face_down_sprite(sd)["permanent"][field] = value
    with pytest.raises(ValidatorViolation, match=rf"players\[1\]\.battlefield\[0\]\.permanent\.{field} ") as caught:
        _validator().check(_decision(sd))
    assert caught.value.rule == "V6"


@pytest.mark.parametrize(
    ("changes", "path"),
    [
        ({"characteristics": {**FACE_DOWN, "supertypes": ["legendary"]}}, "characteristics.supertypes"),
        ({"characteristics": {**FACE_DOWN, "types": ["artifact", "creature"]}}, "characteristics.types"),
        ({"characteristics": {**FACE_DOWN, "subtypes": ["beast"]}}, "characteristics.subtypes"),
        ({"characteristics": {**FACE_DOWN, "colors": ["green"]}}, "characteristics.colors"),
        ({"characteristics": {**FACE_DOWN, "mana_value": 5}}, "characteristics.mana_value"),
        ({"characteristics": {**FACE_DOWN, "keywords": ["trample"]}}, "characteristics.keywords"),
        ({"targets": [{"player": "p0"}]}, "targets"),
        ({"divided": []}, "divided"),
        ({"modes": [0]}, "modes"),
        ({"x_value": 3}, "x_value"),
    ],
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_v6_a_face_down_spell_hides_each_printed_characteristic_and_choice(changes: dict, path: str) -> None:
    sd = seat_decision()
    sd["observation"]["stack"].append(_face_down_spell(**changes))
    with pytest.raises(ValidatorViolation, match=rf"stack\[0\]\.{re.escape(path)} ") as caught:
        _validator().check(_decision(sd))
    assert caught.value.rule == "V6"


# C2 (spec 5.1, 6.8; V1): a trigger item names its source, so a nameless source leaves it nameless.


def _trigger(source: dict, name: str | None) -> dict:
    return {"kind": "order_pick", "source": None, "purpose": "triggers", "position": 0, "count": 2,
            "item": {"trigger": {"source": source, "source_name": name, "ability_index": 0, "event_objects": [],
                                 "instance": 0, "label": None}}}


def test_v1_an_order_pick_trigger_hides_the_name_of_a_nameless_source() -> None:
    swift = _trigger(R_SWIFTSPEAR, "Monastery Swiftspear")
    named = seat_decision([_trigger(R_HIDDEN_SPRITE, "Spellstutter Sprite"), swift], kind="choice")
    _face_down_sprite(named)
    with pytest.raises(ValidatorViolation, match=r"candidates\[0\]\.semantic\.item\.trigger\.source_name: must be null") as caught:
        _validator().check(_decision(named))                                          # the audit's reproducing input
    assert caught.value.rule == "V1"
    nameless = seat_decision([_trigger(R_HIDDEN_SPRITE, None), swift], kind="choice")
    _face_down_sprite(nameless)
    _validator().check(_decision(nameless))


# C3 (spec 7.1, 6.2; V1 and V2): passing is always legal while holding priority (CR 117.3).


def test_a_priority_decision_offers_pass_first_to_the_seat_holding_priority() -> None:
    with pytest.raises(ValidatorViolation, match=r"candidates\[0\].*pass") as caught:
        _validator().check(_decision(seat_decision([SAMPLES["cast_spell"]])))        # the seat would be forced to act
    assert caught.value.rule == "V1"
    for holder in ("p1", None):                                                       # p1 holds priority, or nobody does
        elsewhere = seat_decision()
        elsewhere["observation"]["priority_seat"] = holder
        with pytest.raises(ValidatorViolation, match="priority_seat") as caught:
            _validator().check(_decision(elsewhere))
        assert caught.value.rule == "V2"                                              # the decision went to the wrong seat
    choice = seat_decision([{**SAMPLES["choose_boolean"]}], kind="choice")
    choice["observation"]["priority_seat"] = "p1"                                     # a choice goes to whoever decides
    _validator().check(_decision(choice))


# I2 (spec 11.3): the live gate runs each V1 check; each defect below is one only that check sees.

COUNTERSPELL = {"object_id": "o-7c7c7c7c7c7c7c7c", "card_name": "Counterspell", "owner_seat": "p1", "controller_seat": "p1",
                "zone": "hand", "full_name": None, "face_down": False, "token": False, "copy": False,
                "characteristics": {"supertypes": [], "types": ["instant"], "subtypes": [], "colors": ["blue"],
                                    "mana_value": 2, "power": None, "toughness": None, "keywords": []},
                "permanent": None, "exiled_by": None}


def _parked_hand_card() -> dict:
    """The other seat's hand card, named, parked in its exile: only the observation schema sees the zone mismatch."""
    sd = seat_decision()
    sd["observation"]["players"][1]["exile"].append(copy.deepcopy(COUNTERSPELL))
    return sd


def _pending_trigger_naming_a_face_down_source() -> dict:
    sd = seat_decision()
    _face_down_sprite(sd)
    sd["observation"]["pending_triggers"] = [{"source": R_HIDDEN_SPRITE, "source_name": "Spellstutter Sprite",
                                              "controller_seat": "p1", "label": None, "optional": False}]
    return sd


@pytest.mark.parametrize(
    ("sd", "detail"),
    [
        (_parked_hand_card(), r"players\[1\]\.exile\[0\]\.zone"),
        (_pending_trigger_naming_a_face_down_source(), r"pending_triggers\[0\]\.source_name"),
        (seat_decision([{**SAMPLES["choose_boolean"], "purpose": "p1_holds_counterspell"}], kind="choice"),
         r"candidates\[0\]\.semantic\.purpose"),
        (seat_decision([SAMPLES["pass"], {**SAMPLES["play_land"], "x_leak": "Counterspell"}]), r"candidates\[1\]\.semantic"),
        (seat_decision([], kind="choice"), "candidates: must have at least 1"),
        (seat_decision([SAMPLES["pass"], SAMPLES["play_land"], SAMPLES["play_land"]]), "duplicates an earlier"),
    ],
    ids=["observation-record-zone", "observation-trigger-name", "candidate-vocabulary", "candidate-field", "no-candidates",
         "duplicate-candidates"],
)
def test_v1_the_live_gate_runs_each_schema_check(sd: dict, detail: str) -> None:
    with pytest.raises(ValidatorViolation, match=detail) as caught:
        _validator().check(_decision(sd))
    assert caught.value.rule == "V1"


# I3 (spec 9.3, 11.3): V10 on terminals.


def test_v10_a_terminal_from_a_drifted_engine_identity() -> None:
    terminal = Terminal.from_json({**TERMINAL, "step_count": 0, "decision_count": 0,
                                   "provenance": {**PROVENANCE, "engine_version": "9.9.9"}})
    with pytest.raises(ValidatorViolation, match="drifted") as caught:
        _validator().check_terminal(terminal)
    assert caught.value.rule == "V10"


# Minor findings through the live gate.


def test_v1_a_library_search_offers_finish_selection() -> None:
    search = {**SAMPLES["select_object"], "source": None, "purpose": "search", "minimum": 0}
    finish = {**SAMPLES["finish_selection"], "source": None, "purpose": "search", "selected_count": 0}
    with pytest.raises(ValidatorViolation, match="finish_selection") as caught:
        _validator().check(_decision(seat_decision([search], kind="choice")))        # finding nothing is not offered (M4)
    assert caught.value.rule == "V1"
    _validator().check(_decision(seat_decision([search, finish], kind="choice")))


def test_v1_a_creature_never_attacks_its_own_controller() -> None:
    own = {**SAMPLES["declare_attack"], "defender": {"player": "p0"}}                 # p0's Swiftspear attacking p0 (M9)
    with pytest.raises(ValidatorViolation, match="own controller") as caught:
        _validator().check(_decision(seat_decision([own], kind="choice")))
    assert caught.value.rule == "V1"


def test_v1_a_pregame_decision_offers_one_kind() -> None:
    starting = [{**SAMPLES["choose_starting_player"], "player": "p0"}, SAMPLES["choose_starting_player"]]
    for candidates in ([MULLIGAN, SAMPLES["choose_boolean"]], [*starting, SAMPLES["choose_boolean"]]):    # M10
        with pytest.raises(ValidatorViolation, match="only") as caught:
            _validator().check(_decision(seat_decision(candidates, kind="choice")))
        assert caught.value.rule == "V1"


def test_v1_one_arrangement_decision_places_one_card() -> None:
    arrange = {**SAMPLES["arrange_card"], "source": None}
    scry = seat_decision([arrange, {**arrange, "destination": "bottom"}], kind="choice")
    scry["group"]["substep_count"] = 3                                                  # scry 2: 2 x 2 - 1 decisions
    _validator().check(_decision(scry))
    for other in ({**arrange, "destination": "bottom", "card_count": 9},               # M10: check_group_shape reads one
                  {**arrange, "destination": "bottom", "card": R_SWIFTSPEAR},
                  SAMPLES["choose_boolean"]):
        mixed = seat_decision([arrange, other], kind="choice")
        mixed["group"]["substep_count"] = 3
        with pytest.raises(ValidatorViolation, match="arrange_card") as caught:
            _validator().check(_decision(mixed))
        assert caught.value.rule == "V1"


def test_v7_an_id_keeps_its_owner() -> None:
    validator = _validator()
    _play(validator, seat_decision([SAMPLES["pass"]]), 0)
    second = seat_decision([SAMPLES["pass"]])
    second.update(seat_step=1, group={"group_id": 1, "substep_index": 0, "substep_count": 1})
    second["observation"]["players"][1]["battlefield"][0].update(owner_seat="p0", card_name="Grizzly Bears")   # M5
    assert _rule(validator, second, step=1) == "V7"


def test_violation_details_quote_engine_values_briefly() -> None:
    long_name = "Black Lotus" + "!" * 5000
    sd = seat_decision([{**SAMPLES["choose_name"], "source": None, "value": long_name}], kind="choice")
    with pytest.raises(ValidatorViolation) as caught:
        _validator().check(_decision(sd))
    assert caught.value.rule == "V1" and len(caught.value.detail) < 300                 # M12: about 64 characters quoted
    assert "'Black Lotus!!!" in caught.value.detail and "..." in caught.value.detail
    assert len(ValidatorViolation("V4", "o-" + "f" * 5000).detail) == 1024              # and every detail is bounded


def test_answered_refuses_a_candidate_id_outside_the_list() -> None:
    validator = _validator()
    sd = seat_decision()
    validator.check(_decision(sd))
    for candidate_id in (-1, 3, True):                                                  # M14
        with pytest.raises(ValueError, match="candidate_id"):
            validator.answered(sd, candidate_id)
    validator.answered(sd, 2)
    assert validator.answered_steps == 1


EXTENSION_RULES = {**RULES, "extensions": ["x_kernel_v5"]}


def _nested(depth: int) -> list:
    payload: list = []
    for _ in range(depth - 1):
        payload = [payload]
    return payload


def _cycle() -> list:
    payload: list = []
    payload.append(payload)
    return payload


@pytest.mark.parametrize(
    "payload",
    [{"score": 1.5}, {"when": float("nan")}, {"count": 1 << 53}, {"name": "\ud800"}, _nested(62), _cycle()],
    ids=["float", "nan", "integer-past-2^53", "lone-surrogate", "nesting-past-64", "cycle"],
)
def test_v1_an_extension_payload_is_json_the_host_can_forward(payload) -> None:
    sd = seat_decision(extensions={"x_kernel_v5": payload})                             # M15: an in-process engine
    with pytest.raises(ValidatorViolation, match=r"extensions: ") as caught:
        _validator(rules=EXTENSION_RULES).check(_decision(sd))
    assert caught.value.rule == "V1"


def test_an_extension_payload_as_deep_as_the_wire_allows_is_accepted() -> None:
    # A forwarded choose request holds the payload at level 4; the wire allows 64 levels (spec 2).
    sd = seat_decision(extensions={"x_kernel_v5": {"view": _nested(60), "ids": ["o-1"], "n": -(1 << 53) + 1}})
    _validator(rules=EXTENSION_RULES).check(_decision(sd))


def test_checks_scoped_to_their_rule_accept_what_lies_outside_it() -> None:
    """M17: a discard need not allow nothing, a named face-down card in exile is not V6's, a single face has no full name."""
    discard = {**SAMPLES["select_object"], "source": None}                              # minimum 1: only a search allows nothing
    _validator().check(_decision(seat_decision([discard], kind="choice")))
    exiled = seat_decision()
    bolt = exiled["observation"]["players"][0]["hand"][0]
    exiled["observation"]["players"][0]["exile"].append(                               # foretold: its owner may look
        {**copy.deepcopy(bolt), "object_id": "o-f0f0f0f0f0f0f0f0", "zone": "exile", "face_down": True})
    exiled["observation"]["players"][1]["exile"].append(                               # an effect lets p0 look (Gonti)
        {**copy.deepcopy(COUNTERSPELL), "zone": "exile", "face_down": True})
    _validator().check(_decision(exiled))
    full_names = {**HELLO_OK, "observation": {**HELLO_OK["observation"], "full_name": True}}
    _validator(hello=full_names).check(_decision(seat_decision()))                    # single-faced cards: full_name null


NAME = {**SAMPLES["choose_name"], "source": None}
BOLT_SPELL = {"object_id": R_STACK["object_id"], "card_name": "Lightning Bolt", "owner_seat": "p0", "controller_seat": "p0",
              "zone": "stack", "stack_kind": "spell", "source": None, "face_down": False, "copy": False,
              "characteristics": {"supertypes": [], "types": ["instant"], "subtypes": [], "colors": ["red"], "mana_value": 1,
                                  "power": None, "toughness": None, "keywords": []},
              "targets": [{"player": "p1"}], "divided": None, "modes": None, "x_value": None, "text": None}


def _offer(*semantics: dict):
    """Pose ``semantics`` as a choice decision instead of the default priority one."""
    def mutate(sd: dict) -> None:
        sd["candidates"] = [{"candidate_id": index, "semantic": copy.deepcopy(semantic), "display_text": None}
                            for index, semantic in enumerate(semantics)]
        sd["context"]["kind"] = "choice"
    return mutate


def _set(where, **changes):
    return lambda sd: where(sd).update(changes)


def _with_spell(**changes):
    return lambda sd: sd["observation"]["stack"].append({**copy.deepcopy(BOLT_SPELL), **changes})


def _group(sd: dict) -> dict:
    return sd["group"]


def _context(sd: dict) -> dict:
    return sd["context"]


def _p0(sd: dict) -> dict:
    return sd["observation"]["players"][0]


_REVEALED_BY_P2 = {"owner_seat": "p2", "zone": "hand", "card_name": "Island", "object_id": None,
                   "position_from_top": None, "position_from_bottom": None, "how": "revealed"}

# M16: checks no other test reached. Each case trips only its own check; without it, another rule would
# report it or the decision would be forwarded.
UNGUARDED = {
    # V1: the envelope, the group and the context.
    "acting_seat not a seat": (lambda sd: sd.update(acting_seat="p2"), "V1"),
    "seat_step a boolean": (lambda sd: sd.update(seat_step=True), "V1"),
    "group with an extra field": (_set(_group, x_extra=0), "V1"),
    "group_id a string": (_set(_group, group_id="0"), "V1"),
    "substep_count a boolean": (_set(_group, substep_count=True), "V1"),
    "substep_index a boolean": (_set(_group, substep_index=False), "V1"),
    "substep_index past the count": (_set(_group, substep_index=1), "V1"),
    "context with an extra field": (_set(_context, x_extra=0), "V1"),
    "context kind outside its vocabulary": (_set(_context, kind="prio"), "V1"),
    "context source not a reference": (_set(_context, source={"object_id": "o-1"}), "V1"),
    "context purpose not snake_case": (_set(_context, purpose="Mana Payment"), "V1"),
    "context text not a string": (_set(_context, text=5), "V1"),
    "context rewind not a boolean": (_set(_context, rewind="yes"), "V1"),
    # V1: the choose_name domains and a known entry's owner.
    "creature type not snake_case": (_offer({**NAME, "purpose": "creature_type", "value": "Faerie"}), "V1"),
    "land type not snake_case": (_offer({**NAME, "purpose": "land_type", "value": "Snow Covered"}), "V1"),
    "basic land type outside the five": (_offer({**NAME, "purpose": "basic_land_type", "value": "wastes"}), "V1"),
    "card type outside the vocabulary": (_offer({**NAME, "purpose": "card_type", "value": "tribal"}), "V1"),
    "known owner not a seat": (lambda sd: sd["observation"]["known"].append(dict(_REVEALED_BY_P2)), "V1"),
    # V1: the spec 7.3 field constraints.
    "cost target minimum above maximum": (_offer({**SAMPLES["choose_cost_target"], "minimum": 2}), "V1"),
    "cost target selected at maximum": (_offer({**SAMPLES["choose_cost_target"], "selected_count": 1}), "V1"),
    "selection minimum above maximum": (_offer({**SAMPLES["select_object"], "minimum": 2}), "V1"),
    "selection selected at maximum": (_offer({**SAMPLES["select_object"], "selected_count": 1}), "V1"),
    "mode minimum above maximum": (_offer({**SAMPLES["choose_spell_mode"], "minimum": 3}), "V1"),
    "mode selected at maximum": (_offer({**SAMPLES["choose_spell_mode"], "selected_count": 2}), "V1"),
    "number below its minimum": (_offer({**SAMPLES["choose_number"], "value": -1}), "V1"),
    "replacement index past its count": (_offer({**SAMPLES["choose_replacement"], "replacement_index": 2}), "V1"),
    # V8: each optional field follows its flag (the example's flags).
    "player counters with the flag off": (_set(_p0, counters={"energy": 1}), "V8"),
    "designations null with the flag on": (_set(_p0, designations=None), "V8"),
    "progress with the flag off": (_set(_p0, progress={"dungeon": None, "dungeon_room": None, "ring_tempted": 0,
                                                       "speed": None}), "V8"),
    "day_night with the flag off": (_set(lambda sd: sd["observation"], day_night="day"), "V8"),
    "pending_triggers null with the flag on": (_set(lambda sd: sd["observation"], pending_triggers=None), "V8"),
    "full_name with the flag off": (_set(lambda sd: _p0(sd)["hand"][0], full_name="Lightning Bolt"), "V8"),
    "chosen null with the flag on": (_set(lambda sd: _p0(sd)["battlefield"][0]["permanent"], chosen=None), "V8"),
    "stack text with the flag off": (_with_spell(text="Lightning Bolt deals 3 damage to any target."), "V8"),
    "stack keywords null with the flag on": (_with_spell(characteristics={**BOLT_SPELL["characteristics"], "keywords": None}),
                                             "V8"),
}


@pytest.mark.parametrize("name", sorted(UNGUARDED))
def test_each_check_is_reported_through_the_gate(name: str) -> None:
    mutate, rule = UNGUARDED[name]
    sd = seat_decision()
    mutate(sd)
    assert _rule(_validator(), sd) == rule


def test_v8_exiled_by_follows_its_flag() -> None:
    hello = {**HELLO_OK, "observation": {**HELLO_OK["observation"], "exiled_by": False}}
    sd = seat_decision()
    sd["observation"]["players"][1]["exile"].append({**copy.deepcopy(COUNTERSPELL), "zone": "exile",
                                                     "exiled_by": R_SWIFTSPEAR})
    assert _rule(_validator(hello=hello), sd) == "V8"
