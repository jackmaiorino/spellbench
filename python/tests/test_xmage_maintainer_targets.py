"""Original target slots, direct returns, STOP and source identities stay bound."""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import xmage_maintainer_targets as targets
from xmage_maintainer_selection import GREEDY, MaintainerSelectionSession
from xmage_maintainer_sources import CALLBACK_SHA256, MANA_PAYMENT_VARIANT, stage, target_source
from xmage_neural_decisions import decision_hash
from test_xmage_maintainer_inference import Peer
from test_xmage_maintainer_modes import fixture as mode_fixture, Model

SOURCES = {key: char * 64 for key, char in zip(targets.SOURCE_KEYS, "abcdef1")}


def fixture(*, stop=False, same=False, single=False, many=False, players=False):
    start, decision, anchor, replay, _, frame = mode_fixture()
    count = 65 if many else 1 if single else 2
    refs = [{"object_id":f"target-{i}", "card_name":("Forest" if same else f"Target {i}"),
             "controller_seat":"p1", "owner_seat":"p1", "zone":"battlefield"} for i in range(count)]
    decision["observation"]["players"].append({"seat":"p1", "battlefield":refs,
        **{key:[] for key in ("hand", "graveyard", "exile", "command")}})
    decision["candidates"] = [{"candidate_id":i+100, "semantic":{"kind":"choose_target",
        "source":decision["context"]["source"], "slot":0, "selected_count":0,
        "minimum":0 if stop else 1, "maximum":2 if stop else 1, "target":{"object":copy.deepcopy(ref)}}} for i, ref in enumerate(refs)]
    order = [{"object":ref} for ref in reversed(refs)]
    names = [ref["card_name"] for ref in reversed(refs)]
    if stop:
        decision["candidates"].append({"candidate_id":9, "semantic":{"kind":"finish_target_selection",
            "source":decision["context"]["source"], "slot":0, "selected_count":0}})
        order.insert(0, None); names.insert(0, None)
    total, slots = len(order), min(64, len(order))
    frame.update(schema="spellbench-maintainer-target-features/v1", head="target", variant=targets.VARIANT,
        mana_payment_variant=MANA_PAYMENT_VARIANT, target_count=total, candidate_count=slots,
        original_targets=order, original_names=names, selected_count=0,
        minimum=0 if stop else 1, maximum=2 if stop else 1,
        decision_sha256=decision_hash(decision), **SOURCES)
    frame.pop("available_count"); frame.pop("original_mode_indices")
    bound = {"null":9} if stop else {}
    bound.update({str(ref["object_id"]):i+100 for i, ref in enumerate(refs)})
    frame["candidate_refs"] = [{"index":i, "target":value,
        "candidate_id":bound["null" if value is None else value["object"]["object_id"]]} for i, value in enumerate(order[:slots])]
    frame["candidate_features"] = [[i+0.25]+[0]*47 if i < slots else [0]*48 for i in range(64)]
    frame["candidate_ids"] = [i+70 if i < slots else 0 for i in range(64)]
    frame["candidate_mask"] = [True]*slots+[False]*(64-slots)
    if single or same:
        index = 1 if stop else 0
        frame.update(kind="maintainer-target-forced", forced_original_index=index,
            forced_candidate_id=bound[order[index]["object"]["object_id"]], reason="single_option" if single else "same_name")
    if players:
        for i, candidate in enumerate(decision["candidates"]): candidate["semantic"]["target"] = {"player":f"p{i}"}
        frame["original_targets"] = [{"player":"p1"}, {"player":"p0"}]
        frame["original_names"] = [None, None]
        frame["candidate_refs"] = [{"index":i,"candidate_id":101-i,"target":value} for i,value in enumerate(frame["original_targets"])]
        frame["decision_sha256"] = decision_hash(decision)
    ready = {"ready":True, "encoder":targets.TargetSession.ENCODER, "variant":targets.VARIANT,
        "mana_payment_variant":MANA_PAYMENT_VARIANT, "original_callback_sha256":CALLBACK_SHA256, "embedding_count":4, **SOURCES}
    return start, decision, anchor, replay, ready, frame


def setup(*, edit_frame=None, edit_ready=None, chosen=1, **kwargs):
    start, decision, anchor, replay, ready, frame = fixture(**kwargs)
    frame["request_sha256"] = decision_hash({"id":"1", "game_start":start, "decision":decision,
        "anchor":anchor, "replay":replay, "world_seed":"1"*64, "id_seed":"2"*64})
    if edit_frame: edit_frame(frame)
    if edit_ready: edit_ready(ready)
    peer = Peer([ready, {"id":"1", "ok":True, "encoded":frame}])
    chooser_peer = Peer([{"ready":True, "selection":"maintainer-original-no-training", "profile":GREEDY,
        "seed":7, "callback_source_sha256":CALLBACK_SHA256}, {"id":"1", "ok":True, "indices":[chosen]}])
    selector = MaintainerSelectionSession(chooser_peer, profile=GREEDY, seed=7)
    model = Model(start); model.encoding["card_embeddings_sha256"] = SOURCES["embedding_cache_sha256"]
    model.scores["probabilities"] = [1/frame["candidate_count"]]*frame["candidate_count"]+[0]*(64-frame["candidate_count"])
    try: owned = targets.TargetSession(peer, model, selector, game_start=start, sources=SOURCES)
    except BaseException:
        assert peer.closed and chooser_peer.closed and model.closed == 1
        assert not peer.writes and not chooser_peer.writes and not model.requests
        raise
    return owned, decision, anchor, replay, peer, model, chooser_peer, frame


def choose(values):
    owned, decision, anchor, replay = values[:4]
    return owned.choose(decision, anchor=anchor, replay=replay, world_seed="1"*64, id_seed="2"*64, timeout_s=5)


def test_target_head_preserves_original_order_chooser_and_shared_clock():
    values = setup(); owned, decision, _, _, peer, model, selector, frame = values
    result = choose(values)
    assert result["selection"]["candidate_id"] == 100
    assert result["selection"]["semantic_echo"] == decision["candidates"][0]["semantic"]
    features, timeout = model.requests[0]
    assert features["head"] == "target" and features["candidate_features"] == frame["candidate_features"]
    assert 0 < selector.timeouts[0] <= timeout <= peer.timeouts[0] <= 5
    assert owned.selection.sequence == 1
    owned.close(); assert peer.closed and selector.closed and model.closed == 1


@pytest.mark.parametrize("kwargs,index", [({"single":True}, 0), ({"same":True}, 0), ({"same":True,"stop":True}, 1)])
def test_original_single_and_same_name_bypass_network_and_rng_even_with_stop(kwargs, index):
    values = setup(**kwargs); owned, _, _, _, _, model, selector, frame = values
    result = choose(values)
    assert result["selection"]["candidate_id"] == frame["forced_candidate_id"]
    assert frame["forced_original_index"] == index and result["scores"] is None
    assert not model.requests and not selector.writes and owned.selection.sequence == 0
    owned.close()


def test_stop_is_original_first_slot_when_nontrivial_and_minimum_allows():
    values = setup(stop=True, chosen=0)
    result = choose(values)
    assert result["selection"]["candidate_id"] == 9
    assert result["selection"]["semantic_echo"]["kind"] == "finish_target_selection"
    assert values[5].requests[0][0]["candidate_mask"][:3] == [True]*3
    values[0].close()


def test_more_than_64_targets_preserve_complete_order_but_only_first_slots_are_scored():
    values = setup(many=True, chosen=63); result = choose(values)
    assert result["selection"]["candidate_id"] == 101
    assert values[7]["target_count"] == 65 and values[7]["candidate_count"] == 64
    assert len(values[5].requests[0][0]["candidate_refs"]) == 64
    values[0].close()


def test_visible_player_targets_use_original_order_and_nullable_engine_names():
    values = setup(players=True); result = choose(values)
    assert result["selection"]["semantic_echo"]["target"] == {"player":"p0"}
    assert values[5].requests[0][0]["head"] == "target"
    values[0].close()


@pytest.mark.parametrize("edit", [
    lambda f:f.update(request_sha256="0"*64), lambda f:f.update(variant="other"),
    lambda f:f.update(target_rules_source_sha256="0"*64), lambda f:f.update(mana_payment_variant="other"),
    lambda f:f.update(head="action"), lambda f:f.update(target_count=3),
    lambda f:f.update(candidate_count=1), lambda f:f.update(selected_count=1), lambda f:f.update(maximum=2),
    lambda f:f["original_targets"].reverse(), lambda f:f["original_names"].__setitem__(0,"Hidden card"),
    lambda f:f["candidate_refs"][0].update(candidate_id=100), lambda f:f["candidate_refs"][0].update(index=True),
    lambda f:f["candidate_refs"].pop(), lambda f:f["candidate_mask"].__setitem__(63,True),
    lambda f:f["candidate_ids"].__setitem__(0,0), lambda f:f["candidate_ids"].__setitem__(63,17),
    lambda f:f["candidate_features"][63].__setitem__(1,1), lambda f:f.update(world_flags=["unsupported:target"]),
])
def test_changed_identity_range_order_or_binding_refuses_before_inference_and_closes(edit):
    values = setup(edit_frame=edit)
    with pytest.raises(ValueError): choose(values)
    assert not values[5].requests and not values[6].writes
    assert values[4].closed and values[6].closed and values[5].closed == 1


@pytest.mark.parametrize("edit", [
    lambda f:f.update(forced_original_index=0), lambda f:f.update(forced_candidate_id=9),
    lambda f:f.update(reason="single_option"), lambda f:f.update(kind="candidates"),
])
def test_same_name_direct_return_cannot_be_replaced_with_stop_or_model(edit):
    values = setup(same=True, stop=True, edit_frame=edit)
    with pytest.raises(ValueError): choose(values)
    assert not values[5].requests and not values[6].writes


@pytest.mark.parametrize("edit", [
    lambda d:d.update(acting_seat="p1"), lambda d:d["context"].update(kind="priority"),
    lambda d:d["context"]["source"].update(card_name=None),
    lambda d:d["candidates"][0]["semantic"].update(slot=True),
    lambda d:d["candidates"][0]["semantic"].update(selected_count=1),
    lambda d:d["candidates"][0]["semantic"].update(maximum=2),
    lambda d:d["candidates"][0]["semantic"]["target"]["object"].update(card_name="Unseen"),
    lambda d:d["candidates"][0]["semantic"].update(kind="choose_cost_target"),
    lambda d:d["candidates"].append(d["candidates"][0]),
])
def test_invalid_or_out_of_scope_target_refuses_before_encoder_io(edit):
    values = setup(); edit(values[1])
    with pytest.raises(ValueError): choose(values)
    assert not values[4].writes and not values[5].requests and not values[6].writes


@pytest.mark.parametrize("edit", [lambda r:r.update(target_rules_source_sha256="0"*64),
    lambda r:r.update(encoder="maintainer-permitted-mode-payment"), lambda r:r.update(mana_payment_variant=None)])
def test_target_readiness_requires_full_variant_and_each_source(edit):
    with pytest.raises(ValueError): setup(edit_ready=edit)


@pytest.mark.parametrize("value", [0, 1, "true", None, []])
def test_target_staging_flag_must_be_explicit_boolean_before_file_access(tmp_path, value):
    with pytest.raises(ValueError, match="target staging needs an explicit boolean"):
        stage({"schema":"spellbench-xmage-release-inputs/v1", "inference_backends":{"maintainer-rl-april":{"target_callback":value}}},
              tmp_path / "unread", tmp_path / "unwritten")
    assert not (tmp_path / "unread").exists() and not (tmp_path / "unwritten").exists()


def test_target_staging_requires_original_payment_and_prefix_rules_before_file_access(tmp_path):
    with pytest.raises(ValueError, match="targets require the original payment"):
        stage({"schema":"spellbench-xmage-release-inputs/v1", "inference_backends":{"maintainer-rl-april":{"target_callback":True}}},
              tmp_path / "unread", tmp_path / "unwritten")
    assert not (tmp_path / "unwritten").exists()


def test_target_extraction_refuses_unpinned_source():
    with pytest.raises(ValueError, match="pinned April callback"): target_source("untrusted target code")
