"""Mixed roots must share identity, sequence, clock and failure ownership."""
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import xmage_neural_bridge as bridge
import xmage_neural_rpc as rpc
import xmage_neural_search as search
import xmage_neural_combat as combat
from test_xmage_neural_search import fixture as search_fixture, Model
from test_xmage_neural_combat import fixture as combat_fixture, later_decision


class Peer:
    def __init__(self, messages, ready=None):
        self.messages = iter([bridge.READY if ready is None else ready, *messages])
        self.writes, self.timeouts = [], []
        self.closed = False
    def read_line(self):
        item = next(self.messages)
        if isinstance(item, Exception):
            raise item
        return json.dumps(item, allow_nan=False).encode()
    def write_line(self, payload):
        self.writes.append(json.loads(payload))
    def set_timeout(self, value):
        self.timeouts.append(value)
    def close(self):
        self.closed = True


def exchange(result, number, operation):
    return [{"id": str(number), "event": "infer", "call": call, "features": [4, 800]}
            for call in range(1, result["neural_calls"] + 1)] + [
        {"id": str(number), "operation": operation, "event": "result", "ok": True, "result": result}]


def test_priority_attack_priority_block_share_one_checkpoint_and_pipe():
    roots = [(search_fixture(), "search"), (combat_fixture(), "combat"),
             (search_fixture(), "search"), (combat_fixture("block"), "combat")]
    messages = [message for number, ((_, result), operation) in enumerate(roots, 1)
                for message in exchange(result, number, operation)]
    peer, model = Peer(messages), Model()
    session = bridge.BridgeSession(peer, model)
    for (record, result), operation in roots:
        record.update(id="injected", visits=999, operation="other")
        result["checkpoint"] = "spoofed-checkpoint"
        run = session.choose if operation == "search" else session.plan
        actual = run(record, visits=2, timeout_s=3)
        assert actual["checkpoint"] == model.checkpoint
        if operation == "combat":
            plan = combat.CombatPlan(record["decision"], actual, visits=2)
            assert plan.select(record["decision"])["candidate_id"] == 7
            assert plan.select(later_decision(record, result["combat"]))["candidate_id"] == 19
            assert plan.complete
        else:
            assert actual["selection"] == result["selection"]
    requests = [message for message in peer.writes if "decision" in message]
    assert [message["id"] for message in requests] == ["1", "2", "3", "4"]
    assert [message["operation"] for message in requests] == ["search", "combat", "search", "combat"]
    assert all(message["visits"] == 2 for message in requests)
    assert len(model.calls) == 6 and session.sequence == 4
    assert not peer.closed and not model.closed
    assert all(0 < value <= 3 for value in peer.timeouts)
    session.close()
    assert peer.closed and model.closed


@pytest.mark.parametrize("mutation", ["stale-id", "wrong-operation", "failed-inference", "lost-combat-work"])
def test_one_family_failure_poisoning_prevents_later_searches(mutation):
    record, result = search_fixture()
    combat_record, combat_output = combat_fixture()
    messages = exchange(result, 1, "search") + exchange(combat_output, 2, "combat")
    if mutation == "stale-id":
        messages[-1]["id"] = "1"
    elif mutation == "wrong-operation":
        messages[-1]["operation"] = "search"
    elif mutation == "failed-inference":
        messages[-2] = TimeoutError("confined checkpoint stopped")
    else:
        combat_output["neural_calls"] = 1
    peer, model = Peer(messages), Model()
    session = bridge.BridgeSession(peer, model)
    session.choose(record, visits=2, timeout_s=3)
    with pytest.raises((ValueError, TimeoutError)):
        session.plan(combat_record, visits=2, timeout_s=3)
    count = len(peer.writes)
    assert session.failed and session.closed and peer.closed and model.closed
    with pytest.raises(ValueError, match="closed or has failed"):
        session.choose(record, visits=2, timeout_s=3)
    assert len(peer.writes) == count


@pytest.mark.parametrize("session_type,ready", [
    (bridge.BridgeSession, search.READY), (bridge.BridgeSession, combat.READY),
    (search.SearchSession, bridge.READY), (combat.CombatSession, bridge.READY)])
def test_a_different_private_protocol_is_refused_and_cleaned_up(session_type, ready):
    peer, model = Peer([], ready=ready), Model()
    with pytest.raises(ValueError, match="readiness"):
        session_type(peer, model)
    assert peer.closed and model.closed


@pytest.mark.parametrize("operation", ["search", "combat"])
def test_slow_checkpoint_cannot_get_a_new_clock_after_inference(monkeypatch, operation):
    record, result = search_fixture() if operation == "search" else combat_fixture()
    clock = [0.0]
    monkeypatch.setattr(rpc.time, "monotonic", lambda: clock[0])
    peer, model = Peer(exchange(result, 1, operation)), Model()
    score = model.score
    def slow_score(*args, **kwargs):
        value = score(*args, **kwargs)
        clock[0] = 3.1
        return value
    model.score = slow_score
    session = bridge.BridgeSession(peer, model)
    run = session.choose if operation == "search" else session.plan
    with pytest.raises(TimeoutError, match="shared decision clock"):
        run(record, visits=2, timeout_s=3)
    assert len(peer.writes) == 1 and session.failed and peer.closed and model.closed


@pytest.mark.parametrize("operation", ["search", "combat"])
def test_refused_decision_family_never_spawns_a_policy_fallback(operation):
    record, _ = search_fixture() if operation == "search" else combat_fixture()
    record = copy.deepcopy(record)
    record["decision"]["context"] = {"kind": "replacement-order"}
    record["decision"]["candidates"] = [{"candidate_id": 1, "semantic": {"kind": "order_replacement"}}]
    peer, model = Peer([]), Model()
    session = bridge.BridgeSession(peer, model)
    run = session.choose if operation == "search" else session.plan
    with pytest.raises(ValueError):
        run(record, visits=2, timeout_s=3)
    assert not peer.writes and not model.calls
    session.close()
    assert peer.closed and model.closed
