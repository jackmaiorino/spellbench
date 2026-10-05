"""Published Exp1 settings must survive the private pipe and public lifecycle."""
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import xmage_exp1_play as play
import xmage_neural_runtime as runtime
from spellbench import wire
from spellbench.bot import GameStart
from xmage_neural_decisions import decision_hash
from xmage_neural_search import search_result as diagnostic_result
from test_xmage_neural_search import Model as OriginalModel, fixture as original_search
from test_xmage_neural_combat import fixture as original_combat, later_decision
from test_xmage_neural_bridge import Peer, exchange
from test_xmage_neural_agent import game, view, decision
from test_xmage_neural_runtime import fixture as build_fixture


class Model(OriginalModel):
    architecture = "draftzero-exp1"


def search_fixture(callback=False):
    record, result = original_search()
    record["game_start"]["seat"] = "p0"
    root = record["decision"]
    root.update(acting_seat="p0", seat_step=0, observation={"viewer": "p0"})
    root["context"]["rewind"] = False
    if callback:
        root["context"]["kind"] = "choice"
        root["candidates"] = [{"candidate_id": 11, "semantic": {"kind": "choose_boolean", "value": False}},
                              {"candidate_id": 3, "semantic": {"kind": "choose_boolean", "value": True}}]
        result["selection"]["semantic_echo"] = root["candidates"][1]["semantic"]
        for child, offered in zip(result["children"], root["candidates"]):
            child["semantic"] = offered["semantic"]
        record.update(anchor={"decision": {}}, replay={"earlier": [], "priority_passes": ["p1"]})
        result["replay"] = {"earlier": 0, "priority_passes": 1, "observation_identical": True}
    result.update(decision_sha256=decision_hash(root), policy_width=1024,
                  settings=copy.deepcopy(play.PUBLISHED_SETTINGS), search_budget=play.budget())
    return record, result


def combat_fixture(family="attack"):
    record, result = original_combat(family)
    seat = record["decision"]["acting_seat"]
    record["game_start"]["seat"] = seat
    record["decision"]["observation"].update(active_seat="p0",
        phase_step="declare_attackers" if family == "attack" else "declare_blockers")
    result.update(decision_sha256=decision_hash(record["decision"]), policy_width=1024,
                  settings=copy.deepcopy(play.PUBLISHED_SETTINGS), search_budget=play.budget())
    for root in result["roots"]:
        root.update(requested_minimum=0, search_budget=play.budget())
    return record, result


@pytest.mark.parametrize("callback", [False, True])
def test_source_time_can_finish_below_96_visits_with_exact_settings_and_public_replay(callback):
    record, result = search_fixture(callback)
    peer, model = Peer(exchange(result, 1, "search")), Model()
    session = play.PublishedSession(peer, model)
    actual = session.choose(record, visits=96, timeout_s=3)
    assert actual["root_visits"] == 2 and actual["checkpoint"] == model.checkpoint
    assert peer.writes[0]["settings"] == play.PUBLISHED_SETTINGS and "visits" not in peer.writes[0]
    assert len(peer.writes[1]["scores"]["priority"]) == 1024
    assert model.calls and all(0 < clock <= 3 for _, clock in model.calls)
    with pytest.raises(ValueError):
        diagnostic_result(record, result, 96, result["neural_calls"])
    session.close()
    assert peer.closed and model.closed


@pytest.mark.parametrize("family", ["attack", "block"])
def test_source_time_combat_retains_one_original_plan_without_a_minimum_visit_claim(family):
    record, result = combat_fixture(family)
    peer, model = Peer(exchange(result, 1, "combat")), Model()
    session = play.PublishedSession(peer, model)
    actual = session.plan(record, visits=96, timeout_s=3)
    assert all(root["root_visits"] < 96 and root["requested_minimum"] == 0 for root in actual["roots"])
    plan = play.PublishedPlan(record["decision"], actual, visits=96)
    assert plan.select(record["decision"])["candidate_id"] == 7
    actual["pairs"].clear()
    assert plan.select(later_decision(record, family))["candidate_id"] == 19 and plan.complete
    assert len([r for r in peer.writes if "decision" in r]) == 1
    session.close()
    assert peer.closed and model.closed


@pytest.mark.parametrize("key", list(play.PUBLISHED_SETTINGS))
def test_changed_released_settings_are_refused_instead_of_becoming_the_same_profile(key):
    settings = copy.deepcopy(play.PUBLISHED_SETTINGS)
    value = settings[key]
    settings[key] = not value if type(value) is bool else value+1 if type(value) is int else "changed"
    with pytest.raises(ValueError, match="exact released"):
        play.validate_settings(settings)


@pytest.mark.parametrize("fault", ["width", "settings", "budget", "missing-budget", "stale",
                                  "missing-work", "replay", "minimum", "root-budget", "lost-work"])
def test_changed_results_close_the_whole_typed_session(fault):
    combat = fault in ("minimum", "root-budget", "lost-work")
    record, result = combat_fixture() if combat else search_fixture(callback=fault == "replay")
    if fault == "width": result["policy_width"] = 128
    elif fault == "settings": result["settings"]["noPolicyPriority"] = False
    elif fault == "budget": result["search_budget"]["timeout_seconds"] = "600"
    elif fault == "missing-budget": result.pop("search_budget")
    elif fault == "stale": result["decision_sha256"] = "0"*64
    elif fault == "missing-work": result["neural_calls"] = 0
    elif fault == "replay": result["replay"]["observation_identical"] = False
    elif fault == "minimum": result["roots"][0]["requested_minimum"] = 96
    elif fault == "root-budget": result["roots"][0]["search_budget"]["requested"] = 6
    else: result["roots"][0]["children"][1]["visits"] = 1
    peer, model = Peer(exchange(result, 1, "combat" if combat else "search")), Model()
    session = play.PublishedSession(peer, model)
    with pytest.raises(ValueError):
        (session.plan if combat else session.choose)(record, visits=96, timeout_s=3)
    assert session.failed and session.closed and peer.closed and model.closed


@pytest.mark.parametrize("fault", ["visits", "bool-visits", "viewer", "rewind", "later-combat"])
def test_bad_public_roots_close_before_request_or_inference(fault):
    record, _ = combat_fixture() if fault == "later-combat" else search_fixture()
    visits = 6 if fault == "visits" else True if fault == "bool-visits" else 96
    if fault == "viewer": record["decision"]["observation"]["viewer"] = "p1"
    elif fault == "rewind": record["decision"]["context"]["rewind"] = True
    elif fault == "later-combat": record["decision"]["group"]["substep_index"] = 1
    peer, model = Peer([]), Model()
    session = play.PublishedSession(peer, model)
    with pytest.raises(ValueError):
        (session.plan if fault == "later-combat" else session.choose)(record, visits=visits, timeout_s=3)
    assert not peer.writes and not model.calls and peer.closed and model.closed


@pytest.mark.parametrize("family", ["attack", "block"])
def test_public_frontend_binds_profile_through_priority_combat_and_terminal_cleanup(family):
    record, result = combat_fixture(family)
    seat = record["game_start"]["seat"]
    priority_record, priority_result = search_fixture()
    priority = priority_record["decision"]
    priority.update(acting_seat=seat, seat_step=0)
    priority["observation"].update(viewer=seat, turn=1, phase_step="precombat_main", players=[], stack=[])
    def received_hash(root):
        return decision_hash({**root, "x_history": {"loyalty_used": [], "card_origins": {}},
                              "x_observation_flags": {"passed_seats": True, "keywords": True}})
    priority_result["decision_sha256"] = received_hash(priority)
    initial = record["decision"]
    initial.update(seat_step=1)
    initial["observation"]["turn"] = 1
    result["decision_sha256"] = received_hash(initial)
    later = later_decision(record, family)
    later["seat_step"] = 2
    peer = Peer(exchange(priority_result, 1, "search")+exchange(result, 2, "combat"))
    model, audits = Model(), []
    bot = play.PublishedAgent(lambda: play.PublishedSession(peer, model), checkpoint=model.checkpoint, audit=audits.append)
    public = bot.public_session(name="published-test", version="pinned")
    def call(request):
        return json.loads(public.handle_line(wire.canonical_json_dumps(request)))
    assert call(game(seat=seat))["response_type"] == "ack"
    assert call(view(priority).raw)["selection"]["candidate_id"] == 3
    assert call(view(initial).raw)["selection"]["candidate_id"] == 7
    assert call(view(later).raw)["selection"]["candidate_id"] == 19
    requests = [r for r in peer.writes if "decision" in r]
    assert [r["operation"] for r in requests] == ["search", "combat"]
    assert all(r["settings"] == play.PUBLISHED_SETTINGS and "visits" not in r for r in requests)
    assert audits[0]["profile"]["source_opponent_hand_encoding"] is True
    assert audits[0]["profile"]["opponent_hand_encoding"] is False
    assert audits[0]["profile"]["full_game_qualified"] is False
    assert call({"protocol": "spellbench/v2", "request_id": "over", "request_type": "game_over",
                 "game_id": "opaque", "terminal": {}})["response_type"] == "ack"
    assert peer.closed and model.closed and bot.game is None


def test_wrong_architecture_and_legacy_session_cannot_serve_the_published_identity():
    peer, model = Peer([]), Model()
    model.architecture = "magezero-v02"
    with pytest.raises(ValueError, match="1024-slot"):
        play.PublishedSession(peer, model)
    assert peer.closed and model.closed
    peer, model = Peer([]), Model()
    legacy = runtime.BridgeSession(peer, model)
    bot = play.PublishedAgent(lambda: legacy, checkpoint=model.checkpoint)
    with pytest.raises(ValueError, match="typed play session"):
        bot.on_game_start(GameStart.from_request(game()))
    assert peer.closed and model.closed and not peer.writes


def test_public_mulligan_keeps_without_running_search():
    peer, model = Peer([]), Model()
    bot = play.PublishedAgent(lambda: play.PublishedSession(peer, model), checkpoint=model.checkpoint)
    bot.on_game_start(GameStart.from_request(game()))
    root = decision({"kind": "mulligan", "keep": False}, {"kind": "mulligan", "keep": True}, phase="pregame")
    assert bot.choose(view(root)) == 11 and not peer.writes and not model.calls
    bot.close()
    assert peer.closed and model.closed


def test_runtime_profile_is_separate_and_requires_its_new_compiled_support(tmp_path, monkeypatch):
    manifest = {"inference_backends": {"draftzero-exp1": {"checkpoints": ["gen33"]}},
                "assets": [{"id": "gen33", "sha256": "0"*64}]}
    params = dict(checkpoint="gen33", visits=96, build_sha256="a"*64, image="sha256:"+"b"*64, manifest=manifest)
    published = runtime.identity(**params, play_profile=play.PROFILE_NAME)
    diagnostic = runtime.identity(**params)
    assert published["name"] != diagnostic["name"] and published["version"] != diagnostic["version"]
    assert published["identity"]["profile"]["settings"]["backpropDiscount"] == "0.99"
    assert len(published["identity"]["source_sha256"]) == 10
    assert runtime.selected_visits(play.PROFILE_NAME, None) == 96
    assert runtime.selected_visits("minimum-visits-diagnostic", None) == 1000
    for visits in (6, 96.0, True):
        with pytest.raises(ValueError): runtime.selected_visits(play.PROFILE_NAME, visits)
    build, engine, release, metadata = build_fixture(tmp_path)
    monkeypatch.setattr(runtime, "verify_build", lambda *args: None)
    def write_manifest():
        (build/"BUILD.json").write_text(json.dumps(metadata))
        return runtime.sha(build/"BUILD.json")
    with pytest.raises(ValueError, match="published Exp1 play settings"):
        runtime.verify_model_build(build, write_manifest(), engine, release, play_profile=play.PROFILE_NAME)
    support = build/"model/spellbench/models/exp1/PlaySettings.class"
    support.parent.mkdir(parents=True)
    support.write_bytes(b"compiled support")
    metadata["class_files_sha256"]["model/spellbench/models/exp1/PlaySettings.class"] = runtime.sha(support)
    assert runtime.verify_model_build(build, write_manifest(), engine, release, play_profile=play.PROFILE_NAME) == metadata


def test_source_provenance_differentiates_training_labels_from_play_and_records_port_changes():
    source = json.loads((Path(__file__).parents[2]/"engines/xmage/draftzero-published-play.json").read_bytes())
    assert source["effective_play"] == {k:v for k,v in play.PUBLISHED_SETTINGS.items() if k != "profile"}
    assert len(source["sources"]) == 7 and source["rated_games"] == 0 and source["full_game_qualified"] is False
    assert source["hf_revision"] == "c0ac902361c041f986f429ad9d42e7b92494741f"
