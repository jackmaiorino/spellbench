"""Original multi-pick combat preserves DONE/RNG work and binds public substeps."""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import xmage_jack_combat as combat
from xmage_jack_selection import GREEDY, JackSelectionSession
from xmage_jack_sources import CALLBACK_SHA256, ENCODER_SHA256, COMBAT_VARIANT, combat_source, stage
from xmage_neural_decisions import decision_hash
from test_xmage_neural_combat import fixture as combat_fixture
from test_xmage_jack_inference import Peer
from test_xmage_jack_modes import Model, fixture as mode_fixture

SOURCES = {"embedding_cache_sha256":"a"*64, "encoder_source_sha256":ENCODER_SHA256,
           "candidate_source_sha256":CALLBACK_SHA256, "combat_rules_source_sha256":"b"*64}


def fixture(family="attack", *, indices=None, extra_round=None, edit_frame=None, edit_result=None, edit_ready=None):
    record, old_result = combat_fixture(family)
    decision = record["decision"]
    start = {"seat":decision["acting_seat"], "game_id":"combat-game", "agent_seed":7}
    _, _, _, _, _, features = mode_fixture()
    features = {k:copy.deepcopy(features[k]) for k in ("sequence", "padding", "token_ids", "candidate_ids", "candidate_features", "candidate_mask")}
    features.update(kind="candidates", head="attack" if family == "attack" else "block")
    context = None if family == "attack" else {"object_id":"other-1"}
    frame = {"id":"1", "event":"choose", "call":1, "type":"DECLARE_ATTACKS" if family == "attack" else "DECLARE_BLOCKS",
             "candidate_count":3, "picks":3, "sequential":True,
             "candidate_refs":[{"creature":name, "context":context} for name in ("own-1", "own-2", None)],
             "features":features, "decision_sha256":decision_hash(decision)}
    selected = [0,2,1] if indices is None else indices
    receipt = {k:copy.deepcopy(v) for k,v in frame.items() if k not in ("id", "event", "features")}
    receipt["indices"] = selected
    request = {"id":"1", "game_start":start, "decision":decision, "world_seed":"1"*64, "id_seed":"2"*64}
    result = {"decision_sha256":decision_hash(decision), "request_sha256":decision_hash(request), "combat":family,
              "variant":COMBAT_VARIANT, "neural_calls":1, "world_flags":[], "pairs":old_result["pairs"], "rounds":[receipt]}
    if selected[0] == 2: result["pairs"] = []
    ready = {"ready":True, "encoder":"jack-permitted-combat", "original_callback_sha256":CALLBACK_SHA256,
             "variant":COMBAT_VARIANT, "embedding_count":4, **SOURCES}
    if edit_frame: edit_frame(frame)
    if edit_result: edit_result(result)
    if edit_ready: edit_ready(ready)
    messages = [ready, frame]
    chooser_messages = [{"ready":True, "selection":"jack-original-no-training", "profile":GREEDY,
                         "seed":7, "callback_source_sha256":CALLBACK_SHA256}, {"id":"1", "ok":True, "indices":selected}]
    if extra_round is not None:
        extra = copy.deepcopy(frame)
        extra.update(call=2, type="DECLARE_ATTACK_TARGET", candidate_count=2, picks=1, sequential=False)
        extra["candidate_refs"] = [{"creature":"own-1", "context":{"player":"p1"}},
                                   {"creature":"own-1", "context":{"object_id":"other-1"}}]
        extra["features"]["candidate_mask"] = [True]*2+[False]*62
        extra["features"]["candidate_ids"][2] = 0; extra["features"]["candidate_features"][2] = [0]*48
        extra_round(extra)
        messages.append(extra)
        receipt = {k:copy.deepcopy(v) for k,v in extra.items() if k not in ("id", "event", "features")}; receipt["indices"] = [0]
        result["rounds"].append(receipt); result["neural_calls"] = 2
        chooser_messages.append({"id":"2", "ok":True, "indices":[0]})
    messages.append({"id":"1", "event":"result", "ok":True, "result":result})
    peer, chooser_peer = Peer(messages), Peer(chooser_messages)
    model = Model(start)
    model.encoding["card_embeddings_sha256"] = SOURCES["embedding_cache_sha256"]
    if extra_round is not None:
        def score(value, *, timeout_s):
            model.requests.append((copy.deepcopy(value), timeout_s))
            count = sum(value["candidate_mask"])
            return {"probabilities":[1/count]*count+[0]*(64-count), "value":0.2}
        model.score = score
    chooser = JackSelectionSession(chooser_peer, profile=GREEDY, seed=7)
    return start, decision, peer, model, chooser_peer, chooser, ready, result


def setup(**kwargs):
    start, decision, peer, model, chooser_peer, chooser, ready, result = fixture(**kwargs)
    owned = combat.CombatSession(peer, model, chooser, game_start=start, sources=SOURCES)
    return owned, decision, peer, model, chooser_peer, result


def run(owned, decision):
    return owned.plan(decision, world_seed="1"*64, id_seed="2"*64, timeout_s=5)


@pytest.mark.parametrize("family", ["attack", "block"])
def test_original_full_sequential_draw_includes_choices_after_done(family):
    owned, decision, peer, model, chooser, _ = setup(family=family)
    result, plan = run(owned, decision)
    assert result["selection"]["candidate_id"] == 7
    assert chooser.writes[0]["picks"] == 3 and chooser.writes[0]["sequential"] is True
    assert peer.writes[1]["indices"] == [0,2,1]
    assert model.requests[0][0]["head"] == ("attack" if family == "attack" else "block")
    assert 0 < chooser.timeouts[0] <= model.requests[0][1] <= peer.timeouts[0] <= 5
    assert plan.select(decision)["candidate_id"] == 7
    second = copy.deepcopy(decision)
    second["seat_step"] += 1; second["group"]["substep_index"] = 1
    for candidate in second["candidates"]:
        candidate["semantic"]["attacker" if family == "attack" else "blocker"]["object_id"] = "own-2"
    assert plan.select(second)["candidate_id"] == 19 and plan.complete
    owned.close(); owned.close()
    assert peer.closed and chooser.closed and model.closed == 1


def test_done_first_keeps_full_original_rng_work_but_declares_no_attack():
    owned, decision, peer, model, chooser, _ = setup(indices=[2,0,1])
    result, _ = run(owned, decision)
    assert result["pairs"] == [] and result["selection"]["candidate_id"] == 19
    assert chooser.writes[0]["picks"] == 3
    owned.close()


def test_separate_defender_round_uses_same_attack_head_and_single_original_pick():
    owned, decision, peer, model, chooser, _ = setup(extra_round=lambda frame:None)
    result, _ = run(owned, decision)
    assert result["neural_calls"] == 2
    assert [message["picks"] for message in chooser.writes] == [3,1]
    assert [message["sequential"] for message in chooser.writes] == [True,False]
    assert [features["head"] for features, _ in model.requests] == ["attack","attack"]
    owned.close()


@pytest.mark.parametrize("edit", [
    lambda f:f.update(id="2"), lambda f:f.update(call=2), lambda f:f.update(type="DECLARE_BLOCKS"),
    lambda f:f.update(decision_sha256="0"*64), lambda f:f.update(picks=1), lambda f:f.update(sequential=False),
    lambda f:f["candidate_refs"].reverse(), lambda f:f["candidate_refs"][0].update(creature="other-1"),
    lambda f:f["candidate_refs"][0].update(context={"player":"p1"}),
    lambda f:f["features"].update(head="target"), lambda f:f["features"]["candidate_mask"].__setitem__(3,True),
    lambda f:f["features"]["candidate_ids"].__setitem__(3,100),
    lambda f:f["features"]["candidate_features"][3].__setitem__(0,0.2),
    lambda f:f["features"]["sequence"][0].__setitem__(0,float("nan")),
])
def test_changed_combat_frame_fails_and_closes_all_owned_components(edit):
    owned, decision, peer, model, chooser, _ = setup(edit_frame=edit)
    with pytest.raises((ValueError, RuntimeError)): run(owned, decision)
    assert owned.failed and peer.closed and chooser.closed and model.closed == 1
    assert not model.requests


@pytest.mark.parametrize("edit", [
    lambda r:r.update(request_sha256="0"*64), lambda r:r.update(neural_calls=0),
    lambda r:r.update(variant="native MAD combat"), lambda r:r.update(world_flags=["unsupported:card"]),
    lambda r:r["rounds"][0].update(indices=[2,0,1]),
    lambda r:r["pairs"][0].update(attacker="own-2"), lambda r:r["pairs"].append(copy.deepcopy(r["pairs"][0])),
])
def test_unobserved_choices_or_invented_combat_pairs_fail(edit):
    owned, decision, peer, model, chooser, _ = setup(edit_result=edit)
    with pytest.raises(ValueError): run(owned, decision)
    assert owned.failed and peer.closed and chooser.closed and model.closed == 1


def test_original_cached_base_state_cannot_change_between_defender_rounds():
    owned, decision, peer, model, chooser, _ = setup(extra_round=lambda f:f["features"]["sequence"][0].__setitem__(0,1))
    with pytest.raises(ValueError, match="cached base state"): run(owned, decision)
    assert len(model.requests) == 1 and owned.failed


def test_encoder_readiness_cannot_substitute_other_source_or_policy():
    start, _, peer, model, chooser_peer, chooser, _, _ = fixture(edit_ready=lambda r:r.update(combat_rules_source_sha256="f"*64))
    with pytest.raises(ValueError, match="readiness"):
        combat.CombatSession(peer, model, chooser, game_start=start, sources=SOURCES)
    assert peer.closed and chooser_peer.closed and model.closed == 1


@pytest.mark.parametrize("flag", ["true", 1, None, []])
def test_combat_flag_is_not_coerced(tmp_path, flag):
    with pytest.raises(ValueError, match="explicit boolean"):
        stage({"schema":"spellbench-xmage-release-inputs/v1", "inference_backends":{"jack-rl-april":{"combat_callback":flag}}}, tmp_path, tmp_path/"out")


def test_original_callback_bytes_must_match_before_source_extraction():
    with pytest.raises(ValueError, match="pinned April"):
        combat_source("public class ReplacementPolicy {}")
