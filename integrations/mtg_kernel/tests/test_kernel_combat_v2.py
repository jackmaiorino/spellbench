"""No blocker choice may create a dead-end aggregate declaration."""
import importlib.util
import itertools
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
spec = importlib.util.spec_from_file_location("kernel_combat_v2", Path(__file__).parents[1] / "kernel_combat_v2.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
BlockPlan = module.BlockPlan


def test_one_menace_blocker_never_offers_an_illegal_single_block():
    plan = BlockPlan(("b",), {"b": ("a",)}, {"a": 2})
    assert plan.choices(()) == (None,)


def test_completed_binding_refuses_a_foreign_game_declaration_or_blocker():
    binding = module.NativeBlockBinding("g", "root", {"blocker": None}, {"blocker": ("attacker",)})
    view = {"game_id": "g", "extensions": {"x_kernel_v2_support": {"block_declaration_instance": "root"},
            "x_kernel_flat_v4": {"row_candidate_ids": [0, 1]}}, "candidates": [
        {"candidate_id": index, "semantic": {"kind": "choose_blocker_inclusion", "include": include,
         "blocker": {"object_id": "blocker"}, "attacker": {"object_id": "attacker"}}}
        for index, include in enumerate((False, True))]}
    assert module.native_block_pick(view, binding) == 0
    view["game_id"] = "foreign"
    with pytest.raises(module.CombatError, match="another game"):
        module.native_block_pick(view, binding)
    view["game_id"] = "g"
    view["extensions"]["x_kernel_v2_support"]["block_declaration_instance"] = "later"
    with pytest.raises(module.CombatError, match="another game"):
        module.native_block_pick(view, binding)
    view["extensions"]["x_kernel_v2_support"]["block_declaration_instance"] = "root"
    view["candidates"][0]["semantic"]["blocker"]["object_id"] = "foreign"
    with pytest.raises(module.CombatError, match="absent"):
        module.native_block_pick(view, binding)


def test_a_later_untouched_attacker_is_not_accepted_as_the_declaration_root():
    with pytest.raises(module.CombatError, match="root marker"):
        module.native_block_plan({"projection": {"surface_context": {"private_blockers": {}},
            "policy_surface_context": {"private_combat_selection": {}}}},
            {"at_block_root": False, "block_declaration_instance": "root"}, None)


def test_a_public_zero_minimum_reads_as_one_like_the_native_engine():
    # a bestowed Nyxborn Hydra attacks with minimum_blockers 0 (2026-10-06 smoke halt)
    assert module.public_minimum(0) == 1 and module.public_minimum(2) == 2
    for bad in (-1, None, True, 1.0):
        with pytest.raises(module.CombatError, match="invalid minimum"):
            module.public_minimum(bad)
    plan = BlockPlan(("b",), {"b": ("a",)}, {"a": module.public_minimum(0)})
    assert plan.choices(()) == (None, "a")


def test_lone_remaining_blocker_is_forced_to_complete_menace():
    plan = BlockPlan(("b0", "b1"), {"b0": ("a",), "b1": ("a",)}, {"a": 2})
    assert plan.choices(()) == (None, "a")
    assert plan.choices(("a",)) == ("a",)
    assert plan.completion(("a",)) == ("a", "a")


def test_shared_blocker_cannot_fill_two_separate_deficits():
    plan = BlockPlan(("b0", "b1", "last"),
                     {"b0": ("a",), "b1": ("c",), "last": ("a", "c")}, {"a": 2, "c": 2})
    assert plan.completion(("a", "c")) is None
    assert plan.choices(("a",)) == (None,)


def test_each_blocker_is_offered_once_with_all_extendable_attackers():
    plan = BlockPlan(("b0", "b1"), {"b0": ("a", "c"), "b1": ("a", "c")}, {"a": 1, "c": 1})
    assert plan.choices(()) == (None, "a", "c")
    assert plan.choices(("a",)) == (None, "a", "c")


def test_matching_agrees_with_exhaustive_aggregate_legality():
    # All 64 graphs between three blockers and two attackers. Independent
    # exhaustive final assignments catch shared-capacity and zero-block cases.
    blockers = (0, 1, 2)
    for bits in range(64):
        edges = {b: tuple(a for i, a in enumerate(("a", "c")) if bits & (1 << (2*b+i))) for b in blockers}
        plan = BlockPlan(blockers, edges, {"a": 2, "c": 2})
        assignments = list(itertools.product(*(tuple([None]) + edges[b] for b in blockers)))
        valid = [assignment for assignment in assignments
                 if all(assignment.count(a) in (0, 2, 3) for a in ("a", "c"))]
        for length in range(3):
            for prefix in set(assignment[:length] for assignment in assignments):
                expected = tuple(choice for choice in (None,) + edges[blockers[length]]
                                 if any(assignment[:length+1] == prefix + (choice,) for assignment in valid))
                if expected:
                    assert plan.choices(prefix) == expected
                else:
                    with pytest.raises(module.CombatError, match="no legal completion"):
                        plan.choices(prefix)
