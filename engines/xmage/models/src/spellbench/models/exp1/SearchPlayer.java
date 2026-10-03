package spellbench.models.exp1;

import mage.constants.RangeOfInfluence;
import mage.game.Game;
import mage.player.ai.encoder.ActionEncoder;
import java.util.HashSet;
import java.util.Set;

/** Original Exp1 tree with an explicit deterministic, no-noise play profile. */
public final class SearchPlayer extends ComputerPlayerMCTS2 {
    public SearchPlayer(String name) { super(name, RangeOfInfluence.ALL, 6); }
    private SearchPlayer(SearchPlayer player) { super(player); }
    @Override public SearchPlayer copy() { return new SearchPlayer(this); }
    public void configure(RemoteModelEvaluator model, int visits) {
        if (visits < 2 || visits > 1000) throw new IllegalArgumentException("search visits must be 2..1000");
        nn = model;
        actionEncoder = new ActionEncoder();
        searchBudget = visits;
        // The fixed visit count controls normal completion. The caller's clock
        // aborts the process instead of selecting a partially searched result.
        searchTimeout = 600;
        noNoise = true;
        noPolicyPriority = noPolicyTarget = noPolicyUse = noPolicyOpponent = false;
        priorTemp = 1.5; priorBonus = 0.1; backpropDiscount = 0.99;
        selectionTemperature = 0; dirichletNoiseEps = 0;
        offlineMode = false;
        SHOW_THREAD_INFO = false;
    }
    public MCTSNode2 searchPriority(Game game) {
        if (stateEncoder == null) RLInit(game);
        Set<Integer> observedFeatures = new HashSet<>(stateEncoder.processState(game, playerId));
        MCTSNode2 best = getNextAction(game, ActionEncoder.ActionType.PRIORITY);
        if (best == null || root == null || root.getVisits() < searchBudget) {
            throw new IllegalStateException("original search did not complete its visit budget");
        }
        if (!playerId.equals(root.playerId) || root.actionType != ActionEncoder.ActionType.PRIORITY
                || !observedFeatures.equals(root.stateVector)) {
            throw new IllegalStateException("search root differs from the received priority state");
        }
        return best;
    }
    public MCTSNode2 tree() { return root; }
    @Override public boolean chooseMulligan(Game game) {
        // WorldBuilder initializes zones itself. Full pregame search needs its
        // own bridge; no mulligan decision is made during snapshot construction.
        return false;
    }
}
