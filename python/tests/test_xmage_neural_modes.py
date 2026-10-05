"""Mode searches retain their public binding and account for original masked work."""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import xmage_neural_search as search
from xmage_neural_decisions import decision_hash
from test_xmage_neural_search import fixture
from test_xmage_neural_agent import Session, decision, ready, view


def mode_fixture():
    _, result = fixture()
    offered = {"context": {"kind": "choose_spell_mode"}, "candidates": [
        {"candidate_id": cid, "semantic": {"kind": "choose_spell_mode", "source": {"object_id": "spell"},
                                           "mode_index": index, "mode_count": 2,
                                           "selected_count": 0, "minimum": 1, "maximum": 1}}
        for cid, index in ((7, 0), (3, 1))]}
    result.update(decision_sha256=decision_hash(offered), root_visits=4, neural_calls=2,
                  selection={"candidate_id": 3, "semantic_echo": offered["candidates"][1]["semantic"]},
                  children=[{"semantic": candidate["semantic"], "visits": index + 1, "value": 0.2}
                            for index, candidate in enumerate(offered["candidates"])],
                  unoffered_mode_branches=[{"ordinal": 0, "mode_index": -1, "visits": 0,
                                           "pruned": False, "selection_masked": True, "discarded_visits": 1,
                                           "reason": "original mode branch is unoffered and has no legal future"}])
    return offered, result


def test_original_unoffered_stop_keeps_its_spent_work_and_cannot_be_chosen():
    offered, result = mode_fixture()
    assert search.root_family(offered) == "mode"
    search.validate_result(offered, result, 4, 2)
    bad = copy.deepcopy(result)
    bad["selection"] = {"candidate_id": 99, "semantic_echo": {"kind": "finish_selection", "purpose": "modes"}}
    with pytest.raises(ValueError, match="unoffered"):
        search.validate_result(offered, bad, 4, 2)


@pytest.mark.parametrize("mutation", ["lost-work", "extra-work", "retained", "pruned-work", "aliased", "wrong-ordinal",
                                     "offered-index", "positive-visits", "wrong-reason", "different-family"])
def test_internal_branches_cannot_hide_work_or_a_retained_unoffered_action(mutation):
    offered, result = mode_fixture()
    branch = result["unoffered_mode_branches"][0]
    if mutation == "lost-work":
        result["unoffered_mode_branches"] = []
    elif mutation == "extra-work":
        branch["discarded_visits"] = 2
    elif mutation == "retained":
        branch["selection_masked"] = False
    elif mutation == "pruned-work":
        branch.update(selection_masked=False, pruned=True)
    elif mutation == "aliased":
        result["unoffered_mode_branches"].append(copy.deepcopy(branch))
    elif mutation == "wrong-ordinal":
        branch["ordinal"] = 1
    elif mutation == "offered-index":
        branch.update(ordinal=1, mode_index=0)
    elif mutation == "positive-visits":
        branch["visits"] = 1
    elif mutation == "wrong-reason":
        branch["reason"] = "uncaptured pruning"
    else:
        offered["context"]["kind"] = "priority"
        result["decision_sha256"] = decision_hash(offered)
    with pytest.raises(ValueError):
        search.validate_result(offered, result, 4, 2)


def test_offered_stop_cannot_also_be_an_internal_unoffered_branch():
    offered, result = mode_fixture()
    offered["candidates"].append({"candidate_id": 8, "semantic": {"kind": "finish_selection", "purpose": "modes"}})
    with pytest.raises(ValueError, match="unoffered mode branch"):
        search.validate_unoffered_modes(offered, result, 4)


def test_modes_and_target_finishes_remain_distinct_families():
    assert search.root_family({"candidates": [{"semantic": {"kind": "finish_selection", "purpose": "modes"}}]}) == "mode"
    assert search.root_family({"candidates": [{"semantic": {"kind": "finish_selection", "purpose": "search"}}]}) == "target"
    with pytest.raises(ValueError):
        search.root_family({"candidates": [{"semantic": {"kind": "choose_spell_mode"}},
                                           {"semantic": {"kind": "finish_selection", "purpose": "search"}}]})


def test_selected_mode_is_replayed_before_later_target_and_uses_the_same_own_cast():
    bot, session = ready(Session([1, 1, 0]))
    bot.choose(view(decision({"kind": "pass"}, {"kind": "cast_spell", "source": {"object_id": "spell"}})))
    offered, _ = mode_fixture()
    modes = decision(*(c["semantic"] for c in offered["candidates"]), step=1)
    assert bot.choose(view(modes)) == 11
    target = decision({"kind": "choose_target", "target": {"player": "p0"}},
                      {"kind": "choose_target", "target": {"player": "p1"}}, step=2)
    assert bot.choose(view(target)) == 10
    replay = session.requests[-1][0]
    assert replay["anchor"]["selection"]["semantic_echo"]["kind"] == "cast_spell"
    assert replay["replay"]["earlier"][0]["selection"]["semantic_echo"]["mode_index"] == 1
    bot.close()
