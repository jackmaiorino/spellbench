"""Stage MageZero v0.2's actual search with the audited core compatibility recipe.

Only pinned public source bytes are read. The separate namespace and original
128-slot visit labels prevent an Exp1 policy from being substituted for MageZero.
This prepares the tree implementation; it does not qualify a playing adapter.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from xmage_search_sources import NAMES, stage as stage_compatibility

NAMESPACE = "spellbench.models.magezero.v02.search"
ENCODER = "spellbench.models.magezero.v02.encoder"
REVISION = "cb7e9c6fe2dcbe2f650a77dd98a87771e730f22f"


def stage(manifest: dict, root: Path, output: Path) -> dict:
    if manifest.get("sources", {}).get("magezero_engine_v02", {}).get("revision") != REVISION:
        raise ValueError("MageZero search requires the pinned v0.2 engine source")
    assets = {asset["id"]: asset for asset in manifest["assets"]}
    names = (*NAMES, "PlayerImpl", "GameImpl", "RemoteModelEvaluator")
    selected = [assets["magezero-v02-search-" + name.lower()] for name in names]
    for asset in selected:
        if asset.get("source_revision") != REVISION or asset.get("kind") != "source-code":
            raise ValueError("MageZero search source association differs")
    # The same core edits apply to these independently pinned original bytes.
    # These aliases are internal recipe parameters, never checkpoint aliases.
    recipe = copy.deepcopy(manifest)
    recipe["sources"]["draftzero_engine_exp1"] = copy.deepcopy(recipe["sources"]["magezero_engine_v02"])
    recipe["assets"] = [dict(asset, id="draftzero-exp1-search-" + name.lower())
                        for name, asset in zip(names, selected)]
    result = stage_compatibility(recipe, root, output)
    rewrites = {"spellbench.models.exp1": NAMESPACE,
                "import mage.player.ai.encoder.ActionEncoder;": "import " + ENCODER + ".ActionEncoder;",
                "import mage.player.ai.encoder.StateEncoder;": "import " + ENCODER + ".StateEncoder;",
                "// Pinned Exp1 source, XMage MIT.": "// Pinned MageZero v0.2 source, XMage MIT."}
    for path in sorted(output.glob("*.java")):
        text = path.read_text(encoding="utf-8")
        changes = []
        for before, after in rewrites.items():
            count = text.count(before)
            if count:
                text = text.replace(before, after)
                changes.append({"before": before, "after": after, "count": count})
        data = text.encode("utf-8")
        path.write_bytes(data)
        result["edits"][path.name].extend(changes)
        result["staged_source_sha256"][path.name] = hashlib.sha256(data).hexdigest()
    result.update(schema="spellbench-magezero-v02-search-stage/v1", architecture="magezero-v02",
                  source_commit=REVISION, source_assets={asset["id"]: asset["sha256"] for asset in selected},
                  policy_width=128, feature_hash_bins=2147483647,
                  compatibility_recipe_sha256=hashlib.sha256(Path(__file__).with_name("xmage_search_sources.py").read_bytes()).hexdigest(),
                  scope="original MageZero tree in a separate namespace; synchronous private inference, permitted sampled worlds and no offline fallback; request adapter and pretrained qualification unfinished")
    (output / "STAGE.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result
