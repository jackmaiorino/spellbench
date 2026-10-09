"""Print the fdn-draftzero-v1 entrant for the DraftZero FDN graph network from a finished build.

Every pinned input comes from observed files: the model build's BUILD.json and
class list, the release inputs, the frontend sources and the engine jars. Paths
are written with the board's placeholders, so the entry carries no local path.
This prepares a definition edit only; it runs nothing and rates nothing.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from xmage_gnn_backend import ARCHITECTURE  # noqa: E402
from xmage_gnn_runtime import SOURCES, identity  # noqa: E402
from xmage_neural_runtime import sha  # noqa: E402

JAVA_SHA256 = "5bee08593994e11c8679f4f0d951e6d199bd88b03f3723e794f6af6297bbd018"
DB_SHA256 = "fcdba7e7e5a0875d70380d8d99a5e776fe1eead630ef2a4d6c3340f9378919e3"


def entrant(*, build: Path, image: str, simulations: int, manifest_path: Path, engine: Path) -> dict:
    raw = manifest_path.read_bytes()
    manifest = json.loads(raw)
    build_sha = sha(build / "BUILD.json")
    meta = json.loads((build / "BUILD.json").read_bytes())
    if not meta.get("draftzero_gnn_stage"):
        raise ValueError("the entrant needs a model build with the graph network stage")
    descriptor = identity(simulations=simulations, build_sha256=build_sha, image=image, manifest_bytes=raw)
    config = manifest["inference_backends"][ARCHITECTURE]
    assets = {a["id"]: a for a in manifest["assets"]}
    release = [assets[config[key]]["filename"] for key in ("vocab", "config", "model")]
    inputs = ["${XMAGE_GNN_MODEL_BUILD}/BUILD.json"]
    # BUILD.json records platform-relative paths; the definition uses forward slashes.
    inputs += ["${XMAGE_GNN_MODEL_BUILD}/" + name for name in sorted(n.replace("\\", "/") for n in meta["class_files_sha256"])]
    inputs += ["${XMAGE_GNN_MODEL_BUILD}/kit/" + name for name in sorted(n.replace("\\", "/") for n in meta["resource_files_sha256"])]
    inputs += ["${XMAGE_GNN_ROOT}/" + name for name in release]
    inputs += ["${XMAGE_GNN_MANIFEST}", "${XMAGE_SEARCH_MATH}"]
    inputs += ["${XMAGE_GNN_SOURCE}/" + name for name in sorted(SOURCES) if name != "xmage_gnn_runtime.py"]
    inputs += ["${XMAGE_BUILD}/lib/" + p.name for p in sorted((engine / "lib").glob("*.jar"))]
    return {
        "name": descriptor["name"], "version": descriptor["version"], "type": "subprocess", "owner": "spellbench",
        "engine": "xmage", "training_style_tags": ["learned", "search", "pretrained", "imitation", "fair-variant"],
        "command": ["${PYTHON}", "${XMAGE_GNN_RUNTIME}", "--java", "${JAVA}", "--java-sha256", JAVA_SHA256,
                    "--engine", "${XMAGE_BUILD}", "--model-build", "${XMAGE_GNN_MODEL_BUILD}",
                    "--model-build-sha256", build_sha, "--manifest", "${XMAGE_GNN_MANIFEST}",
                    "--search-math", "${XMAGE_SEARCH_MATH}",
                    "--root", "${XMAGE_GNN_ROOT}", "--image", image, "--simulations", str(simulations),
                    "--db-file", "${XMAGE_DB}/cards.h2.mv.db", "--db-sha256", DB_SHA256,
                    "--work", "${XMAGE_AGENT_WORK}"],
        "checkpoint": "${XMAGE_GNN_ROOT}/" + assets[config["checkpoints"][0]]["filename"],
        "evaluation_inputs": inputs,
        "display": {
            "label": f"DraftZero FDN graph network, {simulations} sims",
            "author": "DraftZero / Spellbench",
            "description": (f"DraftZero's FDN graph network (MageZero NetGraph, trained on 17lands top-player games) with "
                            f"its released PIMC tree search at {simulations} simulations a decision. Fair variant: one "
                            "permitted sampled world, opponent hand hidden, confined CPU float32 inference."),
            "url": "https://huggingface.co/danbrooks/draftzero-fdn-gnn",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-build", type=Path, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--simulations", type=int, default=100)
    parser.add_argument("--manifest", type=Path, default=Path(__file__).resolve().parents[2] / "engines/xmage/releases.json")
    parser.add_argument("--engine", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(entrant(build=args.model_build, image=args.image, simulations=args.simulations,
                             manifest_path=args.manifest, engine=args.engine), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
