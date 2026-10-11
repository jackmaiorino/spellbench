"""Only public, observed native resolutions may seed transient effect history."""
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
from xmage_neural_agent import PublicHistory
from xmage_public_effects import PublicEffects, battlefield, resolution

FIXTURE = Path(__file__).parents[2] / "engines/xmage/tests/stack-text/temporary-effects-public-replay.json"


def fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_saved_public_resolutions_reproduce_only_anchor_history():
    data = fixture()
    history = PublicHistory("p0")
    for view in data["visible_resolutions"]:
        history.observe(view)
    anchor = data["record"]["anchor"]["decision"]
    history.observe(anchor["observation"])
    assert history.fields(anchor["observation"])["public_effects"] == anchor["x_history"]["public_effects"]
    for effect in history.effects.fields():
        assert set(effect) == {"kind", "viewer", "turn", "phase_step", "stack_before", "stack_after",
                               "before", "after", "battlefield_before", "battlefield_after"}
    # Repeated observation cannot apply the same disappearance twice.
    history.observe(anchor["observation"])
    assert len(history.effects.fields()) == 2


@pytest.mark.parametrize("mutation", ["counter", "attachment", "other_permanent", "power", "source", "turn", "phase"])
def test_unproved_or_contradictory_changes_do_not_seed_effects(mutation):
    before, after, _ = fixture()["visible_resolutions"]
    source = before["stack"][-1]["source"]["object_id"]
    target = battlefield(after)[source]
    if mutation == "counter":
        target["permanent"]["counters"]["+1/+1"] = 1
    elif mutation == "attachment":
        target["permanent"]["attached_to"] = {"object_id": "other"}
    elif mutation == "other_permanent":
        after["players"][0]["battlefield"].pop(0)
    elif mutation == "power":
        target["characteristics"]["power"] += 1
    elif mutation == "source":
        before["stack"][-1]["source"]["object_id"] = "unknown"
    elif mutation == "turn":
        after["turn"] += 1
    elif mutation == "phase":
        after["phase_step"] = "postcombat_main"
    assert resolution(before, after) is None


def test_turn_change_and_departure_retire_witness_but_cleanup_discard_retains_it():
    views = fixture()["visible_resolutions"]
    history = PublicEffects("p0")
    for view in views:
        history.observe(view)
    cleanup = copy.deepcopy(views[-1])
    cleanup["phase_step"] = "cleanup"
    history.observe(cleanup)
    assert len(history.fields()) == 2  # discard precedes native removeEotEffects
    departed = copy.deepcopy(cleanup)
    departed["players"][0]["battlefield"] = [card for card in departed["players"][0]["battlefield"]
                                              if card["card_name"] != "Heartfire Immolator"]
    history.observe(departed)
    assert [effect["kind"] for effect in history.fields()] == ["fleeting_distraction"]
    reentered = copy.deepcopy(cleanup)
    for card in reentered["players"][0]["battlefield"]:
        if card["card_name"] == "Heartfire Immolator":
            card["object_id"] = "fresh-entry-id"
    history.observe(reentered)
    assert len(history.fields()) == 1
    reentered["turn"] += 1
    history.observe(reentered)
    assert history.fields() == []


def test_distinct_prowess_occurrences_accumulate_without_duplicate_resolution():
    before, after, _ = fixture()["visible_resolutions"]
    history = PublicEffects("p0")
    history.observe(before)
    history.observe(after)
    again = copy.deepcopy(after)
    again["stack"].append(copy.deepcopy(before["stack"][-1]))
    again["stack"][-1]["object_id"] = "second-public-trigger"
    history.observe(again)
    resolved = copy.deepcopy(after)
    target = battlefield(resolved)[again["stack"][-1]["source"]["object_id"]]
    target["characteristics"]["power"] += 1
    target["characteristics"]["toughness"] += 1
    history.observe(resolved)
    assert len(history.fields()) == 2
    history.observe(resolved)
    assert len(history.fields()) == 2


def test_another_viewer_is_refused():
    with pytest.raises(ValueError, match="another viewer"):
        PublicEffects("p1").observe(fixture()["visible_resolutions"][0])
