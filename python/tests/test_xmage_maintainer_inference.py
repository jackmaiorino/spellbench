"""Exercise the private paired protocol without importing or loading a model."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import xmage_maintainer_inference as maintainer
import xmage_maintainer_selection as selection
from spellbench import digests
from test_xmage_maintainer_backend import IMAGE, inputs


class Peer:
    def __init__(self, rows):
        self.rows = [json.dumps(row).encode() if isinstance(row, dict) else row for row in rows]
        self.writes, self.timeouts = [], []
        self.closed = False

    def read_line(self):
        return self.rows.pop(0)

    def write_line(self, data):
        self.writes.append(json.loads(data))

    def set_timeout(self, seconds):
        assert seconds > 0
        self.timeouts.append(seconds)

    def close(self):
        self.closed = True


def fixture(root, monkeypatch, *, policy_format="keep-logit"):
    manifest = inputs(root)
    assets = {a["id"]: a for a in manifest["assets"]}
    assets["encoder"]["sha256"] = maintainer.ENCODER_SHA256
    assets["callback"]["sha256"] = maintainer.CALLBACK_SHA256
    deck = {"decklist": [{"name": "Forest", "count": 60}]}
    assets["policy"].update(deck_id=digests.deck_id(deck["decklist"]),
                            deck_association_evidence="test source registry and exact deck", mulligan_format=policy_format)
    _, ready = maintainer.encoding(manifest, "policy")
    cleanup = []
    monkeypatch.setattr(maintainer, "cleanup_container", lambda name: cleanup.append(name) or {"confirmed_absent": True})
    # The real command construction and seven read-only mounts are exercised
    # in test_xmage_maintainer_backend. This fixture models only the private peer.
    monkeypatch.setattr(maintainer, "pinned_command", lambda *args: ["confined-test-peer"])
    return manifest, {"own_deck": deck}, ready, cleanup


def features(head="action"):
    return {"kind": "candidates", "head": head, "sequence": [[0] * 128 for _ in range(256)],
            "padding": [False] + [True] * 255, "token_ids": [1] + [0] * 255,
            "candidate_features": [[0] * 48 for _ in range(64)],
            "candidate_ids": [7, 8] + [0] * 62, "candidate_mask": [True, True] + [False] * 62}


@pytest.mark.parametrize("head", maintainer.HEADS)
def test_all_five_heads_keep_original_distribution_and_increasing_request_ids(tmp_path, monkeypatch, head):
    manifest, game, ready, cleanup = fixture(tmp_path, monkeypatch)
    distribution = [0.25, 0.75] + [0] * 62
    scores = {"probabilities": distribution, "value": -0.3}
    peer = Peer([ready, {"id": "1", **scores}, {"id": "2", **scores}])
    registered = []
    session = maintainer.MaintainerInferenceSession(manifest, tmp_path, "policy", IMAGE, game_start=game,
        peer_factory=lambda *a, **k: peer, on_owned=registered.append)
    request = features(head)
    assert session.score(request, timeout_s=3) == scores
    assert session.score(request, timeout_s=3) == scores
    assert [row["id"] for row in peer.writes] == ["1", "2"]
    assert all(row["encoding"] == session.encoding and row["features"] == request for row in peer.writes)
    assert registered == [session.container]
    session.close()
    session.close()
    assert peer.closed and cleanup == registered


@pytest.mark.parametrize("policy_format,scores", [
    ("keep-logit", {"keep_logit": 0, "keep_probability": 0.5}),
    ("keep-mull-q", {"q_keep": 1.5, "q_mulligan": 1.5, "keep": True}),
    ("keep-mull-q", {"q_keep": -2, "q_mulligan": 1, "keep": False}),
])
def test_paired_mulligan_uses_original_format_without_replacing_its_policy(tmp_path, monkeypatch, policy_format, scores):
    manifest, game, ready, _ = fixture(tmp_path, monkeypatch, policy_format=policy_format)
    peer = Peer([ready, {"id": "1", **scores}])
    session = maintainer.MaintainerInferenceSession(manifest, tmp_path, "policy", IMAGE, game_start=game,
        peer_factory=lambda *a, **k: peer)
    request = {"kind": "mulligan", "values": [0, 1, 0, 0] + list(range(1, 68))}
    assert session.score(request, timeout_s=3) == scores
    session.close()


def test_actual_own_deck_is_checked_before_any_peer_or_container_registration(tmp_path, monkeypatch):
    manifest, game, ready, cleanup = fixture(tmp_path, monkeypatch)
    game["own_deck"]["decklist"][0]["count"] = 59
    with pytest.raises(ValueError, match="actual own deck"):
        maintainer.MaintainerInferenceSession(manifest, tmp_path, "policy", IMAGE, game_start=game,
            peer_factory=lambda *a, **k: pytest.fail("wrong deck reached inference"),
            on_owned=lambda name: pytest.fail("wrong deck registered a container"))
    assert cleanup == []


@pytest.mark.parametrize("field,value", [
    ("checkpoint_sha256", "0" * 64), ("mulligan_sha256", "0" * 64),
    ("candidate_heads", ["action"]), ("strict_load", 1), ("weights_only", False),
    ("device", "cuda"), ("encoding", {"input_dim": 128}),
    ("mulligan_parameters", {**maintainer.MULLIGAN_PARAMETERS, "num_explicit": 4}),
])
def test_wrong_readiness_closes_the_owned_peer_and_container(tmp_path, monkeypatch, field, value):
    manifest, game, ready, cleanup = fixture(tmp_path, monkeypatch)
    ready[field] = value
    peer = Peer([ready])
    with pytest.raises(RuntimeError, match="readiness") as failure:
        maintainer.MaintainerInferenceSession(manifest, tmp_path, "policy", IMAGE, game_start=game,
            peer_factory=lambda *a, **k: peer)
    assert peer.closed and len(cleanup) == 1 and failure.value.cleanup == {"confirmed_absent": True}


@pytest.mark.parametrize("fault", ["stale", "nonfinite", "masked", "not-normalized", "short", "duplicate-key"])
def test_invalid_policy_receipt_fails_session_without_an_argmax_fallback(tmp_path, monkeypatch, fault):
    manifest, game, ready, cleanup = fixture(tmp_path, monkeypatch)
    row = {"id": "1", "probabilities": [0.25, 0.75] + [0] * 62, "value": 0}
    if fault == "stale": row["id"] = "0"
    elif fault == "nonfinite": row["value"] = float("inf")
    elif fault == "masked": row["probabilities"][2] = 0.2
    elif fault == "not-normalized": row["probabilities"][0] = 0.5
    elif fault == "short": row["probabilities"].pop()
    else: row = b'{"id":"1","id":"1"}'
    peer = Peer([ready, row])
    session = maintainer.MaintainerInferenceSession(manifest, tmp_path, "policy", IMAGE, game_start=game,
        peer_factory=lambda *a, **k: peer)
    with pytest.raises(ValueError):
        session.score(features(), timeout_s=3)
    assert session.failed and peer.closed and len(cleanup) == 1
    with pytest.raises(ValueError, match="closed"):
        session.score(features(), timeout_s=3)


@pytest.mark.parametrize("fault", ["legacy-actor", "bad-mask", "empty-state", "vocab-overflow", "candidate-zero", "wrong-shape"])
def test_invalid_encoded_input_never_reaches_checkpoint(tmp_path, monkeypatch, fault):
    manifest, game, ready, cleanup = fixture(tmp_path, monkeypatch)
    peer = Peer([ready])
    session = maintainer.MaintainerInferenceSession(manifest, tmp_path, "policy", IMAGE, game_start=game,
        peer_factory=lambda *a, **k: peer)
    request = features()
    if fault == "legacy-actor": request["kind"] = "legacy_actor"
    elif fault == "bad-mask": request["candidate_mask"][0] = 1
    elif fault == "empty-state": request["padding"][0] = True
    elif fault == "vocab-overflow": request["token_ids"][0] = 65536
    elif fault == "candidate-zero": request["candidate_ids"][0] = 0
    else: request["candidate_features"].pop()
    with pytest.raises(ValueError):
        session.score(request, timeout_s=3)
    assert peer.writes == [] and session.failed and peer.closed and len(cleanup) == 1


def test_validation_time_uses_the_same_request_clock(tmp_path, monkeypatch):
    manifest, game, ready, cleanup = fixture(tmp_path, monkeypatch)
    peer = Peer([ready])
    session = maintainer.MaintainerInferenceSession(manifest, tmp_path, "policy", IMAGE, game_start=game,
        peer_factory=lambda *a, **k: peer)
    ticks = iter([0, 4])
    monkeypatch.setattr(maintainer.time, "monotonic", lambda: next(ticks))
    with pytest.raises(TimeoutError):
        session.score(features(), timeout_s=3)
    assert peer.writes == [] and peer.closed and len(cleanup) == 1


def test_unconfirmed_checkpoint_cleanup_is_retained_as_a_failure(tmp_path, monkeypatch):
    manifest, game, ready, _ = fixture(tmp_path, monkeypatch)
    peer = Peer([ready])
    session = maintainer.MaintainerInferenceSession(manifest, tmp_path, "policy", IMAGE, game_start=game,
        peer_factory=lambda *a, **k: peer)
    monkeypatch.setattr(maintainer, "cleanup_container", lambda name: {"confirmed_absent": False})
    with pytest.raises(RuntimeError, match="unconfirmed"):
        session.close()
    assert session.cleanup == {"confirmed_absent": False} and peer.closed


def selection_ready(profile=selection.GREEDY, seed=7):
    return {"ready": True, "selection": "maintainer-original-no-training", "profile": profile,
            "seed": seed, "callback_source_sha256": maintainer.CALLBACK_SHA256}


@pytest.mark.parametrize("profile", selection.PROFILES)
@pytest.mark.parametrize("sequential,picks", [(False, 1), (True, 1), (True, 2)])
def test_selection_component_preserves_explicit_profile_and_original_index_order(profile, sequential, picks):
    indices = [1, 0][:picks]
    peer = Peer([selection_ready(profile), {"id": "1", "ok": True, "indices": indices}])
    session = selection.MaintainerSelectionSession(peer, profile=profile, seed=7)
    assert session.choose([0.25, 0.75] + [0] * 62, [True, True] + [False] * 62,
        count=2, picks=picks, sequential=sequential, timeout_s=3) == indices
    assert peer.writes[0]["probabilities"][:2] == [0.25, 0.75]
    assert peer.writes[0]["sequential"] == sequential
    session.close()
    assert peer.closed


@pytest.mark.parametrize("indices", [[0, 0], [2, 0], [True, 0], [0], None])
def test_original_selection_receipt_rejects_repeated_illegal_and_incomplete_indices(indices):
    peer = Peer([selection_ready(), {"id": "1", "ok": True, "indices": indices}])
    session = selection.MaintainerSelectionSession(peer, profile=selection.GREEDY, seed=7)
    with pytest.raises(ValueError, match="picks"):
        session.choose([0.25, 0.75] + [0] * 62, [True, True] + [False] * 62,
            count=2, picks=2, sequential=True, timeout_s=3)
    assert session.failed and peer.closed


def test_masked_and_out_of_count_selection_cannot_be_dispatched():
    peer = Peer([selection_ready()])
    session = selection.MaintainerSelectionSession(peer, profile=selection.GREEDY, seed=7)
    with pytest.raises(ValueError, match="mask"):
        session.choose([0.25, 0.75] + [0] * 62, [True, True] + [False] * 62,
            count=1, picks=1, sequential=False, timeout_s=3)
    assert peer.writes == [] and peer.closed


@pytest.mark.parametrize("profile,seed", [("training-epsilon", 7), (selection.GREEDY, -1), (selection.GREEDY, True)])
def test_no_implicit_training_profile_or_invalid_game_seed(profile, seed):
    peer = Peer([])
    with pytest.raises(ValueError, match="no-training"):
        selection.MaintainerSelectionSession(peer, profile=profile, seed=seed)
    assert peer.closed


def test_q_ties_and_sigmoid_cannot_be_changed_by_the_peer():
    request = {"kind": "mulligan"}
    with pytest.raises(ValueError, match="tie rule"):
        maintainer.validate_scores({"q_keep": 0, "q_mulligan": 0, "keep": False}, request, "keep-mull-q")
    with pytest.raises(ValueError, match="sigmoid"):
        maintainer.validate_scores({"keep_logit": 0, "keep_probability": 0.9}, request, "keep-logit")
