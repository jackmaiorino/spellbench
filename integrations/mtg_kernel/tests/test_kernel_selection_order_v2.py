import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
from kernel_selection_order_v2 import SelectionOrder
from spellbench.candidates import validate_semantic


def cards(n):
    return [{"object_id": str(i), "card_name": f"Card {i}", "owner_seat": "p0",
             "controller_seat": "p0", "zone": "hand"} for i in range(n)]


def test_brainstorm_selection_and_ordering_are_independent_fixed_groups():
    plan = SelectionOrder(cards(3), source=None, count=2, destination="top", select=True)
    assert (plan.substep_index, plan.substep_count) == (0, 2)
    assert not plan.choose(0)
    assert (plan.substep_index, plan.substep_count) == (1, 2)
    assert not plan.choose(0)
    assert (plan.substep_index, plan.substep_count) == (0, 1)
    assert [s["kind"] for s in plan.semantics()] == ["order_pick"] * 2
    assert plan.choose(1)
    assert plan.result() == {"top": ("1", "0")}


def test_forced_whole_hand_selection_poses_every_pick():
    plan = SelectionOrder(cards(2), source=None, count=2, destination="top", select=True)
    assert not plan.choose(0)
    assert len(plan.semantics()) == 1
    assert not plan.choose(0)
    assert plan.choose(0)
    assert plan.result() == {"top": ("0", "1")}


def test_pure_mill_has_n_minus_one_order_picks_and_keeps_native_graveyard_direction():
    plan = SelectionOrder(cards(3), source=None, count=3, destination="graveyard", select=False)
    assert plan.substep_count == 2
    assert not plan.choose(2)
    assert plan.choose(0)
    assert plan.result() == {"graveyard": ("2", "0", "1")}


def test_single_card_selection_has_no_ordering_decision():
    plan = SelectionOrder(cards(1), source=None, count=1, destination="graveyard", select=True,
                          selection_purpose="discard")
    for semantic in plan.semantics():
        validate_semantic(semantic)
    assert plan.choose(0)
    assert plan.result() == {"graveyard": ("0",)}


def test_incomplete_plan_cannot_commit():
    plan = SelectionOrder(cards(2), source=None, count=2, destination="top", select=True)
    with pytest.raises(ValueError, match="incomplete"):
        plan.result()
