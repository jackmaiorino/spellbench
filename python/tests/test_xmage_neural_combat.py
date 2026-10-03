"""Combat search must bind legal declarations, account for work and close failures."""
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import xmage_neural_combat as combat
from xmage_neural_decisions import decision_hash


def fixture(family="attack"):
    viewer = "p0" if family == "attack" else "p1"
    other = "p1" if viewer == "p0" else "p0"
    objects = [{"object_id": name, "controller_seat": viewer, "permanent": {}}
               for name in ("own-1", "own-2")]
    opposing = {"object_id": "other-1", "controller_seat": other,
                "permanent": {"attacking": family == "block"}}
    name = "attacker" if family == "attack" else "blocker"
    reference = "defender" if family == "attack" else "attacker"
    chosen = {"player": other} if family == "attack" else {"object_id": "other-1"}
    decision = {"acting_seat": viewer, "seat_step": 10, "context": {"rewind": False},
        "group": {"group_id": 88, "substep_index": 0, "substep_count": 2},
        "observation": {"viewer": viewer, "players": [
        {"seat": viewer, "battlefield": objects}, {"seat": other, "battlefield": [opposing]}]},
        "candidates": [{"candidate_id": 19, "semantic": {"kind": "declare_" + family,
                        name: {"object_id": "own-1"}, reference: None}},
                       {"candidate_id": 7, "semantic": {"kind": "declare_" + family,
                        name: {"object_id": "own-1"}, reference: chosen}}]}
    record = {"game_start": {}, "decision": decision, "world_seed": "a" * 64, "id_seed": "b" * 64}
    result = {"decision_sha256": decision_hash(decision), "combat": family, "neural_calls": 2,
              "pairs": [{name: "own-1", reference: {"player": other} if family == "attack" else "other-1"}],
              "world_flags": ["approximate:watchers_reset"], "roots": []}
    for index in range(2):
        actions = [False, True] if family == "attack" else [None, "other-1"]
        selected = actions[1] if index == 0 else actions[0]
        result["roots"].append({"index": index, "type": "CHOOSE_USE" if family == "attack" else "CHOOSE_TARGET",
                                "root_visits": 2, "requested_minimum": 2, "neural_calls": 1,
                                "selected": selected, "children": [
            {"action": action, "visits": 2 if action == selected else 0, "value": 0.2,
             "pruned": False, "selection_masked": False, "discarded_visits": 0} for action in actions]})
    return record, result


class Peer:
    def __init__(self, messages):
        self.messages = iter([combat.READY, *messages])
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


class Model:
    checkpoint = "pinned-test-checkpoint"
    def __init__(self, failure=None):
        self.calls, self.closed, self.failure = [], False, failure
    def score(self, features, *, timeout_s):
        if self.failure:
            raise self.failure
        self.calls.append((features, timeout_s))
        return {"priority": [0.0] * 1024, "opponent_priority": [0.0] * 1024,
                "target": [0.0] * 1024, "binary": [0.0, 0.0], "value": 0.2}
    def close(self):
        self.closed = True


def exchange(result):
    return [{"id": "1", "event": "infer", "call": number, "features": [4, 800]}
            for number in (1, 2)] + [{"id": "1", "event": "result", "ok": True, "result": result}]


@pytest.mark.parametrize("family", ["attack", "block"])
def test_original_plan_binds_offered_declarations_with_one_shared_clock(family):
    record, result = fixture(family)
    peer, model = Peer(exchange(result)), Model()
    session = combat.CombatSession(peer, model)
    record.update(id="untrusted-id", visits=999)
    chosen = session.plan(record, visits=2, timeout_s=3)
    assert chosen["selection"] == {"candidate_id": 7, "semantic_echo": record["decision"]["candidates"][1]["semantic"]}
    assert chosen["checkpoint"] == model.checkpoint
    assert peer.writes[0]["id"] == "1" and peer.writes[0]["visits"] == 2
    assert [message["call"] for message in peer.writes[1:]] == [1, 2]
    assert all(features == [4, 800] and 0 < remaining <= 3 for features, remaining in model.calls)
    assert all(0 < remaining <= 3 for remaining in peer.timeouts)
    session.close()
    assert peer.closed and model.closed


@pytest.mark.parametrize("family", ["attack", "block"])
def test_a_creature_absent_from_the_plan_uses_the_offered_decline(family):
    record, result = fixture(family)
    result["pairs"] = []
    assert combat.select_candidate(record["decision"], result)["candidate_id"] == 19


def test_original_selection_mask_preserves_completed_work():
    record, result = fixture()
    root = result["roots"][0]
    root["root_visits"] = 41
    root["children"][0].update(visits=0, value=None, selection_masked=True, discarded_visits=33)
    root["children"][1]["visits"] = 8
    combat.validate_result(record["decision"], result, 2, 2)
    root["children"][0]["discarded_visits"] = 32
    with pytest.raises(ValueError, match="search work"):
        combat.validate_result(record["decision"], result, 2, 2)


@pytest.mark.parametrize("mutation", ["stale", "family", "hidden", "opposing", "duplicate", "defender",
                                     "own-defender", "horizon", "partial", "missing-action", "aliased-action",
                                     "root-index", "root-type", "work", "calls", "winner", "value", "masked"])
def test_invalid_plans_poison_the_session_without_a_fallback(mutation):
    record, result = fixture()
    root = result["roots"][0]
    if mutation == "stale": result["decision_sha256"] = "c" * 64
    elif mutation == "family": result["combat"] = "block"
    elif mutation == "hidden": result["pairs"][0]["attacker"] = "unseen"
    elif mutation == "opposing": result["pairs"][0]["attacker"] = "other-1"
    elif mutation == "duplicate": result["pairs"] *= 2
    elif mutation == "defender": result["pairs"][0]["defender"] = {"object_id": "unseen"}
    elif mutation == "own-defender": result["pairs"][0]["defender"] = {"player": "p0"}
    elif mutation == "horizon": result["world_flags"] = ["horizon:stack_object"]
    elif mutation == "partial": root["root_visits"] = 1
    elif mutation == "missing-action": root["children"].pop(0)
    elif mutation == "aliased-action": root["children"][0] = copy.deepcopy(root["children"][1])
    elif mutation == "root-index": root["index"] = 1
    elif mutation == "root-type": root["type"] = "PRIORITY"
    elif mutation == "work": root["children"][1]["visits"] = 1
    elif mutation == "calls": root["neural_calls"] = 2
    elif mutation == "winner": root["selected"] = False
    elif mutation == "value": root["children"][0]["value"] = "NaN"
    elif mutation == "masked": root["children"][1]["discarded_visits"] = 2
    peer, model = Peer(exchange(result)), Model()
    session = combat.CombatSession(peer, model)
    with pytest.raises(ValueError):
        session.plan(record, visits=2, timeout_s=3)
    assert session.failed and session.closed and peer.closed and model.closed
    with pytest.raises(ValueError, match="closed or failed"):
        session.plan(record, visits=2, timeout_s=3)


@pytest.mark.parametrize("mutation", ["hidden", "own", "not-attacking"])
def test_blockers_cannot_target_hidden_friendly_or_nonattacking_objects(mutation):
    record, result = fixture("block")
    if mutation == "hidden": result["pairs"][0]["attacker"] = "unseen"
    elif mutation == "own": result["pairs"][0]["attacker"] = "own-2"
    else:
        record["decision"]["observation"]["players"][1]["battlefield"][0]["permanent"]["attacking"] = False
        result["decision_sha256"] = decision_hash(record["decision"])
    with pytest.raises(ValueError, match="nonattacking"):
        combat.validate_result(record["decision"], result, 2, 2)


@pytest.mark.parametrize("failure", ["stale-id", "stale-call", "transport", "model", "clock"])
def test_rpc_failures_close_both_owned_processes(failure):
    record, _ = fixture()
    message = {"id": "1", "event": "infer", "call": 1, "features": [4]}
    model = Model()
    if failure == "stale-id": message["id"] = "old"
    elif failure == "stale-call": message["call"] = 2
    elif failure == "transport": message = EOFError("Java exited")
    elif failure == "model": model.failure = ValueError("checkpoint failed")
    else: message = TimeoutError("remaining clock expired")
    peer = Peer([message])
    session = combat.CombatSession(peer, model)
    with pytest.raises((ValueError, EOFError, TimeoutError)):
        session.plan(record, visits=2, timeout_s=3)
    assert session.failed and peer.closed and model.closed


@pytest.mark.parametrize("mutation", ["unoffered", "alias", "two-creatures"])
def test_wire_assignment_must_have_one_unique_offered_choice(mutation):
    record, result = fixture()
    decision = record["decision"]
    if mutation == "unoffered": decision["candidates"].pop()
    elif mutation == "alias": decision["candidates"].append(copy.deepcopy(decision["candidates"][1]))
    else: decision["candidates"][0]["semantic"]["attacker"]["object_id"] = "own-2"
    result["decision_sha256"] = decision_hash(decision)
    with pytest.raises(ValueError): combat.select_candidate(decision, result)


def later_decision(record, family):
    decision = copy.deepcopy(record["decision"])
    decision["seat_step"] += 1
    decision["group"]["substep_index"] = 1
    own = decision["observation"]["players"][0]["battlefield"][0]
    if family == "attack":
        own["permanent"].update(tapped=True, attacking=True, attack_target={"player": "p1"})
    else:
        own["permanent"].update(blocking=True, blocked_attackers=[{"object_id": "other-1"}])
    name = "attacker" if family == "attack" else "blocker"
    for candidate in decision["candidates"]:
        candidate["semantic"][name]["object_id"] = "own-2"
    return decision


@pytest.mark.parametrize("family", ["attack", "block"])
def test_one_original_plan_answers_all_substeps_and_then_closes(family):
    record, result = fixture(family)
    plan = combat.CombatPlan(record["decision"], result, visits=2)
    assert plan.select(record["decision"])["candidate_id"] == 7
    later = later_decision(record, family)
    result["pairs"] = []  # caller mutation cannot rewrite a retained plan
    record["decision"]["group"].update(group_id=999, substep_count=3)
    assert plan.select(later)["candidate_id"] == 19
    assert plan.complete
    with pytest.raises(ValueError, match="complete or failed"):
        plan.select(record["decision"])


@pytest.mark.parametrize("mutation", ["group", "index", "count", "step", "seat", "rewind", "life",
                                     "attack-target", "tap", "creature", "ids"])
def test_cached_plan_refuses_stale_groups_and_changes_outside_its_declared_prefix(mutation):
    record, result = fixture()
    plan = combat.CombatPlan(record["decision"], result, visits=2)
    plan.select(record["decision"])
    decision = later_decision(record, "attack")
    if mutation == "group": decision["group"]["group_id"] += 1
    elif mutation == "index": decision["group"]["substep_index"] = 0
    elif mutation == "count": decision["group"]["substep_count"] = 3
    elif mutation == "step": decision["seat_step"] += 1
    elif mutation == "seat": decision["acting_seat"] = "p1"
    elif mutation == "rewind": decision["context"]["rewind"] = True
    elif mutation == "life": decision["observation"]["players"][1]["life"] = 11
    elif mutation == "attack-target": decision["observation"]["players"][0]["battlefield"][0]["permanent"]["attack_target"] = {"player": "p0"}
    elif mutation == "tap": decision["observation"]["players"][0]["battlefield"][0]["permanent"]["tapped"] = False
    elif mutation == "creature":
        for candidate in decision["candidates"]: candidate["semantic"]["attacker"]["object_id"] = "own-1"
    elif mutation == "ids": decision["candidates"][0]["candidate_id"] = 7
    with pytest.raises(ValueError): plan.select(decision)
    assert plan.failed
    with pytest.raises(ValueError, match="complete or failed"): plan.select(later_decision(record, "attack"))


def test_a_vigilance_attack_preserves_its_observed_untapped_state():
    record, result = fixture()
    own = record["decision"]["observation"]["players"][0]["battlefield"][0]
    own["characteristics"] = {"keywords": ["vigilance"]}
    result["decision_sha256"] = decision_hash(record["decision"])
    plan = combat.CombatPlan(record["decision"], result, visits=2)
    plan.select(record["decision"])
    decision = later_decision(record, "attack")
    decision["observation"]["players"][0]["battlefield"][0]["permanent"]["tapped"] = False
    assert plan.select(decision)["candidate_id"] == 19


@pytest.mark.parametrize("family", ["attack", "block"])
def test_engine_can_hold_declarations_pending_until_the_group_completes(family):
    record, result = fixture(family)
    plan = combat.CombatPlan(record["decision"], result, visits=2)
    assert plan.select(record["decision"])["candidate_id"] == 7
    decision = later_decision(record, family)
    decision["observation"]["players"][0]["battlefield"][0]["permanent"] = copy.deepcopy(
        record["decision"]["observation"]["players"][0]["battlefield"][0]["permanent"])
    assert plan.select(decision)["candidate_id"] == 19
    assert plan.complete


def test_a_late_valid_result_exhausts_the_same_clock_and_closes_processes(monkeypatch):
    record, result = fixture()
    peer, model = Peer(exchange(result)), Model()
    session = combat.CombatSession(peer, model)
    ticks = iter([0, .1, .2, .3, .4, .5, .6, .7, 3.1])
    monkeypatch.setattr(combat.time, "monotonic", lambda: next(ticks))
    with pytest.raises(TimeoutError, match="validation clock"):
        session.plan(record, visits=2, timeout_s=3)
    assert session.failed and peer.closed and model.closed


def test_a_different_bridge_cannot_pass_combat_readiness():
    peer, model = Peer([]), Model()
    peer.messages = iter([{"ready": True, "search": "draftzero-exp1-original-search"}])
    with pytest.raises(ValueError, match="readiness"):
        combat.CombatSession(peer, model)
    assert peer.closed and model.closed
