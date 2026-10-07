"""General choices preserve original target features and their actual wire semantics."""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import xmage_maintainer_general_targets as general
from xmage_maintainer_selection import GREEDY, MaintainerSelectionSession
from xmage_maintainer_sources import CALLBACK_SHA256
from xmage_neural_decisions import decision_hash
from test_xmage_maintainer_inference import Peer
from test_xmage_maintainer_modes import Model
from test_xmage_maintainer_targets import fixture as target_fixture, SOURCES


def fixture(kind="select_object", *, slot=0, **kwargs):
    start, decision, anchor, replay, ready, encoded = target_fixture(**kwargs)
    for candidate in decision["candidates"]:
        semantic = candidate["semantic"]
        if kind == "choose_target": continue
        semantic.pop("slot")
        if semantic["kind"] == "finish_target_selection":
            assert kind == "select_object"
            semantic.update(kind="finish_selection", purpose="discard")
        elif kind == "select_object":
            semantic.update(kind=kind, purpose="discard", choice=semantic.pop("target"))
        else:
            assert kind == "choose_cost_target"
            semantic.update(kind=kind, cost_kind="discard", candidate=semantic.pop("target")["object"])
    normalized = general.normalize_decision(decision, slot)
    encoded.update(schema="spellbench-maintainer-general-target-features/v1", variant=general.VARIANT,
        decision_sha256=decision_hash(decision), normalized_decision_sha256=decision_hash(normalized), target_slot=slot)
    ready.update(encoder=general.GeneralTargetSession.ENCODER, variant=general.VARIANT)
    return start, decision, anchor, replay, ready, encoded


def setup(kind="select_object", *, edit_decision=None, edit_frame=None, edit_ready=None, chosen=1, **kwargs):
    start, decision, anchor, replay, ready, encoded = fixture(kind, **kwargs)
    if edit_decision: edit_decision(decision)
    encoded["request_sha256"] = decision_hash({"id":"1", "game_start":start, "decision":decision,
        "anchor":anchor, "replay":replay, "world_seed":"1"*64, "id_seed":"2"*64})
    if edit_frame: edit_frame(encoded)
    if edit_ready: edit_ready(ready)
    peer = Peer([ready, {"id":"1", "ok":True, "encoded":encoded}])
    chooser = Peer([{"ready":True, "selection":"maintainer-original-no-training", "profile":GREEDY,
        "seed":7, "callback_source_sha256":CALLBACK_SHA256}, {"id":"1", "ok":True, "indices":[chosen]}])
    selector = MaintainerSelectionSession(chooser, profile=GREEDY, seed=7)
    model = Model(start); model.encoding["card_embeddings_sha256"] = SOURCES["embedding_cache_sha256"]
    count = encoded["candidate_count"]
    model.scores["probabilities"] = [1/count]*count+[0]*(64-count)
    try: owned = general.GeneralTargetSession(peer, model, selector, game_start=start, sources=SOURCES)
    except BaseException:
        assert peer.closed and chooser.closed and model.closed == 1
        raise
    return owned, decision, anchor, replay, peer, model, chooser, encoded


def choose(values):
    owned, decision, anchor, replay = values[:4]
    return owned.choose(decision, anchor=anchor, replay=replay, world_seed="1"*64, id_seed="2"*64, timeout_s=5)


@pytest.mark.parametrize("kind,slot", [("choose_target", 0), ("choose_cost_target", 0), ("select_object", 0), ("select_object", 3)])
def test_general_callback_returns_exact_original_wire_action_and_target_features(kind, slot):
    values = setup(kind, slot=slot)
    result = choose(values)
    assert result["selection"]["candidate_id"] == 100
    assert result["selection"]["semantic_echo"] == values[1]["candidates"][0]["semantic"]
    assert result["selection"]["semantic_echo"]["kind"] == kind
    features, timeout = values[5].requests[0]
    assert features["head"] == "target" and features["candidate_features"] == values[7]["candidate_features"]
    assert features["decision_sha256"] == decision_hash(values[1])
    assert 0 < values[6].timeouts[0] <= timeout <= values[4].timeouts[0] <= 5
    values[0].close(); assert values[4].closed and values[6].closed and values[5].closed == 1


@pytest.mark.parametrize("kind,kwargs", [("choose_cost_target", {"same":True}), ("select_object", {"single":True}),
                                       ("select_object", {"same":True, "stop":True})])
def test_general_direct_choices_preserve_original_model_and_rng_bypass(kind, kwargs):
    values = setup(kind, **kwargs)
    result = choose(values)
    assert result["selection"]["candidate_id"] == values[7]["forced_candidate_id"]
    assert result["scores"] is None and not values[5].requests and not values[6].writes
    assert values[0].selection.sequence == 0
    values[0].close()


def test_general_stop_returns_finish_selection_and_keeps_original_first_slot():
    values = setup(stop=True, chosen=0)
    assert choose(values)["selection"]["semantic_echo"]["kind"] == "finish_selection"
    assert values[5].requests[0][0]["original_targets"][0] is None
    values[0].close()


def test_general_normalization_preserves_request_and_normalizes_only_callback_fields():
    _, decision, _, _, _, _ = fixture("choose_cost_target", slot=3)
    before = copy.deepcopy(decision)
    normalized = general.normalize_decision(decision, 3)
    assert decision == before
    assert normalized["context"] == decision["context"] and normalized["observation"] == decision["observation"]
    for original, mapped in zip(decision["candidates"], normalized["candidates"]):
        assert original["candidate_id"] == mapped["candidate_id"]
        assert mapped["semantic"]["target"] == {"object":original["semantic"]["candidate"]}
        assert mapped["semantic"]["slot"] == 3 and mapped["semantic"]["kind"] == "choose_target"


@pytest.mark.parametrize("edit", [
    lambda d:d["candidates"][0]["semantic"].update(kind="choose_number"),
    lambda d:d["candidates"][0]["semantic"].update(target={"object":{}}),
    lambda d:d["candidates"][0]["semantic"].update(purpose="sacrifice"),
    lambda d:d["candidates"][0]["semantic"].update(purpose=""),
    lambda d:d["candidates"][0]["semantic"].update(purpose=True),
    lambda d:d["candidates"][0]["semantic"].update(selected_count=True),
    lambda d:d["candidates"][0]["semantic"].update(minimum=-1),
    lambda d:d["candidates"][0]["semantic"].update(maximum=99999),
    lambda d:d["candidates"][0]["semantic"]["choice"]["object"].update(card_name="Hidden"),
    lambda d:d["candidates"][0]["semantic"]["choice"]["object"].update(object_id="hidden"),
    lambda d:d["candidates"][0].update(candidate_id=True),
    lambda d:d["candidates"][1].update(candidate_id=100),
])
def test_bad_general_wire_action_refuses_before_encoder_io_and_closes_all_owners(edit):
    values = setup(edit_decision=edit)
    with pytest.raises(ValueError): choose(values)
    assert not values[4].writes and not values[5].requests and not values[6].writes
    assert values[4].closed and values[6].closed and values[5].closed == 1


@pytest.mark.parametrize("edit", [
    lambda f:f.update(schema="spellbench-maintainer-target-features/v1"),
    lambda f:f.update(variant="other"), lambda f:f.update(normalized_decision_sha256="0"*64),
    lambda f:f.update(decision_sha256="0"*64), lambda f:f.update(request_sha256="0"*64),
    lambda f:f.update(target_slot=True), lambda f:f.update(target_slot=-1), lambda f:f.update(target_slot=4097),
    lambda f:f.update(target_slot=3), lambda f:f.update(head="card_select"),
    lambda f:f.update(target_rules_source_sha256="0"*64), lambda f:f.update(mana_payment_variant="other"),
    lambda f:f["original_targets"].reverse(), lambda f:f["candidate_refs"][0].update(candidate_id=100),
])
def test_bad_general_frame_refuses_before_model_or_original_chooser(edit):
    values = setup(edit_frame=edit)
    with pytest.raises(ValueError): choose(values)
    assert not values[5].requests and not values[6].writes
    assert values[4].closed and values[6].closed and values[5].closed == 1


@pytest.mark.parametrize("edit", [lambda r:r.update(encoder="maintainer-permitted-target"), lambda r:r.update(variant="other")])
def test_general_pipe_cannot_be_replaced_with_legacy_or_wrong_variant(edit):
    with pytest.raises(ValueError): setup(edit_ready=edit)


def test_original_spell_pipe_keeps_its_cost_and_object_refusal_boundaries():
    import xmage_maintainer_targets
    for kind in ("select_object", "choose_cost_target"):
        start, decision, *_ = fixture(kind)
        with pytest.raises(ValueError): xmage_maintainer_targets.bound_view(start, decision)
