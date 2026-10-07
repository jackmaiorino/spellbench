"""Automatic payment variants bind original sources and preserve owned inference."""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import xmage_maintainer_modes as modes
import xmage_maintainer_dialogs as dialogs
from xmage_maintainer_selection import MaintainerSelectionSession, GREEDY
from xmage_maintainer_sources import CALLBACK_SHA256, MANA_PAYMENT_VARIANT, mana_payment_source, stage
from xmage_neural_decisions import decision_hash
from test_xmage_maintainer_inference import Peer
from test_xmage_maintainer_modes import Model as ModeModel
from test_xmage_maintainer_mode_mana import fixture as mode_fixture, MANA_SOURCES
from test_xmage_maintainer_dialogs import fixture as dialog_fixture, Model as DialogModel, SOURCES as DIALOG_SOURCES

PAYMENT_SHA = "f" * 64


def setup(family, *, edit_ready=None, edit_frame=None, edit_sources=None, legacy=False):
    if family == "mode":
        start, decision, anchor, replay, ready, frame = mode_fixture()
        sources, kind, model = dict(MANA_SOURCES), modes.PaymentModeSession, ModeModel(start)
        old = modes.ManaModeSession
    else:
        numeric = family == "x"
        start, decision, anchor, replay, ready, frame = dialog_fixture(numeric=numeric)
        sources, kind, model = dict(DIALOG_SOURCES), dialogs.PaymentDialogSession, DialogModel(start, numeric)
        old = dialogs.DialogSession
    sources["mana_payment_rules_source_sha256"] = PAYMENT_SHA
    ready.update(encoder=kind.ENCODER, variant=kind.VARIANT, mana_payment_variant=MANA_PAYMENT_VARIANT, **sources)
    frame.update(variant=kind.VARIANT, mana_payment_variant=MANA_PAYMENT_VARIANT, **sources)
    frame["request_sha256"] = decision_hash({"id":"1", "game_start":start, "decision":decision,
        "anchor":anchor, "replay":replay, "world_seed":"1"*64, "id_seed":"2"*64})
    if edit_ready: edit_ready(ready)
    if edit_frame: edit_frame(frame)
    if edit_sources: edit_sources(sources)
    peer = Peer([ready, {"id":"1", "ok":True, "encoded":frame}])
    chooser_peer = Peer([{"ready":True, "selection":"maintainer-original-no-training", "profile":GREEDY,
        "seed":7, "callback_source_sha256":CALLBACK_SHA256}, {"id":"1", "ok":True, "indices":[1]}])
    chooser = MaintainerSelectionSession(chooser_peer, profile=GREEDY, seed=7)
    try:
        owned = (old if legacy else kind)(peer, model, chooser, game_start=start, sources=sources)
    except BaseException:
        assert peer.closed and chooser_peer.closed and model.closed == 1
        assert not peer.writes and not chooser_peer.writes and not model.requests
        raise
    return owned, decision, anchor, replay, peer, model, chooser_peer, frame


def choose(values):
    owned, decision, anchor, replay = values[:4]
    return owned.choose(decision, anchor=anchor, replay=replay, world_seed="1"*64, id_seed="2"*64, timeout_s=5)


@pytest.mark.parametrize("family", ["mode", "binary", "x"])
def test_payment_variants_use_same_paired_policy_chooser_and_clock(family):
    values = setup(family)
    owned, _, _, _, peer, model, chooser, frame = values
    result = choose(values)
    assert result["variant"] == owned.VARIANT
    features, timeout = model.requests[0]
    assert features["candidate_features"] == frame["candidate_features"]
    assert features["candidate_ids"] == frame["candidate_ids"]
    assert 0 < chooser.timeouts[0] <= timeout <= peer.timeouts[0] <= 5
    if family == "mode":
        assert [row[13] for row in features["candidate_features"][:3]] == [1, 0, 1]
    owned.close(); owned.close()
    assert peer.closed and chooser.closed and model.closed == 1


@pytest.mark.parametrize("family", ["mode", "binary", "x"])
@pytest.mark.parametrize("field", ["mana_payment_rules_source_sha256", "mana_payment_variant", "variant"])
def test_payment_frame_tampering_refuses_before_model_and_closes(family, field):
    values = setup(family, edit_frame=lambda frame: frame.update({field:"changed"}))
    with pytest.raises(ValueError): choose(values)
    assert not values[5].requests and not values[6].writes
    assert values[4].closed and values[6].closed and values[5].closed == 1


@pytest.mark.parametrize("family", ["mode", "binary", "x"])
@pytest.mark.parametrize("field", ["mana_payment_rules_source_sha256", "mana_payment_variant"])
def test_payment_readiness_must_bind_rule_pin_and_variant(family, field):
    with pytest.raises(ValueError): setup(family, edit_ready=lambda ready: ready.pop(field))


@pytest.mark.parametrize("family", ["mode", "binary", "x"])
def test_old_consumers_cannot_accept_new_payment_pipe(family):
    with pytest.raises(ValueError): setup(family, legacy=True)


@pytest.mark.parametrize("family", ["mode", "binary", "x"])
@pytest.mark.parametrize("change", ["missing", "extra", "malformed"])
def test_payment_source_set_refuses_before_request(family, change):
    def edit(sources):
        if change == "missing": sources.pop("mana_payment_rules_source_sha256")
        elif change == "extra": sources["unbound"] = "e"*64
        else: sources["mana_payment_rules_source_sha256"] = "F"*64
    with pytest.raises(ValueError): setup(family, edit_sources=edit)


@pytest.mark.parametrize("flag", [1, 0, "true", "false", None, [], {}])
def test_payment_staging_requires_explicit_boolean_before_source_access(tmp_path, flag):
    manifest = {"schema":"spellbench-xmage-release-inputs/v1", "inference_backends":{"maintainer-rl-april":{
        "mana_payment_callback":flag}}}
    with pytest.raises(ValueError, match="explicit boolean"):
        stage(manifest, tmp_path / "missing", tmp_path / "output")
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("flag", [False, None])
def test_payment_staging_requires_filtered_mana_path_before_source_access(tmp_path, flag):
    config = {"mode_callback":True, "dialog_callback":True, "mana_payment_callback":True}
    if flag is not None: config["mode_mana_callback"] = flag
    manifest = {"schema":"spellbench-xmage-release-inputs/v1", "inference_backends":{"maintainer-rl-april":config}}
    with pytest.raises(ValueError, match="filtered mana callback"):
        stage(manifest, tmp_path / "missing", tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_mana_rule_extraction_refuses_unpinned_source():
    with pytest.raises(ValueError, match="pinned April callback"):
        mana_payment_source("untrusted or different private source")
