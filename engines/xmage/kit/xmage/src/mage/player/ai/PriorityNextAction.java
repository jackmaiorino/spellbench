// Vendored from XMage fd40ad5c (MIT, see engines/xmage/NOTICE). Kit changes are marked KIT; the diff is published in kit/diffs/.
package mage.player.ai;

import mage.abilities.Ability;
import mage.abilities.ActivatedAbility;
import mage.game.Game;

import java.util.ArrayList;
import java.util.List;

public class PriorityNextAction implements MCTSNodeNextAction{

    @Override
    public List<MCTSNode> performNextAction(MCTSNode node, MCTSPlayer player, Game game, String fullStateValue) {
        List<MCTSNode> children = new ArrayList<>();
        List<Ability> abilities;
        if (!MCTSNode.USE_ACTION_CACHE)
            abilities = player.getPlayableOptions(game);
        else
            abilities = MCTSNode.getPlayables(player, fullStateValue, game);
        for (Ability ability: abilities) {
            Game sim = game.createSimulationForAI();
            MCTSPlayer simPlayer = (MCTSPlayer) sim.getPlayer(player.getId());
            int before = sim.getStack().size();
            long dialogsBefore = spellbench.kit.xmage.KitContext.dialogs(); // KIT
            try { // KIT: option-generation and operation budgets in expansion (addendum change 2)
                simPlayer.activateAbility((ActivatedAbility)ability, sim);
            } catch (spellbench.kit.xmage.KitContext.BudgetExceeded e) {
                spellbench.kit.xmage.KitContext.caught("mcts_expansion_activation");
                spellbench.kit.xmage.KitContext.count("mcts:options_capped");
                continue; // the child is dropped
            }
            // KIT: an action at the root that leaves no stack object and asked a dialog while it executed carries
            // its choices in no executed copy: unsupported (review change 4), so it is never a root child
            if (node.kitIsRoot() && !(ability instanceof mage.abilities.common.PassAbility)
                    && sim.getStack().size() <= before && spellbench.kit.xmage.KitContext.dialogs() > dialogsBefore) {
                spellbench.kit.xmage.KitContext.count("mcts:non_stack_dialog_excluded");
                continue;
            }
            // KIT: payload witness (design 5.3 N1): read from the executed object before the game resumes
            java.util.Map<String, Object> payload = spellbench.kit.xmage.KitContext.witness(sim, before);
            // KIT: horizon in expansion (addendum change 4): a pass that would let a flagged object resolve
            if (spellbench.kit.xmage.KitContext.passWouldResolveFlagged(sim, player.getId(), ability)) {
                MCTSNode child = new MCTSNode(node, sim, ability);
                child.kitTruncate(spellbench.kit.xmage.KitContext.truncationResult(sim, node.kitTargetPlayer()));
                child.kitSetPayload(payload);
                spellbench.kit.xmage.KitContext.count("horizon:mcts_expansion");
                spellbench.kit.xmage.KitContext.count("mcts:truncated_expansions");
                children.add(child);
                continue;
            }
            try {
                sim.resume();
            } catch (spellbench.kit.xmage.KitContext.BudgetExceeded e) {
                spellbench.kit.xmage.KitContext.caught("mcts_expansion_resume");
                spellbench.kit.xmage.KitContext.count("mcts:truncated_expansions");
                MCTSNode child = new MCTSNode(node, sim, ability);
                child.kitTruncate(spellbench.kit.xmage.KitContext.truncationResult(sim, node.kitTargetPlayer()));
                child.kitSetPayload(payload);
                children.add(child);
                continue;
            }
            MCTSNode child = new MCTSNode(node, sim, ability);
            child.kitSetPayload(payload);
            children.add(child);
            spellbench.kit.xmage.KitContext.count("mcts:expanded_children"); // KIT: E4 accounting denominator
        }

        return children;
    }
}
