"""Exercise the JVM owner protocol with the existing paired-session validation."""
import hashlib
import json
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import xmage_jack_native_inference as native
from spellbench import wire
from test_xmage_jack_backend import IMAGE
from test_xmage_jack_inference import Peer, features, fixture


def owner_fixture(tmp_path, monkeypatch, *, policy_format="keep-logit", rows=None):
    manifest, game, ready, cleanup = fixture(tmp_path, monkeypatch, policy_format=policy_format)
    pair = Peer([ready, *(rows or [])])
    owner = native.JackNativeInferenceOwner(manifest, tmp_path, "policy", IMAGE, game_start=game,
        profile=native.PROFILES[0], seed=31, peer_factory=lambda *a, **k: pair)
    return owner, pair, cleanup


def packet(owner, operation="score", **changes):
    row = {"schema": native.SCHEMA, "id": owner.sequence + 1, "operation": operation,
           "callback_sha256": native.CALLBACK_SHA256, "profile": owner.profile, "seed": owner.seed,
           "game_start_sha256": owner.start_sha256, "remaining_s": 2}
    if operation == "score":
        row.update(features=features(), selection={"pick_index": 0, "minimum": 1, "maximum": 1, "count": 2})
    row.update(changes)
    return row


def test_one_confined_pair_serves_callbacks_and_shared_copy_stream(tmp_path, monkeypatch):
    scores = {"probabilities": [0.25, 0.75] + [0] * 62, "value": -0.25}
    owner, pair, cleanup = owner_fixture(tmp_path, monkeypatch, rows=[{"id": "1", **scores}, {"id": "2", **scores}])
    assert owner.handle(packet(owner)) == {"id": 1, **scores}
    assert owner.handle(packet(owner, "physical_copy", count=1)) == {"id": 2, "index": 0}
    assert owner.copy_draws == 0
    seeded = random.Random(int.from_bytes(hashlib.sha256(b"spellbench-jack-card-copy-mt19937/v1\0"
                   + wire.canonical_json_dumps(owner.start)).digest(), "big"))
    assert owner.handle(packet(owner, "physical_copy", count=4)) == {"id": 3, "index": seeded.randrange(4)}
    assert owner.handle(packet(owner, features=features("target"),
            selection={"pick_index": 1, "minimum": 1, "maximum": 3, "count": 2})) == {"id": 4, **scores}
    assert owner.copy_draws == 1 and [r["id"] for r in pair.writes] == ["1", "2"]
    assert owner.handle(packet(owner, "close")) == {"id": 5, "closed": True}
    assert pair.closed and len(cleanup) == 1


@pytest.mark.parametrize("fmt,scores,expected", [
    ("keep-logit", {"keep_logit": 0, "keep_probability": 0.5}, (0, 0.5)),
    ("keep-mull-q", {"q_keep": 2, "q_mulligan": 2, "keep": True}, (2, 2)),
])
def test_original_mulligan_format_and_ties(tmp_path, monkeypatch, fmt, scores, expected):
    owner, _, _ = owner_fixture(tmp_path, monkeypatch, policy_format=fmt, rows=[{"id": "1", **scores}])
    encoded = {"kind": "mulligan", "values": [0, 1, 0, 0] + list(range(1, 68))}
    result = owner.handle(packet(owner, "mulligan", features=encoded))
    assert result == {"id": 1, "format": fmt, "first": expected[0], "second": expected[1]}
    owner.close()


@pytest.mark.parametrize("changes", [
    {"schema": "foreign"}, {"callback_sha256": "0" * 64}, {"game_start_sha256": "0" * 64},
    {"profile": native.PROFILES[1]}, {"seed": True}, {"seed": 32}, {"id": 2}, {"id": True},
    {"remaining_s": 0}, {"remaining_s": float("inf")}, {"operation": "train"},
    {"features": {"kind": "mulligan"}}, {"selection": {"pick_index": -1, "minimum": 1, "maximum": 1, "count": 2}},
    {"selection": {"pick_index": 0, "minimum": 2, "maximum": 1, "count": 2}},
    {"selection": {"pick_index": 0, "minimum": 1, "maximum": 1, "count": 1}},
])
def test_wrong_native_identity_or_prefix_closes_owned_pair(tmp_path, monkeypatch, changes):
    owner, pair, cleanup = owner_fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        owner.handle(packet(owner, **changes))
    assert owner.closed and pair.closed and len(cleanup) == 1 and not pair.writes


@pytest.mark.parametrize("count", [0, -1, 65, True, 1.5])
def test_invalid_physical_copy_count_fails_closed(tmp_path, monkeypatch, count):
    owner, pair, _ = owner_fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="physical-copy count"):
        owner.handle(packet(owner, "physical_copy", count=count))
    assert pair.closed


def test_existing_pair_rejects_nonfinite_response_before_native_reply(tmp_path, monkeypatch):
    owner, pair, _ = owner_fixture(tmp_path, monkeypatch, rows=[{"id": "1", "probabilities": [0.5, 0.5] + [0] * 62, "value": float("nan")}])
    with pytest.raises(ValueError):
        owner.handle(packet(owner))
    assert owner.closed and pair.closed


def test_private_response_write_uses_remaining_clock_and_closes_on_pipe_failure(tmp_path, monkeypatch):
    scores = {"probabilities": [0.25, 0.75] + [0] * 62, "value": 0}
    owner, pair, _ = owner_fixture(tmp_path, monkeypatch, rows=[{"id": "1", **scores}])
    peer = Peer([])
    result = owner.service(peer, packet(owner))
    assert peer.writes == [result] and 0 < peer.timeouts[0] <= 2
    owner.close()
    owner, pair, _ = owner_fixture(tmp_path, monkeypatch)
    def broken(_):
        raise OSError("private JVM response pipe closed")
    peer.write_line = broken
    with pytest.raises(OSError):
        owner.service(peer, packet(owner, "physical_copy", count=2))
    assert owner.closed and pair.closed


@pytest.mark.parametrize("cause", ["pipe", "deadline"])
def test_response_failure_survives_owned_pair_cleanup_error(tmp_path, monkeypatch, cause):
    owner, pair, _ = owner_fixture(tmp_path, monkeypatch)
    peer = Peer([])
    original_close = owner.session.close

    def broken_cleanup():
        original_close()
        raise RuntimeError("owned pair cleanup failed")

    monkeypatch.setattr(owner.session, "close", broken_cleanup)
    failure = OSError("private JVM response pipe closed")
    if cause == "pipe":
        def broken_write(_):
            raise failure
        peer.write_line = broken_write
        expected = OSError
    else:
        times = iter((0, 3))
        monkeypatch.setattr(native.time, "monotonic", lambda: next(times))
        expected = TimeoutError

    with pytest.raises(expected) as caught:
        owner.service(peer, packet(owner, "physical_copy", count=2))
    if cause == "pipe":
        assert caught.value is failure
    assert any("owned pair cleanup failed" in note for note in caught.value.__notes__)
    assert owner.closed and pair.closed
