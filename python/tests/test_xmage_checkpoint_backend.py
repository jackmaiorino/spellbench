"""Verify real input refusal and the authority granted to the container."""

import copy
import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import xmage_checkpoint_backend as backend


def fixture_inputs(root):
    specs = [("ckpt", "weights.pt.gz", "checkpoint"), ("model", "model.py", "source-code"),
             ("vocab", "vocab.py", "source-code"), ("actions", "actions.tsv", "action-vocabulary")]
    assets = []
    for aid, name, kind in specs:
        data = ("opaque pinned " + aid).encode()
        (root / name).write_bytes(data)
        assets.append({"id": aid, "filename": name, "kind": kind, "bytes": len(data),
                       "sha256": hashlib.sha256(data).hexdigest(), "url": "https://example.invalid/" + name})
    return {"schema": "spellbench-xmage-release-inputs/v1", "assets": assets,
            "inference_backends": {"draftzero-exp1": {"model": "model", "feature_vocab_code": "vocab",
                                                    "action_vocab": "actions", "checkpoints": ["ckpt"]}}}


IMAGE = "sha256:" + "a" * 64


def test_container_receives_only_four_pinned_files_read_only_and_has_no_network(tmp_path):
    argv = backend.pinned_command(fixture_inputs(tmp_path), tmp_path, "ckpt", IMAGE, "probe")
    assert argv[:2] == ["docker", "run"]
    assert argv[argv.index("--network") + 1] == "none"
    assert "--read-only" in argv and argv[argv.index("--cap-drop") + 1] == "ALL"
    mounts = [argv[i + 1] for i, a in enumerate(argv) if a == "--mount"]
    assert len(mounts) == 4 and all(m.endswith(",readonly") for m in mounts)
    assert {m.split(",dst=")[1].split(",")[0] for m in mounts} == {
        "/inputs/checkpoint.pt.gz", "/inputs/source/model.py", "/inputs/source/vocab.py", "/inputs/actions.tsv"}
    assert all(str(tmp_path) in m for m in mounts)
    assert "/var/run/docker.sock" not in " ".join(argv)
    assert IMAGE in argv and "--privileged" not in argv


@pytest.mark.parametrize("filename", ["weights.pt.gz", "model.py", "vocab.py", "actions.tsv"])
def test_changed_weight_source_or_action_mapping_cannot_launch(tmp_path, filename):
    manifest = fixture_inputs(tmp_path)
    (tmp_path / filename).write_bytes(b"changed")
    with pytest.raises(ValueError, match="does not match"):
        backend.pinned_command(manifest, tmp_path, "ckpt", IMAGE, "serve")


def test_wrong_checkpoint_or_mutable_image_refused(tmp_path):
    manifest = fixture_inputs(tmp_path)
    with pytest.raises(ValueError, match="no pinned inference"):
        backend.pinned_command(manifest, tmp_path, "absent", IMAGE, "probe")
    with pytest.raises(ValueError, match="immutable"):
        backend.pinned_command(manifest, tmp_path, "ckpt", "models:latest", "probe")


def test_source_link_and_duplicate_identity_refused(tmp_path):
    manifest = fixture_inputs(tmp_path)
    duplicated = copy.deepcopy(manifest)
    duplicated["assets"].append(copy.deepcopy(duplicated["assets"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        backend.pinned_command(duplicated, tmp_path, "ckpt", IMAGE, "probe")
    target = tmp_path / "real-model.py"
    (tmp_path / "model.py").rename(target)
    try:
        (tmp_path / "model.py").symlink_to(target)
    except OSError:
        pytest.skip("this host does not permit creating a symlink")
    with pytest.raises(ValueError, match="regular file"):
        backend.pinned_command(manifest, tmp_path, "ckpt", IMAGE, "probe")


def test_deck_local_magezero_weight_requires_association_and_keeps_its_own_architecture(tmp_path):
    manifest = fixture_inputs(tmp_path)
    config = manifest["inference_backends"].pop("draftzero-exp1")
    config.pop("action_vocab")
    manifest["inference_backends"]["magezero-v02"] = config
    with pytest.raises(ValueError, match="deck association"):
        backend.pinned_command(manifest, tmp_path, "ckpt", IMAGE, "probe")
    manifest["assets"][0].update(deck_id="sha256:" + "b" * 64, deck_association_evidence="author's export metadata")
    argv = backend.pinned_command(manifest, tmp_path, "ckpt", IMAGE, "probe")
    assert argv[argv.index("--architecture") + 1] == "magezero-v02"
    assert "--actions" not in argv and argv.count("--mount") == 3
