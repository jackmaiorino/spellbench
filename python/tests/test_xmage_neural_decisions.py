"""A model can select only its bound offered choices; failures close its container."""
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import xmage_neural_decisions as adapter

IMAGE = "sha256:" + "a" * 64


def decision():
    offered = {"seat_step": 4, "candidates": [
        {"candidate_id": 83, "semantic": {"kind": "pass"}},
        {"candidate_id": 27, "semantic": {"kind": "cast_spell", "source": {"object_id": "visible-card"}}}]}
    encoded = {"schema": "spellbench-draftzero-decision-features/v1", "head": "priority",
               "encoding": adapter.ENCODING, "features": [3, 500], "decision_sha256": adapter.decision_hash(offered),
               "policy_slots": [{"candidate_id": 83, "policy_slot": 0}, {"candidate_id": 27, "policy_slot": 5}]}
    return offered, encoded


def scores():
    values = {head: [0.0] * 1024 for head in ("priority", "opponent_priority", "target")}
    values.update(binary=[0.0, 0.0], value=0.25)
    values["priority"][0], values["priority"][5], values["priority"][10] = -4.0, 2.0, 99.0
    return values


def inputs(root):
    assets = []
    for name in ("policy", "model", "vocab", "actions"):
        data = ("pinned " + name).encode()
        (root / name).write_bytes(data)
        assets.append({"id": name, "filename": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
                       "kind": "checkpoint" if name == "policy" else "source-code",
                       "transport": "local-file", "provenance": "test input fixture"})
    return {"schema": "spellbench-xmage-release-inputs/v1", "assets": assets,
            "inference_backends": {"draftzero-exp1": {"checkpoints": ["policy"], "model": "model",
                                                       "feature_vocab_code": "vocab", "action_vocab": "actions"}}}


def readiness(manifest):
    hashes = {a["id"]: a["sha256"] for a in manifest["assets"]}
    return {"ready": True, "architecture": "draftzero-exp1", "policy_width": 1024, "encoding": adapter.ENCODING,
            "checkpoint_sha256": hashes["policy"], "model_source_sha256": hashes["model"],
            "vocab_source_sha256": hashes["vocab"], "action_vocab_sha256": hashes["actions"]}


class Peer:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.writes = []
        self.closed = False
        self.timeouts = []

    def read_line(self):
        item = next(self.replies)
        if isinstance(item, Exception):
            raise item
        return json.dumps(item, allow_nan=False).encode()

    def write_line(self, value):
        assert not value.endswith(b"\n")  # SubprocessPeer owns the NDJSON delimiter.
        self.writes.append(json.loads(value))

    def set_timeout(self, value):
        self.timeouts.append(value)

    def close(self):
        self.closed = True


def test_argmax_masks_unoffered_actions_and_ties_do_not_depend_on_candidate_order():
    offered, encoded = decision()
    result = adapter.select_candidate(offered, encoded, scores())
    assert result["selection"] == {"candidate_id": 27, "semantic_echo": offered["candidates"][1]["semantic"]}
    logits = scores()
    logits["priority"][0] = logits["priority"][5]
    offered["candidates"].reverse()
    encoded["decision_sha256"] = adapter.decision_hash(offered)
    assert adapter.select_candidate(offered, encoded, logits)["selection"]["candidate_id"] == 27


@pytest.mark.parametrize("mutation", ["stale-decision", "missing-candidate", "duplicate-candidate", "overflow-slot",
                                     "boolean-slot", "unknown-head", "bad-feature"])
def test_stale_or_incomplete_encodings_cannot_choose_a_candidate(mutation):
    offered, encoded = decision()
    if mutation == "stale-decision":
        offered["seat_step"] = 5
    elif mutation == "missing-candidate":
        encoded["policy_slots"].pop()
    elif mutation == "duplicate-candidate":
        encoded["policy_slots"][1]["candidate_id"] = 83
    elif mutation == "overflow-slot":
        encoded["policy_slots"][1]["policy_slot"] = 1024
    elif mutation == "boolean-slot":
        encoded["policy_slots"][1]["policy_slot"] = True
    elif mutation == "unknown-head":
        encoded["head"] = "made-up"
    else:
        encoded["features"] = [2000000]
    with pytest.raises(ValueError):
        adapter.select_candidate(offered, encoded, scores())


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), True, "0"])
def test_invalid_policy_outputs_never_turn_into_a_native_fallback(invalid):
    offered, encoded = decision()
    logits = scores()
    logits["target"][7] = invalid
    with pytest.raises(ValueError, match="policy head"):
        adapter.select_candidate(offered, encoded, logits)


def test_live_requests_share_the_clock_and_confirm_owned_container_cleanup(tmp_path, monkeypatch):
    manifest = inputs(tmp_path)
    peer = Peer([readiness(manifest), {"id": "1", **scores()}])
    removed = []
    monkeypatch.setattr(adapter, "cleanup_container", lambda name: removed.append(name) or {"confirmed_absent": True})
    session = adapter.InferenceSession(manifest, tmp_path, "policy", IMAGE, peer_factory=lambda *a, **k: peer)
    offered, encoded = decision()
    assert session.choose(offered, encoded, timeout_s=2)["selection"]["candidate_id"] == 27
    assert peer.writes == [{"id": "1", "features": encoded["features"], "encoding": adapter.ENCODING}]
    assert 0 < peer.timeouts[1] <= peer.timeouts[0] <= 2
    session.close()
    session.close()
    assert peer.closed and removed == [session.container] and session.cleanup["confirmed_absent"]


@pytest.mark.parametrize("record_fails", [False, True])
def test_container_ownership_is_recorded_before_launch_including_failed_startup(tmp_path, monkeypatch, record_fails):
    manifest = inputs(tmp_path)
    peer = Peer([readiness(manifest)])
    events = []
    monkeypatch.setattr(adapter, "cleanup_container", lambda name: events.append(("cleanup", name))
                        or {"confirmed_absent": True})
    def owned(name):
        events.append(("owned", name))
        if record_fails:
            raise OSError("ownership destination unavailable")
    def start(*args, **kwargs):
        assert events[0][0] == "owned"
        events.append(("launch", args[0]))
        return peer
    if record_fails:
        with pytest.raises(RuntimeError, match="ownership destination"):
            adapter.InferenceSession(manifest, tmp_path, "policy", IMAGE, peer_factory=start, on_owned=owned)
        assert [kind for kind, _ in events] == ["owned", "cleanup"]
    else:
        session = adapter.InferenceSession(manifest, tmp_path, "policy", IMAGE, peer_factory=start, on_owned=owned)
        assert events[0] == ("owned", session.container)
        session.close()
        assert [kind for kind, _ in events] == ["owned", "launch", "cleanup"]


@pytest.mark.parametrize("reply", [{"id": "old", **scores()}, EOFError("model exited")])
def test_failed_or_stale_inference_poison_the_session_and_close_it(tmp_path, monkeypatch, reply):
    manifest = inputs(tmp_path)
    peer = Peer([readiness(manifest), reply])
    removed = []
    monkeypatch.setattr(adapter, "cleanup_container", lambda name: removed.append(name) or {"confirmed_absent": True})
    session = adapter.InferenceSession(manifest, tmp_path, "policy", IMAGE, peer_factory=lambda *a, **k: peer)
    offered, encoded = decision()
    with pytest.raises((ValueError, EOFError)):
        session.choose(offered, encoded, timeout_s=2)
    with pytest.raises(ValueError, match="closed or has failed"):
        session.choose(offered, encoded, timeout_s=2)
    assert peer.closed and removed == [session.container]


def test_wrong_checkpoint_readiness_preserves_cleanup_evidence(tmp_path, monkeypatch):
    manifest = inputs(tmp_path)
    ready = readiness(manifest)
    ready["checkpoint_sha256"] = "b" * 64
    peer = Peer([ready])
    monkeypatch.setattr(adapter, "cleanup_container", lambda name: {"confirmed_absent": True})
    with pytest.raises(RuntimeError, match="readiness") as failure:
        adapter.InferenceSession(manifest, tmp_path, "policy", IMAGE, peer_factory=lambda *a, **k: peer)
    assert peer.closed and failure.value.cleanup["confirmed_absent"]


def test_cleanup_failure_is_visible_even_after_a_successful_handshake(tmp_path, monkeypatch):
    manifest = inputs(tmp_path)
    peer = Peer([readiness(manifest)])
    monkeypatch.setattr(adapter, "cleanup_container", lambda name: {"confirmed_absent": False})
    session = adapter.InferenceSession(manifest, tmp_path, "policy", IMAGE, peer_factory=lambda *a, **k: peer)
    with pytest.raises(RuntimeError, match="cleanup could not be confirmed"):
        session.close()
    assert peer.closed


def test_candidate_selection_uses_the_remaining_inference_clock(tmp_path, monkeypatch):
    manifest = inputs(tmp_path)
    peer = Peer([readiness(manifest), {"id": "1", **scores()}])
    monkeypatch.setattr(adapter, "cleanup_container", lambda name: {"confirmed_absent": True})
    clock = [0.0]
    monkeypatch.setattr(adapter.time, "monotonic", lambda: clock[0])
    original = adapter.select_candidate
    def delayed_selection(*args):
        result = original(*args)
        clock[0] = 2.0
        return result
    monkeypatch.setattr(adapter, "select_candidate", delayed_selection)
    session = adapter.InferenceSession(manifest, tmp_path, "policy", IMAGE, peer_factory=lambda *a, **k: peer)
    offered, encoded = decision()
    with pytest.raises(TimeoutError, match="selection-validation clock"):
        session.choose(offered, encoded, timeout_s=1)
    assert session.failed and session.closed and peer.closed


@pytest.mark.parametrize("operation", ["choose", "score"])
def test_inference_error_survives_transport_shutdown_failure_with_container_receipt(tmp_path, monkeypatch, operation):
    manifest = inputs(tmp_path)
    failure = EOFError("original inference failure")
    peer = Peer([readiness(manifest), failure])

    def failed_close():
        peer.closed = True
        raise OSError("inference transport shutdown failed")

    peer.close = failed_close
    removed = []
    monkeypatch.setattr(adapter, "cleanup_container", lambda name: removed.append(name) or {"confirmed_absent": False})
    session = adapter.InferenceSession(manifest, tmp_path, "policy", IMAGE, peer_factory=lambda *a, **k: peer)
    offered, encoded = decision()
    with pytest.raises(EOFError) as caught:
        if operation == "choose":
            session.choose(offered, encoded, timeout_s=2)
        else:
            session.score(encoded["features"], timeout_s=2)
    assert caught.value is failure
    assert session.failed and session.closed and peer.closed
    assert removed == [session.container] and session.cleanup == {"confirmed_absent": False}
    assert any("inference transport shutdown failed" in note for note in failure.__notes__)
