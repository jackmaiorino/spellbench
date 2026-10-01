// Vendored from XMage fd40ad5c (MIT, see engines/xmage/NOTICE). Kit changes are marked KIT; the diff is published in kit/diffs/.
package mage.player.ai;

import mage.game.Game;

import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

import static mage.player.ai.MCTSNode.getAttacks;

public class SelectAttackersNextAction implements MCTSNodeNextAction{
    @Override
    public List<MCTSNode> performNextAction(MCTSNode node, MCTSPlayer player, Game game, String fullStateValue) {
        List<MCTSNode> children = new ArrayList<>();
        List<List<UUID>> attacks;
        if (!MCTSNode.USE_ACTION_CACHE)
            attacks = player.getAttacks(game);
        else
            attacks = getAttacks(player, fullStateValue, game);
        UUID defenderId = game.getOpponents(player.getId(), true).iterator().next();
        for (List<UUID> attack: attacks) {
            Game sim = game.createSimulationForAI();
            MCTSPlayer simPlayer = (MCTSPlayer) sim.getPlayer(player.getId());
            for (UUID attackerId: attack) {
                simPlayer.declareAttacker(attackerId, defenderId, sim, false);
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
