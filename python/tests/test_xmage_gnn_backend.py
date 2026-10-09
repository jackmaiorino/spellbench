"""The graph network's inputs reach the container pinned, read-only and without network."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import xmage_gnn_backend as backend

IMAGE = "sha256:" + "b" * 64
SPECS = [("w", "model.safetensors", "checkpoint"), ("v", "vocab.json", "feature-data"),
         ("c", "config.json", "feature-data"), ("g", "graph_net.py", "source-code"),
         ("gold", "goldens.jsonl.gz", "feature-data")]


def fixture_inputs(root):
    assets = []
    for aid, name, kind in SPECS:
        data = ("opaque pinned " + aid).encode()
        (root / name).write_bytes(data)
        assets.append({"id": aid, "filename": name, "kind": kind, "bytes": len(data),
                       "sha256": hashlib.sha256(data).hexdigest(), "url": "https://example.invalid/" + name})
    return {"schema": "spellbench-xmage-release-inputs/v1", "assets": assets,
            "inference_backends": {"draftzero-gnn": {"model": "g", "vocab": "v", "config": "c", "goldens": "gold",
                                                     "checkpoint_format": "safetensors", "checkpoints": ["w"]}}}


def mounts(argv):
    return [argv[i + 1] for i, a in enumerate(argv) if a == "--mount"]


@pytest.mark.parametrize("mode,count", [("serve", 4), ("check", 5)])
def test_container_gets_only_pinned_release_files_read_only_and_no_network(tmp_path, mode, count):
    manifest = fixture_inputs(tmp_path)
    argv = backend.pinned_command(manifest, tmp_path, IMAGE, mode)
    assert argv[argv.index("--network") + 1] == "none"
    assert "--read-only" in argv and argv[argv.index("--cap-drop") + 1] == "ALL"
    assert len(mounts(argv)) == count and all(m.endswith(",readonly") for m in mounts(argv))
    assert "/var/run/docker.sock" not in " ".join(argv) and "--privileged" not in argv
    assert argv[argv.index(IMAGE) + 1] == mode
    pins = {a["id"]: a["sha256"] for a in manifest["assets"]}
    assert argv[argv.index("--model") + 1] == "/inputs/model.safetensors"
    assert argv[argv.index("--model-sha256") + 1] == pins["w"]
    assert argv[argv.index("--graph-net-sha256") + 1] == pins["g"]
    assert ("--goldens" in argv) == (mode == "check")


@pytest.mark.parametrize("filename", [name for _, name, _ in SPECS[:4]])
def test_changed_weights_vocab_config_or_network_code_cannot_launch(tmp_path, filename):
    manifest = fixture_inputs(tmp_path)
    (tmp_path / filename).write_bytes(b"changed")
    with pytest.raises(ValueError, match="does not match"):
        backend.pinned_command(manifest, tmp_path, IMAGE, "serve")


def test_mutable_image_unknown_mode_and_unpinned_format_refused(tmp_path):
    manifest = fixture_inputs(tmp_path)
    with pytest.raises(ValueError, match="immutable"):
        backend.pinned_command(manifest, tmp_path, "spellbench-xmage-models:gnn", "serve")
    with pytest.raises(ValueError, match="unsupported"):
        backend.pinned_command(manifest, tmp_path, IMAGE, "probe")
    manifest["inference_backends"]["draftzero-gnn"]["checkpoint_format"] = "torch"
    with pytest.raises(ValueError, match="safetensors"):
        backend.pinned_command(manifest, tmp_path, IMAGE, "serve")


def test_repository_manifest_pins_the_public_release():
    manifest = json.loads((Path(__file__).parents[2] / "engines/xmage/releases.json").read_text(encoding="utf-8"))
    config = manifest["inference_backends"]["draftzero-gnn"]
    assets = {a["id"]: a for a in manifest["assets"]}
    revision = manifest["sources"]["draftzero_gnn_weights"]["revision"]
    for aid in (config["checkpoints"][0], config["model"], config["vocab"], config["config"], config["goldens"]):
        assert assets[aid]["url"].startswith("https://huggingface.co/danbrooks/draftzero-fdn-gnn/resolve/" + revision + "/")
    assert assets[config["checkpoints"][0]]["sha256"] == "d5ee8323ccca11f18b1667bc2312407d9d5696b6dacf7243d9a30461cdc29b56"
    for aid in config["encoder_source_assets"] + config["search_source_assets"]:
        assert assets[aid]["source_revision"] == manifest["sources"]["draftzero_gnn"]["revision"]
