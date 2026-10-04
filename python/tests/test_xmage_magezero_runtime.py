"""MageZero's launcher binds public sources, deck-local weights and ownership."""
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import xmage_magezero_runtime as runtime
import xmage_magezero_search as search
from spellbench.bot import GameOver, GameStart
from test_xmage_magezero_decisions import mage_inputs, START
from test_xmage_neural_agent import game
from test_xmage_neural_bridge import Peer
from test_xmage_magezero_search import Model
from test_xmage_neural_runtime import fixture as build_fixture

IMAGE = "sha256:" + "a" * 64


def inputs(root):
    manifest, _ = mage_inputs(root)
    manifest["sources"] = {"magezero": {"revision": "pinned-v02"}}
    manifest["inference_backends"]["magezero-v02"].update(feature_hash_bins=2147483647, policy_width=128)
    public = copy.deepcopy(manifest)
    public["assets"] = [asset for asset in public["assets"] if asset["id"] != "policy"]
    public["inference_backends"]["magezero-v02"]["checkpoints"] = []
    return manifest, public


def test_author_weight_extension_preserves_the_current_repository_manifest():
    public = json.loads((Path(__file__).parents[2] / "engines/xmage/releases.json").read_bytes())
    manifest = copy.deepcopy(public)
    asset = {"id": "magezero-author-test", "filename": "author-test.mz", "kind": "checkpoint",
             "transport": "local-file", "provenance": "synthetic author-delivery test; no actual weights",
             "bytes": 128, "sha256": "a" * 64, "checkpoint_format": "magezero-mz",
             "deck_id": "sha256:" + "b" * 64, "deck_association_evidence": "synthetic exact-deck evidence",
             "export_metadata": {"deck": "synthetic deck", "version": 1}}
    manifest["assets"].append(asset)
    manifest["inference_backends"]["magezero-v02"]["checkpoints"].append(asset["id"])
    assert runtime.validate_inputs(manifest, public, asset["id"]) == asset


@pytest.mark.parametrize("fault", [None, "source", "encoder", "width", "duplicate-id", "filename-alias",
                                  "unregistered-weights", "absent-weights", "deck", "provenance", "onnx"])
def test_external_weights_cannot_replace_public_pins_or_bypass_deck_association(tmp_path, fault):
    manifest, public = inputs(tmp_path)
    if fault == "source": manifest["sources"]["magezero"]["revision"] = "different"
    elif fault == "encoder": manifest["inference_backends"]["magezero-v02"]["feature_hash_bins"] = 2000000
    elif fault == "width": manifest["inference_backends"]["magezero-v02"]["policy_width"] = 1024
    elif fault == "duplicate-id": manifest["assets"].append(copy.deepcopy(manifest["assets"][0]))
    elif fault == "filename-alias": manifest["assets"][0]["filename"] = "MODEL"
    elif fault == "unregistered-weights": manifest["assets"].append({**manifest["assets"][0], "id": "extra", "filename": "extra.pt"})
    elif fault == "absent-weights": manifest = copy.deepcopy(public)
    elif fault == "deck": manifest["assets"][0].pop("deck_id")
    elif fault == "provenance": manifest["assets"][0].pop("provenance")
    elif fault == "onnx": manifest["assets"][0]["checkpoint_format"] = "onnx"
    if fault is None:
        assert runtime.validate_inputs(manifest, public, "policy") == manifest["assets"][0]
    else:
        with pytest.raises(ValueError):
            runtime.validate_inputs(manifest, public, "policy")


def test_identity_binds_exact_settings_deck_checkpoint_build_and_image(tmp_path):
    manifest, public = inputs(tmp_path)
    params = {"checkpoint": "policy", "settings": copy.deepcopy(search.ORIGINAL_DEFAULT_SETTINGS),
              "build_sha256": "b" * 64, "image": IMAGE, "manifest": manifest, "public": public}
    original = runtime.identity(**params)
    assert original == runtime.identity(**params)
    changes = [{"settings": search.diagnostic_settings(6)},
               {"settings": {**params["settings"], "searchTimeout": "3", "noPolicyUse": False}},
               {"build_sha256": "c" * 64}, {"image": "sha256:" + "d" * 64}]
    for change in changes:
        assert runtime.identity(**{**params, **change})["version"] != original["version"]
    for field, value in (("deck_id", "sha256:" + "e" * 64), ("sha256", "f" * 64)):
        changed = copy.deepcopy(manifest)
        changed["assets"][0][field] = value
        assert runtime.identity(**{**params, "manifest": changed})["version"] != original["version"]
    assert original["identity"]["profile"]["full_game_qualified"] is False
    assert original["identity"]["deck_id"] == manifest["assets"][0]["deck_id"]
    with pytest.raises(ValueError):
        runtime.identity(**{**params, "image": "image:mutable"})


@pytest.mark.parametrize("fault", [None, "encoder-stage", "search-stage", "old-bridge"])
def test_magezero_build_needs_its_own_encoder_search_and_mixed_entrypoints(tmp_path, monkeypatch, fault):
    build, engine, public, metadata = build_fixture(tmp_path)
    metadata.pop("search_stage")
    metadata.update(magezero_stage={"pinned": True}, magezero_search_stage={"pinned": True})
    names = ["MageZeroSearchMain", "MageZeroSearchCombatMain", "MageZeroSearchBridgeMain"]
    if fault == "old-bridge": names.pop()
    for name in names:
        relative = "model/spellbench/kit/xmage/" + name + ".class"
        path = build / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode())
        metadata["class_files_sha256"][relative] = runtime.sha(path)
    if fault == "encoder-stage": metadata["magezero_stage"] = None
    if fault == "search-stage": metadata["magezero_search_stage"] = None
    (build / "BUILD.json").write_text(json.dumps(metadata), encoding="utf-8")
    import xmage_neural_runtime as common
    monkeypatch.setattr(common, "verify_build", lambda *args: None)
    if fault is None:
        assert runtime.verify_model_build(build, runtime.sha(build / "BUILD.json"), engine, public,
                                          architecture="magezero-v02") == metadata
    else:
        with pytest.raises(ValueError):
            runtime.verify_model_build(build, runtime.sha(build / "BUILD.json"), engine, public,
                                       architecture="magezero-v02")


@pytest.mark.parametrize("fault", [None, "java-startup", "wrong-ready", "cleanup", "close", "changed-input"])
def test_launcher_uses_only_own_deck_context_and_closes_or_retains_owned_runtime(tmp_path, monkeypatch, fault):
    import xmage_magezero_bridge as bridge
    manifest, public = inputs(tmp_path)
    settings = copy.deepcopy(search.ORIGINAL_DEFAULT_SETTINGS)
    paths = {}
    for name, value in (("weights.json", manifest), ("public.json", public), ("settings.json", settings)):
        paths[name] = tmp_path / name
        paths[name].write_text(json.dumps(value), encoding="utf-8")
    java, db = tmp_path / "java.exe", tmp_path / "cards.h2.mv.db"
    java.write_bytes(b"test JDK")
    db.write_bytes(b"test database")
    build, engine, work = tmp_path / "build", tmp_path / "engine", tmp_path / "work"
    build.mkdir()
    metadata = {"dependency_sha256": {str(tmp_path / "commons-math.jar"): "0" * 64}}
    calls, models, peers, cleanup = [], [], [], []
    monkeypatch.setattr(runtime, "verify_model_build", lambda *args, **kwargs: metadata)

    class OwnedModel(Model):
        checkpoint = "policy"
        def close(self):
            super().close()
            if fault == "close": raise RuntimeError("test close failure")

    def inference(*args, **kwargs):
        assert kwargs["architecture"] == "magezero-v02"
        assert kwargs["game_start"] == {"seat": "p0", "own_deck": START["own_deck"]}
        calls.append(kwargs["game_start"])
        kwargs["on_owned"]("spellbench-xmage-" + "1" * 32)
        model = OwnedModel()
        models.append(model)
        return model

    def peer_factory(command, **kwargs):
        assert command[-1] == "spellbench.kit.xmage.MageZeroSearchBridgeMain"
        assert not any("mz.actionVocab" in part for part in command)
        if fault == "java-startup": raise OSError("test JVM startup failure")
        peer = Peer([], ready={"ready": "wrong"} if fault == "wrong-ready" else bridge.READY)
        peers.append(peer)
        return peer

    def serve(bot, **kwargs):
        assert kwargs["requires_observation"] == ("passed_seats", "keywords")
        assert (Path.cwd() / "db/cards.h2.mv.db").read_bytes() == b"test database"
        start = game()
        start.update(own_deck=copy.deepcopy(START["own_deck"]), hidden_engine_state="must be omitted")
        bot.on_game_start(GameStart.from_request(start))
        if fault != "close":
            bot.on_game_over(GameOver.from_request({"game_id": "opaque", "terminal": {}}))
        return 0

    monkeypatch.setattr(runtime, "InferenceSession", inference)
    monkeypatch.setattr(runtime.wire, "SubprocessPeer", peer_factory)
    monkeypatch.setattr(runtime, "serve", serve)
    monkeypatch.setattr(runtime, "cleanup_container", lambda name: cleanup.append(name) or {"confirmed_absent": fault != "cleanup"})
    argv = ["--java", str(java), "--java-sha256", runtime.sha(java), "--engine", str(engine),
            "--model-build", str(build), "--model-build-sha256", "b" * 64,
            "--manifest", str(paths["weights.json"]), "--public-manifest", str(paths["public.json"]),
            "--settings", str(paths["settings.json"]), "--root", str(tmp_path), "--checkpoint", "policy",
            "--image", IMAGE, "--db-file", str(db), "--db-sha256", runtime.sha(db), "--work", str(work)]
    if fault == "changed-input": (tmp_path / "policy").write_bytes(b"changed opaque checkpoint")
    previous = Path.cwd()
    if fault is None:
        assert runtime.main(argv) == 0
    else:
        with pytest.raises((ValueError, RuntimeError, OSError)):
            runtime.main(argv)
    assert Path.cwd() == previous
    if fault == "changed-input":
        assert not work.exists() and not calls and not models and not peers and not cleanup
    else:
        assert len(calls) == len(models) == len(cleanup) == 1 and models[0].closed
        assert all(peer.closed for peer in peers)
        assert len(list(work.glob("*.owned.json"))) == len(list(work.glob("*.cleanup.json"))) == 1
        directories = list(work.glob("magezero-agent-*"))
        assert bool(directories) == (fault in ("cleanup", "close"))
