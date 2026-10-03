"""The original search bridge must complete, bind, and clean up its work."""
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import xmage_neural_search as search
from xmage_neural_decisions import decision_hash


def fixture():
    decision = {"context": {"kind": "priority"}, "candidates": [
        {"candidate_id": 11, "semantic": {"kind": "pass"}},
        {"candidate_id": 3, "semantic": {"kind": "play_land", "source": {"object_id": "visible-land"}}}]}
    record = {"game_start": {}, "decision": decision, "world_seed": "a" * 64, "id_seed": "b" * 64}
    result = {"decision_sha256": decision_hash(decision), "root_visits": 2, "neural_calls": 1,
              "selection": {"candidate_id": 3, "semantic_echo": decision["candidates"][1]["semantic"]},
              "children": [{"semantic": c["semantic"], "visits": 2 if c["candidate_id"] == 3 else 0,
                            "value": 0.2} for c in decision["candidates"]], "world_flags": ["approximate:watchers_reset"]}
    return record, result


class Peer:
    def __init__(self, messages):
        self.messages = iter([search.READY, *messages])
        self.writes, self.timeouts = [], []
        self.closed = False
    def read_line(self):
        item = next(self.messages)
        if isinstance(item, Exception): raise item
        return json.dumps(item, allow_nan=False).encode()
    def write_line(self, payload):
        assert not payload.endswith(b"\n")
        self.writes.append(json.loads(payload))
    def set_timeout(self, value): self.timeouts.append(value)
    def close(self): self.closed = True


class Model:
    checkpoint = "pinned-test-checkpoint"
    def __init__(self, failure=None):
        self.calls, self.closed, self.failure = [], False, failure
    def score(self, features, *, timeout_s):
        if self.failure: raise self.failure
        self.calls.append((features, timeout_s))
        return {"priority": [0.0] * 1024, "opponent_priority": [0.0] * 1024,
                "target": [0.0] * 1024, "binary": [0.0, 0.0], "value": 0.2}
    def close(self): self.closed = True


def test_real_work_clock_and_result_bind_to_the_offered_root():
    record, result = fixture()
    peer = Peer([{"id": "1", "event": "infer", "call": 1, "features": [4, 800]},
                 {"id": "1", "event": "result", "ok": True, "result": result}])
    model = Model()
    session = search.SearchSession(peer, model)
    record.update(id="untrusted-input-id", visits=999)
    chosen = session.choose(record, visits=2, timeout_s=3)
    assert chosen["selection"]["candidate_id"] == 3
    assert chosen["checkpoint"] == model.checkpoint
    assert peer.writes[0]["id"] == "1" and peer.writes[0]["visits"] == 2
    assert peer.writes[1]["id"] == "1" and peer.writes[1]["call"] == 1
    assert model.calls[0][0] == [4, 800] and 0 < model.calls[0][1] <= 3
    assert all(0 < timeout <= 3 for timeout in peer.timeouts)
    session.close()
    assert peer.closed and model.closed


@pytest.mark.parametrize("mutation", ["valid", "missing-budget", "lost-work", "invented-mask", "float-budget"])
def test_original_legal_future_stopping_accounts_for_cleared_branch_visits(mutation):
    record, result = fixture()
    result.update(root_visits=41, search_budget={"kind": "minimum_root_visits_until_legal_future", "requested": 2})
    result["children"][0].update(value=None, selection_masked=True, discarded_visits=33,
                                mask_reason="original Exp1 bestChild resets branches without a legal future")
    result["children"][1]["visits"] = 8
    if mutation == "missing-budget": result.pop("search_budget")
    elif mutation == "lost-work": result["children"][0]["discarded_visits"] = 32
    elif mutation == "invented-mask": result["children"][0]["mask_reason"] = "ignore another legal action"
    elif mutation == "float-budget": result["search_budget"]["requested"] = 2.0
    if mutation == "valid":
        search.validate_result(record["decision"], result, 2, 1)
    else:
        with pytest.raises(ValueError): search.validate_result(record["decision"], result, 2, 1)


@pytest.mark.parametrize("invalid_pruned_statistics", [False, True])
def test_original_pruning_keeps_coverage_and_only_retained_visits_count(invalid_pruned_statistics):
    record, result = fixture()
    result["children"][0].update(pruned=True, visits=1 if invalid_pruned_statistics else 0, value=None)
    peer = Peer([{"id": "1", "event": "infer", "call": 1, "features": [4]},
                 {"id": "1", "event": "result", "ok": True, "result": result}])
    model = Model()
    session = search.SearchSession(peer, model)
    if invalid_pruned_statistics:
        with pytest.raises(ValueError, match="root statistics"):
            session.choose(record, visits=2, timeout_s=3)
        assert session.failed
    else:
        chosen = session.choose(record, visits=2, timeout_s=3)
        assert len(chosen["children"]) == len(record["decision"]["candidates"])
        assert chosen["children"][0]["pruned"] is True
        session.close()
    assert peer.closed and model.closed


@pytest.mark.parametrize("valid_restriction", [True, False])
def test_fail_to_find_restriction_is_explicit_and_cannot_hide_another_action(valid_restriction):
    record, result = fixture()
    decision = {"context": {"kind": "choice", "purpose": "search"}, "candidates": [
        {"candidate_id": 11, "semantic": {"kind": "finish_selection", "purpose": "search"}},
        {"candidate_id": 3, "semantic": {"kind": "select_object", "purpose": "search",
                                        "choice": {"object": {"object_id": "visible-library-card"}}}}]}
    result.update(decision_sha256=decision_hash(decision),
                  selection={"candidate_id": 3, "semantic_echo": decision["candidates"][1]["semantic"]},
                  policy_restrictions=["library_fail_to_find_before_minimum"],
                  children=[{"semantic": c["semantic"], "visits": 2 if c["candidate_id"] == 3 else 0,
                             "value": 0.2 if c["candidate_id"] == 3 else None,
                             "excluded": c["candidate_id"] == 11} for c in decision["candidates"]])
    result["children"][0]["reason"] = ("original Exp1 library target expansion requires its minimum before finishing"
                                        if valid_restriction else "arbitrary unsupported option")
    if valid_restriction:
        search.validate_result(decision, result, 2, 1)
    else:
        with pytest.raises(ValueError, match="original policy restriction"):
            search.validate_result(decision, result, 2, 1)


@pytest.mark.parametrize("mutation", ["stale", "partial", "missing-action", "aliased-action", "unoffered",
                                     "wrong-selection", "invalid-statistics", "horizon", "wrong-visit-winner"])
def test_invalid_search_results_are_refused_without_a_policy_fallback(mutation):
    record, result = fixture()
    result = copy.deepcopy(result)
    if mutation == "stale": result["decision_sha256"] = "c" * 64
    elif mutation == "partial": result["root_visits"] = 1
    elif mutation == "missing-action": result["children"].pop()
    elif mutation == "aliased-action": result["children"][0] = copy.deepcopy(result["children"][1])
    elif mutation == "unoffered": result["children"][0]["semantic"] = {"kind": "cast_spell"}
    elif mutation == "wrong-selection": result["selection"]["semantic_echo"] = {"kind": "pass"}
    elif mutation == "invalid-statistics": result["children"][0]["value"] = "NaN"
    elif mutation == "horizon": result["world_flags"] = ["horizon:stack_object"]
    else:
        result["children"][0]["visits"], result["children"][1]["visits"] = 2, 0
    peer = Peer([{"id": "1", "event": "result", "ok": True, "result": result}])
    model = Model()
    session = search.SearchSession(peer, model)
    with pytest.raises(ValueError): session.choose(record, visits=2, timeout_s=3)
    assert session.failed and session.closed and peer.closed and model.closed
    with pytest.raises(ValueError, match="closed or has failed"): session.choose(record, visits=2, timeout_s=3)


@pytest.mark.parametrize("failure", ["stale-id", "stale-call", "transport", "checkpoint", "clock"])
def test_failed_search_or_inference_closes_both_owned_processes(failure):
    record, _ = fixture()
    event = {"id": "1", "event": "infer", "call": 1, "features": [4]}
    model = Model()
    if failure == "stale-id": event["id"] = "old"
    elif failure == "stale-call": event["call"] = 2
    elif failure == "transport": event = EOFError("owned Java process exited")
    elif failure == "checkpoint": model.failure = ValueError("checkpoint inference failed")
    else: event = TimeoutError("owned Java process exceeded its remaining clock")
    peer = Peer([event])
    session = search.SearchSession(peer, model)
    with pytest.raises((ValueError, EOFError, TimeoutError)): session.choose(record, visits=2, timeout_s=3)
    assert session.failed and peer.closed and model.closed


@pytest.mark.parametrize("confirm_replay", [True, False, 1])
@pytest.mark.parametrize("family", ["binary", "numeric", "named"])
def test_callback_search_requires_a_complete_matching_public_replay(confirm_replay, family):
    record, result = fixture()
    anchor = copy.deepcopy(record["decision"])
    decision = {"context": {"kind": "choose_boolean"}, "candidates": [
        {"candidate_id": 11, "semantic": {"kind": "choose_boolean", "value": False}},
        {"candidate_id": 3, "semantic": {"kind": "choose_boolean", "value": True}}]}
    if family == "numeric":
        decision["context"] = {"kind": "choose_number:amount"}
        for value, candidate in enumerate(decision["candidates"], 1):
            candidate["semantic"] = {"kind": "choose_number", "minimum": 1, "maximum": 2, "value": value}
    elif family == "named":
        decision["context"] = {"kind": "choose_color"}
        for color, candidate in zip(("red", "blue"), decision["candidates"]):
            candidate["semantic"] = {"kind": "choose_color", "color": color}
    record.update(decision=decision, anchor={"decision": anchor, "selection": result["selection"]},
                  replay={"priority_passes": ["p1", "p0"], "earlier": []})
    result.update(decision_sha256=decision_hash(decision),
                  selection={"candidate_id": 3, "semantic_echo": decision["candidates"][1]["semantic"]},
                  children=[{"semantic": c["semantic"], "visits": 2 if c["candidate_id"] == 3 else 0,
                             "value": 0.2} for c in decision["candidates"]],
                  replay={"earlier": 0, "priority_passes": 2, "observation_identical": confirm_replay})
    peer = Peer([{"id": "1", "event": "infer", "call": 1, "features": [4, 800]},
                 {"id": "1", "event": "result", "ok": True, "result": result}])
    model = Model()
    session = search.SearchSession(peer, model)
    if confirm_replay is True:
        chosen = session.choose(record, visits=2, timeout_s=3)
        assert chosen["selection"]["semantic_echo"] == decision["candidates"][1]["semantic"]
        assert peer.writes[0]["anchor"] == record["anchor"]
        assert peer.writes[0]["replay"] == record["replay"]
        session.close()
    else:
        with pytest.raises(ValueError, match="complete public replay"):
            session.choose(record, visits=2, timeout_s=3)
        assert session.failed
    assert peer.closed and model.closed
