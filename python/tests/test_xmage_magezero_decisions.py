"""The MageZero path binds its own hash range, head widths and checkpoint."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import xmage_neural_decisions as adapter
from test_xmage_neural_decisions import IMAGE, Peer, inputs

START = {"own_deck": {"decklist": [{"name": "Swamp", "count": 60}]}}


def decision():
    offered = {"seat_step": 4, "context": {"kind": "priority"}, "candidates": [
        {"candidate_id": 83, "semantic": {"kind": "pass"}},
        {"candidate_id": 27, "semantic": {"kind": "cast_spell", "source": {"object_id": "visible"}}}]}
    encoded = {"schema": "spellbench-magezero-priority-features/v1", "head": "priority",
               "encoding": adapter.MAGEZERO_ENCODING, "features": [3, 2147483646],
               "decision_sha256": adapter.decision_hash(offered),
               "policy_slots": [{"candidate_id": 83, "policy_slot": 0}, {"candidate_id": 27, "policy_slot": 127}]}
    return offered, encoded


def scores():
    result = {head: [0.0] * 128 for head in ("priority", "opponent_priority", "target")}
    result.update(binary=[0.0, 0.0], value=0.25)
    result["priority"][0], result["priority"][127], result["priority"][10] = -1, 2, 99
    return result


def mage_inputs(root):
    manifest = inputs(root)
    config = manifest["inference_backends"].pop("draftzero-exp1")
    config.pop("action_vocab")
    manifest["inference_backends"]["magezero-v02"] = config
    manifest["assets"][0].update(checkpoint_format="torch", deck_id=adapter.digests.deck_id(START["own_deck"]["decklist"]),
                                  deck_association_evidence="synthetic test deck, not a pretrained release")
    hashes = {a["id"]: a["sha256"] for a in manifest["assets"]}
    ready = {"ready": True, "architecture": "magezero-v02", "policy_width": 128,
             "encoding": adapter.MAGEZERO_ENCODING, "checkpoint_sha256": hashes["policy"],
             "model_source_sha256": hashes["model"], "vocab_source_sha256": hashes["vocab"],
             "action_vocab_sha256": None}
    return manifest, ready


def test_magezero_argmax_masks_unoffered_actions_and_accepts_its_wide_hashes():
    offered, encoded = decision()
    assert adapter.select_candidate(offered, encoded, scores(), "magezero-v02")["selection"]["candidate_id"] == 27
    with pytest.raises(ValueError, match="Exp1 encoding"):
        adapter.select_candidate(offered, encoded, scores())


@pytest.mark.parametrize("mutation", ["slot-overflow", "negative-slot", "feature-overflow", "draftzero-encoding",
                                     "draftzero-schema", "callback", "wrong-head", "stale", "wide-head"])
def test_magezero_cannot_accept_another_encoder_or_unsupported_dialog(mutation):
    offered, encoded = decision()
    logits = scores()
    if mutation == "slot-overflow":
        encoded["policy_slots"][1]["policy_slot"] = 128
    elif mutation == "negative-slot":
        encoded["policy_slots"][1]["policy_slot"] = -7
    elif mutation == "feature-overflow":
        encoded["features"] = [2147483647]
    elif mutation == "draftzero-encoding":
        encoded["encoding"] = adapter.ENCODING
    elif mutation == "draftzero-schema":
        encoded["schema"] = "spellbench-draftzero-priority-features/v1"
    elif mutation == "callback":
        offered["context"]["kind"] = "target"
        encoded["decision_sha256"] = adapter.decision_hash(offered)
    elif mutation == "wrong-head":
        encoded["head"] = "target"
    elif mutation == "stale":
        offered["seat_step"] += 1
    else:
        logits["target"] *= 8
    with pytest.raises(ValueError):
        adapter.select_candidate(offered, encoded, logits, "magezero-v02")


def test_magezero_session_uses_the_wide_encoding_and_removes_its_own_container(tmp_path, monkeypatch):
    manifest, ready = mage_inputs(tmp_path)
    peer = Peer([ready, {"id": "1", **scores()}])
    removed = []
    monkeypatch.setattr(adapter, "cleanup_container", lambda name: removed.append(name) or {"confirmed_absent": True})
    session = adapter.InferenceSession(manifest, tmp_path, "policy", IMAGE,
                                       architecture="magezero-v02", game_start=START, peer_factory=lambda *a, **k: peer)
    offered, encoded = decision()
    assert session.choose(offered, encoded, timeout_s=2)["selection"]["candidate_id"] == 27
    assert peer.writes == [{"id": "1", "features": encoded["features"], "encoding": adapter.MAGEZERO_ENCODING}]
    session.close()
    assert removed == [session.container] and peer.closed


@pytest.mark.parametrize("wrong", ["architecture", "encoding", "policy_width", "checkpoint_sha256"])
def test_magezero_refuses_mismatched_readiness_with_cleanup(tmp_path, monkeypatch, wrong):
    manifest, ready = mage_inputs(tmp_path)
    ready[wrong] = "different"
    peer = Peer([ready])
    removed = []
    monkeypatch.setattr(adapter, "cleanup_container", lambda name: removed.append(name) or {"confirmed_absent": True})
    with pytest.raises(RuntimeError, match="readiness"):
        adapter.InferenceSession(manifest, tmp_path, "policy", IMAGE,
                                 architecture="magezero-v02", game_start=START, peer_factory=lambda *a, **k: peer)
    assert peer.closed and len(removed) == 1


def test_absent_magezero_weights_never_launch_an_exp1_substitute(tmp_path):
    manifest, _ = mage_inputs(tmp_path)
    manifest["inference_backends"]["magezero-v02"]["checkpoints"] = []
    with pytest.raises(ValueError, match="pinned MageZero"):
        adapter.InferenceSession(manifest, tmp_path, "policy", IMAGE, architecture="magezero-v02",
                                 peer_factory=lambda *a, **k: pytest.fail("missing checkpoint launched"))


def test_deck_unassociated_magezero_is_refused_before_container_launch(tmp_path):
    manifest, _ = mage_inputs(tmp_path)
    manifest["assets"][0].pop("deck_id")
    with pytest.raises(ValueError, match="deck association"):
        adapter.InferenceSession(manifest, tmp_path, "policy", IMAGE, architecture="magezero-v02",
                                 game_start=START,
                                 peer_factory=lambda *a, **k: pytest.fail("unassociated checkpoint launched"))


@pytest.mark.parametrize("start", [None, {"own_deck": {"decklist": [{"name": "Island", "count": 60}]}}])
def test_missing_or_different_actual_deck_is_refused_before_launch(tmp_path, start):
    manifest, _ = mage_inputs(tmp_path)
    with pytest.raises(ValueError, match="own decklist"):
        adapter.InferenceSession(manifest, tmp_path, "policy", IMAGE, architecture="magezero-v02",
                                 game_start=start, peer_factory=lambda *a, **k: pytest.fail("wrong deck launched"))
