"""Stage Exp1's original search in a separate namespace on the reviewed engine.

The pinned source remains outside Git. Every compatibility edit is recorded.
Search never receives a live game, and neural transport failures are fatal.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from xmage_release_assets import prepare_root, verify

NAMES = ("ComputerPlayer", "ComputerPlayerMCTS", "ComputerPlayerMCTS2", "MCTSPlayer",
         "MCTSNode", "MCTSNode2", "PlayerScript", "MCTSDefaults", "GameStateEvaluator2",
         "ArtificialScoringSystem", "MagicAbility", "PossibleTargetsSelector", "PossibleTargetsComparator", "ChooseCreatureToBlockAbility")

HISTORY_BRIDGE = """
    private PlayerScript playerHistory = new PlayerScript();
    private boolean activating;
    protected boolean isPayingMana;
    public boolean isManualTappingAI() { return !autoTap; }
    public void illegalGameState(Game game) { throw new IllegalStateException("illegal search game state"); }
    public PlayerScript getPlayerHistory() { return playerHistory; }
    public spellbench.models.Exp1Compat.History encoderHistory() {
        return new spellbench.models.Exp1Compat.History(playerHistory.targetSequence,
                playerHistory.choiceSequence, playerHistory.useSequence, playerHistory.numSequence);
    }
    public boolean activating() { return activating; }
    @Override public boolean activateAbility(ActivatedAbility ability, Game game) {
        if (ability == null) throw new IllegalArgumentException("null search ability");
        activating = true;
        try {
            if (!(ability instanceof PassAbility) && !isPayingMana && !game.isPaused()
                    && !game.checkIfGameIsOver() && (isManualTappingAI() || !ability.isManaAbility())) {
                playerHistory.prioritySequence.add(ability.copy());
            }
            return super.activateAbility(ability, game);
        } finally { activating = false; }
    }
    @Override public void pass(Game game) {
        playerHistory.prioritySequence.add(new PassAbility());
        super.pass(game);
    }
"""


def stage(manifest: dict, root: Path, output: Path) -> dict:
    assets = {a["id"]: a for a in manifest["assets"]}
    root = prepare_root(root)
    selected = [assets["draftzero-exp1-search-" + name.lower()] for name in NAMES]
    for asset in selected:
        verify(root / asset["filename"], asset)
    player_asset = assets["draftzero-exp1-search-playerimpl"]
    verify(root / player_asset["filename"], player_asset)
    player_source = (root / player_asset["filename"]).read_text(encoding="utf-8")
    audits = {}
    for name in ("GameImpl", "RemoteModelEvaluator"):
        asset = assets["draftzero-exp1-search-" + name.lower()]
        verify(root / asset["filename"], asset)
        audits[asset["filename"]] = asset["sha256"]
    method_start = player_source.index("    public void getPlayableFromObjectAll(")
    method_end = player_source.index("    @Override\n    public List<ActivatedAbility> getPlayable(Game game, boolean hidden)", method_start)
    playable_methods = player_source[method_start:method_end]
    if output.exists():
        raise ValueError("search source output must be a new job directory")
    output = prepare_root(output)
    edits, hashes = {}, {}
    for asset, name in zip(selected, NAMES):
        text = (root / asset["filename"]).read_text(encoding="utf-8")
        changes = []
        def replace(before, after, *, required=True):
            nonlocal text
            count = text.count(before)
            if required and not count:
                raise ValueError(f"pinned {name} lacks declared edit: {before}")
            if count:
                text = text.replace(before, after)
                changes.append({"before": before, "after": after, "count": count})
        package = "package mage.players;" if name in ("PlayerScript", "ChooseCreatureToBlockAbility") else (
            "package mage.player.ai.config;" if name == "MCTSDefaults" else (
            "package mage.player.ai.score;" if name in ("GameStateEvaluator2", "ArtificialScoringSystem", "MagicAbility") else "package mage.player.ai;"))
        replace(package, "package spellbench.models.exp1;")
        for before in ("import mage.players.PlayerScript;", "import mage.player.ai.config.MCTSDefaults;",
                       "import mage.player.ai.score.GameStateEvaluator2;"):
            replace(before, "", required=False)
        # These helpers were public additions to the fork's core interfaces.
        for game in ("game", "rootGame", "mcts", "baseGame"):
            for method, helper in (("getOpponent", "opponent"), ("getEntityName", "entityName"),
                                   ("getEntityValue", "entityValue"), ("isCheckPoint", "checkPoint"),
                                   ("setLastPriority", "setLastPriority"), ("setState", "setState"),
                                   ("setMCTSSimulation", "setMctsSimulation")):
                replace(f"{game}.{method}(", f"GameAccess.{helper}({game}, ", required=False)
        replace("game.getLastPriority()", "GameAccess.lastPriority(game)", required=False)
        replace("import static mage.target.TargetImpl.STOP_CHOOSING;", "import static spellbench.models.exp1.GameAccess.STOP_CHOOSING;", required=False)
        replace("TargetImpl.STOP_CHOOSING", "GameAccess.STOP_CHOOSING", required=False)
        replace("game.getOpponent(playerId).getPlayerHistory()", "GameAccess.history(GameAccess.opponent(game, playerId))", required=False)
        replace("GameAccess.opponent(game, playerId).getPlayerHistory()", "GameAccess.history(GameAccess.opponent(game, playerId))", required=False)
        if name == "ComputerPlayer":
            replace("public class ComputerPlayer extends PlayerImpl {",
                    "public class ComputerPlayer extends PlayerImpl implements spellbench.models.Exp1Compat.HistoryProvider {\n" + HISTORY_BRIDGE)
            replace("super(player);\n", "super(player);\n        playerHistory = new PlayerScript(player.getPlayerHistory());\n        activating = player.activating;\n")
            replace("super.restore(player);", "super.restore(player);\n        playerHistory = new PlayerScript(GameAccess.history(player));\n        activating = player instanceof ComputerPlayer && ((ComputerPlayer) player).activating;")
            replace("autoTap = !isHumanManualTap;", "autoTap = !GameAccess.manualTap(player);")
            replace("game.getLocalRandom().nextInt(", "mage.util.RandomUtil.nextInt(")
            replace("import mage.cards.Card;", "import mage.cards.*;")
            replace(HISTORY_BRIDGE, HISTORY_BRIDGE + "\n" + playable_methods)
        if name == "MCTSNode":
            replace("import mage.player.ai.score.GameStateEvaluator3;", "", required=False)
            # Deprecated random playouts are not used by Exp1's neural tree.
            before = text.index("    /**\n     * Copies game and replaces all players in copy with simulated players")
            changes.append({"operation": "remove unused deprecated random-playout methods", "start": before})
            text = text[:before] + "}\n"
        if name == "ComputerPlayerMCTS2":
            replace("    @Override\n    protected MCTSNode calculateActions(Game game, ActionEncoder.ActionType action) {",
                    "    protected void beforeBestChild(MCTSNode2 tree) {}\n"
                    "    @Override\n    protected MCTSNode calculateActions(Game game, ActionEncoder.ActionType action) {")
            replace("        MCTSNode best = root.bestChild(game);",
                    "        beforeBestChild(root);\n        MCTSNode best = root.bestChild(game);")
            # WorldBuilder's deterministic, per-world random stream owns the seed.
            before = "        if(stateEncoder == null){"
            for _ in range(2):
                start = text.index(before)
                end = text.index("\n        }", start) + len("\n        }")
                removed = text[start:end]
                text = text[:start] + "        // Per-world seed is installed by the permitted world builder." + text[end:]
                changes.append({"before": removed, "after": "use per-world random stream"})
            start = text.index("        //find model endpoint")
            end = text.index("\n\n    }", start)
            removed = text[start:end]
            text = text[:start] + "        if (nn == null) throw new IllegalStateException(\"neural transport is required\");\n        offlineMode = false;\n        stateEncoder.perfectInfo = false;" + text[end:]
            changes.append({"before": removed, "after": "required private inference transport; no offline fallback"})
        if name == "MCTSNode2":
            replace("import mage.player.ai.score.GameStateEvaluator3;", "")
            start = text.index("        if(((ComputerPlayerMCTS2)basePlayer).offlineMode) {")
            end = text.index("        while (((ComputerPlayerMCTS2)basePlayer).pendingNodes.get()", start)
            removed = text[start:end]
            text = text[:start] + '        if (((ComputerPlayerMCTS2)basePlayer).offlineMode) throw new IllegalStateException("offline neural search is refused");\n' + text[end:]
            changes.append({"before": removed, "after": "refuse offline heuristic evaluation"})
            # A completed future runs this block synchronously. The original
            # evaluate-before-expand order must still install priors afterward.
            replace("    public void awaitEvaluation() {", "    @Override public void expand() {\n        super.expand();\n        if (!evaluationPending) setPriors();\n    }\n    public void awaitEvaluation() {")
            replace('throw new RuntimeException("REMOTE EVAL FAILURE");\n                });',
                    'throw new RuntimeException("REMOTE EVAL FAILURE");\n                }).join();')
        if name == "MCTSPlayer":
            replace("import mage.util.RateLimitedLogger;", "")
            replace("RateLimitedLogger.warn(", "logger.warn(")
            replace("        if(min >= max) {//one or fewer choices",
                    "        max = GameAccess.numberMaximum(playerId, source, min, max, getPlayerHistory().numSequence.size());\n"
                    "        if(min >= max) {//one or fewer choices")
        data = ("// Pinned Exp1 source, XMage MIT. Explicit edits are in STAGE.json.\n" + text).encode()
        (output / (name + ".java")).write_bytes(data)
        hashes[name + ".java"] = hashlib.sha256(data).hexdigest()
        edits[name + ".java"] = changes
    result = {"schema": "spellbench-draftzero-search-stage/v1", "staged_source_sha256": hashes,
              "edits": edits, "source_commit": manifest["sources"]["draftzero_engine_exp1"]["revision"],
              "core_transport_audit_sha256": audits, "playable_helper_source_sha256": player_asset["sha256"],
              "scope": "ported original search; synchronous private inference and permitted sampled worlds; unqualified"}
    (output / "STAGE.json").write_text(json.dumps(result, indent=2) + "\n")
    return result
