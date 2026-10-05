"""Runtime startup and existing guards, using opaque synthetic files only."""
import copy
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import xmage_jack_native_runtime as runtime
import xmage_neural_runtime as common
from xmage_jack_sources import CALLBACK_SHA256, ENCODER_SHA256, MULLIGAN_JAVA_SHA256
from spellbench.bot import GameStart, GameOver
from test_xmage_neural_agent import game
from test_xmage_jack_inference import fixture as inputs
from test_xmage_neural_runtime import fixture as build_fixture

IMAGE = "sha256:" + "a" * 64


@pytest.mark.parametrize("fault", [None, "manifest", "callback", "encoder", "mulligan", "stage", "class", "mode-class", "named-class", "target-class", "general-target-class", "card-set-class", "parent-card-class"])
def test_original_runtime_rejects_partial_builds_and_changed_private_manifest(tmp_path, monkeypatch, fault):
    build, engine, releases, metadata = build_fixture(tmp_path)
    private = tmp_path / "private.json"; private.write_bytes(b'{"private":true}')
    stage = {"original_source_sha256": ENCODER_SHA256, "original_callback_sha256": CALLBACK_SHA256,
             "original_mulligan_encoder_sha256": MULLIGAN_JAVA_SHA256,
             **{key: "a" * 64 for key in ("staged_callback_player_sha256", "staged_priority_choice_player_sha256",
                "staged_neural_selection_sha256", "staged_priority_rules_sha256", "staged_activation_player_sha256",
                "staged_parent_mana_player_sha256", "staged_parent_dialog_player_sha256")}}
    metadata.update(jack_stage=stage, jack_inputs_manifest_sha256=runtime.sha(private))
    for package, names in (("models/jack", ("OriginalCallbackPlayer", "OriginalPriorityChoicePlayer", "OriginalNeuralSelection",
            "OriginalActivationPlayer", "OriginalParentManaPlayer", "OriginalParentDialogsPlayer", "StateSequenceBuilder",
            "CandidateEncoder", "MulliganEncoder", "PriorityRules", "DialogRules", "ModeRules", "TargetRules",
            "CardSetRules", "CombatRules", "LondonRules")), ("kit/xmage", ("JackOriginalBridgeMain", "JackRootDecision",
            "JackPriorityState", "JackDialogReplay", "JackDialogEncoder", "JackModeEncoder", "JackNamedChoices", "JackTargetEncoder", "JackGeneralTargetEncoder", "JackCardSetEncoder", "JackParentCardEncoder", "JackInferenceChannel", "JackPermittedWorlds",
            "JackPlayerBootstrap", "ModelReplay"))):
        for name in names:
            path = build / ("model/spellbench/" + package + "/" + name + ".class")
            path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(name.encode())
            metadata["class_files_sha256"][path.relative_to(build).as_posix()] = runtime.sha(path)
    if fault == "manifest": metadata["jack_inputs_manifest_sha256"] = "0" * 64
    if fault == "callback": stage["original_callback_sha256"] = "0" * 64
    if fault == "encoder": stage["original_source_sha256"] = "0" * 64
    if fault == "mulligan": stage["original_mulligan_encoder_sha256"] = "0" * 64
    if fault == "stage": del stage["staged_neural_selection_sha256"]
    if fault == "class": del metadata["class_files_sha256"]["model/spellbench/kit/xmage/JackDialogReplay.class"]
    if fault == "mode-class": del metadata["class_files_sha256"]["model/spellbench/kit/xmage/JackModeEncoder.class"]
    if fault == "named-class": del metadata["class_files_sha256"]["model/spellbench/kit/xmage/JackNamedChoices.class"]
    if fault == "target-class": del metadata["class_files_sha256"]["model/spellbench/kit/xmage/JackTargetEncoder.class"]
    if fault == "general-target-class": del metadata["class_files_sha256"]["model/spellbench/kit/xmage/JackGeneralTargetEncoder.class"]
    if fault == "card-set-class": del metadata["class_files_sha256"]["model/spellbench/kit/xmage/JackCardSetEncoder.class"]
    if fault == "parent-card-class": del metadata["class_files_sha256"]["model/spellbench/kit/xmage/JackParentCardEncoder.class"]
    (build / "BUILD.json").write_text(json.dumps(metadata), encoding="utf-8")
    monkeypatch.setattr(common, "verify_build", lambda *a: None)
    if fault is None:
        assert common.verify_model_build(build, runtime.sha(build / "BUILD.json"), engine, releases,
            architecture="jack-rl-april", jack_manifest=private) == metadata
    else:
        with pytest.raises(ValueError):
            common.verify_model_build(build, runtime.sha(build / "BUILD.json"), engine, releases,
                architecture="jack-rl-april", jack_manifest=private)


@pytest.mark.parametrize("fault", [None, "hold", "helper", "no-token", "free", "foreign", "outside", "test-root"])
def test_existing_host_guard_refuses_before_any_native_resource(tmp_path, monkeypatch, fault):
    hold = tmp_path / "priority-hold.json"
    if fault == "hold": hold.write_bytes(b'{"research":true}')
    args = SimpleNamespace(priority_hold=hold, host_guard=tmp_path / "helper.py", host_work_id="owned-check")
    calls = []
    monkeypatch.setattr(runtime, "sha", lambda p: "0" * 64 if fault == "helper" else runtime.HOST_GUARD_SHA256)
    monkeypatch.setenv("TEST_JOB_TOKEN", "owned")
    if fault == "no-token": monkeypatch.delenv("TEST_JOB_TOKEN")
    def status(token):
        calls.append(token)
        return {"state": "free" if fault == "free" else "held", "token_fate": "holds",
                "test_root": fault == "test-root", "host": "jack",
                "record": {"work_id": "foreign" if fault == "foreign" else "owned-check"}}
    guard = SimpleNamespace(TOKEN_ENV="TEST_JOB_TOKEN", HOST="jack", status=status,
                            job_members=lambda _: [] if fault == "outside" else [os.getpid()])
    spec = SimpleNamespace(loader=SimpleNamespace(exec_module=lambda module: None))
    monkeypatch.setattr(runtime.importlib.util, "spec_from_file_location", lambda *a: spec)
    monkeypatch.setattr(runtime.importlib.util, "module_from_spec", lambda *a: guard)
    if fault is None:
        runtime.require_guard(args); assert calls == ["owned"]
    else:
        with pytest.raises(ValueError): runtime.require_guard(args)
        if fault in ("hold", "helper", "no-token"): assert not calls


def test_identity_binds_pair_deck_profile_manifest_build_and_image(tmp_path, monkeypatch):
    manifest, _, _, _ = inputs(tmp_path, monkeypatch)
    params = (manifest, "policy", runtime.PROFILES[0], "b" * 64, IMAGE, 90)
    original = runtime.identity(*params)
    assert original == runtime.identity(*params) and original["identity"]["full_original_player_qualified"] is False
    assert runtime.identity(*params[:-1], 90.0) == original
    for index, value in ((2, runtime.PROFILES[1]), (3, "c" * 64), (4, "sha256:" + "d" * 64), (5, 30)):
        changed = list(params); changed[index] = value
        assert runtime.identity(*changed)["version"] != original["version"]
    manifest["assets"][0].pop("deck_id")
    with pytest.raises(ValueError, match="deck association"): runtime.identity(*params)


@pytest.mark.parametrize("fault", [None, "java-startup", "ready", "cleanup", "hold-after-first", "changed-java", "identity"])
def test_runtime_binds_game_and_command_and_cleans_only_owned_resources(tmp_path, monkeypatch, fault):
    manifest, context, _, _ = inputs(tmp_path, monkeypatch)
    manifest_path = tmp_path / "inputs.json"; manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    java, database = tmp_path / "java.exe", tmp_path / "cards.h2.mv.db"
    java.write_bytes(b"java"); database.write_bytes(b"database")
    args = ["--java", str(java), "--java-sha256", runtime.sha(java), "--engine", str(tmp_path / "engine"),
        "--model-build", str(tmp_path / "build"), "--model-build-sha256", "b" * 64,
        "--manifest", str(manifest_path), "--root", str(tmp_path), "--checkpoint", "policy", "--image", IMAGE,
        "--db-file", str(database), "--db-sha256", runtime.sha(database), "--work", str(tmp_path / "work"),
        "--host-guard", str(tmp_path / "guard.py"), "--host-work-id", "owned-check",
        "--priority-hold", str(tmp_path / "hold.json"), "--profile", runtime.PROFILES[0]]
    if fault == "identity": args.append("--print-identity")
    if fault == "changed-java": java.write_bytes(b"changed")
    monkeypatch.setattr(runtime, "verify_model_build", lambda *a, **k: {"dependency_sha256": {"math.jar": "a" * 64}})
    monkeypatch.setattr(runtime, "pinned_command", lambda *a: ["confined-opaque-test-peer"])
    guards, owners, peers, commands = [], [], [], []
    def guard(args):
        guards.append(args)
        if fault == "hold-after-first" and len(guards) > 2:
            raise ValueError("research priority resumed")
    monkeypatch.setattr(runtime, "require_guard", guard)
    class Owner:
        def __init__(self, *a, game_start, profile, seed, on_owned):
            self.start, self.profile, self.seed = copy.deepcopy(game_start), profile, seed
            self.closed = False; owners.append(self)
            on_owned("spellbench-xmage-" + str(len(owners)) * 32)
        def close(self): self.closed = True
    def peer(command, **options):
        commands.append(command)
        if fault == "java-startup": raise RuntimeError("JVM startup failed")
        value = SimpleNamespace(closed=False)
        value.close = lambda: setattr(value, "closed", True)
        peers.append(value); return value
    class Session:
        def __init__(self, peer, owner, **options):
            self.peer, self.owner = peer, owner
            self.start, self.profile, self.seed, self.checkpoint = owner.start, owner.profile, owner.seed, "policy"
            if fault == "ready": raise ValueError("readiness failed")
        def close(self): self.peer.close(); self.owner.close()
    monkeypatch.setattr(runtime, "JackNativeInferenceOwner", Owner)
    monkeypatch.setattr(runtime.wire, "SubprocessPeer", peer)
    monkeypatch.setattr(runtime, "JackNativeSession", Session)
    monkeypatch.setattr(runtime, "cleanup_container", lambda _: {"confirmed_absent": fault != "cleanup"})
    def serving(bot, **identity):
        start = game(); start["own_deck"] = context["own_deck"]
        start["hidden_engine_state"] = "forbidden"
        for _ in range(2):
            bot.on_game_start(GameStart.from_request(start))
            bot.on_game_over(GameOver.from_request({"game_id": "opaque", "terminal": {}}))
        return 0
    monkeypatch.setattr(runtime, "serve", serving)
    previous = Path.cwd()
    if fault in (None, "identity"):
        assert runtime.main(args) == 0
    else:
        with pytest.raises((ValueError, RuntimeError)): runtime.main(args)
    assert Path.cwd() == previous and all(owner.closed for owner in owners) and all(p.closed for p in peers)
    if fault in ("changed-java", "identity"):
        assert not guards and not owners and not (tmp_path / "work").exists()
    if owners:
        assert "hidden_engine_state" not in owners[0].start and "game_id" not in owners[0].start
    if commands:
        command = commands[0]
        assert command[-4:] == [runtime.PROFILES[0], "12", runtime.digest(owners[0].start), "90"]
        assert "spellbench.kit.xmage.JackOriginalBridgeMain" in command
        assert any(value.startswith("-Dspellbench.jack.embeddingFile=") for value in command)
    if fault == "cleanup": assert list((tmp_path / "work").glob("jack-original-agent-*"))
    elif fault not in ("changed-java", "identity"): assert not list((tmp_path / "work").glob("jack-original-agent-*"))
