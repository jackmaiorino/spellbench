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
    /**
     * A different search over this player's original root: the DraftZero graph
     * network's BenchSearch (GnnSearch). The graph bridge binds it per request,
     * before any player or simulation copy is built, as MCTSDefaults.CURRENT is.
     * Null keeps MageZero's own tree.
     */
    public interface GraphSearch {
        Game createMCTSGame(SearchPlayer player, Game anchor);
        MCTSNode choose(SearchPlayer player, Game game, MCTSNode2 root, ActionEncoder.ActionType type);
        Map<String, Object> settings();
        Map<String, Object> searchBudget();
        List<Object> receipts();
        String variant();
    }
    /** The private pipe a graph search sends encoded states through; scores per node come back. */
    public interface GraphPipe {
        Map<String, Object> infer(Map<String, Object> graph);
    }
    public static GraphSearch GRAPH;
    private Map<MCTSNode, Integer> graphVisits = new IdentityHashMap<>();
    private Map<MCTSNode, Double> graphValues = new IdentityHashMap<>();
    private Set<MCTSNode> graphPruned = java.util.Collections.newSetFromMap(new IdentityHashMap<MCTSNode, Boolean>());
    private int graphRootVisits;
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
        if (best == null || root == null || (requireVisitBudget && rootVisits() < searchBudget)) {
            throw new IllegalStateException("original search did not complete its declared stopping rule");
        }
        if (!playerId.equals(root.playerId) || root.actionType != type
                || !observedFeatures.equals(root.stateVector)) {
            throw new IllegalStateException("search root differs from the received callback state");
        }
        return best;
    }
    public MCTSNode2 tree() { return root; }
    /** A graph search's root statistics, reported on the original root's children. */
    public void graphStatistics(Map<MCTSNode, Integer> visits, Map<MCTSNode, Double> values, Set<MCTSNode> pruned, int rootVisits) {
        graphVisits = new IdentityHashMap<>(visits); graphValues = new IdentityHashMap<>(values);
        graphPruned = java.util.Collections.newSetFromMap(new IdentityHashMap<MCTSNode, Boolean>());
        graphPruned.addAll(pruned); graphRootVisits = rootVisits;
    }
    public int rootVisits() { return GRAPH == null ? root.getVisits() : graphRootVisits; }
    public int visits(MCTSNode child) {
        if (GRAPH == null) return child.getVisits();
        Integer value = graphVisits.get(child);
        if (value == null) throw new IllegalStateException("graph search has no statistics for a root option");
        return value;
    }
    public Double meanScore(MCTSNode child) {
        if (GRAPH == null) return child.getMeanScore();
        if (!graphVisits.containsKey(child)) throw new IllegalStateException("graph search has no statistics for a root option");
        return graphValues.get(child);
    }
    /** Not part of the searched tree: MageZero's pruning, or a graph search's merged copy or dead option. */
    public boolean pruned(MCTSNode child) {
        return GRAPH == null ? !root.getChildren().contains(child) : graphPruned.contains(child);
    }
    @Override protected Game createMCTSGame(Game game) {
        return GRAPH == null ? super.createMCTSGame(game) : GRAPH.createMCTSGame(this, game);
    }
    @Override protected MCTSNode2 getNextAction(Game game, ActionEncoder.ActionType actionType) {
        if (GRAPH == null) return super.getNextAction(game, actionType);
        // ComputerPlayerMCTS2.getNextAction's original root, without its flat
        // root evaluation; the graph search starts a fresh tree every decision.
        if (stateEncoder == null) RLInit(game);
        if (actionEncoder == null) {
            actionEncoder = new ActionEncoder();
            try { printAllActionsFromDeck(getMatchPlayer().getDeck(), actionEncoder); }
            catch (mage.game.GameException e) { throw new RuntimeException(e); }
        }
        Game sim = createMCTSGame(GameAccess.lastPriority(game));
        PlayerScript prefixScript = new PlayerScript(getPlayerHistory());
        PlayerScript opponentPrefixScript = new PlayerScript(GameAccess.history(GameAccess.opponent(game, playerId)));
        MCTSNode2 newRoot = new MCTSNode2(this, sim, actionType, prefixScript, opponentPrefixScript);
        newRoot.validateState();
        newRoot.expand();
        root = newRoot;
        root.emancipate();
        return (MCTSNode2) calculateActions(game, actionType);
    }
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
        if (GRAPH != null) return GRAPH.choose(this, game, root, type);
        return super.calculateActions(game, type);
    }
    @Override public boolean chooseMulligan(Game game) {
        // WorldBuilder initializes zones itself. Full pregame search needs its
        // own bridge; no mulligan decision is made during snapshot construction.
        return false;
    }
}
