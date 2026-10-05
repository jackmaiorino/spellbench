"""Launch a deck-bound MageZero frontend under the guarded arena launcher.

Supply an external release manifest containing author weights and exact deck
evidence, plus every search setting. Weights remain opaque on this host.
"""
from __future__ import annotations

import argparse
import copy
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
from xmage_checkpoint_backend import cleanup_container, pinned_command
from xmage_magezero_agent import MageZeroAgent, profile
from xmage_magezero_bridge import BridgeSession
from xmage_magezero_search import validate_settings
from xmage_neural_decisions import InferenceSession
from xmage_neural_runtime import close_owned_runtime, sha, verify_model_build
from xmage_release_assets import prepare_root, validate_asset


def validate_inputs(manifest: dict, public: dict, checkpoint: str) -> dict:
    """Allow weights to extend the public pins without replacing their sources."""
    if (not isinstance(manifest, dict) or set(manifest) != set(public)
            or public.get("schema") != "spellbench-xmage-release-inputs/v1"
            or any(manifest[key] != public[key] for key in public if key not in ("assets", "inference_backends"))):
        raise ValueError("MageZero weights manifest changed its public source or schema pins")
    configs = manifest.get("inference_backends", {})
    original = public["inference_backends"]
    if set(configs) != set(original) or "magezero-v02" not in configs:
        raise ValueError("MageZero weights manifest changed its public architectures")
    config = configs["magezero-v02"]
    if (set(config) != set(original["magezero-v02"])
            or any(config[key] != original["magezero-v02"][key] for key in config if key != "checkpoints")
            or any(configs[name] != original[name] for name in configs if name != "magezero-v02")):
        raise ValueError("MageZero weights manifest changed its pinned encoder or backend")
    checkpoints = config["checkpoints"]
    if (not isinstance(checkpoints, list) or any(not isinstance(item, str) for item in checkpoints)
            or len(set(checkpoints)) != len(checkpoints) or checkpoint not in checkpoints
            or not set(original["magezero-v02"]["checkpoints"]).issubset(checkpoints)):
        raise ValueError("MageZero needs a registered, pinned checkpoint")
    entries = manifest.get("assets")
    if not isinstance(entries, list) or any(not isinstance(asset, dict) for asset in entries):
        raise ValueError("MageZero weights manifest needs pinned assets")
    for asset in entries:
        validate_asset(asset)
    assets = {asset["id"]: asset for asset in entries}
    baseline = {asset["id"]: asset for asset in public["assets"]}
    if (len(assets) != len(entries) or len({asset["filename"].lower() for asset in entries}) != len(entries)
            or any(assets.get(name) != asset for name, asset in baseline.items())
            or set(assets) - set(baseline) != set(checkpoints) - set(baseline)):
        raise ValueError("MageZero weights manifest replaced, aliased or added unregistered inputs")
    for name in checkpoints:
        asset = assets.get(name, {})
        if (asset.get("kind") != "checkpoint" or asset.get("checkpoint_format", "torch-gzip") not in
                ("torch", "torch-gzip", "magezero-mz")
                or not isinstance(asset.get("deck_id"), str)
                or re.fullmatch(r"sha256:[a-f0-9]{64}", asset["deck_id"]) is None
                or not isinstance(asset.get("deck_association_evidence"), str)
                or not asset["deck_association_evidence"].strip()):
            raise ValueError("MageZero checkpoint needs supported weights and an exact deck association")
        export = asset.get("export_metadata")
        if asset.get("checkpoint_format") == "magezero-mz":
            if (not isinstance(export, dict) or set(export) != {"deck", "version"}
                    or not isinstance(export["deck"], str) or not export["deck"].strip()
                    or len(export["deck"]) > 128 or type(export["version"]) is not int or export["version"] < 0):
                raise ValueError("MageZero export needs its pinned deck name and version")
        elif export is not None:
            raise ValueError("MageZero export metadata requires .mz weights")
    return copy.deepcopy(assets[checkpoint])


def identity(*, checkpoint, settings, build_sha256, image, manifest, public):
    asset = validate_inputs(manifest, public, checkpoint)
    settings = validate_settings(settings)
    if (not isinstance(build_sha256, str) or re.fullmatch(r"[a-f0-9]{64}", build_sha256) is None
            or not isinstance(image, str) or re.fullmatch(r"sha256:[a-f0-9]{64}", image) is None):
        raise ValueError("MageZero identity needs immutable build and confined image pins")
    config = manifest["inference_backends"]["magezero-v02"]
    assets = {entry["id"]: entry for entry in manifest["assets"]}
    bound = {"profile": profile(settings), "checkpoint": checkpoint,
             "checkpoint_sha256": asset["sha256"], "checkpoint_format": asset.get("checkpoint_format", "torch-gzip"),
             "deck_id": asset["deck_id"], "deck_association_evidence": asset["deck_association_evidence"],
             "export_metadata": asset.get("export_metadata"), "model_build_sha256": build_sha256, "image": image,
             "weights_manifest_sha256": hashlib.sha256(wire.canonical_json_dumps(manifest)).hexdigest(),
             "public_manifest_sha256": hashlib.sha256(wire.canonical_json_dumps(public)).hexdigest(),
             "model_source_sha256": assets[config["model"]]["sha256"],
             "vocab_source_sha256": assets[config["feature_vocab_code"]]["sha256"],
             "source_sha256": {name: sha(Path(__file__).with_name(name)) for name in (
                 "xmage_magezero_agent.py", "xmage_magezero_runtime.py", "xmage_magezero_bridge.py",
                 "xmage_magezero_search.py", "xmage_magezero_combat.py", "xmage_neural_agent.py",
                 "xmage_neural_runtime.py", "xmage_neural_rpc.py", "xmage_neural_search.py",
                 "xmage_neural_combat.py", "xmage_neural_decisions.py", "xmage_checkpoint_backend.py",
                 "xmage_release_assets.py")}}
    digest = hashlib.sha256(wire.canonical_json_dumps(bound)).hexdigest()
    return {"name": checkpoint + "-fair-search", "version": "magezero-v02-visible-v1-" + digest[:24], "identity": bound}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--java", type=Path, required=True)
    parser.add_argument("--java-sha256", required=True)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--model-build", type=Path, required=True)
    parser.add_argument("--model-build-sha256", required=True)
    parser.add_argument("--manifest", type=Path, required=True, help="external public manifest extended with author weights")
    parser.add_argument("--public-manifest", type=Path,
                        default=Path(__file__).resolve().parents[2] / "engines/xmage/releases.json")
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--db-file", type=Path, required=True)
    parser.add_argument("--db-sha256", required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--print-identity", action="store_true")
    args = parser.parse_args(argv)
    for key in ("java", "engine", "model_build", "manifest", "public_manifest", "settings", "root", "db_file", "work"):
        setattr(args, key, getattr(args, key).absolute())
    manifest, public = json.loads(args.manifest.read_bytes()), json.loads(args.public_manifest.read_bytes())
    settings = validate_settings(json.loads(args.settings.read_bytes()))
    descriptor = identity(checkpoint=args.checkpoint, settings=settings, build_sha256=args.model_build_sha256,
                          image=args.image, manifest=manifest, public=public)
    metadata = verify_model_build(args.model_build, args.model_build_sha256, args.engine, args.public_manifest,
                                  architecture="magezero-v02")
    if sha(args.java) != args.java_sha256 or sha(args.db_file) != args.db_sha256:
        raise ValueError("MageZero Java or database differs from its pin")
    # This validates opaque files and the no-network command before creating a
    # private database. InferenceSession rechecks them when each game starts.
    pinned_command(manifest, args.root, args.checkpoint, args.image, "serve")
    if args.print_identity:
        print(json.dumps(descriptor, indent=2))
        return 0
    work = prepare_root(args.work)
    directory = Path(tempfile.mkdtemp(prefix="magezero-agent-", dir=work)).resolve()
    previous, agent, owned = Path.cwd(), None, []
    try:
        (directory / "db").mkdir()
        database = directory / "db/cards.h2.mv.db"
        shutil.copyfile(args.db_file, database)
        if sha(database) != args.db_sha256:
            raise ValueError("private MageZero database copy differs")
        os.chdir(directory)
        cp = os.pathsep.join(str(args.model_build / name) for name in ("model", "core", "kit"))
        cp += os.pathsep + str(args.engine / "lib/*")
        cp += os.pathsep + next(iter(metadata["dependency_sha256"]))
        command = [str(args.java), "-Xmx1g", "-cp", cp, "spellbench.kit.xmage.MageZeroSearchBridgeMain"]

        def factory(context):
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
                model = InferenceSession(manifest, args.root, args.checkpoint, args.image, on_owned=record_owned,
                                         architecture="magezero-v02", game_start=context)
                peer = wire.SubprocessPeer(command, timeout_s=90)
                return BridgeSession(peer, model)
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

        agent = MageZeroAgent(factory, checkpoint=args.checkpoint, settings=settings, audit=audit)
        return serve(agent, name=descriptor["name"], version=descriptor["version"],
                     requires_observation=("passed_seats", "keywords"))
    finally:
        close_owned_runtime(agent, previous, work, directory, owned, failure=sys.exception(),
                            remove_container=cleanup_container)


if __name__ == "__main__":
    raise SystemExit(main())
