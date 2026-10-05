"""Cost-mode frames retain original slots, masks, flags and source bindings."""
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import xmage_jack_modes as modes
from xmage_jack_selection import JackSelectionSession, GREEDY
from xmage_jack_sources import CALLBACK_SHA256, stage
from xmage_neural_decisions import decision_hash
from test_xmage_jack_inference import Peer
from test_xmage_jack_modes import fixture as plain_fixture, Model, SOURCES

MANA_SOURCES = {**SOURCES, "dialog_rules_source_sha256": "e" * 64}


def fixture():
    start, decision, anchor, replay, ready, frame = plain_fixture()
    ready.update(encoder=modes.ManaModeSession.ENCODER, variant=modes.MODE_MANA_VARIANT, **MANA_SOURCES)
    frame.update(variant=modes.MODE_MANA_VARIANT, original_mode_cost_flags=[True, False, True], **MANA_SOURCES)
    frame["candidate_features"][0][13] = 1
    frame["candidate_features"][2][13] = 1
    return start, decision, anchor, replay, ready, frame


def session(*, edit_frame=None, edit_ready=None, sources=None, kind=modes.ManaModeSession, selected=1):
    start, decision, anchor, replay, ready, frame = fixture()
    request = {"id":"1", "game_start":start, "decision":decision, "anchor":anchor, "replay":replay,
               "world_seed":"1"*64, "id_seed":"2"*64}
    frame["request_sha256"] = decision_hash(request)
    if edit_frame: edit_frame(frame)
    if edit_ready: edit_ready(ready)
    peer = Peer([ready, {"id":"1", "ok":True, "encoded":frame}])
    model = Model(start)
    chooser_peer = Peer([{"ready":True, "selection":"jack-original-no-training", "profile":GREEDY,
                         "seed":7, "callback_source_sha256":CALLBACK_SHA256}, {"id":"1", "ok":True, "indices":[selected]}])
    chooser = JackSelectionSession(chooser_peer, profile=GREEDY, seed=7)
    try:
        owned = kind(peer, model, chooser, game_start=start, sources=MANA_SOURCES if sources is None else sources)
    except BaseException:
        assert peer.closed and chooser_peer.closed and model.closed == 1
        assert not peer.writes and not chooser_peer.writes and not model.requests
        raise
    return owned, decision, anchor, replay, peer, model, chooser_peer, frame


def choose(owned, decision, anchor, replay):
    return owned.choose(decision, anchor=anchor, replay=replay, world_seed="1"*64, id_seed="2"*64, timeout_s=5)


def test_cost_flags_reach_paired_model_without_changing_original_slot_binding():
    owned, decision, anchor, replay, peer, model, chooser_peer, frame = session()
    result = choose(owned, decision, anchor, replay)
    assert result["selection"] == {"candidate_id":100, "semantic_echo":decision["candidates"][2]["semantic"]}
    features, seconds = model.requests[0]
    assert [row[13] for row in features["candidate_features"][:3]] == [1, 0, 1]
    assert features["candidate_features"] == frame["candidate_features"]
    assert chooser_peer.writes[0]["count"] == 3 and chooser_peer.writes[0]["mask"][:3] == [True]*3
    assert result["variant"] == modes.MODE_MANA_VARIANT
    assert 0 < chooser_peer.timeouts[0] <= seconds <= peer.timeouts[0] <= 5
    owned.close(); owned.close()
    assert peer.closed and chooser_peer.closed and model.closed == 1


def test_unaffordable_mask_keeps_original_cost_feature_and_ordinal():
    def mask(frame):
        frame["candidate_mask"][0] = False
        frame["candidate_refs"].pop(0)
    owned, decision, anchor, replay, _, model, chooser_peer, frame = session(edit_frame=mask)
    model.scores["probabilities"] = [0, 0.6, 0.4]+[0]*61
    assert choose(owned, decision, anchor, replay)["selection"]["candidate_id"] == 100
    assert model.requests[0][0]["candidate_features"][0][13] == 1
    assert model.requests[0][0]["candidate_features"][1][0] == frame["candidate_features"][1][0]
    assert chooser_peer.writes[0]["mask"][:3] == [False, True, True]
    owned.close()


@pytest.mark.parametrize("edit", [
    lambda f:f.pop("original_mode_cost_flags"), lambda f:f.update(original_mode_cost_flags=None),
    lambda f:f.update(original_mode_cost_flags=[True, False]),
    lambda f:f.update(original_mode_cost_flags=[True, False, True, False]),
    lambda f:f.update(original_mode_cost_flags=[1, False, True]),
    lambda f:f.update(original_mode_cost_flags=[True, "false", True]),
    lambda f:f.update(original_mode_cost_flags=[False, False, True]),
    lambda f:f["candidate_features"][0].__setitem__(13, 0),
    lambda f:f["candidate_features"][0].__setitem__(13, 0.5),
    lambda f:f["candidate_features"][0].__setitem__(13, True),
    lambda f:f["candidate_features"][1].__setitem__(13, 1),
    lambda f:f["candidate_features"][7].__setitem__(13, 1),
    lambda f:f.update(dialog_rules_source_sha256="0"*64),
    lambda f:f.update(variant=modes.MODE_VARIANT),
])
def test_changed_cost_features_or_mana_source_refuse_before_inference(edit):
    owned, decision, anchor, replay, peer, model, chooser_peer, _ = session(edit_frame=edit)
    with pytest.raises(ValueError): choose(owned, decision, anchor, replay)
    assert not model.requests and not chooser_peer.writes
    assert peer.closed and chooser_peer.closed and model.closed == 1


@pytest.mark.parametrize("edit", [
    lambda r:r.pop("dialog_rules_source_sha256"), lambda r:r.update(dialog_rules_source_sha256="0"*64),
    lambda r:r.update(variant=modes.MODE_VARIANT), lambda r:r.update(encoder="jack-permitted-mode"),
])
def test_legacy_or_wrong_mana_readiness_cannot_serve_cost_modes(edit):
    with pytest.raises(ValueError): session(edit_ready=edit)


def test_legacy_session_cannot_silently_accept_added_mana_rules():
    with pytest.raises(ValueError): session(kind=modes.ModeSession)


def test_mana_session_requires_the_extra_original_rules_pin():
    with pytest.raises(ValueError): session(sources=SOURCES)


def test_direct_cost_frame_validation_also_requires_the_mana_source_pin():
    start, decision, anchor, replay, _, frame = fixture()
    request = {"id":"1", "game_start":start, "decision":decision, "anchor":anchor, "replay":replay,
               "world_seed":"1"*64, "id_seed":"2"*64}
    frame["request_sha256"] = decision_hash(request)
    with pytest.raises(ValueError, match="every original staged source pin"):
        modes.validate_mana_encoding(start, decision, frame, SOURCES, decision_hash(request))


@pytest.mark.parametrize("available", [0, 1])
def test_original_direct_return_preserves_rng_even_when_single_mode_has_cost(available):
    owned, decision, anchor, replay, peer, model, chooser_peer, frame = session()
    if available:
        cid, reason, order, flags = 100, "single_available_mode", [0], [True]
    else:
        cid, reason, order, flags = 111, "no_available_modes", [], []
        decision["candidates"] = [{"candidate_id":cid, "semantic":{"kind":"finish_selection", "source":decision["context"]["source"],
                                  "selected_count":0, "purpose":"modes"}}]
    frame.update(kind="jack-mode-forced", available_count=available, candidate_count=available,
                 original_mode_indices=order, original_mode_cost_flags=flags,
                 forced_candidate_id=cid, reason=reason, decision_sha256=decision_hash(decision))
    frame["request_sha256"] = decision_hash({"id":"1", "game_start":owned.start, "decision":decision,
                                            "anchor":anchor, "replay":replay, "world_seed":"1"*64, "id_seed":"2"*64})
    peer.rows[-1] = json.dumps({"id":"1", "ok":True, "encoded":frame}).encode()
    result = choose(owned, decision, anchor, replay)
    assert result["selection"]["candidate_id"] == cid and result["scores"] is None
    assert not model.requests and not chooser_peer.writes and owned.selection.sequence == 0
    owned.close()


def test_first_64_modes_keep_cost_flags_and_exclude_tail_modes():
    owned, decision, anchor, replay, peer, model, chooser_peer, frame = session(selected=63)
    source = decision["context"]["source"]
    decision["candidates"] = [{"candidate_id":i+500, "semantic":{"kind":"choose_spell_mode", "source":source,
                              "mode_index":i, "mode_count":65, "selected_count":0, "minimum":1, "maximum":1}} for i in range(65)]
    flags = [i % 2 == 0 for i in range(64)]
    features = [[i/64]+[0]*47 for i in range(64)]
    for row, has_cost in zip(features, flags): row[13] = int(has_cost)
    frame.update(available_count=65, candidate_count=64, original_mode_indices=list(range(64)),
                 original_mode_cost_flags=flags, candidate_features=features, candidate_ids=list(range(101, 165)),
                 candidate_mask=[True]*64, candidate_refs=[{"index":i, "candidate_id":i+500, "mode_index":i} for i in range(64)],
                 decision_sha256=decision_hash(decision))
    frame["request_sha256"] = decision_hash({"id":"1", "game_start":owned.start, "decision":decision,
                                            "anchor":anchor, "replay":replay, "world_seed":"1"*64, "id_seed":"2"*64})
    peer.rows[-1] = json.dumps({"id":"1", "ok":True, "encoded":frame}).encode()
    model.scores["probabilities"] = [0]*63+[1]
    assert choose(owned, decision, anchor, replay)["selection"]["candidate_id"] == 563
    assert chooser_peer.writes[0]["count"] == 64 and len(model.requests[0][0]["candidate_ids"]) == 64
    assert [row[13] for row in model.requests[0][0]["candidate_features"]] == [int(value) for value in flags]
    owned.close()


@pytest.mark.parametrize("config", [
    {"mode_mana_callback":"true"}, {"mode_mana_callback":1}, {"mode_mana_callback":None},
    {"mode_mana_callback":True}, {"mode_mana_callback":True, "mode_callback":True},
    {"mode_mana_callback":True, "dialog_callback":True},
    {"mode_mana_callback":True, "mode_callback":True, "dialog_callback":False},
])
def test_mana_mode_staging_needs_both_original_rules_before_any_file_access(tmp_path, config):
    manifest = {"schema":"spellbench-xmage-release-inputs/v1", "assets":[],
                "inference_backends":{"jack-rl-april":config}}
    with pytest.raises(ValueError, match="boolean flag|original mode and dialog rules"):
        stage(manifest, tmp_path / "missing-inputs", tmp_path / "output")
    assert not (tmp_path / "output").exists() and not (tmp_path / "missing-inputs").exists()
