"""Original priority slots survive offered order, IDs and additional choices."""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import xmage_jack_priority as priority
from xmage_jack_selection import GREEDY, JackSelectionSession
from xmage_jack_sources import CALLBACK_SHA256, ENCODER_SHA256
from xmage_neural_decisions import decision_hash
from test_xmage_jack_inference import Peer
from test_xmage_jack_modes import Model, fixture as mode_fixture

SOURCES = dict(zip(priority.SOURCE_KEYS, ("a"*64, ENCODER_SHA256, CALLBACK_SHA256, "b"*64)))


def fixture(*, pass_only=False, indices=None):
    start, _, _, _, _, features = mode_fixture()
    start["game_id"] = "priority-game"
    source = {"object_id":"first", "card_name":"Forest", "owner_seat":"p0", "controller_seat":"p0", "zone":"battlefield"}
    semantics = [{"kind":"pass"}, {"kind":"activate_mana_ability", "source":source,
                 "ability_index":0, "mana_choice":None, "cost_target":None}]
    extra = {"kind":"play_land", "source":{**source, "object_id":"second", "zone":"hand"}, "face":0}
    start["engine_profile"] = {"decision_kinds":["activate_mana_ability"]}
    decision = {"acting_seat":"p0", "seat_step":7, "context":{"kind":"priority"},
                "observation":{"viewer":"p0", "players":[]},
                "candidates":[{"candidate_id":88, "semantic":extra}, {"candidate_id":5, "semantic":semantics[1]},
                              {"candidate_id":100, "semantic":semantics[0]}]}
    count = 1 if pass_only else 2
    features = {k:copy.deepcopy(features[k]) for k in ("sequence", "padding", "token_ids", "candidate_ids", "candidate_features", "candidate_mask")}
    features.update(kind="candidates", head="action", candidate_mask=[True]*count+[False]*(64-count))
    features["candidate_ids"][count:] = [0]*(64-count)
    features["candidate_features"][count:] = [[0]*48 for _ in range(64-count)]
    frame = {"schema":"spellbench-jack-original-priority/v1", "variant":priority.VARIANT,
             "decision_sha256":decision_hash(decision), "game_start_sha256":decision_hash(start),
             "original_callback_sha256":CALLBACK_SHA256, "sources":SOURCES,
             "world_flags":[], "full_priority_player_qualified":False, "candidate_count":count,
             "candidate_refs":[{"index":i, "candidate_id":cid, "semantic":semantics[i]}
                               for i, cid in enumerate((100, 5)[:count])],
             "features":None if pass_only else features}
    chooser_peer = Peer([{"ready":True, "selection":"jack-original-no-training", "profile":GREEDY,
                         "seed":7, "callback_source_sha256":CALLBACK_SHA256},
                        {"id":"1", "ok":True, "indices":[1] if indices is None else indices}])
    chooser = JackSelectionSession(chooser_peer, profile=GREEDY, seed=7)
    model = Model(start)
    model.encoding["card_embeddings_sha256"] = SOURCES["embedding_cache_sha256"]
    def score(features, *, timeout_s):
        model.requests.append((copy.deepcopy(features), timeout_s))
        return {"probabilities":[0.8, 0.2]+[0]*62, "value":0.25}
    model.score = score
    return start, decision, frame, model, chooser_peer, chooser


def setup(**kwargs):
    start, decision, frame, model, peer, chooser = fixture(**kwargs)
    owned = priority.PrioritySelection(model, chooser, game_start=start, sources=SOURCES)
    return owned, decision, frame, model, peer


def test_uses_shared_original_chooser_instead_of_local_argmax_or_public_order():
    owned, decision, frame, model, peer = setup()
    result = owned.choose(decision, frame, timeout_s=5)
    assert result["selection"] == {"candidate_id":5, "semantic_echo":decision["candidates"][1]["semantic"]}
    assert result["full_priority_player_qualified"] is False
    assert peer.writes[0]["probabilities"][:2] == [0.8, 0.2]
    assert peer.writes[0]["count"] == 2 and peer.writes[0]["picks"] == 1 and peer.writes[0]["sequential"] is False
    assert 0 < peer.timeouts[0] <= model.requests[0][1] <= 5
    owned.close(); owned.close()
    assert peer.closed and model.closed == 1


def test_reassigned_public_ids_and_reordered_offerings_keep_original_slot():
    owned, decision, frame, model, peer = setup()
    decision["candidates"].reverse()
    for candidate in decision["candidates"]: candidate["candidate_id"] += 1000
    for ref in frame["candidate_refs"]: ref["candidate_id"] += 1000
    frame["decision_sha256"] = decision_hash(decision)
    result = owned.choose(decision, frame, timeout_s=5)
    assert result["selection"]["candidate_id"] == 1005
    assert model.requests[0][0] == frame["features"]
    owned.close()


def test_pass_only_avoids_network_and_original_rng_even_with_other_offered_choices():
    owned, decision, frame, model, peer = setup(pass_only=True)
    result = owned.choose(decision, frame, timeout_s=5)
    assert result["selection"] == {"candidate_id":100, "semantic_echo":{"kind":"pass"}}
    assert result["scores"] is None and not model.requests and not peer.writes
    owned.close()


@pytest.mark.parametrize("edit", [
    lambda f:f.update(decision_sha256="0"*64), lambda f:f.update(game_start_sha256="0"*64),
    lambda f:f["sources"].update(priority_rules_source_sha256="0"*64),
    lambda f:f.update(original_callback_sha256="0"*64), lambda f:f.update(full_priority_player_qualified=True),
    lambda f:f.update(world_flags=["unsupported:unimplemented"]), lambda f:f.update(world_flags=["horizon:incomplete"]),
    lambda f:f["candidate_refs"].reverse(), lambda f:f["candidate_refs"][1].update(candidate_id=88),
    lambda f:f["candidate_refs"][1]["semantic"].update(ability_index=True),
    lambda f:f["features"].update(head="target"), lambda f:f["features"]["candidate_mask"].__setitem__(2,True),
    lambda f:f["features"]["candidate_ids"].__setitem__(2,99),
    lambda f:f["features"]["candidate_features"][2].__setitem__(0,0.5),
    lambda f:f["features"]["sequence"][0].__setitem__(0,float("nan")),
])
def test_unbound_or_altered_frame_refuses_before_inference_and_closes_shared_components(edit):
    owned, decision, frame, model, peer = setup()
    frame = copy.deepcopy(frame); edit(frame)
    with pytest.raises(ValueError): owned.choose(decision, frame, timeout_s=5)
    assert owned.failed and peer.closed and model.closed == 1 and not model.requests and not peer.writes


@pytest.mark.parametrize("indices", [[2], [True], [], [0,1]])
def test_chooser_cannot_return_an_unbound_slot(indices):
    owned, decision, frame, model, peer = setup(indices=indices)
    with pytest.raises((ValueError, RuntimeError)): owned.choose(decision, frame, timeout_s=5)
    assert owned.failed and peer.closed and model.closed == 1


@pytest.mark.parametrize("change", ["duplicate_id", "duplicate_semantic", "wrong_viewer", "undeclared_mana"])
def test_invalid_offerings_or_profile_cannot_reach_the_model(change):
    start, decision, frame, model, peer, chooser = fixture()
    if change == "duplicate_id": decision["candidates"][0]["candidate_id"] = 5
    elif change == "duplicate_semantic": decision["candidates"][0]["semantic"] = copy.deepcopy(decision["candidates"][1]["semantic"])
    elif change == "wrong_viewer": decision["observation"]["viewer"] = "p1"
    else: start["engine_profile"]["decision_kinds"] = []; model.game_start_sha256 = decision_hash(start)
    frame["decision_sha256"] = decision_hash(decision); frame["game_start_sha256"] = decision_hash(start)
    owned = priority.PrioritySelection(model, chooser, game_start=start, sources=SOURCES)
    with pytest.raises(ValueError): owned.choose(decision, frame, timeout_s=5)
    assert peer.closed and model.closed == 1 and not model.requests


@pytest.mark.parametrize("change", ["game", "seed", "boolean_seed", "profile", "encoder", "embedding"])
def test_constructor_requires_same_game_model_and_chooser(change):
    start, _, _, model, peer, chooser = fixture()
    if change == "game": model.game_start_sha256 = "0"*64
    elif change == "seed": chooser.seed = 8
    elif change == "boolean_seed": start["agent_seed"] = True; chooser.seed = True; model.game_start_sha256 = decision_hash(start)
    elif change == "profile": chooser.profile = "substitute"
    elif change == "encoder": model.encoding["state_encoder_sha256"] = "0"*64
    else: model.encoding["card_embeddings_sha256"] = "0"*64
    with pytest.raises(ValueError): priority.PrioritySelection(model, chooser, game_start=start, sources=SOURCES)
    assert peer.closed and model.closed == 1


def test_shared_clock_expires_before_any_second_component_call(monkeypatch):
    owned, decision, frame, model, peer = setup()
    times = iter((100, 100.1, 106))
    monkeypatch.setattr(priority.time, "monotonic", lambda: next(times))
    with pytest.raises(TimeoutError): owned.choose(decision, frame, timeout_s=5)
    assert len(model.requests) == 1 and not peer.writes and peer.closed and model.closed == 1
