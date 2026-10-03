"""Stage the pinned MageZero v0.2 encoder in its own Java namespace.

The feature and action hash algorithms stay in their original source files.
Base-engine helpers support a priority slice with empty dialog history. This
does not qualify a complete MageZero player or a checkpoint.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from xmage_encoder_sources import REWRITES
from xmage_release_assets import prepare_root, verify

NAMES = ("ActionEncoder", "FeatureMap", "Features", "LabeledState", "StateEncoder")
PACKAGE = "spellbench.models.magezero.v02.encoder"
REVISION = "cb7e9c6fe2dcbe2f650a77dd98a87771e730f22f"


def stage(manifest: dict, root: Path, output: Path) -> dict:
    if manifest.get("schema") != "spellbench-xmage-release-inputs/v1":
        raise ValueError("unknown release input manifest")
    assets = {a["id"]: a for a in manifest["assets"]}
    if len(assets) != len(manifest["assets"]):
        raise ValueError("duplicate release input id")
    selected = [assets["magezero-v02-" + name.lower()] for name in NAMES]
    root = prepare_root(root)
    sources = {}
    edits = {}
    for name, asset in zip(NAMES, selected):
        if asset.get("source_revision") != REVISION or asset.get("kind") != "source-code":
            raise ValueError("MageZero encoder needs its pinned v0.2 source revision")
        verify(root / asset["filename"], asset)
        text = (root / asset["filename"]).read_text(encoding="utf-8")
        filename = name + ".java"
        rewrites = {"package mage.player.ai.encoder;": "package " + PACKAGE + ";",
                    **REWRITES.get(filename, {})}
        for before, after in rewrites.items():
            if before not in text:
                raise ValueError("pinned source lacks the declared compatibility edit")
            text = text.replace(before, after)
        sources[filename] = text.encode("utf-8")
        edits[filename] = rewrites
    if output.exists():
        raise ValueError("MageZero source output must be a new job directory")
    output = prepare_root(output)
    hashes = {}
    for filename, data in sources.items():
        with (output / filename).open("xb") as stream:
            stream.write(data)
        hashes[filename] = hashlib.sha256(data).hexdigest()
    result = {"schema": "spellbench-magezero-encoder-stage/v1", "source_revision": REVISION,
              "java_package": PACKAGE, "staged_source_sha256": hashes, "rewrites": edits,
              "feature_hash_bins": 2147483647, "policy_width": 128,
              "scope": "priority encoder slice; empty dialog history; no checkpoint or full player qualification"}
    with (output / "STAGE.json").open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    return result
