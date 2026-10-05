"""Serve the original Jack frontend inside an existing guarded native job.

The supported arena launcher owns throughput/placement and working-copy storage
qualification. This entry requires its existing host reservation and containment
before any database copy, JVM startup or confined checkpoint execution.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

from spellbench import wire
from spellbench.bot import serve
from xmage_checkpoint_backend import cleanup_container, pinned_command
from xmage_jack_inference import encoding
from xmage_jack_native_agent import JackNativeAgent
from xmage_jack_native_inference import JackNativeInferenceOwner, PROFILES
from xmage_jack_native_session import JackNativeSession, digest
from xmage_neural_runtime import sha, verify_model_build
from xmage_release_assets import is_link, prepare_root, validate_asset, verify

HOST_GUARD_SHA256 = "a736f9cc617db898aba1b150eb92193cae80dd500cbd5419a6e0867eeb5a9570"


def require_guard(args):
    # Do not even query host availability while the explicit research hold exists.
    if args.priority_hold.exists():
        raise ValueError("research priority holds native execution until explicit handback")
    if sha(args.host_guard) != HOST_GUARD_SHA256:
        raise ValueError("original runtime needs the existing pinned host reservation helper")
    spec = importlib.util.spec_from_file_location("jack_runtime_host_guard", args.host_guard)
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    token = os.environ.get(guard.TOKEN_ENV)
    if not token:
        raise ValueError("original runtime requires an existing guarded native job")
    status = guard.status(token)
    if (status.get("state") != "held" or status.get("token_fate") != "holds"
            or status.get("test_root") is not False or status.get("host") != guard.HOST
            or status.get("record", {}).get("work_id") != args.host_work_id
            or os.getpid() not in guard.job_members(None)):
        raise ValueError("original runtime is outside its declared guarded native job")


def identity(manifest, checkpoint, profile, build_sha256, image, idle_seconds):
    if (profile not in PROFILES or re.fullmatch("[a-f0-9]{64}", build_sha256) is None
            or re.fullmatch("sha256:[a-f0-9]{64}", image) is None
            or type(idle_seconds) not in (int, float) or not math.isfinite(idle_seconds)
            or not 0 < idle_seconds <= 86400):
        raise ValueError("original runtime needs pinned identity and a bounded idle clock")
    for asset in manifest["assets"]:
        validate_asset(asset)
    features, ready = encoding(manifest, checkpoint)
    assets = {asset["id"]: asset for asset in manifest["assets"]}
    policy = assets[checkpoint]
    if (re.fullmatch("sha256:[a-f0-9]{64}", policy.get("deck_id", "")) is None
            or not isinstance(policy.get("deck_association_evidence"), str)
            or not policy["deck_association_evidence"].strip()):
        raise ValueError("original runtime requires its exact checkpoint/deck association")
    bound = {"checkpoint": checkpoint, "profile": profile, "encoding": features,
             "paired_inference_identity": ready, "deck_id": policy["deck_id"],
             "deck_association_evidence": policy["deck_association_evidence"],
             "model_build_sha256": build_sha256, "image": image,
             "idle_seconds": format(idle_seconds, ".17g"), "private_manifest_sha256": digest(manifest),
             "source_sha256": {name: sha(Path(__file__).with_name(name)) for name in (
                 "xmage_jack_native_runtime.py", "xmage_jack_native_agent.py", "xmage_jack_native_session.py",
                 "xmage_jack_native_inference.py", "xmage_jack_inference.py", "xmage_checkpoint_backend.py",
                 "xmage_neural_runtime.py", "xmage_neural_agent.py", "xmage_release_assets.py")},
             "full_original_player_qualified": False}
    return {"name": checkpoint + "-" + profile, "version": "jack-original-visible-v1-" + digest(bound)[:24],
            "identity": bound}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("java", "engine", "model-build", "manifest", "root", "db-file", "work",
                 "host-guard", "priority-hold"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("java-sha256", "model-build-sha256", "checkpoint", "image", "db-sha256", "host-work-id"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--public-manifest", type=Path,
                        default=Path(__file__).resolve().parents[2] / "engines/xmage/releases.json")
    parser.add_argument("--profile", choices=PROFILES, required=True)
    parser.add_argument("--idle-seconds", type=float, default=90)
    parser.add_argument("--print-identity", action="store_true")
    args = parser.parse_args(argv)
    for name in ("java", "engine", "model_build", "manifest", "public_manifest", "root", "db_file",
                 "work", "host_guard", "priority_hold"):
        setattr(args, name, getattr(args, name).absolute())
    manifest = json.loads(args.manifest.read_bytes())
    descriptor = identity(manifest, args.checkpoint, args.profile, args.model_build_sha256, args.image, args.idle_seconds)
    metadata = verify_model_build(args.model_build, args.model_build_sha256, args.engine, args.public_manifest,
                                  architecture="jack-rl-april", jack_manifest=args.manifest)
    if sha(args.java) != args.java_sha256 or sha(args.db_file) != args.db_sha256:
        raise ValueError("original runtime Java or database differs from its pin")
    pinned_command(manifest, args.root, args.checkpoint, args.image, "serve")
    config = manifest["inference_backends"]["jack-rl-april"]
    assets = {asset["id"]: asset for asset in manifest["assets"]}
    cache = assets[assets[args.checkpoint].get("embedding_cache", config.get("embedding_cache"))]
    embeddings = args.root / cache["filename"]
    verify(embeddings, cache)
    if args.print_identity:
        print(json.dumps(descriptor, indent=2))
        return 0
    require_guard(args)
    work = prepare_root(args.work)
    directory = Path(tempfile.mkdtemp(prefix="jack-original-agent-", dir=work)).resolve()
    previous, agent, owned = Path.cwd(), None, []
    try:
        (directory / "db").mkdir()
        database = directory / "db/cards.h2.mv.db"
        shutil.copyfile(args.db_file, database)
        if sha(database) != args.db_sha256:
            raise ValueError("private original-player database copy differs")
        os.chdir(directory)
        cp = os.pathsep.join(str(args.model_build / name) for name in ("model", "core", "kit"))
        cp += os.pathsep + str(args.engine / "lib/*") + os.pathsep + next(iter(metadata["dependency_sha256"]))

        def record_owned(container):
            with (work / (container + ".owned.json")).open("x", encoding="utf-8") as record:
                json.dump({"schema": "spellbench-owned-model-container/v1", "container": container,
                           "creator_pid": os.getpid(), "work_directory": str(directory)}, record)
                record.write("\n"); record.flush(); os.fsync(record.fileno())
            owned.append(container)

        def factory(start):
            require_guard(args)
            owner = peer = None
            try:
                owner = JackNativeInferenceOwner(manifest, args.root, args.checkpoint, args.image,
                    game_start=start, profile=args.profile, seed=start["agent_seed"], on_owned=record_owned)
                command = [str(args.java), "-Xmx1g", "-Dspellbench.jack.embeddingFile=" + str(embeddings),
                    "-Dspellbench.jack.embeddingSha256=" + cache["sha256"], "-cp", cp,
                    "spellbench.kit.xmage.JackOriginalBridgeMain", args.profile, str(start["agent_seed"]),
                    digest(start), format(args.idle_seconds, ".17g")]
                peer = wire.SubprocessPeer(command, timeout_s=90)
                return JackNativeSession(peer, owner, startup_s=90)
            except BaseException as failure:
                for resource in (peer, owner):
                    if resource is not None:
                        try: resource.close()
                        except BaseException as cleanup: failure.add_note("Original startup cleanup failed: " + str(cleanup))
                raise

        def audit(event):
            print(json.dumps(event, separators=(",", ":"), allow_nan=False), file=sys.stderr, flush=True)
        agent = JackNativeAgent(factory, checkpoint=args.checkpoint, profile=args.profile, audit=audit)
        return serve(agent, name=descriptor["name"], version=descriptor["version"],
                     requires_observation=("passed_seats", "keywords"))
    finally:
        failure, errors = sys.exception(), []
        try:
            if agent is not None: agent.close()
        except BaseException as error: errors.append(error)
        finally: os.chdir(previous)
        for container in owned:
            try:
                cleanup = cleanup_container(container)
                with (work / (container + ".cleanup.json")).open("x", encoding="utf-8") as record:
                    json.dump({"container": container, **cleanup}, record); record.write("\n")
                if cleanup.get("confirmed_absent") is not True:
                    raise RuntimeError("owned original container remains; work directory retained")
            except BaseException as error: errors.append(error)
        if not errors:
            try:
                if directory.parent != work or any(is_link(path) for path in (directory, *directory.rglob("*"))):
                    raise ValueError("owned original directory changed or contains a link; retained")
                shutil.rmtree(directory)
            except BaseException as error: errors.append(error)
        if errors:
            if failure is not None:
                for error in errors: failure.add_note("Original runtime cleanup failed: " + str(error))
            else:
                for error in errors[1:]: errors[0].add_note(str(error))
                raise errors[0]


if __name__ == "__main__":
    raise SystemExit(main())
