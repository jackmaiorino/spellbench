"""V2, V4 and V6 (spec 5.1, 6.8, 11.3)."""

import copy

import pytest

from spellbench.host.refs import check_face_down, check_references, check_seat
from spellbench.host.violation import ValidatorViolation

from v2_sample_semantics import R_BOLT, R_STACK, R_SWIFTSPEAR, SAMPLES, seat_decision


def _rule(check, decision) -> str:
    with pytest.raises(ValidatorViolation) as caught:
        check(decision)
    return caught.value.rule


def test_a_consistent_decision_passes() -> None:
    decision = seat_decision()
    check_seat(decision)
    check_references(decision)
    check_face_down(decision)


def test_v2_the_viewer_is_the_acting_seat() -> None:
    assert _rule(check_seat, seat_decision(acting_seat="p1")) == "V2"


def test_v2_a_priority_decision_goes_to_the_seat_holding_priority() -> None:
    decision = seat_decision()
    decision["observation"]["priority_seat"] = "p1"
    with pytest.raises(ValidatorViolation, match="priority_seat p1 is not acting_seat p0") as caught:
        check_seat(decision)
    assert caught.value.rule == "V2"
    choice = seat_decision([SAMPLES["choose_boolean"]], kind="choice")
    choice["observation"]["priority_seat"] = "p1"                             # a choice goes to whoever decides
    check_seat(choice)


@pytest.mark.parametrize(
    "decision",
    [
        seat_decision([SAMPLES["pass"], {**SAMPLES["cast_spell"], "source": {**R_BOLT, "card_name": "Chain Lightning"}}]),
        seat_decision([SAMPLES["pass"], {**SAMPLES["cast_spell"], "source": {**R_BOLT, "zone": "graveyard"}}]),
        seat_decision([SAMPLES["pass"], {**SAMPLES["activate_ability"], "source": {**R_SWIFTSPEAR, "controller_seat": "p1"}}]),
        seat_decision([SAMPLES["choose_target"]], kind="choice"),          # its source is a stack entry that is not held
        seat_decision(source=R_STACK),                                      # context.source absent too
    ],
)
def test_v4_references_equal_the_held_object(decision: dict) -> None:
    assert _rule(check_references, decision) == "V4"


def test_v4_ids_are_unique_and_observation_links_are_checked() -> None:
    duplicate = seat_decision()
    duplicate["observation"]["players"][0]["hand"][1]["object_id"] = R_BOLT["object_id"]
    assert _rule(check_references, duplicate) == "V4"
    stale_block = seat_decision()
    sprite = stale_block["observation"]["players"][1]["battlefield"][0]
    swift = stale_block["observation"]["players"][0]["battlefield"][0]
    swift["permanent"].update(attacking=True, attack_target={"player": "p1"})
    sprite["permanent"].update(blocking=True, blocked_attackers=[{**R_SWIFTSPEAR, "card_name": "Goblin Guide"}])
    assert _rule(check_references, stale_block) == "V4"


def test_v4_a_byte_identical_duplicate_id_fails_on_uniqueness_alone() -> None:
    decision = seat_decision([SAMPLES["pass"]])   # no candidate references either copy
    hand = decision["observation"]["players"][0]["hand"]
    hand.append(copy.deepcopy(hand[0]))           # two records, one id, every other field consistent
    with pytest.raises(ValidatorViolation, match="appears twice"):
        check_references(decision)


def test_v6_face_down_names_are_hidden_from_other_seats() -> None:
    leak = seat_decision()
    leak["observation"]["players"][1]["battlefield"][0]["face_down"] = True   # p1's face-down Sprite, still named
    assert _rule(check_face_down, leak) == "V6"
    own = seat_decision()
    own["observation"]["players"][0]["battlefield"][0]["face_down"] = True    # the viewer's own: it may look (CR 708.5)
    check_face_down(own)


def test_v6_a_face_down_record_hides_its_full_name_too() -> None:
    leak = seat_decision()
    sprite = leak["observation"]["players"][1]["battlefield"][0]
    sprite.update(face_down=True, card_name=None, full_name="Spellstutter Sprite")   # only full_name leaks
    with pytest.raises(ValidatorViolation, match=r"\.full_name"):
        check_face_down(leak)


def _stack_spell(**overrides) -> dict:
    entry = {
        "object_id": "o-8c1d2e3f4a5b6c7d", "card_name": "Lightning Bolt", "owner_seat": "p1", "controller_seat": "p1",
        "zone": "stack", "stack_kind": "spell", "source": None, "face_down": True, "copy": False,
        "characteristics": {"supertypes": [], "types": ["instant"], "subtypes": [], "colors": ["red"],
                            "mana_value": 1, "power": None, "toughness": None, "keywords": []},
        "targets": [], "divided": None, "modes": None, "x_value": None, "text": None,
    }
    entry.update(overrides)
    return entry


def test_v6_face_down_stack_entries_are_hidden_from_other_seats() -> None:
    leak = seat_decision()
    leak["observation"]["stack"].append(_stack_spell())           # p1's face-down spell, still named
    assert _rule(check_face_down, leak) == "V6"
    own = seat_decision()
    own["observation"]["stack"].append(_stack_spell(owner_seat="p0", controller_seat="p0"))   # the viewer's own
    check_face_down(own)


FACE_DOWN = {"supertypes": [], "types": ["creature"], "subtypes": [], "colors": [], "mana_value": 0, "power": 2,
             "toughness": 2, "keywords": []}


def _morph(**characteristics) -> dict:
    """p0's view of p1's Sprite turned face down, with ``characteristics`` over the face-down 2/2 (spec 6.4)."""
    decision = seat_decision()
    decision["observation"]["players"][1]["battlefield"][0].update(
        face_down=True, card_name=None, full_name=None, characteristics={**FACE_DOWN, **characteristics})
    return decision


def test_v6_a_face_down_permanent_shows_only_the_face_down_characteristics() -> None:
    for keywords in ([], ["ward"], None):                                      # null under a keywords flag that is off
        check_face_down(_morph(keywords=keywords))
    check_face_down(_morph(power=4, toughness=1))                              # counters and effects apply
    for printed in ({"mana_value": 2}, {"colors": ["blue"]}, {"keywords": ["flash"]}, {"subtypes": ["faerie"]}):
        with pytest.raises(ValidatorViolation, match="characteristics") as caught:
            check_face_down(_morph(**printed))
        assert caught.value.rule == "V6"
    stolen = _morph(mana_value=2)                                              # the viewer controls it: it may look
    stolen["observation"]["players"][1]["battlefield"][0]["controller_seat"] = "p0"
    stolen["observation"]["players"][0]["battlefield"].append(stolen["observation"]["players"][1]["battlefield"].pop())
    check_face_down(stolen)


def test_v6_a_face_down_spell_chooses_nothing_that_identifies_it() -> None:
    hidden = seat_decision()
    hidden["observation"]["stack"].append(_stack_spell(card_name=None, characteristics=dict(FACE_DOWN)))
    check_face_down(hidden)
    for choice in ({"x_value": 2}, {"modes": [1]}, {"targets": [None]}, {"divided": [3]}):
        chosen = seat_decision()
        chosen["observation"]["stack"].append(_stack_spell(card_name=None, characteristics=dict(FACE_DOWN), **choice))
        assert _rule(check_face_down, chosen) == "V6"
