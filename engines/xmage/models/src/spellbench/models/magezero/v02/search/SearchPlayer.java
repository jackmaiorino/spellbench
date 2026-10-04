package spellbench.models.magezero.v02.search;

import mage.constants.RangeOfInfluence;
import mage.game.Game;
import mage.abilities.Ability;
import mage.choices.Choice;
import spellbench.models.magezero.v02.encoder.ActionEncoder;
import java.util.HashSet;
import java.util.Set;
import java.util.List;
import java.util.ArrayList;
import java.util.Map;
import java.util.IdentityHashMap;
import spellbench.models.magezero.v02.search.MCTSNode;

/** Original MageZero v0.2 tree with an explicit deterministic, no-noise play profile. */
public class SearchPlayer extends ComputerPlayerMCTS2 {
    private boolean requireVisitBudget;
    private List<MCTSNode> initialRootChildren = new ArrayList<>();
    private Map<MCTSNode, Integer> beforeSelectionVisits = new IdentityHashMap<>();
    private Set<MCTSNode> selectionMasked = java.util.Collections.newSetFromMap(new IdentityHashMap<MCTSNode, Boolean>());
    public SearchPlayer(String name) { super(name, RangeOfInfluence.ALL, 6); }
    protected SearchPlayer(SearchPlayer player) { super(player); requireVisitBudget = player.requireVisitBudget; }
    @Override public SearchPlayer copy() { return new SearchPlayer(this); }
    public void configure(RemoteModelEvaluator model, MCTSDefaults settings) {
        if (model == null || settings == null || settings.searchBudget < 2 || settings.searchBudget > 1000
                || !Double.isFinite(settings.searchTimeout) || settings.searchTimeout <= 0 || settings.searchTimeout > 600
                || !Double.isFinite(settings.priorTemp) || settings.priorTemp < 0
                || !Double.isFinite(settings.priorBonus) || settings.priorBonus < 0
                || !Double.isFinite(settings.backpropDiscount) || settings.backpropDiscount < 0 || settings.backpropDiscount > 1
                || !Double.isFinite(settings.selectionTemperature) || settings.selectionTemperature < 0
                || !Double.isFinite(settings.dirichletNoiseEps) || settings.dirichletNoiseEps < 0 || settings.dirichletNoiseEps > 1) {
            throw new IllegalArgumentException("MageZero needs explicit supported source search settings");
        }
        nn = model;
        actionEncoder = new ActionEncoder();
        searchBudget = settings.searchBudget;
        searchTimeout = settings.searchTimeout;
        noNoise = settings.noNoise;
        noPolicyPriority = settings.noPolicyPriority;
        noPolicyTarget = settings.noPolicyTarget;
        noPolicyUse = settings.noPolicyUse;
        noPolicyOpponent = settings.noPolicyOpponent;
        priorTemp = settings.priorTemp;
        priorBonus = settings.priorBonus;
        backpropDiscount = settings.backpropDiscount;
        selectionTemperature = settings.selectionTemperature;
        dirichletNoiseEps = settings.dirichletNoiseEps;
        requireVisitBudget = false;
        offlineMode = false;
        SHOW_THREAD_INFO = false;
    }
    public void configureDiagnostic(RemoteModelEvaluator model, int visits) {
        MCTSDefaults settings = new MCTSDefaults();
        settings.searchBudget = visits;
        settings.searchTimeout = 600;
        settings.noNoise = true;
        settings.noPolicyPriority = settings.noPolicyTarget = settings.noPolicyUse = settings.noPolicyOpponent = false;
        configure(model, settings);
        requireVisitBudget = true;
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
        resetSearchTree();
        MCTSNode2 best = getNextAction(game, type);
        if (best == null || root == null || (requireVisitBudget && root.getVisits() < searchBudget)) {
            throw new IllegalStateException("original search did not complete its declared stopping rule");
        }
        if (!playerId.equals(root.playerId) || root.actionType != type
                || !observedFeatures.equals(root.stateVector)) {
            throw new IllegalStateException("search root differs from the received callback state");
        }
        return best;
    }
    public MCTSNode2 tree() { return root; }
    protected void resetSearchTree() { root = null; }
    protected void requireRootType(ActionEncoder.ActionType type) {
        if (root == null || root.actionType != type || !playerId.equals(root.playerId)) {
            throw new IllegalStateException("original search resumed a different callback or player");
        }
    }
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
