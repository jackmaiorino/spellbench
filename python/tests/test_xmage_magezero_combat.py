"""MageZero combat preserves source stopping rules, architecture and ownership."""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import xmage_magezero_combat as combat
import xmage_magezero_bridge as bridge
import xmage_magezero_search as search
from xmage_neural_decisions import decision_hash
from test_xmage_neural_combat import fixture as original_fixture, later_decision
from test_xmage_neural_bridge import Peer, exchange
from test_xmage_magezero_search import Model, fixture as search_fixture


def fixture(family="attack", settings=None):
    record, result = original_fixture(family)
    settings = copy.deepcopy(settings or search.diagnostic_settings(2))
    seat = record["decision"]["acting_seat"]
    record["game_start"]["seat"] = seat
    record["decision"]["observation"].update(active_seat="p0",
        phase_step="declare_attackers" if family == "attack" else "declare_blockers")
    result.update(decision_sha256=decision_hash(record["decision"]), settings=copy.deepcopy(settings),
                  policy_width=128, search_budget=search.budget(settings))
    for root in result["roots"]:
        root.update(search_budget=search.budget(settings),
                    requested_minimum=settings["searchBudget"] if settings["profile"] == "minimum-visits-diagnostic" else 0)
    return record, result, settings


@pytest.mark.parametrize("family", ["attack", "block"])
@pytest.mark.parametrize("source_profile", [False, True])
def test_combat_keeps_the_source_stopping_rule_and_reuses_one_plan(family, source_profile):
    record, result, settings = fixture(family, search.ORIGINAL_DEFAULT_SETTINGS if source_profile else None)
    peer, model = Peer(exchange(result, 1, "combat"), ready=combat.READY), Model()
    session = combat.CombatSession(peer, model)
    actual = session.plan(record, settings=settings, timeout_s=3)
    assert actual["checkpoint"] == model.checkpoint and actual["selection"]["candidate_id"] == 7
    assert peer.writes[0]["settings"] == settings and "visits" not in peer.writes[0]
    assert all(len(reply["scores"]["priority"]) == 128 for reply in peer.writes[1:])
    plan = combat.CombatPlan(record["decision"], actual, settings=settings)
    assert plan.select(record["decision"])["candidate_id"] == 7
    actual["pairs"].clear()
    assert plan.select(later_decision(record, family))["candidate_id"] == 19 and plan.complete
    session.close()
    assert peer.closed and model.closed


def test_source_time_stop_cannot_be_relabelled_as_completed_minimum_visits():
    record, result, settings = fixture(settings=search.diagnostic_settings(1000))
    with pytest.raises(ValueError, match="original search budget"):
        combat.combat_result(record, result, settings, result["neural_calls"])
    with pytest.raises(ValueError, match="original search budget"):
        combat.CombatPlan(record["decision"], result, settings=settings)


@pytest.mark.parametrize("fault", ["width", "settings", "stopping-rule", "root-stopping-rule",
                                  "minimum", "work", "hidden", "calls"])
def test_changed_policy_settings_work_or_public_binding_poison_the_owned_session(fault):
    record, result, settings = fixture()
    if fault == "width": result["policy_width"] = 1024
    elif fault == "settings": result["settings"]["profile"] = "guessed"
    elif fault == "stopping-rule": result["search_budget"]["timeout_seconds"] = "4"
    elif fault == "root-stopping-rule": result["roots"][0]["search_budget"]["requested"] = 6
    elif fault == "minimum": result["roots"][0]["requested_minimum"] = 0
    elif fault == "work": result["roots"][0]["children"][1]["visits"] = 1
    elif fault == "hidden": result["pairs"][0]["attacker"] = "hidden-creature"
    else: result["neural_calls"] = 1
    peer, model = Peer(exchange(result, 1, "combat"), ready=combat.READY), Model()
    session = combat.CombatSession(peer, model)
    with pytest.raises(ValueError):
        session.plan(record, settings=settings, timeout_s=3)
    assert session.failed and session.closed and peer.closed and model.closed


@pytest.mark.parametrize("fault", ["seat", "viewer", "active", "phase", "rewind", "later-group", "missing-settings"])
def test_refused_initial_declaration_closes_before_any_inference(fault):
    record, _, settings = fixture()
    if fault == "seat": record["game_start"]["seat"] = "p1"
    elif fault == "viewer": record["decision"]["observation"]["viewer"] = "p1"
    elif fault == "active": record["decision"]["observation"]["active_seat"] = "p1"
    elif fault == "phase": record["decision"]["observation"]["phase_step"] = "postcombat_main"
    elif fault == "rewind": record["decision"]["context"]["rewind"] = True
    elif fault == "later-group": record["decision"]["group"]["substep_index"] = 1
    else: settings.pop("noPolicyTarget")
    peer, model = Peer([], ready=combat.READY), Model()
    session = combat.CombatSession(peer, model)
    with pytest.raises(ValueError):
        session.plan(record, settings=settings, timeout_s=3)
    assert not peer.writes and not model.calls and peer.closed and model.closed


def test_mixed_priority_attack_priority_block_share_one_checkpoint_and_sequence():
    roots = [(search_fixture(), "search"), (fixture(), "combat"),
             (search_fixture(), "search"), (fixture("block"), "combat")]
    messages = [item for number, ((_, result, _), operation) in enumerate(roots, 1)
                for item in exchange(result, number, operation)]
    peer, model = Peer(messages, ready=bridge.READY), Model()
    session = bridge.BridgeSession(peer, model)
    for (record, result, settings), operation in roots:
        record.update(operation="injected", id="999", settings={"ignored": True})
        run = session.choose if operation == "search" else session.plan
        assert run(record, settings=settings, timeout_s=3)["checkpoint"] == model.checkpoint
    requests = [message for message in peer.writes if "decision" in message]
    assert [item["id"] for item in requests] == ["1", "2", "3", "4"]
    assert [item["operation"] for item in requests] == ["search", "combat", "search", "combat"]
    assert len(model.calls) == 6
    session.close()
    assert peer.closed and model.closed


@pytest.mark.parametrize("session_type,ready", [(combat.CombatSession, combat.READY),
                                               (bridge.BridgeSession, bridge.READY)])
def test_exp1_weights_are_refused_before_search_or_combat(session_type, ready):
    peer, model = Peer([], ready=ready), Model()
    model.architecture = "draftzero-exp1"
    with pytest.raises(ValueError, match="128-slot checkpoint"):
        session_type(peer, model)
    assert not peer.writes and peer.closed and model.closed


def test_mixed_operation_mismatch_prevents_later_search():
    record, result, settings = fixture()
    messages = exchange(result, 1, "search")
    peer, model = Peer(messages, ready=bridge.READY), Model()
    session = bridge.BridgeSession(peer, model)
    with pytest.raises(ValueError, match="requested operation"):
        session.plan(record, settings=settings, timeout_s=3)
    count = len(peer.writes)
    search_record, _, search_settings = search_fixture()
    with pytest.raises(ValueError, match="closed or has failed"):
        session.choose(search_record, settings=search_settings, timeout_s=3)
    assert len(peer.writes) == count and peer.closed and model.closed
