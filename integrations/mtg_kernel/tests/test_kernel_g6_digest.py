"""G6 point digests: a known-hand divergence is told apart from a drifted state.

The fixture holds two real point pairs from the W1 soak shake-out (kernel
4badeac06, deterministic rerun): the walk's point on the imported state and
the committed point, whose full digests differ (the receipts failed
``plans_match``) only in V's knowledge of the opponent's hand.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kernel_flat_bot as flat
import kernel_g6_digest as g6

CASES = json.loads((Path(__file__).parent / "fixtures" / "g6_known_hand_points.json").read_text(encoding="utf-8"))["cases"]


def test_the_mask_belongs_to_the_flat_bots_encoding():
    assert g6.MASK_ENCODING_DIGEST == flat.FEATURE_ENCODING_DIGEST


@pytest.mark.parametrize("case", CASES, ids=[c["game_id"] for c in CASES])
def test_soak_points_differ_only_in_the_known_opponent_hand(case):
    walk, committed = case["walk"], case["committed"]
    assert g6.tensor_digest(walk["tensor"]) == case["walk_digest"]
    assert g6.tensor_digest(committed["tensor"]) == case["committed_digest"]
    assert case["walk_digest"] != case["committed_digest"]
    masked = g6.known_hand_masked_digest(walk)
    assert masked is not None and masked == g6.known_hand_masked_digest(committed)


def _kept_edge_feature(tensor):
    """The first feature of the first edge outside the known opponent hand."""
    groups, width = tensor["object_groups"], len(tensor["edge_features"]) // len(tensor["edge_source_indices"])
    j = next(j for j, x in enumerate(tensor["edge_source_indices"]) if groups[x] != g6.KNOWN_OPPONENT_HAND)
    return j * width


@pytest.mark.parametrize("field,index", [("object_features", 0), ("action_features", 0), ("state", 0),
                                         ("state", 70), ("state", 122), ("edge_features", None)])
def test_any_other_difference_still_differs(field, index):
    case = CASES[0]
    drifted = copy.deepcopy(case["walk"])
    t = drifted["tensor"]
    t[field][_kept_edge_feature(t) if index is None else index] ^= 1
    assert g6.known_hand_masked_digest(drifted) != g6.known_hand_masked_digest(case["committed"])


def test_a_card_outside_the_known_hand_still_differs():
    drifted = copy.deepcopy(CASES[0]["walk"])
    groups = drifted["tensor"]["object_groups"]
    first = groups.index(g6.KNOWN_OPPONENT_HAND)
    groups[first] = 2  # the same card counted on the opponent's battlefield instead
    assert g6.known_hand_masked_digest(drifted) is None  # the count in the state no longer matches
    drifted["tensor"]["state"][g6.STATE_KNOWN_OPPONENT_HAND] = g6._f32_bits(groups.count(18) / 16.0)
    assert g6.known_hand_masked_digest(drifted) not in (None, g6.known_hand_masked_digest(CASES[0]["committed"]))


def test_other_encodings_and_shapes_are_not_masked():
    walk = CASES[0]["walk"]
    assert g6.known_hand_masked_digest({**walk, "feature_encoding_digest": "0" * 64}) is None
    short = copy.deepcopy(walk)
    short["tensor"]["state"] = short["tensor"]["state"][:-1]
    assert g6.known_hand_masked_digest(short) is None
    referenced = copy.deepcopy(walk)
    t = referenced["tensor"]
    t["action_ref_node_indices"][0] = t["object_groups"].index(g6.KNOWN_OPPONENT_HAND)
    assert g6.known_hand_masked_digest(referenced) is None  # an action names a known-hand object
    assert g6.known_hand_masked_digest({"feature_encoding_digest": g6.MASK_ENCODING_DIGEST, "tensor": None}) is None


def _reconcile(tmp_path, walk_masked, committed_masked):
    """plans_match for one walked group whose full tensor digests differ."""
    import entrant_availability
    (tmp_path / "g-x.bridge.json").write_text(json.dumps({
        "receipt": "x_kernel_infoset_v1", "game_id": "g-x", "eligible": [1, 0],
        "tally": [{"by_code": {}, "by_subclass": {}}, {"by_code": {}}], "order_map_missing": [0, 0]}))
    group = {"type": "SelectionOrder", "root_seat": "p0", "points": 1, "composition": True, "witness": {},
             "views_equal": True, "keys_equal": True, "committed_keys": ["k"], "expected_keys": ["k"],
             "committed_tensors": ["native"], "committed_masked_tensors": committed_masked}
    (tmp_path / "g-x.adapter.json").write_text(json.dumps({
        "receipt": "x_kernel_infoset_v1_adapter", "game_id": "g-x", "native_seats": {"p0": "p0", "p1": "p1"},
        "composition": {}, "internal": {}, "groups": [group]}))
    plan = {"kind": "group_plan", "mode": "walk", "step": 7, "plan": ["k"], "tensors": ["imported"], "wire": [0]}
    if walk_masked is not None:
        plan["masked_tensors"] = walk_masked
    final = {"tally": {}, "eligible": 1}
    return entrant_availability._reconcile(tmp_path, "g-x", "p0", final, [plan])


def test_plans_match_accepts_a_known_hand_divergence_and_reports_it(tmp_path):
    out = _reconcile(tmp_path, ["m"], ["m"])
    assert out["plans_match"] and out["reconciled"]
    assert out["known_hand_divergent_points"] == [{"step": 7, "point": 0}]


@pytest.mark.parametrize("walk,committed", [(["m"], ["other"]), (None, ["m"]), (["m"], None),
                                            ([None], [None]), ([], ["m"])])
def test_plans_match_fails_without_equal_masked_digests(tmp_path, walk, committed):
    # A drifted state, logs or receipts written before the masked digests,
    # or an encoding the mask does not cover: the full digests decide.
    out = _reconcile(tmp_path, walk, committed)
    assert not out["plans_match"] and not out["reconciled"]
