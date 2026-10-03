"""Private neural inputs stay individually pinned and unassociated entries cannot serve."""

import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import xmage_checkpoint_backend as backend

_spec = importlib.util.spec_from_file_location(
    "jack_runtime", Path(__file__).parents[2] / "integrations/xmage-models/jack_runtime.py")
runtime = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runtime)
IMAGE = "sha256:" + "a" * 64


def inputs(root):
    assets = []
    for aid, kind in (("policy", "checkpoint"), ("mulligan", "checkpoint"), ("model", "source-code"),
                      ("mulligan-source", "source-code"), ("encoder", "source-code"),
                      ("callback", "source-code"), ("embeddings", "feature-data")):
        data = ("opaque " + aid).encode()
        (root / aid).write_bytes(data)
        assets.append({"id": aid, "kind": kind, "filename": aid, "bytes": len(data),
                       "sha256": hashlib.sha256(data).hexdigest(), "transport": "local-file",
                       "provenance": "private supplied input"})
    assets[0].update(checkpoint_format="torch", mulligan_checkpoint="mulligan", embedding_cache="embeddings")
    return {"schema": "spellbench-xmage-release-inputs/v1", "assets": assets,
            "inference_backends": {"jack-rl-april": {"checkpoints": ["policy"], "model": "model",
                "mulligan_source": "mulligan-source", "state_encoder": "encoder", "callback_source": "callback"}}}


def test_private_probe_pins_seven_files_and_serve_requires_exact_deck_association(tmp_path):
    manifest = inputs(tmp_path)
    argv = backend.pinned_command(manifest, tmp_path, "policy", IMAGE, "probe")
    assert argv.count("--mount") == 7 and argv[argv.index("--network") + 1] == "none"
    assert "--read-only" in argv and "--vocab-sha256" not in argv
    assert argv[argv.index("--architecture") + 1] == "jack-rl-april"
    assert argv[argv.index("--embeddings-sha256") + 1] == manifest["assets"][-1]["sha256"]
    with pytest.raises(ValueError, match="deck association"):
        backend.pinned_command(manifest, tmp_path, "policy", IMAGE, "serve")
    manifest["assets"][0].update(deck_id="sha256:" + "b" * 64, deck_association_evidence="pinned source registry and deck")
    assert "serve" in backend.pinned_command(manifest, tmp_path, "policy", IMAGE, "serve")


@pytest.mark.parametrize("name", ["mulligan", "mulligan-source", "encoder", "callback", "embeddings"])
def test_changed_paired_network_or_encoder_input_refuses_launch(tmp_path, name):
    manifest = inputs(tmp_path)
    (tmp_path / name).write_bytes(b"changed")
    with pytest.raises(ValueError, match="does not match"):
        backend.pinned_command(manifest, tmp_path, "policy", IMAGE, "probe")


def test_missing_paired_mulligan_and_aliased_embedding_identity_are_refused(tmp_path):
    manifest = inputs(tmp_path)
    manifest["assets"][0].pop("mulligan_checkpoint")
    with pytest.raises(ValueError, match="paired mulligan"):
        backend.pinned_command(manifest, tmp_path, "policy", IMAGE, "probe")
    manifest["assets"][0].update(mulligan_checkpoint="mulligan", embedding_cache="encoder")
    with pytest.raises(ValueError, match="distinct"):
        backend.pinned_command(manifest, tmp_path, "policy", IMAGE, "probe")


def test_legacy_mulligan_preserves_its_explicit_q_value_format(tmp_path):
    manifest = inputs(tmp_path)
    manifest["assets"][0]["mulligan_format"] = "keep-mull-q"
    argv = backend.pinned_command(manifest, tmp_path, "policy", IMAGE, "probe")
    assert argv[argv.index("--mulligan-format") + 1] == "keep-mull-q"
    manifest["assets"][0]["mulligan_format"] = "invented-softmax"
    with pytest.raises(ValueError, match="mulligan policy format"):
        backend.pinned_command(manifest, tmp_path, "policy", IMAGE, "probe")


def test_request_envelope_refuses_nonfinite_features_fake_masks_and_hashed_id_overflow():
    assert runtime.matrix([[0] * 128], 128) == [[0] * 128]
    for value in (float("nan"), float("inf"), True):
        with pytest.raises(ValueError, match="finite"):
            runtime.vector([value], 1)
    with pytest.raises(ValueError, match="booleans"):
        runtime.vector([0], 1, boolean=True)
    with pytest.raises(ValueError, match="vocabulary"):
        runtime.vector([65536], 1, integers=65536)
    with pytest.raises(ValueError, match="row bound"):
        runtime.matrix([[0] * 48] * 513, 48)
