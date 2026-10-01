// Vendored from XMage fd40ad5c (MIT, see engines/xmage/NOTICE). Kit changes are marked KIT; the diff is published in kit/diffs/.
package mage.player.ai;

import mage.game.Game;
import mage.game.combat.CombatGroup;

import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

import static mage.player.ai.MCTSNode.getBlocks;

public class SelectBlockersNextAction implements MCTSNodeNextAction{
    @Override
    public List<MCTSNode> performNextAction(MCTSNode node, MCTSPlayer player, Game game, String fullStateValue) {
        List<MCTSNode> children = new ArrayList<>();
        List<List<List<UUID>>> blocks;
        if (!MCTSNode.USE_ACTION_CACHE)
            blocks = player.getBlocks(game);
        else
            blocks = getBlocks(player, fullStateValue, game);
        for (List<List<UUID>> block : blocks) {
            Game sim = game.createSimulationForAI();
            MCTSPlayer simPlayer = (MCTSPlayer) sim.getPlayer(player.getId());
            List<CombatGroup> groups = sim.getCombat().getGroups();
            for (int i = 0; i < groups.size(); i++) {
                if (i < block.size()) {
                    for (UUID blockerId : block.get(i)) {
                        simPlayer.declareBlocker(simPlayer.getId(), blockerId, groups.get(i).getAttackers().get(0), sim);
                    }
                }
            }
            try { // KIT: operation budget in combat expansion (MCTS combat dispatch, A1 result review change 6)
                sim.resume();
            } catch (spellbench.kit.xmage.KitContext.BudgetExceeded e) {
                spellbench.kit.xmage.KitContext.caught("mcts_combat_expansion");
                spellbench.kit.xmage.KitContext.count("mcts:truncated_expansions");
                MCTSNode child = new MCTSNode(node, sim, sim.getCombat());
                child.kitTruncate(spellbench.kit.xmage.KitContext.truncationResult(sim, node.kitTargetPlayer()));
                children.add(child);
                continue;
            }
            children.add(new MCTSNode(node, sim, sim.getCombat()));
            spellbench.kit.xmage.KitContext.count("mcts:expanded_children"); // KIT: E4 accounting denominator
        }

        return children;
    }
}
