"""Stage the DraftZero FDN graph network's pinned encoder and search beside MageZero v0.2.

The release's graph encoder (MageZero's graph-encoder branch, vendored by
DraftZero) and DraftZero's search driver (BenchSearch, GraphNet,
GraphMCTSPlayer, GraphRecord) stay outside Git. Each compatibility edit is
declared here and recorded in STAGE.json:

- packages move into Spellbench namespaces; the search classes join the staged
  MageZero v0.2 search package, whose package-private tree fields they read;
- fork-only engine calls use the existing Exp1Compat/GameAccess helpers;
- Java 9 List.of calls become a Java 8 helper (the kit builds with --release 8);
- GraphNet's HTTP/msgpack graph-server client becomes the confined pipe transport;
- GraphRecord's training-record JSON (Gson) and bridge Decision adapter are removed;
- BenchSearch's IS-MCTS method and heuristic leaf are removed: the played
  configuration is one-world tree search (PIMC) with network leaves.

BenchPlayer is pinned as the played configuration's reference and not compiled.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from xmage_release_assets import prepare_root, verify

ENCODER = "spellbench.models.draftzero.gnn.encoder"
GRAPH = "spellbench.models.draftzero.gnn"
SEARCH = "spellbench.models.magezero.v02.search"
COMPAT = "spellbench.models.Exp1Compat"
LIST_OF = "spellbench.models.draftzero.gnn.GnnCompat.listOf("

COMMON = [("import mage.player.ai.encoder.ActionEncoder;", "import spellbench.models.magezero.v02.encoder.ActionEncoder;"),
          ("import static mage.target.TargetImpl.STOP_CHOOSING;", f"import static {SEARCH}.GameAccess.STOP_CHOOSING;")]

SOURCES = {
    "StateEncoder": ("stateencoder", ENCODER, [
        ("package org.draftzero.mzbridge.graph;", f"package {ENCODER};"),
        ("import mage.player.ai.encoder.FeatureMap;", "import spellbench.models.magezero.v02.encoder.FeatureMap;"),
        ("import static org.draftzero.mzbridge.graph.FeatureGraph.*;", f"import static {ENCODER}.FeatureGraph.*;"),
        ("(Card) p.getPairedCard()", f"{COMPAT}.pairedCard(p, game)"),
        ("game.getOpponent(playerId)", f"{COMPAT}.opponent(game, playerId)"),
        ("gy.getCardsSorted(game)", f"{COMPAT}.sortedCards(gy, game)"),
        ("hand.getCardsSorted(game)", f"{COMPAT}.sortedCards(hand, game)"),
        ("exileZone.getCardsSorted(game)", f"{COMPAT}.sortedCards(exileZone, game)"),
        ("game.getEntityName(id, myPlayerId)", f"{COMPAT}.entityName(game, id, myPlayerId)"),
        ("myPlayer.getPlayerHistory()", f"{COMPAT}.history(myPlayer)"),
        ("((PlayerImpl)myPlayer).isActivating", f"{COMPAT}.isActivating(myPlayer)"),
        # The release's engine fork comments out PhaseStep.toString(), so its step leaf is the enum name
        # (UPKEEP, PRECOMBAT_MAIN); the reviewed engine's toString() returns display text ("Upkeep").
        ("addFeature(game.getTurnStepType().toString(), GAME_ROOT_ID);", "addFeature(game.getTurnStepType().name(), GAME_ROOT_ID);"),
        # The reviewed engine keeps always-present UX helper emblems (rad counters, day or night, storm) whose
        # texts never occur in the release's training states or vocabulary.
        ("for (Emblem emblem : game.getState().getHelperEmblems())", "for (Emblem emblem : java.util.Collections.<Emblem>emptyList())"),
    ]),
    "FeatureGraph": ("featuregraph", ENCODER, [
        ("package org.draftzero.mzbridge.graph;", f"package {ENCODER};"),
        ("import static org.draftzero.mzbridge.graph.StateEncoder.stringToUUID;", f"import static {ENCODER}.StateEncoder.stringToUUID;"),
    ]),
    "GraphRecord": ("graphrecord", GRAPH, [
        ("package org.draftzero.mzbridge;", f"package {GRAPH};"),
        ("import com.google.gson.JsonArray;\n", ""),
        ("import com.google.gson.JsonObject;\n", ""),
        ("import org.draftzero.mzbridge.graph.FeatureGraph;", f"import {ENCODER}.FeatureGraph;"),
        ("import org.draftzero.mzbridge.graph.StateEncoder;", f"import {ENCODER}.StateEncoder;"),
        ("game.getOpponent(agent)", f"{COMPAT}.opponent(game, agent)"),
        ("List.of(", LIST_OF),
    ]),
    "GraphNet": ("graphnet", SEARCH, [
        ("package mage.player.ai;", f"package {SEARCH};"),
        ("import org.draftzero.mzbridge.GraphRecord;", f"import {GRAPH}.GraphRecord;"),
        ("import org.draftzero.mzbridge.graph.FeatureGraph;", f"import {ENCODER}.FeatureGraph;"),
        ("import org.msgpack.core.MessageBufferPacker;\n", ""),
        ("import org.msgpack.core.MessagePack;\n", ""),
        ("import org.msgpack.core.MessageUnpacker;\n", ""),
        ("import java.net.URI;\n", ""),
        ("import java.net.http.HttpClient;\n", ""),
        ("import java.net.http.HttpRequest;\n", ""),
        ("import java.net.http.HttpResponse;\n", ""),
        ("import java.time.Duration;\n", ""),
        ("List.of(", LIST_OF),
    ]),
    "GraphMCTSPlayer": ("graphmctsplayer", SEARCH, [
        ("package mage.player.ai;", f"package {SEARCH};"),
        ("import mage.player.ai.encoder.StateEncoder;", "import spellbench.models.magezero.v02.encoder.StateEncoder;"),
        ("import mage.players.ChooseCreatureToBlockAbility;\n", ""),
    ]),
    "BenchSearch": ("benchsearch", SEARCH, [
        ("package mage.player.ai;", f"package {SEARCH};"),
        ("import mage.player.ai.score.GameStateEvaluator3;\n", ""),
        ("import mage.players.PlayerScript;\n", ""),
        ("TargetImpl.STOP_CHOOSING", "GameAccess.STOP_CHOOSING"),
        ("g.getEntityValue(id, me)", "GameAccess.entityValue(g, id, me)"),
        ("live.getEntityName(c.getTargetAction(), me)", "GameAccess.entityName(live, c.getTargetAction(), me)"),
        ("GameStateEvaluator3.evaluateNormalized(eng.targetPlayer, eng.getGame())",
         "spellbench.models.draftzero.gnn.GnnCompat.heuristicLeafRefused()"),
        # The staged v0.2 evaluator is synchronous behind inferAsync (flat networks only; unused here).
        ("cfg.nn.infer(idx)", "cfg.nn.inferAsync(idx).join()"),
        ("List.of(", LIST_OF),
    ]),
}

# GraphNet's client for DraftZero's HTTP graph server, from its cache to the
# end of the class, becomes the confined pipe. infer(eng, q) is kept verbatim.
GRAPHNET_CLIENT_START = "    private static final Map<String, GraphNet> CACHE = new HashMap<>();"
GRAPHNET_KEPT = """    /** The network's output for the state at search node `eng`, from the searcher's seat. */
    Out infer(MCTSNode eng, Ask q) {
        FeatureGraph.GraphArrays a = GraphRecord.arrays(eng.getGame(), eng.targetPlayer, eng.playerId, q.ask, false);
        return infer(a);
    }
"""
GRAPHNET_CONFINED = """    // Spellbench: the HTTP graph-server client is replaced by the confined
    // NDJSON pipe. One state per call; per-node scores are -inf at leaves.
    public interface Transport {
        Out infer(FeatureGraph.GraphArrays a);
    }

    private final Transport transport;
    public long calls;

    public GraphNet(Transport transport) {
        if (transport == null) throw new IllegalArgumentException("missing graph network transport");
        this.transport = transport;
    }

    public static Out out(float value, float[] priority, float[] target, float[] use, Map<UUID, Integer> index) {
        return new Out(value, priority, target, use, index);
    }

""" + GRAPHNET_KEPT + """
    public Out infer(FeatureGraph.GraphArrays a) {
        calls++;
        return transport.infer(a);
    }
}
"""
# BenchSearch's IS-MCTS method (searchIS, shadowRoot, redeal, selectIS) is not
# the played PIMC configuration and uses fork-only engine calls.
IS_START = "    // ============================================================================ IS-MCTS\n"
IS_END = "    /** A world-independent name for an option: the same choice in any world gets the same key. */\n"
# GraphRecord's record writers need Gson; its Decision adapter needs the bridge.
RECORD_REMOVALS = [
    ("        /** A priority, target or \"may\" decision, as the bridge's Decision records it. */\n",
     "        }\n\n", "Decision adapter"),
    ("    /**\n     * The graph of `game` from `me`'s seat",
     "    /**\n     * The state graph of `game`", "training-record JSON writers"),
    ("    static String b64(int[] xs) {", "\n}\n", "base64 record helper"),
]
REVISION = "2a461518985e3b2bb393bddac4649e217f8fddfe"


def _cut(text: str, start: str, end: str, keep_end: bool) -> tuple[str, str]:
    a = text.index(start)
    b = text.index(end, a + len(start))
    if not keep_end:
        b += len(end)
    return text[:a] + text[b:], text[a:b]


def stage(manifest: dict, root: Path, output: Path) -> dict:
    if manifest.get("schema") != "spellbench-xmage-release-inputs/v1":
        raise ValueError("unknown release input manifest")
    if manifest.get("sources", {}).get("draftzero_gnn", {}).get("revision") != REVISION:
        raise ValueError("graph network sources need their pinned draft-zero revision")
    assets = {a["id"]: a for a in manifest["assets"]}
    if len(assets) != len(manifest["assets"]):
        raise ValueError("duplicate release input id")
    root = prepare_root(root)
    staged, edits = {}, {}
    for name, (key, package, rewrites) in SOURCES.items():
        asset = assets["draftzero-gnn-src-" + key]
        if asset.get("source_revision") != REVISION or asset.get("kind") != "source-code":
            raise ValueError("graph network source needs its pinned revision")
        verify(root / asset["filename"], asset)
        text = (root / asset["filename"]).read_text(encoding="utf-8")
        changes = []
        for before, after in [*COMMON, *rewrites]:
            count = text.count(before)
            if not count and (before, after) not in COMMON:
                raise ValueError(f"pinned {name} lacks declared edit: {before!r}")
            if count:
                text = text.replace(before, after)
                changes.append({"before": before, "after": after, "count": count})
        if name == "GraphNet":
            start = text.index(GRAPHNET_CLIENT_START)
            if GRAPHNET_KEPT not in text[start:]:
                raise ValueError("pinned GraphNet changed its kept inference method")
            changes.append({"operation": "replace HTTP graph-server client with the confined pipe transport",
                            "removed_sha256": hashlib.sha256(text[start:].encode()).hexdigest()})
            text = text[:start] + GRAPHNET_CONFINED
        if name == "BenchSearch":
            text, removed = _cut(text, IS_START, IS_END, keep_end=True)
            changes.append({"operation": "remove IS-MCTS (not the played PIMC method)",
                            "removed_sha256": hashlib.sha256(removed.encode()).hexdigest()})
        if name == "GraphRecord":
            for start, end, label in RECORD_REMOVALS:
                text, removed = _cut(text, start, end, keep_end=label == "training-record JSON writers")
                if label == "base64 record helper":
                    text = text.rstrip() + "\n}\n"
                changes.append({"operation": "remove " + label,
                                "removed_sha256": hashlib.sha256(removed.encode()).hexdigest()})
        if "package " + package + ";" not in text:
            raise ValueError(f"staged {name} is not in its declared package")
        header = f"// Pinned danieljbrooks/draft-zero@{REVISION} source, MIT. Explicit edits are in STAGE.json.\n"
        staged[name + ".java"] = (package, (header + text).encode("utf-8"))
        edits[name + ".java"] = changes
    if output.exists():
        raise ValueError("graph network source output must be a new job directory")
    output = prepare_root(output)
    hashes = {}
    for filename, (package, data) in staged.items():
        directory = output.joinpath(*package.split("."))
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / filename).open("xb") as stream:
            stream.write(data)
        hashes[filename] = hashlib.sha256(data).hexdigest()
    reference = assets["draftzero-gnn-src-benchplayer"]
    verify(root / reference["filename"], reference)
    result = {"schema": "spellbench-draftzero-gnn-stage/v1", "source_revision": REVISION,
              "packages": {name: package for name, (_, package, _) in SOURCES.items()},
              "staged_source_sha256": hashes, "edits": edits,
              "reference_only": {reference["filename"]: reference["sha256"]},
              "scope": "graph encoder and one-world tree search with confined inference; unqualified"}
    with (output / "STAGE.json").open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    return result


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("engines/xmage/releases.json"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(stage(json.loads(args.manifest.read_text(encoding="utf-8")), args.root, args.out)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
