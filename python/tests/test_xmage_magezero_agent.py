"""Exercise MageZero's public lifecycle through its typed mixed bridge."""
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import xmage_magezero_agent as agent
import xmage_magezero_bridge as bridge
import xmage_magezero_search as search
from spellbench import wire
from spellbench.bot import GameOver, GameStart
from xmage_neural_decisions import decision_hash
from test_xmage_magezero_search import Model, fixture as search_fixture
from test_xmage_magezero_combat import fixture as combat_fixture
from test_xmage_neural_agent import Session, cleanup_decisions, decision, game, view
from test_xmage_neural_bridge import Peer, exchange
from test_xmage_neural_combat import later_decision


@pytest.mark.parametrize("family", ["attack", "block"])
@pytest.mark.parametrize("source_profile", [False, True])
def test_public_lifecycle_preserves_settings_and_reuses_the_original_combat_plan(family, source_profile):
    settings = copy.deepcopy(search.ORIGINAL_DEFAULT_SETTINGS if source_profile else search.diagnostic_settings(2))
    record, result, _ = combat_fixture(family, settings)
    seat = record["game_start"]["seat"]
    priority_record, priority_result, _ = search_fixture(settings)
    priority = priority_record["decision"]
    priority.update(acting_seat=seat, seat_step=0)
    priority["observation"].update(viewer=seat, turn=1, phase_step="precombat_main", players=[], stack=[])
    def received_hash(decision):
        return decision_hash({**decision, "x_history": {"loyalty_used": [], "card_origins": {}},
                              "x_observation_flags": {"passed_seats": True, "keywords": True}})
    priority_result["decision_sha256"] = received_hash(priority)
    initial = record["decision"]
    initial.update(seat_step=1)
    initial["observation"]["turn"] = 1
    result["decision_sha256"] = received_hash(initial)
    later = later_decision(record, family)
    later["seat_step"] = 2
    peer = Peer(exchange(priority_result, 1, "search") + exchange(result, 2, "combat"), ready=bridge.READY)
    model, contexts, audits = Model(), [], []

    def factory(context):
        contexts.append(context)
        return bridge.BridgeSession(peer, model)

    bot = agent.MageZeroAgent(factory, checkpoint=model.checkpoint, settings=settings, audit=audits.append)
    settings["searchBudget"] = 17  # External mutation cannot change the bound settings.
    public = bot.public_session(name="magezero-test", version="pinned")

    def call(request):
        return json.loads(public.handle_line(wire.canonical_json_dumps(request)))

    hello = call({"protocol": "spellbench/v2", "request_id": "hello", "request_type": "hello"})
    assert hello["requires"]["observation"] == ["passed_seats", "keywords"]
    start = game(seat=seat)
    start["hidden_engine_state"] = {"opponent_library": "must not reach the model factory"}
    assert call(start)["response_type"] == "ack"
    assert contexts == [{"seat": seat, "own_deck": start["own_deck"]}]
    response = call(view(priority).raw)
    assert "selection" in response, (response, audits)
    assert response["selection"]["candidate_id"] == priority_result["selection"]["candidate_id"]
    assert call(view(initial).raw)["selection"]["candidate_id"] == 7
    assert call(view(later).raw)["selection"]["candidate_id"] == 19
    requests = [item for item in peer.writes if "decision" in item]
    assert [item["operation"] for item in requests] == ["search", "combat"]
    assert all(item["settings"] == audits[0]["profile"]["settings"] and "visits" not in item for item in requests)
    assert audits[0]["profile"]["architecture"] == "magezero-v02"
    assert audits[0]["profile"]["full_game_qualified"] is False
    if source_profile:
        assert result["roots"][0]["root_visits"] < bot.visits
        assert "original_source_time_or_visits" in audits[0]["profile"]["search_budget"]["kind"]
    terminal = {"protocol": "spellbench/v2", "request_id": "over", "request_type": "game_over",
                "game_id": "opaque", "terminal": {}}
    assert call(terminal)["response_type"] == "ack"
    assert peer.closed and model.closed and bot.game is None


def test_original_mulligan_and_public_cleanup_history_use_the_magezero_settings():
    session = Session([0, 1], checkpoint="magezero-test")
    session.model.architecture = "magezero-v02"
    requests = []

    class TypedSession:
        model = session.model
        def choose(self, record, *, settings, timeout_s):
            requests.append((copy.deepcopy(record), copy.deepcopy(settings)))
            return session.choose(record, visits=settings["searchBudget"], timeout_s=timeout_s)
        def close(self):
            session.close()

    settings = search.ORIGINAL_DEFAULT_SETTINGS
    bot = agent.MageZeroAgent(lambda context: TypedSession(), checkpoint="magezero-test", settings=settings)
    bot.on_game_start(GameStart.from_request(game()))
    mulligan = decision({"kind": "mulligan", "keep": False}, {"kind": "mulligan", "keep": True}, phase="pregame")
    assert bot.choose(view(mulligan)) == 11 and not requests
    anchor, callback = cleanup_decisions()
    anchor["seat_step"], callback["seat_step"] = 1, 2
    assert bot.choose(view(anchor)) == 10
    assert bot.choose(view(callback)) == 10
    later = copy.deepcopy(callback)
    later["seat_step"] = 3
    assert bot.choose(view(later)) == 11
    assert all(actual == settings for _, actual in requests)
    assert requests[0][0]["replay"] == {"priority_passes": ["p1"], "earlier": []}
    assert len(requests[1][0]["replay"]["earlier"]) == 1
    bot.on_game_over(GameOver.from_request({"game_id": "opaque", "terminal": {}}))
    assert session.closed


@pytest.mark.parametrize("fault", ["architecture", "checkpoint", "changed-budget"])
def test_mismatched_identity_or_settings_close_without_a_substitute(fault):
    peer, model = Peer([], ready=bridge.READY), Model()
    session = bridge.BridgeSession(peer, model)
    if fault == "architecture": model.architecture = "draftzero-exp1"
    if fault == "checkpoint": model.checkpoint = "different"
    bot = agent.MageZeroAgent(lambda context: session, checkpoint="author-supplied-pinned-model",
                             settings=search.diagnostic_settings(2))
    with pytest.raises(ValueError):
        bot.on_game_start(GameStart.from_request(game()))
        bot.session.choose({}, visits=3, timeout_s=1)
    assert peer.closed and model.closed and not peer.writes


def test_game_over_starts_a_new_deck_bound_session_without_history_carryover():
    models, contexts = [], []
    def factory(context):
        model = Model()
        models.append(model)
        contexts.append(context)
        return bridge.BridgeSession(Peer([], ready=bridge.READY), model)
    bot = agent.MageZeroAgent(factory, checkpoint=Model.checkpoint, settings=search.diagnostic_settings(2))
    bot.on_game_start(GameStart.from_request(game()))
    bot.on_game_over(GameOver.from_request({"game_id": "opaque", "terminal": {}}))
    bot.on_game_start(GameStart.from_request(game("second", seat="p1")))
    assert len(models) == 2 and models[0].closed and bot.history.anchor is None
    assert [context["seat"] for context in contexts] == ["p0", "p1"]
    bot.close()
    assert models[1].closed
