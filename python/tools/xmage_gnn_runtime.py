"""Launch the DraftZero FDN graph network frontend under the guarded arena launcher.

The release weights and network code stay opaque on this host: they load only
in the no-network `gnn` image. The bot version binds the release inputs, the
played search settings with this entrant's simulation count, the model build,
the image and these frontend sources.
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
from pathlib import Path

from spellbench import wire
from spellbench.bot import serve
from xmage_checkpoint_backend import cleanup_container
from xmage_gnn_backend import ARCHITECTURE, pinned_command
from xmage_gnn_model import GraphInference
from xmage_gnn_search import BridgeSession, GraphAgent, played_settings, profile
from xmage_neural_decisions import close_resources
from xmage_neural_runtime import close_owned_runtime, sha, verify_model_build
from xmage_release_assets import prepare_root

SOURCES = ("xmage_gnn_runtime.py", "xmage_gnn_search.py", "xmage_gnn_model.py", "xmage_gnn_backend.py",
           "xmage_neural_agent.py", "xmage_neural_runtime.py", "xmage_neural_rpc.py", "xmage_neural_search.py",
           "xmage_neural_combat.py", "xmage_neural_decisions.py", "xmage_checkpoint_backend.py",
           "xmage_release_assets.py", "xmage_draftzero_gnn_sources.py")


def identity(*, simulations, build_sha256, image, manifest_bytes):
    settings = played_settings(simulations)
    manifest = json.loads(manifest_bytes)
    if (not isinstance(build_sha256, str) or re.fullmatch(r"[a-f0-9]{64}", build_sha256) is None
            or not isinstance(image, str) or re.fullmatch(r"sha256:[a-f0-9]{64}", image) is None):
        raise ValueError("graph network identity needs immutable build and confined image pins")
    config = manifest["inference_backends"][ARCHITECTURE]
    assets = {entry["id"]: entry for entry in manifest["assets"]}
    checkpoint = config["checkpoints"][0]
    bound = {"profile": profile(settings), "checkpoint": checkpoint,
             "release_revision": manifest["sources"]["draftzero_gnn_weights"]["revision"],
             "input_sha256": {key: assets[config[key] if key != "checkpoint" else checkpoint]["sha256"]
                              for key in ("checkpoint", "vocab", "config", "model")},
             "source_assets_sha256": {aid: assets[aid]["sha256"] for aid in
                                      config["encoder_source_assets"] + config["search_source_assets"]},
             "model_build_sha256": build_sha256, "image": image,
             "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
             "source_sha256": {name: sha(Path(__file__).with_name(name)) for name in SOURCES}}
    digest = hashlib.sha256(wire.canonical_json_dumps(bound)).hexdigest()
    return {"name": f"draftzero-fdn-gnn-{simulations}-fair", "version": "draftzero-gnn-pimc-v1-" + digest[:24],
            "identity": bound}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--java", type=Path, required=True)
    parser.add_argument("--java-sha256", required=True)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--model-build", type=Path, required=True)
    parser.add_argument("--model-build-sha256", required=True)
    parser.add_argument("--manifest", type=Path,
                        default=Path(__file__).resolve().parents[2] / "engines/xmage/releases.json")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--simulations", type=int, required=True)
    parser.add_argument("--db-file", type=Path, required=True)
    parser.add_argument("--db-sha256", required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--print-identity", action="store_true")
    args = parser.parse_args(argv)
    for key in ("java", "engine", "model_build", "manifest", "root", "db_file", "work"):
        setattr(args, key, getattr(args, key).absolute())
    raw = args.manifest.read_bytes()
    manifest = json.loads(raw)
    settings = played_settings(args.simulations)
    descriptor = identity(simulations=args.simulations, build_sha256=args.model_build_sha256,
                          image=args.image, manifest_bytes=raw)
    metadata = verify_model_build(args.model_build, args.model_build_sha256, args.engine, args.manifest,
                                  architecture=ARCHITECTURE)
    if sha(args.java) != args.java_sha256 or sha(args.db_file) != args.db_sha256:
        raise ValueError("graph network Java or database differs from its pin")
    # Validate the opaque release files and the no-network command before any game.
    pinned_command(manifest, args.root, args.image, "serve")
    if args.print_identity:
        print(json.dumps(descriptor, indent=2))
        return 0
    work = prepare_root(args.work)
    directory = Path(tempfile.mkdtemp(prefix="draftzero-gnn-agent-", dir=work)).resolve()
    previous, agent, owned = Path.cwd(), None, []
    try:
        (directory / "db").mkdir()
        database = directory / "db/cards.h2.mv.db"
        shutil.copyfile(args.db_file, database)
        if sha(database) != args.db_sha256:
            raise ValueError("private graph network database copy differs")
        os.chdir(directory)
        cp = os.pathsep.join(str(args.model_build / name) for name in ("model", "core", "kit"))
        cp += os.pathsep + str(args.engine / "lib/*")
        cp += os.pathsep + next(iter(metadata["dependency_sha256"]))
        command = [str(args.java), "-Xmx1g", "-cp", cp, "spellbench.kit.xmage.GnnBridgeMain"]

        def audit(event):
            print(json.dumps(event, separators=(",", ":"), allow_nan=False), file=sys.stderr, flush=True)

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
                model = GraphInference(manifest, args.root, args.image, on_owned=record_owned, on_close=audit)
                peer = wire.SubprocessPeer(command, timeout_s=90)
                return BridgeSession(peer, model)
            except BaseException as failure:
                close_resources(peer, model, failure=failure)
                raise

        agent = GraphAgent(factory, checkpoint=manifest["inference_backends"][ARCHITECTURE]["checkpoints"][0],
                           settings=settings, audit=audit)
        return serve(agent, name=descriptor["name"], version=descriptor["version"],
                     requires_observation=("passed_seats", "keywords"))
    finally:
        close_owned_runtime(agent, previous, work, directory, owned, failure=sys.exception(),
                            remove_container=cleanup_container)


if __name__ == "__main__":
    raise SystemExit(main())
