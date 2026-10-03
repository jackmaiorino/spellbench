package spellbench.models.exp1;

import mage.constants.RangeOfInfluence;
import mage.game.Game;
import mage.abilities.Ability;
import mage.choices.Choice;
import mage.player.ai.encoder.ActionEncoder;
import java.util.HashSet;
import java.util.Set;
import java.util.List;
import java.util.ArrayList;
import java.util.Map;
import java.util.IdentityHashMap;
import spellbench.models.exp1.MCTSNode;

/** Original Exp1 tree with an explicit deterministic, no-noise play profile. */
public class SearchPlayer extends ComputerPlayerMCTS2 {
    private List<MCTSNode> initialRootChildren = new ArrayList<>();
    private Map<MCTSNode, Integer> beforeSelectionVisits = new IdentityHashMap<>();
    private Set<MCTSNode> selectionMasked = java.util.Collections.newSetFromMap(new IdentityHashMap<MCTSNode, Boolean>());
    public SearchPlayer(String name) { super(name, RangeOfInfluence.ALL, 6); }
    protected SearchPlayer(SearchPlayer player) { super(player); }
    @Override public SearchPlayer copy() { return new SearchPlayer(this); }
    public void configure(RemoteModelEvaluator model, int visits) {
        if (visits < 2 || visits > 1000) throw new IllegalArgumentException("search visits must be 2..1000");
        nn = model;
        actionEncoder = new ActionEncoder();
        searchBudget = visits;
        // Original normal completion requires this minimum and a legal future.
        // The caller's clock aborts an unfinished search.
        searchTimeout = 600;
        noNoise = true;
        noPolicyPriority = noPolicyTarget = noPolicyUse = noPolicyOpponent = false;
        priorTemp = 1.5; priorBonus = 0.1; backpropDiscount = 0.99;
        selectionTemperature = 0; dirichletNoiseEps = 0;
        offlineMode = false;
        SHOW_THREAD_INFO = false;
    }
    public MCTSNode2 searchPriority(Game game) {
        return searchAction(game, ActionEncoder.ActionType.PRIORITY, "priority");
    }
    public MCTSNode2 searchAmount(Game game, int min, int max, Ability source) {
        if (min >= max || (long) max - min > 64 || source == null) {
            throw new IllegalArgumentException("numeric search needs an original 2..65 option callback with a source");
        }
        numOptionsSize = max - min + 1;
        return searchAction(game, ActionEncoder.ActionType.CHOOSE_NUM, "choose num for " + source.toString());
    }
    public MCTSNode2 searchChoice(Game game, Choice choice) {
        choiceOptions = new HashSet<>(choice.getKeyChoices().keySet());
        if (choiceOptions.isEmpty()) choiceOptions = choice.getChoices();
        if (choiceOptions.size() < 2) throw new IllegalArgumentException("named search needs a non-forced original choice");
        return searchAction(game, ActionEncoder.ActionType.MAKE_CHOICE, choice.getMessage());
    }
    public MCTSNode2 searchAction(Game game, ActionEncoder.ActionType type, String text) {
        if (stateEncoder == null) RLInit(game);
        Set<Integer> observedFeatures = new HashSet<>(stateEncoder.processState(game, playerId, type, text));
        root = null;
        MCTSNode2 best = getNextAction(game, type);
        if (best == null || root == null || root.getVisits() < searchBudget) {
            throw new IllegalStateException("original search did not complete its visit budget");
        }
        if (!playerId.equals(root.playerId) || root.actionType != type
                || !observedFeatures.equals(root.stateVector)) {
            throw new IllegalStateException("search root differs from the received callback state");
        }
        return best;
    }
    public MCTSNode2 tree() { return root; }
    public List<MCTSNode> initialRootChildren() { return new ArrayList<>(initialRootChildren); }
    public int discardedSelectionVisits(MCTSNode node) {
        return selectionMasked.contains(node) ? beforeSelectionVisits.get(node) : 0;
    }
    public boolean selectionMasked(MCTSNode node) { return selectionMasked.contains(node); }
    @Override protected void beforeBestChild(MCTSNode2 tree) {
        beforeSelectionVisits.clear();
        selectionMasked.clear();
        // Original bestChild resets these branches without changing root
        // visits. Capture their spent work before the original reset executes.
        for (MCTSNode child : tree.getChildren()) {
            beforeSelectionVisits.put(child, child.getVisits());
            if (!(child.isLegalState() || child.containsLegalNode())) selectionMasked.add(child);
        }
    }
    @Override protected MCTSNode calculateActions(Game game, ActionEncoder.ActionType type) {
        // Preserve original pruning. The bridge still accounts for every
        // initially offered action, including those removed from the tree.
        initialRootChildren = new ArrayList<>(root.getChildren());
        return super.calculateActions(game, type);
    }
    @Override public boolean chooseMulligan(Game game) {
        // WorldBuilder initializes zones itself. Full pregame search needs its
        // own bridge; no mulligan decision is made during snapshot construction.
        return false;
    }
}
