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
    assert record["replay"] == {"priority_passes": ["p1"], "earlier": history.earlier, "attack_declarations": 2,
                                "characteristic_gaps": True, "fungible_tapped": True,
                                "visible_draws": True}
    history.earlier = [attack(0)]                      # an incomplete group is not replayable
    with pytest.raises(ValueError):
        history.callback(callback)


def test_unreproduced_callbacks_take_the_fallback_but_priority_roots_cannot():
    record, _, settings = fixture()
    refusal = {"unsupported": "callback replay observation differs: [/players/0/battlefield/4/permanent/tapped]",
               "neural_calls": 0}
    with pytest.raises(ValueError, match="priority root"):
        search.unsupported_result(record, refusal, 0)
    record["decision"] = {"context": {"kind": "choice"}, "candidates": [
        {"candidate_id": 5, "semantic": {"kind": "choose_target"}}, {"candidate_id": 6, "semantic": {"kind": "choose_target"}}]}
    out = search.unsupported_result(record, refusal, 0)
    assert out["world_flags"] == ["unreproduced_callback"] and out["selection"]["candidate_id"] == 5


def test_library_fail_to_find_binds_the_graph_frontends_own_reason():
    # The graph frontend runs the MageZero tree in Java under its own name; the host checks that name.
    record, result, settings = fixture()
    decision = {"context": {"kind": "choice", "purpose": "search"}, "candidates": [
        {"candidate_id": 11, "semantic": {"kind": "finish_selection", "purpose": "search"}},
        {"candidate_id": 3, "semantic": {"kind": "select_object", "purpose": "search",
                                        "choice": {"object": {"object_id": "visible-library-card"}}}}]}
    result.update(decision_sha256=decision_hash(decision), root_visits=100,
                  selection={"candidate_id": 3, "semantic_echo": decision["candidates"][1]["semantic"]},
                  policy_restrictions=["library_fail_to_find_before_minimum"],
                  children=[{"semantic": c["semantic"], "visits": 100 if c["candidate_id"] == 3 else 0,
                             "value": 0.2 if c["candidate_id"] == 3 else None,
                             "excluded": c["candidate_id"] == 11} for c in decision["candidates"]])
    reason = "original {} library target expansion requires its minimum before finishing"
    result["children"][0]["reason"] = reason.format("graph network")
    from xmage_neural_search import validate_result
    validate_result(decision, result, settings["simulations"], 1, expected_budget=search.budget(settings),
                    minimum_visits=False, source_label="graph network")
    result["children"][0]["reason"] = reason.format("MageZero")
    with pytest.raises(ValueError, match="original policy restriction"):
        validate_result(decision, result, settings["simulations"], 1, expected_budget=search.budget(settings),
                        minimum_visits=False, source_label="graph network")
    java = (Path(__file__).parents[2] / "engines/xmage/models/src/spellbench/kit/xmage/MageZeroSearchMain.java").read_text()
    assert 'String source = graph == null ? "MageZero" : "graph network";' in java
    assert java.count('"original " + source + " ') == 3 and "original MageZero library" not in java


def lone_target_fixture():
    record, _, settings = fixture()
    record["decision"].update(context={"kind": "choice", "purpose": "search", "rewind": False}, candidates=[
        {"candidate_id": 0, "semantic": {"kind": "select_object", "purpose": "search",
                                        "choice": {"object": {"object_id": "only-match", "zone": "library"}}}},
        {"candidate_id": 1, "semantic": {"kind": "finish_selection", "purpose": "search"}}])
    record.update(anchor={"decision": {}, "selection": {}}, replay={"priority_passes": ["p1"], "earlier": [{}]})
    result = {"forced": search.LONE_TARGET, "neural_calls": 0, "decision_sha256": decision_hash(record["decision"]),
              "selection": {"candidate_id": 0, "semantic_echo": record["decision"]["candidates"][0]["semantic"]},
              "world_flags": ["approximate:watchers_reset"],
              "replay": {"earlier": 1, "priority_passes": 1, "observation_identical": True}}
    return record, result, settings


def test_a_lone_original_target_is_answered_without_a_search():
    # A library search's one match: the original player takes it itself (no stop before the search's minimum).
    record, result, settings = lone_target_fixture()
    peer = Peer([{"id": "1", "operation": "search", "event": "result", "ok": True, "result": result}])
    model = Model()
    out = search.BridgeSession(peer, model).choose(record, settings=settings, timeout_s=30)
    assert out["selection"]["candidate_id"] == 0 and out["neural_calls"] == 0 and model.calls == []


@pytest.mark.parametrize("fault", ["calls", "reported-calls", "priority", "unoffered", "changed", "stale",
                                   "unsupported", "proof", "extra", "reason", "single"])
def test_a_lone_original_target_refuses_anything_else(fault):
    record, result, _ = lone_target_fixture()
    calls = 0
    if fault == "calls":
        calls = 1
    elif fault == "reported-calls":
        result["neural_calls"] = 1
    elif fault == "priority":
        record["decision"]["context"]["kind"] = "priority"
        result["decision_sha256"] = decision_hash(record["decision"])
    elif fault == "unoffered":
        result["selection"]["candidate_id"] = 7
    elif fault == "changed":
        result["selection"]["semantic_echo"] = {"kind": "finish_selection", "purpose": "search"}
    elif fault == "stale":
        result["decision_sha256"] = "0" * 64
    elif fault == "unsupported":
        result["world_flags"] = ["unsupported:x"]
    elif fault == "proof":
        result["replay"]["earlier"] = 0
    elif fault == "extra":
        result["children"] = []
    elif fault == "reason":
        result["forced"] = "kit declining"
    elif fault == "single":
        del record["decision"]["candidates"][1]
        result["decision_sha256"] = decision_hash(record["decision"])
    with pytest.raises(ValueError):
        search.lone_target_result(record, result, calls)


def test_the_java_lone_target_follows_the_original_make_choice_options():
    java = Path(__file__).parents[2] / "engines/xmage/models/src/spellbench/kit/xmage"
    replay = (java / "MageZeroSearchReplay.java").read_text()
    main = (java / "MageZeroSearchMain.java").read_text()
    # MCTSPlayer.makeChoice: possible targets not yet chosen, stop only once chosen, a lone option taken itself.
    assert "if (!target.contains(id)) possible.add(id);" in replay
    assert "if (target.isChosen(game)) possible.add(GameAccess.STOP_CHOOSING);" in replay
    assert "if (possible.size() == 1) {" in replay
    assert f'LONE_TARGET = "{search.LONE_TARGET}"' in main


def test_replayed_zone_changes_bind_the_received_ids_to_their_world_objects():
    # A spell resolved during the replay is a new object id in the received callback (Apothecary Stomper's
    # own enter trigger targets it); the compare binds only ids the world does not know yet.
    java = (Path(__file__).parents[2] / "engines/xmage/models/src/spellbench/kit/xmage/MageZeroSearchReplay.java").read_text()
    # The projection names objects by its own ids, never the world's: look each world object up there.
    assert "bindNewIds(projection, projected, current);" in java
    assert 'String id = ref == null ? null : aligned.get(Json.str(ref, "object_id"));' in java
    assert "if (!world.idToUuid.containsKey(id)) {" in java


def food(object_id):
    return {"kind": "activate_ability", "ability_index": 0,
            "source": {"card_name": "Food Token", "controller_seat": "p0", "object_id": object_id,
                       "owner_seat": "p0", "zone": "battlefield"}}


def test_a_duplicate_activation_hidden_by_the_original_playable_list_is_excluded():
    # XMage's getPlayable keeps one activated ability per rule text, so the original tree expands one of two Food
    # tokens; the other offered activation is recorded as hidden behind that branch, with no work of its own.
    record, result, settings = fixture()
    decision = {"context": {"kind": "priority"}, "candidates": [
        {"candidate_id": 0, "semantic": {"kind": "pass"}},
        {"candidate_id": 1, "semantic": food("o-first")}, {"candidate_id": 2, "semantic": food("o-second")}]}
    reason = "original graph network playable list keeps one ability per rule text"
    result.update(decision_sha256=decision_hash(decision), root_visits=100,
                  selection={"candidate_id": 0, "semantic_echo": {"kind": "pass"}},
                  policy_restrictions=["hidden_duplicate_abilities"],
                  children=[{"semantic": {"kind": "pass"}, "visits": 60, "value": 0.3},
                            {"semantic": food("o-first"), "visits": 40, "value": 0.1},
                            {"semantic": food("o-second"), "visits": 0, "value": None, "excluded": True,
                             "duplicate_of": food("o-first"), "reason": reason}])
    from xmage_neural_search import validate_result
    def check(changed):
        validate_result(decision, changed, settings["simulations"], 1, expected_budget=search.budget(settings),
                        minimum_visits=False, source_label="graph network")
    check(result)
    bad = []
    for path, value in ((("policy_restrictions",), []), (("children", 2, "reason"), reason.replace("graph network", "MageZero")),
                        (("children", 2, "duplicate_of"), food("o-second")),
                        (("children", 2, "duplicate_of", "ability_index"), 1),
                        (("children", 2, "duplicate_of", "source", "card_name"), "Clue Token")):
        changed = copy.deepcopy(result)
        target = changed
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        bad.append(changed)
    callback = copy.deepcopy(result)
    callback["children"][2]["duplicate_of"] = {"kind": "pass"}
    bad.append(callback)
    for changed in bad:
        with pytest.raises(ValueError, match="not a duplicate"):
            check(changed)
    java = (Path(__file__).parents[2] / "engines/xmage/models/src/spellbench/kit/xmage/MageZeroSearchMain.java").read_text()
    assert ".getPlayable(world.game, true, mage.constants.Zone.ALL, false)) {" in java
    assert "Map<String, Object> shown = branchTexts.get(a.toString());" in java
    assert "branchTexts.put(child.getPriorityAction().toString(), action);" in java


def test_a_diverged_callback_replay_takes_the_kits_declining_fallback():
    # A replayed callback that reaches a priority its received history does not hold does not reproduce it: the
    # kit's no-search policy answers the declining candidate (a ward payment is declined), never a forfeit.
    record, _, settings = fixture()
    record["decision"].update(context={"kind": "choice", "rewind": False}, candidates=[
        {"candidate_id": 5, "semantic": {"kind": "optional_cost", "cost": "unless_payment", "pay": False}},
        {"candidate_id": 6, "semantic": {"kind": "optional_cost", "cost": "unless_payment", "pay": True}}])
    record.update(anchor={"decision": {}, "selection": {}}, replay={"priority_passes": ["p1"], "earlier": []})
    refusal = {"unsupported": "callback replay diverges: unrecorded or reordered priority", "neural_calls": 0}
    peer = Peer([{"id": "1", "operation": "search", "event": "result", "ok": True, "result": refusal}])
    out = search.BridgeSession(peer, Model()).choose(record, settings=settings, timeout_s=30)
    assert out["selection"]["candidate_id"] == 5 and out["world_flags"] == ["unreproduced_callback"]
    with pytest.raises(ValueError):
        search.unsupported_result(record, {**refusal, "neural_calls": 1}, 0)
    root = (Path(__file__).parents[2] / "engines/xmage/models/src/spellbench/kit/xmage")
    assert '"callback replay diverges: unrecorded or reordered priority"' in (root / "MageZeroSearchReplay.java").read_text()
    assert '"callback replay diverges: "};' in (root / "GnnBridgeMain.java").read_text()
