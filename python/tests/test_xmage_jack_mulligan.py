"""Verify offered mulligans and encoder-to-network binding without model loads."""
import copy
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]/"tools"))
import xmage_jack_mulligan as mull
from spellbench import wire
from xmage_neural_decisions import decision_hash
from test_xmage_jack_inference import Peer

STAGED = "c"*64


def fixture():
    start = {"seat":"p0", "game_id":"bound", "agent_seed":7,
             "own_deck":{"decklist":[{"name":"Mountain", "count":8}, {"name":"Lightning Bolt", "count":2}]}}
    hand = [{"object_id":"own-"+str(i), "card_name":n, "owner_seat":"p0", "zone":"hand"}
            for i, n in enumerate(("Lightning Bolt", "Mountain"))]
    decision = {"acting_seat":"p0", "seat_step":3, "context":{"kind":"choice"},
                "observation":{"viewer":"p0", "phase_step":"pregame", "players":[
                    {"seat":"p0", "mulligans_taken":1, "hand_count":2, "library_count":8, "hand":hand},
                    {"seat":"p1", "mulligans_taken":0, "hand_count":7, "library_count":3, "hand":None}]},
                "candidates":[{"candidate_id":cid, "semantic":{"kind":"mulligan", "keep":k,
                              "hand_size":2, "mulligans_taken":1}} for cid, k in ((20, False), (3, True))]}
    ready = {"ready":True, "encoder":"jack-permitted-mulligan",
             "original_mulligan_encoder_sha256":mull.MULLIGAN_JAVA_SHA256,
             "mulligan_encoder_source_sha256":STAGED, "variant":mull.MULLIGAN_VARIANT}
    encoded = {"schema":"spellbench-jack-mulligan-features/v1", "kind":"mulligan",
               "decision_sha256":decision_hash(decision), "game_start_sha256":decision_hash(start),
               "original_mulligan_encoder_sha256":mull.MULLIGAN_JAVA_SHA256,
               "mulligan_encoder_source_sha256":STAGED, "mulligans_taken":1,
               "hand_size":2, "remaining_library_size":8, "variant":mull.MULLIGAN_VARIANT,
               "world_flags":[], "values":[1,1,0,1.0,11,12]+[0]*5+[13]*8+[0]*52}
    return start, decision, ready, encoded


class Model:
    checkpoint = "paired-private-policy"
    def __init__(self, start, scores, format):
        self.game_start_sha256 = decision_hash(start)
        self.encoding = {"mulligan_format":format}
        self.scores = scores
        self.requests = []
        self.closed = 0
    def score(self, features, *, timeout_s):
        self.requests.append((copy.deepcopy(features), timeout_s))
        return copy.deepcopy(self.scores)
    def close(self): self.closed += 1


def session(*, format="keep-logit", scores=None, edit=None, response_id="1"):
    start, decision, ready, encoded = fixture()
    if edit: edit(encoded)
    peer = Peer([ready, {"id":response_id, "ok":True, "encoded":encoded}])
    model = Model(start, scores or {"keep_logit":0, "keep_probability":0.5}, format)
    owned = mull.MulliganSession(peer, model, game_start=start, staged_source_sha256=STAGED)
    return owned, decision, peer, model, encoded


def choose(owned, decision):
    return owned.choose(decision, world_seed="1"*64, id_seed="2"*64, timeout_s=5)


@pytest.mark.parametrize("format,scores,expected", [
    ("keep-logit", {"keep_logit":0, "keep_probability":0.5}, True),
    ("keep-logit", {"keep_logit":-1, "keep_probability":1/(1+math.e)}, False),
    ("keep-mull-q", {"q_keep":1, "q_mulligan":1, "keep":True}, True),
    ("keep-mull-q", {"q_keep":-2, "q_mulligan":1, "keep":False}, False),
])
def test_exact_original_keep_rules_bind_offered_ids_and_share_clock(format, scores, expected):
    owned, d, peer, model, encoded = session(format=format, scores=scores)
    got = choose(owned, d)
    candidate = next(c for c in d["candidates"] if c["semantic"]["keep"] == expected)
    assert got["selection"] == {"candidate_id":candidate["candidate_id"], "semantic_echo":candidate["semantic"]}
    assert got["scores"] == scores and got["variant"] == mull.MULLIGAN_VARIANT
    assert got["checkpoint"] == model.checkpoint
    assert model.requests[0][0] == {"kind":"mulligan", "values":encoded["values"]}
    assert 0 < model.requests[0][1] <= peer.timeouts[0] <= 5
    assert peer.writes[0]["decision"] == d and peer.writes[0]["id"] == "1"
    owned.close(); owned.close()
    assert peer.closed and model.closed == 1


@pytest.mark.parametrize("edit", [
    lambda e:e.update(decision_sha256="0"*64), lambda e:e.update(game_start_sha256="0"*64),
    lambda e:e.update(original_mulligan_encoder_sha256="0"*64),
    lambda e:e.update(mulligan_encoder_source_sha256="0"*64),
    lambda e:e.update(mulligans_taken=True), lambda e:e.update(hand_size=3),
    lambda e:e.update(remaining_library_size=7), lambda e:e.update(variant="raw library order"),
    lambda e:e.update(world_flags=["unsupported:unknown"]), lambda e:e.update(world_flags=[0]),
    lambda e:e["values"].__setitem__(0, 2), lambda e:e["values"].__setitem__(1, 3),
    lambda e:e["values"].__setitem__(2, 2), lambda e:e["values"].__setitem__(3, float("nan")),
    lambda e:e["values"].__setitem__(4, 0), lambda e:e["values"].__setitem__(6, 9),
    lambda e:e["values"].__setitem__(11, 0), lambda e:e["values"].__setitem__(19, 9),
    lambda e:e["values"].__setitem__(11, 65536), lambda e:e["values"].pop(),
])
def test_changed_or_leaking_encoding_refuses_before_checkpoint_inference(edit):
    owned, d, peer, model, _ = session(edit=edit)
    with pytest.raises(ValueError): choose(owned, d)
    assert peer.closed and model.closed == 1 and not model.requests


@pytest.mark.parametrize("edit", [
    lambda d:d.update(acting_seat="p1"), lambda d:d["observation"].update(viewer="p1"),
    lambda d:d["observation"].update(phase_step="precombat_main"),
    lambda d:d["observation"]["players"][0].update(mulligans_taken=True),
    lambda d:d["observation"]["players"][0].update(library_count=61),
    lambda d:d["observation"]["players"][0].update(hand_count=3),
    lambda d:d["observation"]["players"][0]["hand"][0].update(card_name=None),
    lambda d:d["candidates"][0]["semantic"].update(keep=True),
    lambda d:d["candidates"][0]["semantic"].update(mulligans_taken=2),
    lambda d:d["candidates"][0]["semantic"].update(hand_size=3),
    lambda d:d["candidates"][0].update(candidate_id=True), lambda d:d["candidates"].pop(),
])
def test_invalid_public_mulligan_refuses_before_encoder_io(edit):
    owned, d, peer, model, _ = session()
    edit(d)
    with pytest.raises(ValueError): choose(owned, d)
    assert not peer.writes and not model.requests and peer.closed and model.closed == 1


def test_another_game_or_bad_readiness_closes_both_owned_peers():
    start, d, ready, _ = fixture()
    for changed_game in (True, False):
        model = Model(start, {}, "keep-logit")
        peer = Peer([{**ready, "ready":1} if not changed_game else ready])
        other = copy.deepcopy(start)
        if changed_game: other["game_id"] = "other"
        with pytest.raises(ValueError):
            mull.MulliganSession(peer, model, game_start=other, staged_source_sha256=STAGED)
        assert peer.closed and model.closed == 1


@pytest.mark.parametrize("response_id", ["0", "2", 1])
def test_stale_encoder_result_refuses_before_model_io(response_id):
    owned, d, peer, model, _ = session(response_id=response_id)
    with pytest.raises(ValueError): choose(owned, d)
    assert not model.requests and peer.closed and model.closed == 1


@pytest.mark.parametrize("stage", ["encoder", "model"])
def test_shared_clock_expiry_closes_resources(stage, monkeypatch):
    owned, d, peer, model, _ = session()
    now = [0.0]
    monkeypatch.setattr(mull.time, "monotonic", lambda:now[0])
    if stage == "encoder":
        original = peer.read_line
        def read():
            now[0] = 6.0
            return original()
        peer.read_line = read
    else:
        original = model.score
        def score(*a, **k):
            now[0] = 6.0
            return original(*a, **k)
        model.score = score
    with pytest.raises(TimeoutError): choose(owned, d)
    assert peer.closed and model.closed == 1
    assert bool(model.requests) == (stage == "model")
