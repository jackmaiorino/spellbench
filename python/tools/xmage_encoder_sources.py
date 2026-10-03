"""Stage the pinned Exp1 encoder with explicit base-engine compatibility edits.

Only source files are read. Checkpoints stay opaque on the host. This stage
supports decision slices, with empty micro-decision history and no ongoing
activation. It is not an assertion of original-player equivalence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from xmage_release_assets import prepare_root, verify


REWRITES = {
    "FeatureMap.java": {"import javafx.util.Pair;": "import spellbench.models.Pair;"},
    "StateEncoder.java": {
        "(Card) p.getPairedCard()": "spellbench.models.Exp1Compat.pairedCard(p, game)",
        "game.getOpponent(playerId)": "spellbench.models.Exp1Compat.opponent(game, playerId)",
        "p.getValue(game, playerId)": "spellbench.models.Exp1Compat.permanentValue(p, game, playerId)",
        "gy.getCardsSorted(game)": "spellbench.models.Exp1Compat.sortedCards(gy, game)",
        "hand.getCardsSorted(game)": "spellbench.models.Exp1Compat.sortedCards(hand, game)",
        "exileZone.getCardsSorted(game)": "spellbench.models.Exp1Compat.sortedCards(exileZone, game)",
        "game.getEntityName(id, playerId)": "spellbench.models.Exp1Compat.entityName(game, id, playerId)",
        "game.getEntityName(targetID, playerId)": "spellbench.models.Exp1Compat.entityName(game, targetID, playerId)",
        "myPlayer.getPlayerHistory()": "spellbench.models.Exp1Compat.history(myPlayer)",
        "((PlayerImpl)myPlayer).isActivating": "spellbench.models.Exp1Compat.isActivating(myPlayer)",
    },
}


def stage(manifest: dict, root: Path, output: Path) -> dict:
    if manifest.get("schema") != "spellbench-xmage-release-inputs/v1":
        raise ValueError("unknown release input manifest")
    assets = {a["id"]: a for a in manifest["assets"]}
    selected = [assets["draftzero-exp1-" + name] for name in
                ("actionencoder", "featuremap", "features", "labeledstate", "stateencoder")]
    root = prepare_root(root)
    for asset in selected:
        verify(root / asset["filename"], asset)
    if output.exists():
        raise ValueError("encoder source output must be a new job directory")
    output = prepare_root(output)
    hashes = {}
    for asset in selected:
        text = (root / asset["filename"]).read_text(encoding="utf-8")
        for before, after in REWRITES.get(asset["filename"], {}).items():
            if before not in text:
                raise ValueError("pinned source lacks the declared compatibility edit")
            text = text.replace(before, after)
        data = text.encode()
        with (output / asset["filename"]).open("xb") as stream:
            stream.write(data)
        hashes[asset["filename"]] = hashlib.sha256(data).hexdigest()
    result = {"schema": "spellbench-draftzero-encoder-stage/v1", "staged_source_sha256": hashes,
              "rewrites": REWRITES, "scope": "decision encoder slice; full dialog history and original search not implemented"}
    with (output / "STAGE.json").open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("engines/xmage/releases.json"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(stage(json.loads(args.manifest.read_text()), args.root, args.out)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
