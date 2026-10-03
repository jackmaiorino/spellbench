"""Fetch the small pinned public Java inputs for model compilation in CI.

No checkpoints, private files or engine bundles are fetched. The 32 MiB input
cap and 1 GiB free-space reserve apply to the ephemeral CI input directory.
Local qualification retains the release manifest's existing storage limits.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from xmage_release_assets import fetch, prepare_root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    manifest = Path(__file__).resolve().parents[2] / "engines/xmage/releases.json"
    raw = manifest.read_bytes()
    assets = json.loads(raw)["assets"]
    encoder = {"draftzero-exp1-" + name for name in
               ("actionencoder", "featuremap", "features", "labeledstate", "stateencoder")}
    encoder |= {"magezero-v02-" + name for name in
                ("actionencoder", "featuremap", "features", "labeledstate", "stateencoder")}
    selected = [asset for asset in assets if asset["id"] in encoder
                or asset["id"].startswith(("draftzero-exp1-search-", "magezero-v02-search-"))]
    if encoder - {asset["id"] for asset in selected} or any(
            asset["kind"] != "source-code"
            and not (asset["id"] == "draftzero-exp1-search-commonsmath3" and asset["kind"] == "build-dependency")
            for asset in selected):
        raise ValueError("compile inputs must be the complete pinned public source set")
    root = prepare_root(args.root)
    storage = {"cap_bytes": 32 * 1024**2, "reserve_bytes": 1024**3}
    receipts = [fetch(root, asset, storage) for asset in selected]
    report = {"schema": "spellbench-draftzero-ci-inputs/v1",
              "input_manifest_sha256": hashlib.sha256(raw).hexdigest(),
              "assets": receipts, "storage": storage,
              "scope": "public source compilation; no checkpoints or qualification"}
    with (root / "CI-INPUTS.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"inputs": len(receipts), "bytes": sum(asset["bytes"] for asset in receipts)}))


if __name__ == "__main__":
    main()
