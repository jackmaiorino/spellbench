"""Verify and launch the public Exp1 frontend with its own JVM and confined model.

Use this command under the arena's guarded job launcher. The caller's storage
manifest must include both engine and agent working database copies.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path, PurePosixPath

from spellbench import wire
from spellbench.bot import serve
from xmage_checkpoint_backend import cleanup_container
from xmage_neural_agent import NeuralAgent, PROFILE
from xmage_neural_bridge import BridgeSession
from xmage_exp1_play import PROFILE_NAME, PublishedAgent, PublishedSession, profile as published_profile
from xmage_neural_decisions import InferenceSession
from xmage_release_assets import is_link, prepare_root, verify
from xmage_verified_entry import verify_build

REVIEWED_ENGINE = "3b54f3f66cbb135b55dcc19cac5d310447ca78017d1309db05a4d530030c9d93"


def sha(path):
    if is_link(path) or not path.is_file():
        raise ValueError("runtime input must be a regular file")
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def relative_files(declared):
    if not isinstance(declared, dict) or not declared:
        raise ValueError("model build has no pinned runtime files")
    normalized = {}
    for name, digest in declared.items():
        if not isinstance(name, str):
            raise ValueError("model runtime manifest path must be text")
        # BUILD.json records Path-relative strings on its build platform.
        # Accept Windows separators while checking the same relative tree.
        name = name.replace("\\", "/")
        relative = PurePosixPath(name)
        if (":" in name or relative.is_absolute() or name in normalized
                or ".." in relative.parts or name != relative.as_posix()):
            raise ValueError("model runtime manifest path escapes its build")
        normalized[name] = digest
    return normalized


def checked_tree(root, declared, *, suffix=None):
    declared = relative_files(declared)
    for name, digest in declared.items():
        path = root / name
        if any(is_link(parent) for parent in (path, *path.parents)):
            raise ValueError("model runtime path traverses a link")
        if path.resolve().is_relative_to(root.resolve()) is False or sha(path) != digest:
            raise ValueError("model runtime file differs from its build pin")
    if suffix is not None:
        actual = {p.relative_to(root).as_posix() for p in root.rglob("*" + suffix)}
        if actual != set(declared):
            raise ValueError("model classpath has missing or undeclared classes")


def verify_model_build(build: Path, digest: str, engine: Path, releases: Path, *, architecture="draftzero-exp1",
                       play_profile="minimum-visits-diagnostic", jack_manifest=None):
    if sha(build / "BUILD.json") != digest:
        raise ValueError("model build manifest changed")
    metadata = json.loads((build / "BUILD.json").read_bytes())
    if (metadata.get("schema") != "spellbench-draftzero-encoder-build/v1"
            or metadata.get("engine_manifest_sha256") != REVIEWED_ENGINE
            or metadata.get("inputs_manifest_sha256") != sha(releases)
            or metadata.get("jdk") != "javac 23.0.1"):
        raise ValueError("model runtime needs the reviewed, pinned original search build")
    if architecture == "draftzero-exp1":
        required_stages = ("search_stage",)
    elif architecture == "magezero-v02":
        required_stages = ("magezero_stage", "magezero_search_stage")
    elif architecture == "jack-rl-april":
        required_stages = ("search_stage", "jack_stage")
        from xmage_jack_sources import CALLBACK_SHA256, ENCODER_SHA256, MULLIGAN_JAVA_SHA256
        stage = metadata.get("jack_stage")
        if (jack_manifest is None or metadata.get("jack_inputs_manifest_sha256") != sha(jack_manifest)
                or not isinstance(stage, dict) or stage.get("original_source_sha256") != ENCODER_SHA256
                or stage.get("original_callback_sha256") != CALLBACK_SHA256
                or stage.get("original_mulligan_encoder_sha256") != MULLIGAN_JAVA_SHA256
                or any(not isinstance(stage.get(key), str) or re.fullmatch("[a-f0-9]{64}", stage[key]) is None for key in (
                    "staged_callback_player_sha256", "staged_priority_choice_player_sha256",
                    "staged_neural_selection_sha256", "staged_priority_rules_sha256",
                    "staged_activation_player_sha256", "staged_parent_mana_player_sha256",
                    "staged_parent_dialog_player_sha256"))):
            raise ValueError("Jack runtime needs its complete original player and private manifest pins")
    else:
        raise ValueError("unsupported model runtime architecture")
    if any(not metadata.get(stage) for stage in required_stages):
        raise ValueError("model runtime lacks its pinned architecture and search stages")
    verify_build(engine, engine / "BUILD-MANIFEST.json", REVIEWED_ENGINE)
    classes = relative_files(metadata.get("class_files_sha256"))
    if (not classes or any(not name.startswith(("core/", "kit/", "model/")) or not name.endswith(".class")
                          for name in classes)):
        raise ValueError("model runtime class directories differ")
    if play_profile != "minimum-visits-diagnostic":
        if (architecture != "draftzero-exp1" or play_profile != PROFILE_NAME
                or "model/spellbench/models/exp1/PlaySettings.class" not in classes):
            raise ValueError("model runtime lacks the supported published Exp1 play settings")
    if architecture == "magezero-v02" and not {
            "model/spellbench/kit/xmage/MageZeroSearchMain.class",
            "model/spellbench/kit/xmage/MageZeroSearchCombatMain.class",
            "model/spellbench/kit/xmage/MageZeroSearchBridgeMain.class"}.issubset(classes):
        raise ValueError("MageZero runtime lacks its mixed search and combat entrypoints")
    if architecture == "jack-rl-april":
        required = {"model/spellbench/models/jack/" + name + ".class" for name in (
            "OriginalCallbackPlayer", "OriginalPriorityChoicePlayer", "OriginalNeuralSelection",
            "OriginalActivationPlayer", "OriginalParentManaPlayer", "OriginalParentDialogsPlayer",
            "StateSequenceBuilder", "CandidateEncoder", "MulliganEncoder", "PriorityRules",
            "DialogRules", "ModeRules", "TargetRules", "CardSetRules", "CombatRules", "LondonRules")}
        required |= {"model/spellbench/kit/xmage/" + name + ".class" for name in (
            "JackOriginalBridgeMain", "JackRootDecision", "JackPriorityState", "JackDialogReplay",
            "JackDialogEncoder", "JackInheritedChoices", "JackTriggerOrder", "JackLibraryOrder", "JackTargetAmount", "JackModeEncoder", "JackNamedChoices", "JackTargetEncoder", "JackGeneralTargetEncoder",
            "JackCardSetEncoder", "JackParentCardEncoder", "JackLondonPlan", "JackCombatPlan",
            "JackInferenceChannel", "JackPermittedWorlds", "JackPlayerBootstrap", "JackReplayOpponent", "JackReplayKnowledge", "ModelReplay")}
        if not required.issubset(classes):
            raise ValueError("Jack runtime lacks its complete original callback and serving classes")
    checked_tree(build, classes, suffix=".class")
    resources = relative_files(metadata.get("resource_files_sha256"))
    checked_tree(build / "kit", resources)
    actual = set()
    for directory in (build / "core", build / "kit", build / "model"):
        for path in (directory, *directory.rglob("*")):
            if is_link(path):
                raise ValueError("model class directory contains a link")
            if path.is_file():
                actual.add(path.relative_to(build).as_posix())
    if actual != set(classes) | {"kit/" + name for name in resources}:
        raise ValueError("model classpath has undeclared runtime resources")
    dependencies = metadata.get("dependency_sha256")
    if not isinstance(dependencies, dict) or len(dependencies) != 1:
        raise ValueError("original search needs its one pinned Commons Math dependency")
    for name, digest in dependencies.items():
        if sha(Path(name)) != digest:
            raise ValueError("original search dependency changed")
    return metadata


def selected_visits(play_profile, visits):
    if play_profile == PROFILE_NAME:
        if visits is not None and (type(visits) is not int or visits != 96):
            raise ValueError("published Exp1 play requires its released 96-visit budget")
        return 96
    if play_profile != "minimum-visits-diagnostic":
        raise ValueError("unsupported Exp1 play profile")
    visits = 1000 if visits is None else visits
    if type(visits) is not int or not 2 <= visits <= 1000:
        raise ValueError("Exp1 diagnostic visit budget must be 2..1000")
    return visits


def identity(*, checkpoint, visits, build_sha256, image, manifest, play_profile="minimum-visits-diagnostic"):
    visits = selected_visits(play_profile, visits)
    config = manifest["inference_backends"]["draftzero-exp1"]
    if checkpoint not in config["checkpoints"] or type(visits) is not int or not 2 <= visits <= 1000:
        raise ValueError("neural identity needs a pinned Exp1 checkpoint and visit count")
    assets = {a["id"]: a for a in manifest["assets"]}
    published = play_profile == PROFILE_NAME
    bound = {"profile": published_profile() if published else PROFILE, "checkpoint": checkpoint, "visits": visits,
             "checkpoint_sha256": assets[checkpoint]["sha256"], "model_build_sha256": build_sha256,
             "image": image,
             "source_sha256": {name: sha(Path(__file__).with_name(name)) for name in
                               ("xmage_neural_agent.py", "xmage_neural_runtime.py", "xmage_neural_rpc.py",
                                "xmage_neural_bridge.py", "xmage_neural_search.py", "xmage_neural_combat.py",
                                "xmage_neural_decisions.py", "xmage_checkpoint_backend.py")}}
    if published:
        bound["source_sha256"]["xmage_exp1_play.py"] = sha(Path(__file__).with_name("xmage_exp1_play.py"))
        bound["source_sha256"]["engines/xmage/draftzero-published-play.json"] = sha(
            Path(__file__).resolve().parents[2] / "engines/xmage/draftzero-published-play.json")
    digest = hashlib.sha256(wire.canonical_json_dumps(bound)).hexdigest()
    return {"name": checkpoint + ("-published-final-eval-fair" if published else "-fair-search"),
            "version": ("exp1-published-fair-v1-" if published else "exp1-visible-v1-") + digest[:24], "identity": bound}


def close_owned_runtime(agent, previous, work, directory, owned, *, failure=None, remove_container=None):
    remove_container = cleanup_container if remove_container is None else remove_container
    errors = []
    try:
        if agent is not None:
            agent.close()
    except BaseException as error:
        errors.append(error)
    finally:
        os.chdir(previous)
    for container in owned:
        try:
            cleanup = remove_container(container)
            with (work / (container + ".cleanup.json")).open("x", encoding="utf-8") as record:
                json.dump({"container": container, **cleanup}, record)
                record.write("\n")
            if cleanup.get("confirmed_absent") is not True:
                raise RuntimeError("owned model container remains; work directory retained")
        except BaseException as error:
            errors.append(error)
    if not errors:
        try:
            if directory.parent != work or is_link(directory):
                raise ValueError("owned model work directory changed; retained for inspection")
            if any(is_link(path) for path in directory.rglob("*")):
                raise ValueError("owned model directory contains a link; retained for inspection")
            shutil.rmtree(directory)
        except BaseException as error:
            errors.append(error)
    if errors:
        if failure is not None:
            for error in errors:
                failure.add_note("Model runtime cleanup failed: " + str(error))
        else:
            for error in errors[1:]:
                errors[0].add_note(str(error))
            raise errors[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--java", type=Path, required=True)
    parser.add_argument("--java-sha256", required=True)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--model-build", type=Path, required=True)
    parser.add_argument("--model-build-sha256", required=True)
    parser.add_argument("--manifest", type=Path, default=Path(__file__).resolve().parents[2] / "engines/xmage/releases.json")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--db-file", type=Path, required=True)
    parser.add_argument("--db-sha256", required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--play-profile", choices=("minimum-visits-diagnostic", PROFILE_NAME),
                        default="minimum-visits-diagnostic")
    parser.add_argument("--visits", type=int, help="diagnostic default 1000; published profile requires 96")
    parser.add_argument("--print-identity", action="store_true")
    args = parser.parse_args()
    args.visits = selected_visits(args.play_profile, args.visits)
    for key in ("java", "engine", "model_build", "manifest", "root", "db_file", "work"):
        setattr(args, key, getattr(args, key).absolute())
    manifest = json.loads(args.manifest.read_bytes())
    metadata = verify_model_build(args.model_build, args.model_build_sha256, args.engine, args.manifest,
                                  play_profile=args.play_profile)
    if sha(args.java) != args.java_sha256 or sha(args.db_file) != args.db_sha256:
        raise ValueError("model runtime Java or database differs from its pin")
    descriptor = identity(checkpoint=args.checkpoint, visits=args.visits, build_sha256=args.model_build_sha256,
                          image=args.image, manifest=manifest, play_profile=args.play_profile)
    config = manifest["inference_backends"]["draftzero-exp1"]
    assets = {a["id"]: a for a in manifest["assets"]}
    vocab = args.root / assets[config["action_vocab"]]["filename"]
    verify(vocab, assets[config["action_vocab"]])
    if args.print_identity:
        print(json.dumps(descriptor, indent=2))
        return 0
    work = prepare_root(args.work)
    directory = Path(tempfile.mkdtemp(prefix="exp1-agent-", dir=work)).resolve()
    previous = Path.cwd()
    agent = None
    owned = []
    try:
        (directory / "db").mkdir()
        database = directory / "db/cards.h2.mv.db"
        shutil.copyfile(args.db_file, database)
        if sha(database) != args.db_sha256:
            raise ValueError("private model database copy differs")
        os.chdir(directory)
        cp = os.pathsep.join(str(args.model_build / name) for name in ("model", "core", "kit"))
        cp += os.pathsep + str(args.engine / "lib/*")
        cp += os.pathsep + next(iter(metadata["dependency_sha256"]))
        command = [str(args.java), "-Xmx1g", "-Dmz.actionVocab=" + str(vocab), "-cp", cp,
                   "spellbench.kit.xmage.ModelBridgeMain"]

        def factory():
            model = peer = None
            try:
                def record_owned(container):
                    with (work / (container + ".owned.json")).open("x", encoding="utf-8") as record:
                        json.dump({"schema": "spellbench-owned-model-container/v1", "container": container,
                                   "creator_pid": os.getpid(), "work_directory": str(directory)}, record)
                        record.write("\n")
                        record.flush()
                        os.fsync(record.fileno())
                    owned.append(container)
                model = InferenceSession(manifest, args.root, args.checkpoint, args.image, on_owned=record_owned)
                peer = wire.SubprocessPeer(command, timeout_s=90)
                return (PublishedSession(peer, model) if args.play_profile == PROFILE_NAME else BridgeSession(peer, model))
            except BaseException:
                try:
                    if peer is not None:
                        peer.close()
                finally:
                    if model is not None:
                        model.close()
                raise

        def audit(event):
            print(json.dumps(event, separators=(",", ":"), allow_nan=False), file=sys.stderr, flush=True)

        agent = (PublishedAgent(factory, checkpoint=args.checkpoint, audit=audit) if args.play_profile == PROFILE_NAME
                 else NeuralAgent(factory, checkpoint=args.checkpoint, visits=args.visits, audit=audit))
        return serve(agent, name=descriptor["name"], version=descriptor["version"],
                     requires_observation=("passed_seats", "keywords"))
    finally:
        close_owned_runtime(agent, previous, work, directory, owned, failure=sys.exception())


if __name__ == "__main__":
    raise SystemExit(main())
