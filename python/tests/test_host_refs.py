"""V2, V4 and V6 (spec 5.1, 6.8, 11.3)."""

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


def test_v6_face_down_names_are_hidden_from_other_seats() -> None:
    leak = seat_decision()
    leak["observation"]["players"][1]["battlefield"][0]["face_down"] = True   # p1's face-down Sprite, still named
    assert _rule(check_face_down, leak) == "V6"
    own = seat_decision()
    own["observation"]["players"][0]["battlefield"][0]["face_down"] = True    # the viewer's own: it may look (CR 708.5)
    check_face_down(own)
