"""The graph network's played settings, graph calls and work receipts stay bound."""
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import xmage_gnn_model as model_module
import xmage_gnn_search as search
from xmage_neural_decisions import decision_hash
from test_xmage_neural_search import fixture as original_fixture

GRAPH = {"indices": [0, 499558809, 1234], "values": [0, 0, 20], "edge_child": [1, 2], "edge_parent": [0, 1],
         "edge_label": [77, 88]}


def fixture(simulations=100):
    record, result = original_fixture()
    record["game_start"]["seat"] = "p0"
    record["decision"].update(acting_seat="p0", observation={"viewer": "p0"})
    record["decision"]["context"]["rewind"] = False
    settings = search.played_settings(simulations)
    result.update(decision_sha256=decision_hash(record["decision"]), settings=copy.deepcopy(settings),
                  search_budget=search.budget(settings),
                  graph_search=[{"type": "PRIORITY", "simulations": simulations, "network_calls": 1}])
    return record, result, settings


class Peer:
    def __init__(self, messages):
        self.messages = iter([search.READY, *messages])
        self.writes, self.closed = [], False
    def read_line(self):
        return json.dumps(next(self.messages)).encode()
    def write_line(self, value):
        self.writes.append(json.loads(value))
    def set_timeout(self, value):
        assert value > 0
    def close(self):
        self.closed = True


class Model:
    architecture, checkpoint, input_field = "draftzero-gnn", "draftzero-gnn-model", "graph"
    def __init__(self):
        self.closed, self.calls = False, []
    def score(self, graph, *, timeout_s):
        self.calls.append(graph)
        return {"priority": [None, 0.5, None], "target": [None, -1.0, None], "use": [0.1, -0.1], "value": 0.25}
    def close(self):
        self.closed = True


def test_played_settings_admit_only_the_simulation_count():
    settings = search.played_settings(100)
    assert settings["profile"] == "draftzero-gnn-pimc-tree-v1" and settings["opponentPriors"] == "uniform"
    for key, value in (("priorTemp", "1.0"), ("leaf", "mix"), ("opponentPriors", "net"), ("cPuct", 1),
                       ("discountUnit", "turn"), ("maxIterations", 400)):
        with pytest.raises(ValueError, match="played configuration"):
            search.validate_settings({**settings, key: value})
    for simulations in (0, 1, 1001, 100.0, True):
        with pytest.raises(ValueError):
            search.played_settings(simulations)
    with pytest.raises(ValueError, match="every explicit setting"):
        search.validate_settings({k: v for k, v in settings.items() if k != "timeoutSeconds"})


def test_graph_calls_reach_the_confined_network_and_bind_receipts():
    record, result, settings = fixture()
    peer = Peer([{"id": "1", "event": "infer", "call": 1, "graph": GRAPH},
                 {"id": "1", "operation": "search", "event": "result", "ok": True, "result": result}])
    model = Model()
    session = search.BridgeSession(peer, model)
    out = session.choose(record, settings=settings, timeout_s=30)
    assert model.calls == [GRAPH] and out["checkpoint"] == "draftzero-gnn-model"
    assert peer.writes[0]["operation"] == "search" and peer.writes[0]["settings"] == settings
    assert peer.writes[1]["scores"]["priority"] == [None, 0.5, None]


@pytest.mark.parametrize("fault", ["features-call", "receipt-calls", "policy-width", "budget", "settings"])
def test_unbound_graph_work_poisons_the_session(fault):
    record, result, settings = fixture()
    call = {"id": "1", "event": "infer", "call": 1, "graph": GRAPH}
    if fault == "features-call":
        call = {"id": "1", "event": "infer", "call": 1, "features": [4, 800]}
    elif fault == "receipt-calls":
        result["graph_search"][0]["network_calls"] = 2
    elif fault == "policy-width":
        result["policy_width"] = 128
    elif fault == "budget":
        result["search_budget"] = {**result["search_budget"], "requested": 99}
    else:
        result["settings"] = {**settings, "priorBonus": "0"}
    peer = Peer([call, {"id": "1", "operation": "search", "event": "result", "ok": True, "result": result}])
    model = Model()
    session = search.BridgeSession(peer, model)
    with pytest.raises(ValueError):
        session.choose(record, settings=settings, timeout_s=30)
    assert peer.closed and model.closed


def test_flat_checkpoints_cannot_drive_the_graph_pipe():
    class Flat(Model):
        architecture = "magezero-v02"
    with pytest.raises(ValueError, match="confined graph network"):
        search.BridgeSession(Peer([]), Flat())


def test_graph_states_and_scores_are_checked_on_the_host():
    assert model_module.validate_graph(GRAPH) == 3
    for key, value in (("indices", [0, -1, 2]), ("edge_child", [1, 3]), ("values", [0, 0]), ("edge_label", [1])):
        with pytest.raises(ValueError):
            model_module.validate_graph({**GRAPH, key: value})
    good = {"priority": [None, 0.5, None], "target": [None, 1, None], "use": [0, 1], "value": 0.5}
    model_module.validate_heads(good, 3)
    for key, value in (("priority", [None, float("nan"), None]), ("use", [0]), ("value", 1.5), ("target", [None])):
        with pytest.raises(ValueError):
            model_module.validate_heads({**good, key: value}, 3)


def test_runtime_identity_binds_the_repository_release_inputs():
    import xmage_gnn_runtime as runtime
    raw = (Path(__file__).parents[2] / "engines/xmage/releases.json").read_bytes()
    first = runtime.identity(simulations=100, build_sha256="a" * 64, image="sha256:" + "b" * 64, manifest_bytes=raw)
    assert first["name"] == "draftzero-fdn-gnn-100-fair" and first["version"].startswith("draftzero-gnn-pimc-v1-")
    assert first["identity"]["input_sha256"]["checkpoint"] == "d5ee8323ccca11f18b1667bc2312407d9d5696b6dacf7243d9a30461cdc29b56"
    other = runtime.identity(simulations=300, build_sha256="a" * 64, image="sha256:" + "b" * 64, manifest_bytes=raw)
    assert other["version"] != first["version"]
    with pytest.raises(ValueError):
        runtime.identity(simulations=100, build_sha256="a" * 64, image="gnn:latest", manifest_bytes=raw)


def test_unsearched_worlds_answer_the_kits_declining_candidate():
    record, _, settings = fixture()
    refusal = {"unsupported": "search world is unsupported: horizon:stack_object", "neural_calls": 0}
    peer = Peer([{"id": "1", "operation": "search", "event": "result", "ok": True, "result": refusal}])
    out = search.BridgeSession(peer, Model()).choose(record, settings=settings, timeout_s=30)
    assert out["selection"]["semantic_echo"] == {"kind": "pass"} and out["fallback"] == "kit_declining_unsearched_world"
    for bad in ({**refusal, "neural_calls": 1}, {**refusal, "unsupported": "search world is unsupported: approximate:x"},
                {"unsupported": "callback replay observation differs: []", "neural_calls": 0}):
        peer = Peer([{"id": "1", "operation": "search", "event": "result", "ok": True, "result": bad}])
        with pytest.raises(ValueError):
            search.BridgeSession(peer, Model()).choose(record, settings=settings, timeout_s=30)
    attack = {"candidates": [{"candidate_id": 4, "semantic": {"kind": "declare_attack", "defender": {"player": "p1"}}},
                             {"candidate_id": 9, "semantic": {"kind": "declare_attack", "defender": None}}]}
    assert search.declining(attack)["candidate_id"] == 9


def test_attack_trigger_callbacks_replay_the_recorded_declaration_group():
    history = search.GraphHistory("p0")
    begin = {"turn": 5, "phase_step": "beginning_of_combat", "active_seat": "p0", "stack": [], "passed_seats": []}
    history.anchor = {"decision": {"context": {"kind": "priority"}, "observation": begin},
                      "selection": {"candidate_id": 1, "semantic_echo": {"kind": "pass"}}}
    def attack(index):
        return {"decision": {"group": {"group_id": 7, "substep_count": 2, "substep_index": index},
                             "candidates": [{"candidate_id": 1, "semantic": {"kind": "declare_attack"}}]},
                "selection": {"candidate_id": 1, "semantic_echo": {"kind": "declare_attack"}}}
    history.earlier = [attack(0), attack(1)]
    callback = {"observation": {"turn": 5, "phase_step": "declare_attackers", "viewer": "p0"},
                "candidates": [{"candidate_id": 3, "semantic": {"kind": "choose_target"}}]}
    record = history.callback(callback)
    assert record["replay"] == {"priority_passes": ["p1"], "earlier": history.earlier, "attack_declarations": 2}
    history.earlier = [attack(0)]                      # an incomplete group is not replayable
    with pytest.raises(ValueError):
        history.callback(callback)
