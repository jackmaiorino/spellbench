import itertools
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
from kernel_arrangement_v2 import Arrangement, ArrangementError, native_arrangement_binding, native_arrangement_pick
from spellbench.candidates import validate_semantic


def cards(n):
    return tuple({"object_id": f"look-{i}", "card_name": f"Card {i}", "owner_seat": "p0",
                  "controller_seat": "p0", "zone": "library"} for i in range(n))


def test_all_scry_partitions_have_the_same_fixed_group_shape():
    for n in range(1, 6):
        for partition in itertools.product(("top", "bottom"), repeat=n):
            plan = Arrangement(cards(n), source=None, purpose="scry", destinations=(("top", "bottom"),) * n)
            seen = []
            for destination in partition:
                options = plan.semantics()
                for semantic in options:
                    validate_semantic(semantic)
                seen.append(options)
                index = next(i for i, semantic in enumerate(options) if semantic["destination"] == destination)
                plan.choose(index)
            while not plan.finished:
                options = plan.semantics()
                seen.append(options)
                for semantic in options:
                    validate_semantic(semantic)
                plan.choose(0)
            assert len(seen) == 2*n - 1
            assert len(plan.result()["top"]) == partition.count("top")
            assert len(plan.result()["bottom"]) == partition.count("bottom")
            assert set(plan.result()["top"] + plan.result()["bottom"]) == {card["object_id"] for card in cards(n)}


def test_singletons_of_earlier_destination_blocks_are_explicit():
    plan = Arrangement(cards(2), source=None, purpose="scry", destinations=(("top",), ("bottom",)))
    assert len(plan.semantics()) == 1
    plan.choose(0)
    plan.choose(0)
    pick = plan.semantics()
    assert len(pick) == 1
    assert pick[0]["item"]["object"]["object_id"] == "look-0"
    assert pick[0]["position"] == 0 and pick[0]["count"] == 2
    assert plan.choose(0)
    assert plan.result()["bottom"] == ("look-1",)


def test_dig_completion_enforces_hand_bounds_and_matching_cards():
    plan = Arrangement(cards(3), source=None, purpose="dig",
                       destinations=(("bottom", "hand"), ("bottom",), ("bottom", "hand")),
                       hand_minimum=1, hand_maximum=1)
    plan.choose(0)  # first matching card sent to bottom
    assert [s["destination"] for s in plan.semantics()] == ["bottom"]
    plan.choose(0)
    assert [s["destination"] for s in plan.semantics()] == ["hand"]
    plan.choose(0)
    while not plan.finished:
        plan.choose(0)
    assert plan.result()["hand"] == ("look-2",)


def test_unfinished_plan_cannot_be_committed_and_completed_plan_cannot_change():
    plan = Arrangement(cards(1), source=None, purpose="look_at_top", destinations=(("top",),))
    with pytest.raises(ArrangementError, match="unfinished"):
        plan.result()
    assert plan.choose(0)
    assert plan.result()["top"] == ("look-0",)
    with pytest.raises(ArrangementError, match="already complete"):
        plan.choose(0)


def test_native_look_reverses_old_deepest_first_picks_and_obeys_row_binding():
    import json
    candidates = [{"candidate_id": i, "semantic": {"kind": "choose_effect_target", "target": {
        "object": {"object_id": f"native-{i}"}}}} for i in range(3)]
    view = {"game_id": "game", "candidates": candidates, "extensions": {
        "x_kernel_v2_support": {"effect_instance": "effect-1", "choice": {"purpose": "look", "stage": "top_order"}},
        "x_kernel_flat_v4": {"row_candidate_ids": [0, 1, 2]},
        "x_kernel_v5": {"observation_json": json.dumps({"projection": {"engine_context": {
            "pending_effect": {"choice": {"selected_targets": []}}}}})}}}
    result = {"top": ("neutral-0", "neutral-1", "neutral-2")}
    binding = native_arrangement_binding(view, {f"neutral-{i}": f"native-{i}" for i in range(3)})
    assert native_arrangement_pick(view, result, binding) == 2
    view["extensions"]["x_kernel_flat_v4"]["row_candidate_ids"] = [0, 1]
    with pytest.raises(ArrangementError, match="one native row"):
        native_arrangement_pick(view, result, binding)
    view["extensions"]["x_kernel_v2_support"]["effect_instance"] = "effect-2"
    with pytest.raises(ArrangementError, match="another game or effect"):
        native_arrangement_pick(view, result, binding)
