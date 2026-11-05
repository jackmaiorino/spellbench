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
    hands = g6.known_hand_digest(walk), g6.known_hand_digest(committed)
    assert None not in hands and hands[0] != hands[1]


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


def _reconcile(tmp_path, walk_masked, committed_masked, walk_hands=("h1",), committed_hands=("h2",)):
    """plans_match for one walked group whose full tensor digests differ."""
    import entrant_availability
    (tmp_path / "g-x.bridge.json").write_text(json.dumps({
        "receipt": "x_kernel_infoset_v1", "game_id": "g-x", "eligible": [1, 0],
        "tally": [{"by_code": {}, "by_subclass": {}}, {"by_code": {}}], "order_map_missing": [0, 0]}))
    group = {"type": "SelectionOrder", "root_seat": "p0", "points": 1, "composition": True, "witness": {},
             "views_equal": True, "keys_equal": True, "committed_keys": ["k"], "expected_keys": ["k"],
             "committed_tensors": ["native"], "committed_masked_tensors": committed_masked,
             "committed_known_hands": list(committed_hands)}
    (tmp_path / "g-x.adapter.json").write_text(json.dumps({
        "receipt": "x_kernel_infoset_v1_adapter", "game_id": "g-x", "native_seats": {"p0": "p0", "p1": "p1"},
        "composition": {}, "internal": {}, "groups": [group]}))
    plan = {"kind": "group_plan", "mode": "walk", "step": 7, "plan": ["k"], "tensors": ["imported"], "wire": [0],
            "known_hands": list(walk_hands)}
    if walk_masked is not None:
        plan["masked_tensors"] = walk_masked
    final = {"tally": {}, "eligible": 1}
    return entrant_availability._reconcile(tmp_path, "g-x", "p0", final, [plan])


POINT = [{"step": 7, "point": 0}]


def test_a_known_hand_divergence_fails_and_is_classified(tmp_path):
    # Review round 2: the observation digest is not verified without the
    # known hand, so G6 fails; the report names the class.
    out = _reconcile(tmp_path, ["m"], ["m"])
    assert not out["plans_match"] and not out["reconciled"]
    assert out["known_hand_divergent_points"] == POINT and out["drifted_points"] == []


@pytest.mark.parametrize("case", CASES, ids=[c["game_id"] for c in CASES])
def test_the_soak_points_classify_as_known_hand_divergences(tmp_path, case):
    w, c = case["walk"], case["committed"]
    out = _reconcile(tmp_path, [g6.known_hand_masked_digest(w)], [g6.known_hand_masked_digest(c)],
                     (g6.known_hand_digest(w),), (g6.known_hand_digest(c),))
    assert not out["plans_match"] and out["known_hand_divergent_points"] == POINT


@pytest.mark.parametrize("walk,committed,walk_hands,committed_hands", [
    (["m"], ["other"], ("h1",), ("h2",)),  # a drift beside a known-hand difference
    (None, ["m"], ("h1",), ("h2",)),  # a log without masked digests
    (["m"], None, ("h1",), ("h2",)),  # a receipt without masked digests
    ([None], [None], ("h1",), ("h2",)),  # an encoding the mask does not cover
    ([], ["m"], ("h1",), ("h2",)),
    (["m"], ["m"], ("h",), ("h",)),  # the same known hand: the rest drifted
    (["m"], ["m"], (), ("h",)),
])
def test_other_differences_are_drifts(tmp_path, walk, committed, walk_hands, committed_hands):
    out = _reconcile(tmp_path, walk, committed, walk_hands, committed_hands)
    assert not out["plans_match"] and out["drifted_points"] == POINT and out["known_hand_divergent_points"] == []


def test_a_known_hand_divergence_with_observation_drift_still_fails(tmp_path):
    # Review round 2: a real divergence plus a flipped observation digest
    # classifies as a divergence (the digest is not separable) and fails.
    case = CASES[0]
    drifted = copy.deepcopy(case["committed"])
    drifted["tensor"]["state"][g6.STATE_OBSERVATION_DIGEST] ^= 1
    w = case["walk"]
    out = _reconcile(tmp_path, [g6.known_hand_masked_digest(w)], [g6.known_hand_masked_digest(drifted)],
                     (g6.known_hand_digest(w),), (g6.known_hand_digest(drifted),))
    assert not out["plans_match"] and not out["reconciled"]


def test_every_failing_group_is_classified():
    # Review round 3: a drift in one group does not hide a later group.
    import entrant_availability
    divergent, drifted = [], []
    groups = [{"committed_tensors": ["c"], "committed_masked_tensors": ["x"], "committed_known_hands": ["h"]},
              {"committed_tensors": ["c"], "committed_masked_tensors": ["m"], "committed_known_hands": ["h2"]}]
    plans = [{"step": 7, "plan": ["k"], "tensors": ["w"], "masked_tensors": ["m"], "known_hands": ["h1"]},
             {"step": 8, "plan": ["k"], "tensors": ["w"], "masked_tensors": ["m"], "known_hands": ["h1"]}]
    for r, g in zip(plans, groups):
        entrant_availability._classify_points(r, g, divergent, drifted)
    assert drifted == [{"step": 7, "point": 0}] and divergent == [{"step": 8, "point": 0}]


@pytest.mark.parametrize("field,value", [("masked_tensors", 1), ("masked_tensors", {"0": "m"}),
                                         ("known_hands", "h1"), ("tensors", None), ("plan", 3)])
def test_malformed_classification_fields_do_not_raise(field, value):
    # Review round 3: malformed optional fields classify as drift.
    import entrant_availability
    divergent, drifted = [], []
    plan = {"step": 7, "plan": ["k"], "tensors": ["w"], "masked_tensors": ["m"], "known_hands": ["h1"], field: value}
    group = {"committed_tensors": ["c"], "committed_masked_tensors": ["m"], "committed_known_hands": ["h2"]}
    entrant_availability._classify_points(plan, group, divergent, drifted)
    assert divergent == [] and len(drifted) <= 1


def test_the_pass_fail_expression_is_mains(tmp_path):
    # Review round 3: a committed_tensors string is not a list of digests.
    import entrant_availability
    out = _reconcile(tmp_path, ["m"], ["m"])
    group = json.loads((tmp_path / "g-x.adapter.json").read_text())
    group["groups"][0]["committed_tensors"] = "imported"
    (tmp_path / "g-x.adapter.json").write_text(json.dumps(group))
    plan = {"kind": "group_plan", "mode": "walk", "step": 7, "plan": ["k"], "tensors": ["imported"], "wire": [0]}
    out = entrant_availability._reconcile(tmp_path, "g-x", "p0", {"tally": {}, "eligible": 1}, [plan])
    assert not out["plans_match"] and not out["reconciled"]


def test_an_observation_digest_drift_without_a_known_hand_difference_is_a_drift(tmp_path):
    # Review round 1: the committed point differs from the walk's only in the
    # observation digest (state[123]), with the same known hand.
    walk = CASES[1]["committed"]
    drifted = copy.deepcopy(walk)
    drifted["tensor"]["state"][g6.STATE_OBSERVATION_DIGEST] ^= 1
    assert g6.known_hand_masked_digest(walk) == g6.known_hand_masked_digest(drifted)
    out = _reconcile(tmp_path, [g6.known_hand_masked_digest(walk)], [g6.known_hand_masked_digest(drifted)],
                     (g6.known_hand_digest(walk),), (g6.known_hand_digest(drifted),))
    assert not out["plans_match"] and out["drifted_points"] == POINT
