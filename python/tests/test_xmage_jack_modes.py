"""Bound original mode frames cannot become arbitrary offered-action argmaxes."""
import copy
import json
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import xmage_jack_modes as modes
from xmage_jack_selection import JackSelectionSession, GREEDY
from xmage_jack_sources import CALLBACK_SHA256, ENCODER_SHA256
from xmage_neural_decisions import decision_hash
from test_xmage_jack_inference import Peer

SOURCES = {key: char * 64 for key, char in zip(modes.SOURCE_KEYS, "abcd")}


def fixture():
    start = {"seat":"p0", "game_id":"mode-game", "agent_seed":7, "own_deck":{"decklist":[]}}
    source = {"object_id":"spell", "card_name":"Abrade", "owner_seat":"p0", "controller_seat":"p0", "zone":"stack"}
    obs = {"viewer":"p0", "players":[{"seat":"p0", **{key:[] for key in ("hand", "battlefield", "graveyard", "exile", "command")}}],
           "stack":[source], "known":[]}
    decision = {"acting_seat":"p0", "seat_step":6, "context":{"kind":"choice", "source":source}, "observation":obs,
                "candidates":[{"candidate_id":cid, "semantic":{"kind":"choose_spell_mode", "source":source,
                    "mode_index":index, "mode_count":3, "selected_count":0, "minimum":1, "maximum":1}}
                              for cid, index in ((60, 1), (7, 2), (100, 0))]}
    anchor = {"decision":{"acting_seat":"p0", "context":{"kind":"priority"}, "candidates":[
        {"candidate_id":9, "semantic":{"kind":"pass"}}]}, "selection":{"candidate_id":9, "semantic_echo":{"kind":"pass"}}}
    replay = {"earlier":[], "priority_passes":["p0", "p1"]}
    ready = {"ready":True, "encoder":"jack-permitted-mode", "original_callback_sha256":CALLBACK_SHA256,
             "variant":modes.MODE_VARIANT, "embedding_count":4, **SOURCES}
    frame = {"schema":"spellbench-jack-mode-features/v1", "kind":"candidates", "head":"action",
             "decision_sha256":decision_hash(decision), "game_start_sha256":decision_hash(start),
             "original_callback_sha256":CALLBACK_SHA256, "variant":modes.MODE_VARIANT, "world_flags":[], **SOURCES,
             "available_count":3, "candidate_count":3, "original_mode_indices":[2, 0, 1],
             "sequence":[[0]*128 for _ in range(256)], "padding":[False]+[True]*255,
             "token_ids":[1]+[0]*255, "candidate_ids":[101, 102, 103]+[0]*61,
             "candidate_features":[[struct.unpack("!f", struct.pack("!f", i/3))[0]]+[0]*47 if i<3 else [0]*48 for i in range(64)],
             "candidate_mask":[True]*3+[False]*61,
             "candidate_refs":[{"index":i, "mode_index":mode, "candidate_id":cid} for i, mode, cid in ((0, 2, 7), (1, 0, 100), (2, 1, 60))]}
    return start, decision, anchor, replay, ready, frame


class Model:
    checkpoint = "paired-mode-policy"
    def __init__(self, start):
        self.game_start_sha256 = decision_hash(start)
        self.encoding = {"state_encoder_sha256":ENCODER_SHA256, "callback_sha256":CALLBACK_SHA256,
                         "card_embeddings_sha256":SOURCES["embedding_cache_sha256"], "mulligan_format":"keep-logit"}
        self.scores = {"probabilities":[0.2, 0.5, 0.3]+[0]*61, "value":0.1}
        self.requests, self.closed = [], 0
    def score(self, features, *, timeout_s):
        self.requests.append((copy.deepcopy(features), timeout_s)); return copy.deepcopy(self.scores)
    def close(self): self.closed += 1


def session(*, edit_frame=None, edit_ready=None, edit_model=None, edit_decision=None, response_id="1", selected=1):
    start, decision, anchor, replay, ready, frame = fixture()
    if edit_decision: edit_decision(decision)
    request = {"id":"1", "game_start":start, "decision":decision, "anchor":anchor, "replay":replay,
               "world_seed":"1"*64, "id_seed":"2"*64}
    frame["request_sha256"] = decision_hash(request)
    if edit_frame: edit_frame(frame)
    if edit_ready: edit_ready(ready)
    peer = Peer([ready, {"id":response_id, "ok":True, "encoded":frame}])
    model = Model(start)
    if edit_model: edit_model(model)
    chooser_peer = Peer([{"ready":True, "selection":"jack-original-no-training", "profile":GREEDY,
                         "seed":7, "callback_source_sha256":CALLBACK_SHA256}, {"id":"1", "ok":True, "indices":[selected]}])
    chooser = JackSelectionSession(chooser_peer, profile=GREEDY, seed=7)
    owned = modes.ModeSession(peer, model, chooser, game_start=start, sources=SOURCES)
    return owned, decision, anchor, replay, peer, model, chooser_peer, frame


def choose(owned, decision, anchor, replay, **kwargs):
    return owned.choose(decision, anchor=anchor, replay=replay, world_seed="1"*64, id_seed="2"*64, timeout_s=5, **kwargs)


def test_original_ordinals_map_to_offered_ids_with_owned_rng_and_shared_clock():
    owned, decision, anchor, replay, peer, model, chooser_peer, frame = session()
    result = choose(owned, decision, anchor, replay)
    assert result["selection"] == {"candidate_id":100, "semantic_echo":decision["candidates"][2]["semantic"]}
    assert result["scores"] == model.scores and result["profile"] == GREEDY
    assert model.requests[0][0]["candidate_features"] == frame["candidate_features"]
    assert chooser_peer.writes[0]["count"] == 3 and chooser_peer.writes[0]["picks"] == 1
    assert chooser_peer.writes[0]["sequential"] is False
    assert 0 < chooser_peer.timeouts[0] <= model.requests[0][1] <= peer.timeouts[0] <= 5
    assert owned.selection.game_start_sha256 == decision_hash(owned.start)
    owned.close(); owned.close()
    assert peer.closed and chooser_peer.closed and model.closed == 1


@pytest.mark.parametrize("edit", [
    lambda f:f.update(decision_sha256="0"*64), lambda f:f.update(game_start_sha256="0"*64),
    lambda f:f.update(request_sha256="0"*64), lambda f:f.update(original_callback_sha256="0"*64),
    lambda f:f.update(encoder_source_sha256="0"*64), lambda f:f.update(candidate_source_sha256="0"*64),
    lambda f:f.update(mode_rules_source_sha256="0"*64), lambda f:f.update(embedding_cache_sha256="0"*64),
    lambda f:f.update(variant="all-offered argmax"), lambda f:f.update(world_flags=["unsupported:unknown"]),
    lambda f:f.update(available_count=True), lambda f:f.update(candidate_count=2),
    lambda f:f.update(original_mode_indices=[2, 0, 0]), lambda f:f.update(original_mode_indices=[True, 0, 1]),
    lambda f:f["candidate_features"][1].__setitem__(0, 0.5), lambda f:f["candidate_features"][0].__setitem__(13, 1),
    lambda f:f["candidate_features"][5].__setitem__(4, 1), lambda f:f["candidate_ids"].__setitem__(4, 101),
    lambda f:f["candidate_mask"].__setitem__(5, True), lambda f:f.update(head="card_select"),
    lambda f:f["candidate_refs"][0].update(candidate_id=100), lambda f:f["candidate_refs"][0].update(mode_index=0),
    lambda f:f["candidate_refs"].pop(), lambda f:f["candidate_refs"].append(f["candidate_refs"][0]),
])
def test_changed_encoder_identity_order_padding_or_binding_refuses_before_model(edit):
    owned, d, a, r, peer, model, chooser_peer, _ = session(edit_frame=edit)
    with pytest.raises(ValueError): choose(owned, d, a, r)
    assert not model.requests and not chooser_peer.writes
    assert peer.closed and chooser_peer.closed and model.closed == 1


@pytest.mark.parametrize("edit", [
    lambda d:d.update(acting_seat="p1"), lambda d:d["observation"].update(viewer="p1"),
    lambda d:d["context"].update(kind="priority"), lambda d:d["context"]["source"].update(card_name=None),
    lambda d:d["candidates"][0]["semantic"].update(mode_index=True),
    lambda d:d["candidates"][0]["semantic"].update(mode_count=4),
    lambda d:d["candidates"][0]["semantic"].update(selected_count=1),
    lambda d:d["candidates"][0].update(candidate_id=True), lambda d:d["candidates"].append(d["candidates"][0]),
])
def test_invalid_public_mode_refuses_before_encoder_io(edit):
    owned, d, a, r, peer, model, chooser_peer, _ = session()
    edit(d)
    with pytest.raises(ValueError): choose(owned, d, a, r)
    assert not peer.writes and not model.requests and not chooser_peer.writes
    assert peer.closed and chooser_peer.closed and model.closed == 1


@pytest.mark.parametrize("prefix", ["anchor", "replay"])
def test_encoder_frame_cannot_be_reused_for_another_recorded_prefix(prefix):
    owned, d, a, r, peer, model, chooser_peer, _ = session()
    (a if prefix == "anchor" else r)["changed"] = True
    with pytest.raises(ValueError, match="replay request"): choose(owned, d, a, r)
    assert not model.requests and not chooser_peer.writes


@pytest.mark.parametrize("selected", [True, 3])
def test_illegal_chooser_index_refuses_and_closes_all_resources(selected):
    owned, d, a, r, peer, model, chooser_peer, _ = session(selected=selected)
    with pytest.raises(ValueError): choose(owned, d, a, r)
    assert len(model.requests) == 1 and peer.closed and chooser_peer.closed and model.closed == 1


def test_masked_mode_preserves_ordinal_and_is_excluded_from_the_original_chooser():
    def mask(frame):
        frame["candidate_mask"][0] = False; frame["candidate_refs"].pop(0)
    owned, d, a, r, _, model, chooser_peer, _ = session(edit_frame=mask)
    model.scores["probabilities"] = [0, 0.6, 0.4]+[0]*61
    assert choose(owned, d, a, r)["selection"]["candidate_id"] == 100
    assert chooser_peer.writes[0]["mask"][:3] == [False, True, True]


@pytest.mark.parametrize("available", [0, 1])
def test_original_direct_mode_returns_do_not_use_model_or_advance_rng(available):
    owned, d, a, r, peer, model, chooser_peer, frame = session()
    if available:
        cid, reason, order = 100, "single_available_mode", [0]
    else:
        cid, reason, order = 111, "no_available_modes", []
        d["candidates"] = [{"candidate_id":cid, "semantic":{"kind":"finish_selection", "source":d["context"]["source"],
                            "selected_count":0, "purpose":"modes"}}]
    frame.update(kind="jack-mode-forced", available_count=available, candidate_count=available,
                 original_mode_indices=order, forced_candidate_id=cid, reason=reason, decision_sha256=decision_hash(d))
    frame["request_sha256"] = decision_hash({"id":"1", "game_start":owned.start, "decision":d, "anchor":a, "replay":r,
                                            "world_seed":"1"*64, "id_seed":"2"*64})
    # Peer retains its own encoded queue, independently of the returned fixture.
    peer.rows[-1] = json.dumps({"id":"1", "ok":True, "encoded":frame}).encode()
    result = choose(owned, d, a, r)
    assert result["selection"]["candidate_id"] == cid and result["scores"] is None
    assert not model.requests and not chooser_peer.writes and owned.selection.sequence == 0


@pytest.mark.parametrize("stage", ["encoder", "model", "chooser"])
def test_shared_clock_expiry_closes_all_resources(stage, monkeypatch):
    owned, d, a, r, peer, model, chooser_peer, _ = session()
    now = [0.0]; monkeypatch.setattr(modes.time, "monotonic", lambda:now[0])
    if stage == "encoder":
        original = peer.read_line
        def read(): now[0] = 6.0; return original()
        peer.read_line = read
    elif stage == "model":
        original = model.score
        def score(*args, **kwargs): now[0] = 6.0; return original(*args, **kwargs)
        model.score = score
    else:
        original = chooser_peer.read_line
        def read(): now[0] = 6.0; return original()
        chooser_peer.read_line = read
    with pytest.raises(TimeoutError): choose(owned, d, a, r)
    assert peer.closed and chooser_peer.closed and model.closed == 1


def test_stale_encoder_response_refuses_before_model():
    owned, d, a, r, peer, model, chooser_peer, _ = session(response_id="2")
    with pytest.raises(ValueError, match="stale"): choose(owned, d, a, r)
    assert not model.requests and not chooser_peer.writes and peer.closed and chooser_peer.closed


def test_chooser_accepts_same_game_binding_and_refuses_cross_game_rng_reuse():
    owned, _, _, _, peer, model, chooser_peer, _ = session()
    owned.selection.bind_game_start(copy.deepcopy(owned.start))
    another = {**owned.start, "game_id":"other-game"}
    with pytest.raises(ValueError, match="rebound"): owned.selection.bind_game_start(another)
    assert chooser_peer.closed
    owned.close(); assert peer.closed and model.closed == 1


def test_more_than_64_available_modes_preserves_the_original_cap_and_tail_exclusion():
    owned, d, a, r, peer, model, chooser_peer, frame = session(selected=63)
    source = d["context"]["source"]
    d["candidates"] = [{"candidate_id":i+500, "semantic":{"kind":"choose_spell_mode", "source":source,
                       "mode_index":i, "mode_count":65, "selected_count":0, "minimum":1, "maximum":1}} for i in range(65)]
    frame.update(available_count=65, candidate_count=64, original_mode_indices=list(range(64)),
                 candidate_features=[[i/64]+[0]*47 for i in range(64)], candidate_ids=list(range(101, 165)),
                 candidate_mask=[True]*64, candidate_refs=[{"index":i, "candidate_id":i+500, "mode_index":i} for i in range(64)],
                 decision_sha256=decision_hash(d))
    frame["request_sha256"] = decision_hash({"id":"1", "game_start":owned.start, "decision":d, "anchor":a, "replay":r,
                                            "world_seed":"1"*64, "id_seed":"2"*64})
    peer.rows[-1] = json.dumps({"id":"1", "ok":True, "encoded":frame}).encode()
    model.scores["probabilities"] = [0]*63+[1]
    assert choose(owned, d, a, r)["selection"]["candidate_id"] == 563
    assert chooser_peer.writes[0]["count"] == 64 and len(model.requests[0][0]["candidate_ids"]) == 64


def test_nonfinite_network_scores_refuse_before_original_chooser():
    owned, d, a, r, peer, model, chooser_peer, _ = session()
    model.scores["value"] = float("nan")
    with pytest.raises(ValueError): choose(owned, d, a, r)
    assert not chooser_peer.writes and peer.closed and chooser_peer.closed and model.closed == 1
