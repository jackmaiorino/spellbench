"""Original dialog slots remain bound to actual offered semantics and one game."""
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import xmage_jack_dialogs as dialogs
from xmage_jack_selection import JackSelectionSession, GREEDY
from xmage_jack_sources import CALLBACK_SHA256, ENCODER_SHA256, DIALOG_VARIANT
from xmage_neural_decisions import decision_hash
from test_xmage_jack_inference import Peer

SOURCES = {key: char*64 for key, char in zip(dialogs.SOURCE_KEYS, "abcd")}


def fixture(numeric=False, family="choose_boolean"):
    start = {"seat":"p0", "game_id":"original-dialog", "agent_seed":7, "own_deck":{"decklist":[]}}
    source = {"object_id":"spell", "card_name":"Nyxborn Hydra", "owner_seat":"p0", "controller_seat":"p0", "zone":"stack"}
    obs = {"viewer":"p0", "players":[{"seat":"p0", **{key:[] for key in ("hand", "battlefield", "graveyard", "exile", "command")}}],
           "stack":[source], "known":[]}
    if numeric:
        candidates = [{"candidate_id":100+value, "semantic":{"kind":"choose_number", "purpose":"x_value", "source":source,
                      "value":value, "minimum":0, "maximum":6}} for value in range(7)]
        values, callback = list(range(4)), "announce_x"
    else:
        def semantic(value):
            if family == "optional_cost": return {"kind":family, "source":source, "cost":"kicker", "pay":value}
            if family == "choose_cast_method": return {"kind":family, "source":source, "method":"evoke" if value else "normal"}
            return {"kind":family, "source":source, "purpose":"may", "value":value}
        candidates = [{"candidate_id":9, "semantic":semantic(False)}, {"candidate_id":55, "semantic":semantic(True)}]
        values, callback = [True, False], "choose_use"
    decision = {"acting_seat":"p0", "seat_step":4, "observation":obs, "context":{"kind":"choice", "source":source},
                "candidates":candidates}
    anchor = {"decision":{"acting_seat":"p0", "context":{"kind":"priority"},
              "candidates":[{"candidate_id":1, "semantic":{"kind":"pass"}}]},
              "selection":{"candidate_id":1, "semantic_echo":{"kind":"pass"}}}
    replay = {"earlier":[], "priority_passes":["p0", "p1"]}
    ready = {"ready":True, "encoder":"jack-permitted-dialog", "original_callback_sha256":CALLBACK_SHA256,
             "variant":DIALOG_VARIANT, "embedding_count":7, **SOURCES}
    frame = {"schema":"spellbench-jack-dialog-features/v1", "callback":callback, "kind":"candidates", "head":"action",
             "decision_sha256":decision_hash(decision), "game_start_sha256":decision_hash(start),
             "original_callback_sha256":CALLBACK_SHA256, "variant":DIALOG_VARIANT, "world_flags":[], **SOURCES,
             "candidate_count":len(values), "original_values":values,
             "sequence":[[0]*128 for _ in range(256)], "padding":[False]+[True]*255,
             "token_ids":[1]+[0]*255, "candidate_ids":[], "candidate_features":[],
             "candidate_mask":[True]*len(values)+[False]*(64-len(values)), "candidate_refs":[]}
    if numeric:
        frame.update(original_minimum=0, original_maximum=dialogs.MAX_INT, is_mana_pay=True, real_minimum=0, real_maximum=3)
    for index in range(64):
        row = [0]*48
        ident = 0
        if index < len(values):
            chosen = values[index]
            row[0] = 15/16 if numeric else 12/16
            if numeric:
                row[9], row[10] = dialogs.f32(0.1), dialogs.f32(chosen/20)
                row[13], row[14] = dialogs.f32(4/20), dialogs.f32(chosen/3)
                ident, cid = dialogs.token_id("ANNOUNCE_X:"+str(chosen)), 100+chosen
            else:
                row[1], row[26] = (0, 1) if chosen else (1, 0)
                ident, cid = dialogs.token_id("CHOOSE_USE_"+("YES" if chosen else "NO")), 55 if chosen else 9
            frame["candidate_refs"].append({"index":index, "value":chosen, "candidate_id":cid})
        frame["candidate_features"].append(row); frame["candidate_ids"].append(ident)
    return start, decision, anchor, replay, ready, frame


class Model:
    checkpoint = "paired-dialog-policy"
    def __init__(self, start, numeric):
        self.game_start_sha256 = decision_hash(start)
        self.encoding = {"state_encoder_sha256":ENCODER_SHA256, "callback_sha256":CALLBACK_SHA256,
                         "card_embeddings_sha256":SOURCES["embedding_cache_sha256"], "mulligan_format":"keep-logit"}
        self.scores = {"probabilities":([0.1, 0.2, 0.6, 0.1] if numeric else [0.4, 0.6])+[0]*(60 if numeric else 62), "value":0.0}
        self.requests, self.closed = [], 0
    def score(self, features, *, timeout_s):
        self.requests.append((copy.deepcopy(features), timeout_s))
        return copy.deepcopy(self.scores)
    def close(self): self.closed += 1


def session(*, numeric=False, family="choose_boolean", edit_frame=None, edit_decision=None, selected=None, response_id="1"):
    start, decision, anchor, replay, ready, frame = fixture(numeric, family)
    if edit_decision: edit_decision(decision)
    frame["decision_sha256"] = decision_hash(decision)
    frame["request_sha256"] = decision_hash({"id":"1", "game_start":start, "decision":decision, "anchor":anchor,
                                            "replay":replay, "world_seed":"1"*64, "id_seed":"2"*64})
    if edit_frame: edit_frame(frame)
    peer = Peer([ready, {"id":response_id, "ok":True, "encoded":frame}])
    model = Model(start, numeric)
    chooser_peer = Peer([{"ready":True, "selection":"jack-original-no-training", "profile":GREEDY,
                         "seed":7, "callback_source_sha256":CALLBACK_SHA256},
                         {"id":"1", "ok":True, "indices":[(2 if numeric else 1) if selected is None else selected]}])
    chooser = JackSelectionSession(chooser_peer, profile=GREEDY, seed=7)
    owned = dialogs.DialogSession(peer, model, chooser, game_start=start, sources=SOURCES)
    return owned, decision, anchor, replay, peer, model, chooser_peer, frame


def choose(owned, decision, anchor, replay):
    return owned.choose(decision, anchor=anchor, replay=replay, world_seed="1"*64, id_seed="2"*64, timeout_s=5)


@pytest.mark.parametrize("family", ["choose_boolean", "optional_cost", "choose_cast_method"])
def test_original_yes_no_order_maps_to_actual_offered_semantics(family):
    owned, decision, anchor, replay, peer, model, chooser_peer, frame = session(family=family)
    result = choose(owned, decision, anchor, replay)
    assert result["selection"] == {"candidate_id":9, "semantic_echo":decision["candidates"][0]["semantic"]}
    assert model.requests[0][0]["candidate_ids"][:2] == frame["candidate_ids"][:2]
    assert chooser_peer.writes[0]["count"] == 2 and chooser_peer.writes[0]["sequential"] is False
    assert result["variant"] == DIALOG_VARIANT and owned.selection.game_start_sha256 == decision_hash(owned.start)
    owned.close(); owned.close()
    assert peer.closed and chooser_peer.closed and model.closed == 1


def test_original_affordable_x_subrange_keeps_integer_order_and_source_budget_features():
    owned, decision, anchor, replay, peer, model, chooser_peer, frame = session(numeric=True)
    result = choose(owned, decision, anchor, replay)
    assert result["selection"] == {"candidate_id":102, "semantic_echo":decision["candidates"][2]["semantic"]}
    assert model.requests[0][0]["candidate_features"] == frame["candidate_features"]
    assert chooser_peer.writes[0]["count"] == 4 and chooser_peer.writes[0]["mask"] == [True]*4+[False]*60
    assert 0 < chooser_peer.timeouts[0] <= model.requests[0][1] <= peer.timeouts[0] <= 5


@pytest.mark.parametrize("numeric", [False, True])
@pytest.mark.parametrize("edit", [
    lambda f:f.update(decision_sha256="0"*64), lambda f:f.update(game_start_sha256="0"*64),
    lambda f:f.update(request_sha256="0"*64), lambda f:f.update(original_callback_sha256="0"*64),
    lambda f:f.update(encoder_source_sha256="0"*64), lambda f:f.update(candidate_source_sha256="0"*64),
    lambda f:f.update(dialog_rules_source_sha256="0"*64), lambda f:f.update(embedding_cache_sha256="0"*64),
    lambda f:f.update(variant="offered-action argmax"), lambda f:f.update(world_flags=["unsupported:state"]),
    lambda f:f.update(candidate_count=True), lambda f:f["candidate_ids"].__setitem__(0, 0),
    lambda f:f["candidate_features"][0].__setitem__(0, 0.5), lambda f:f["candidate_mask"].__setitem__(0, False),
    lambda f:f["candidate_features"][8].__setitem__(1, 1), lambda f:f["candidate_ids"].__setitem__(8, 11),
    lambda f:f["candidate_refs"][0].update(candidate_id=999), lambda f:f["candidate_refs"].pop(),
    lambda f:f["candidate_refs"].append(copy.deepcopy(f["candidate_refs"][0])),
])
def test_changed_source_game_slots_or_bindings_refuse_before_model(numeric, edit):
    owned, decision, anchor, replay, peer, model, chooser_peer, _ = session(numeric=numeric, edit_frame=edit)
    with pytest.raises(ValueError): choose(owned, decision, anchor, replay)
    assert not model.requests and not chooser_peer.writes
    assert peer.closed and chooser_peer.closed and model.closed == 1


@pytest.mark.parametrize("edit", [
    lambda f:f.update(original_values=[False, True]), lambda f:f.update(original_values=[1, 0]),
    lambda f:f["candidate_ids"].__setitem__(0, dialogs.token_id("CHOOSE_USE:Boolean")),
    lambda f:f["candidate_features"][0].__setitem__(26, 0),
    lambda f:f["candidate_features"][1].__setitem__(1, 0),
    lambda f:f["candidate_refs"][0].update(value=1),
])
def test_binary_cannot_use_generic_boolean_token_or_reversed_meaning(edit):
    owned, decision, anchor, replay, _, model, chooser_peer, _ = session(edit_frame=edit)
    with pytest.raises(ValueError): choose(owned, decision, anchor, replay)
    assert not model.requests and not chooser_peer.writes


@pytest.mark.parametrize("edit", [
    lambda f:f.update(real_maximum=4), lambda f:f.update(original_minimum=1),
    lambda f:f.update(original_maximum=2), lambda f:f.update(is_mana_pay=1),
    lambda f:f.update(is_mana_pay=False), lambda f:f.update(original_values=[3, 2, 1, 0]),
    lambda f:f["candidate_features"][2].__setitem__(10, 0.5),
    lambda f:f["candidate_features"][2].__setitem__(14, 1.1),
    lambda f:f["candidate_refs"][0].update(value=False),
])
def test_x_cap_mana_context_order_or_features_cannot_be_changed(edit):
    owned, decision, anchor, replay, _, model, chooser_peer, _ = session(numeric=True, edit_frame=edit)
    with pytest.raises(ValueError): choose(owned, decision, anchor, replay)
    assert not model.requests and not chooser_peer.writes


@pytest.mark.parametrize("numeric", [False, True])
def test_forced_original_returns_bypass_model_and_preserve_chooser_rng(numeric):
    def force(frame):
        frame.update(kind="jack-dialog-forced", candidate_count=1,
                     forced_value=0 if numeric else False, original_values=[0] if numeric else [False],
                     forced_candidate_id=100 if numeric else 9,
                     reason="original_x_single_value" if numeric else "original_mana_feasibility_gate")
        if numeric: frame.update(real_maximum=0)
    owned, decision, anchor, replay, _, model, chooser_peer, _ = session(numeric=numeric, edit_frame=force)
    result = choose(owned, decision, anchor, replay)
    assert result["selection"]["candidate_id"] == (100 if numeric else 9)
    assert result["scores"] is None and not model.requests and not chooser_peer.writes
    assert owned.selection.sequence == 0


@pytest.mark.parametrize("numeric", [False, True])
def test_candidate_reordering_preserves_original_slots(numeric):
    owned, decision, anchor, replay, peer, model, chooser_peer, frame = session(numeric=numeric,
        edit_decision=lambda d:d["candidates"].reverse())
    result = choose(owned, decision, anchor, replay)
    assert result["selection"]["candidate_id"] == (102 if numeric else 9)
    assert model.requests[0][0]["candidate_features"] == frame["candidate_features"]


@pytest.mark.parametrize("edit", [
    lambda d:d.update(acting_seat="p1"), lambda d:d["observation"].update(viewer="p1"),
    lambda d:d["context"].update(kind="priority"), lambda d:d["context"]["source"].update(card_name=None),
    lambda d:d["candidates"][0].update(candidate_id=True),
    lambda d:d["candidates"][0]["semantic"].update(value=0),
    lambda d:d["candidates"].append(copy.deepcopy(d["candidates"][0])),
])
def test_invalid_public_dialog_refuses_before_encoder_io(edit):
    owned, decision, anchor, replay, peer, model, chooser_peer, _ = session()
    edit(decision)
    with pytest.raises(ValueError): choose(owned, decision, anchor, replay)
    assert not peer.writes and not model.requests and not chooser_peer.writes


@pytest.mark.parametrize("part", ["anchor", "replay"])
def test_whole_replay_binding_prevents_reusing_a_frame_for_another_prefix(part):
    owned, decision, anchor, replay, _, model, chooser_peer, _ = session()
    (anchor if part == "anchor" else replay)["changed"] = True
    with pytest.raises(ValueError, match="replay request"): choose(owned, decision, anchor, replay)
    assert not model.requests and not chooser_peer.writes


def test_stale_encoder_response_closes_all_three_owned_resources():
    owned, decision, anchor, replay, peer, model, chooser_peer, _ = session(response_id="2")
    with pytest.raises(ValueError, match="stale request"): choose(owned, decision, anchor, replay)
    assert peer.closed and chooser_peer.closed and model.closed == 1


def test_unoffered_original_chooser_slot_closes_resources_after_one_model_request():
    owned, decision, anchor, replay, peer, model, chooser_peer, _ = session(selected=2)
    with pytest.raises(ValueError): choose(owned, decision, anchor, replay)
    assert len(model.requests) == 1 and peer.closed and chooser_peer.closed and model.closed == 1


def test_original_dialog_source_rejects_unpinned_private_bytes():
    from xmage_jack_sources import dialog_source
    with pytest.raises(ValueError, match="pinned April"): dialog_source("class DifferentCallback {}")
