package spellbench.models.magezero.v02.search;

import mage.game.Game;
import mage.players.Player;
import spellbench.models.draftzero.gnn.encoder.FeatureGraph;
import spellbench.models.magezero.v02.encoder.ActionEncoder;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.IdentityHashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

/**
 * The DraftZero FDN graph network's played search (danieljbrooks/draft-zero@2a461518,
 * BenchPlayer.calculateActions with method "pimc"): BenchSearch.searchTree on one world,
 * a fresh tree per decision, network priors and leaf values, the most visited option.
 *
 * The world is the permitted sampled world the kit already built for this decision, so
 * BenchPlayer's extra re-deal of a live game's hidden cards (pimcFallbackWorld) has no
 * counterpart here. The root and its options are MageZero v0.2's (ComputerPlayerMCTS2's
 * root, rebuilt by SearchPlayer); the simulation players are GraphMCTSPlayer.
 */
public final class GnnSearch implements SearchPlayer.GraphSearch {
    public static final String PROFILE = "draftzero-gnn-pimc-tree-v1";
    private static final Set<String> KEYS = new HashSet<>(Arrays.asList(
            "profile", "simulations", "cPuct", "priorTemp", "priorBonus", "discount", "discountUnit",
            "leaf", "opponentPriors", "timeoutSeconds", "maxIterations"));

    private final Map<String, Object> settings;
    private final BenchSearch.Config config;
    private final GraphNet net;
    private final List<Object> receipts = new ArrayList<>();

    public GnnSearch(Map<String, Object> settings, SearchPlayer.GraphPipe pipe) {
        this.settings = checked(settings);
        if (pipe == null) throw new IllegalArgumentException("graph search needs its private pipe");
        net = new GraphNet(arrays -> scores(pipe.infer(payload(arrays)), arrays));
        config = new BenchSearch.Config();
        config.budget = ((Long) settings.get("simulations")).intValue();
        config.cPuct = Double.parseDouble((String) settings.get("cPuct"));
        config.priorTemp = Double.parseDouble((String) settings.get("priorTemp"));
        config.priorBonus = Double.parseDouble((String) settings.get("priorBonus"));
        config.discount = Double.parseDouble((String) settings.get("discount"));
        config.unit = (String) settings.get("discountUnit");
        config.leaf = (String) settings.get("leaf");
        config.opponentPriors = (String) settings.get("opponentPriors");
        config.timeoutSec = Double.parseDouble((String) settings.get("timeoutSeconds"));
        config.maxIterations = ((Long) settings.get("maxIterations")).intValue();
        config.priors = true;
        config.gnn = net;
        config.check();
    }

    /** The played configuration's explicit settings; nothing else is accepted. */
    public static Map<String, Object> checked(Map<String, Object> values) {
        if (values == null || !values.keySet().equals(KEYS) || !PROFILE.equals(values.get("profile"))) {
            throw new IllegalArgumentException("the graph network search needs every explicit setting of its profile");
        }
        Object simulations = values.get("simulations"), iterations = values.get("maxIterations");
        if (!(simulations instanceof Long) || (Long) simulations < 2 || (Long) simulations > 1000
                || !(iterations instanceof Long) || (Long) iterations != 0) {
            throw new IllegalArgumentException("graph search simulations must be 2..1000 with the source iteration cap");
        }
        Map<String, String> fixed = new LinkedHashMap<>();
        fixed.put("cPuct", "1"); fixed.put("priorTemp", "1.5"); fixed.put("priorBonus", "0.1");
        fixed.put("discount", "0.99"); fixed.put("discountUnit", "ply"); fixed.put("leaf", "net");
        fixed.put("opponentPriors", "uniform"); fixed.put("timeoutSeconds", "900");
        for (Map.Entry<String, String> entry : fixed.entrySet()) {
            if (!entry.getValue().equals(values.get(entry.getKey()))) {
                throw new IllegalArgumentException("graph search setting differs from the played configuration: " + entry.getKey());
            }
        }
        return Collections.unmodifiableMap(new LinkedHashMap<>(values));
    }

    @Override public Map<String, Object> settings() { return settings; }
    @Override public List<Object> receipts() { return receipts; }
    @Override public Map<String, Object> searchBudget() {
        Map<String, Object> budget = new LinkedHashMap<>();
        budget.put("kind", "graph_tree_simulations");
        budget.put("requested", settings.get("simulations"));
        budget.put("timeout_seconds", settings.get("timeoutSeconds"));
        return budget;
    }
    @Override public String variant() {
        return "DraftZero FDN graph network: BenchSearch one-world tree on the permitted sampled world; fresh tree per root; "
                + "PUCT c=1; softmax(1.5) priors plus 0.1 off Pass and mana abilities; uniform opponent priors; "
                + "value-head leaves discounted 0.99 per ply; most visited option; synchronous CPU float32 inference";
    }

    /** BenchPlayer.createMCTSGame: GraphMCTSPlayer simulation players keep the encoder's decision context. */
    @Override public Game createMCTSGame(SearchPlayer player, Game game) {
        Game mcts = game.createSimulationForAI();
        for (Player copyPlayer : mcts.getState().getPlayers().values()) {
            Player origPlayer = game.getState().getPlayers().get(copyPlayer.getId());
            GraphMCTSPlayer newPlayer = new GraphMCTSPlayer(copyPlayer.getId(), player.getId(), player.stateEncoder);
            newPlayer.restore(origPlayer);
            newPlayer.setMatchPlayer(origPlayer.getMatchPlayer());
            mcts.getState().getPlayers().put(copyPlayer.getId(), newPlayer);
        }
        mcts.pause();
        GameAccess.setMctsSimulation(mcts, true);
        return mcts;
    }

    @Override public MCTSNode choose(SearchPlayer player, Game game, MCTSNode2 r, ActionEncoder.ActionType action) {
        List<MCTSNode> kids = r.getChildren();
        if (kids.isEmpty()) return null;
        UUID me = player.getId();
        // keys of MageZero's options, as BenchPlayer takes them before searching
        Map<String, List<MCTSNode>> byKey = new LinkedHashMap<>();
        for (MCTSNode c : kids) {
            String key = BenchSearch.key(c, action, r.getGame(), me);
            if (!byKey.containsKey(key)) byKey.put(key, new ArrayList<MCTSNode>());
            byKey.get(key).add(c);
        }
        PlayerScript a = new PlayerScript(player.getPlayerHistory());
        PlayerScript b = new PlayerScript(GameAccess.history(GameAccess.opponent(game, me)));
        // BenchPlayer searches a fresh copy of the root: r is already expanded.
        MCTSNode2 rk = new MCTSNode2(player, createMCTSGame(player, GameAccess.lastPriority(game)), action,
                new PlayerScript(a), new PlayerScript(b));
        rk.validateState();
        if (!rk.isTerminal() && rk.getPlayer().scriptFailed) {
            throw new IllegalStateException("graph search world does not replay to its root");
        }
        long before = net.calls;
        BenchSearch.Result res = BenchSearch.searchTree(new BenchSearch.World(rk, player, a, b, action, game), config);
        if (res.stats.timedOut) throw new IllegalStateException("graph search reached its source timeout");
        Map<String, Integer> visits = new HashMap<>();
        Map<String, Double> weighted = new HashMap<>();
        for (BenchSearch.RootChild k : res.children) {
            if (!byKey.containsKey(k.key)) throw new IllegalStateException("graph search root option is not an original option");
            visits.merge(k.key, k.visits, Integer::sum);
            if (k.q != null && k.visits > 0) weighted.merge(k.key, k.q * k.visits, Double::sum);
        }
        // BenchPlayer's choice: the first most visited key, in its HashMap's order, and that key's first option.
        String bestKey = null;
        int bestN = -1;
        for (Map.Entry<String, Integer> e : visits.entrySet()) {
            if (byKey.containsKey(e.getKey()) && e.getValue() > bestN) {
                bestN = e.getValue();
                bestKey = e.getKey();
            }
        }
        if (bestKey == null || bestN <= 0) throw new IllegalStateException("graph search visited no original option");
        Map<MCTSNode, Integer> reportedVisits = new IdentityHashMap<>();
        Map<MCTSNode, Double> values = new IdentityHashMap<>();
        Set<MCTSNode> pruned = Collections.newSetFromMap(new IdentityHashMap<MCTSNode, Boolean>());
        int total = 0;
        for (Map.Entry<String, List<MCTSNode>> e : byKey.entrySet()) {
            List<MCTSNode> copies = e.getValue();
            Integer n = visits.get(e.getKey());
            for (int i = 0; i < copies.size(); i++) {
                MCTSNode c = copies.get(i);
                // One key is one option to the search: its first copy carries the statistics.
                if (i > 0 || n == null) {
                    reportedVisits.put(c, 0);
                    pruned.add(c);
                    continue;
                }
                reportedVisits.put(c, n);
                values.put(c, n > 0 ? weighted.getOrDefault(e.getKey(), 0.0) / n : 0.0);
                total += n;
            }
        }
        if (total != res.rootVisits) throw new IllegalStateException("graph search root visits are unaccounted");
        player.graphStatistics(reportedVisits, values, pruned, total);
        Map<String, Object> receipt = new LinkedHashMap<>();
        receipt.put("type", action.name());
        receipt.put("simulations", res.stats.sims);
        receipt.put("iterations", res.stats.iterations);
        receipt.put("root_visits", (long) res.rootVisits);
        receipt.put("network_calls", net.calls - before);
        receipt.put("script_failures", res.stats.scriptFailures);
        receipt.put("max_depth", (long) res.stats.maxDepth);
        receipt.put("root_q", res.rootQ);
        receipt.put("root_value", res.rootNet);
        receipt.put("merged_copies", (long) (kids.size() - byKey.size()));
        receipts.add(receipt);
        return byKey.get(bestKey).get(0);
    }

    static Map<String, Object> payload(FeatureGraph.GraphArrays a) {
        Map<String, Object> graph = new LinkedHashMap<>();
        graph.put("indices", longs(a.ids));
        graph.put("values", longs(a.values));
        graph.put("edge_child", longs(a.edgeChild));
        graph.put("edge_parent", longs(a.edgeParent));
        graph.put("edge_label", longs(a.edgeLabel));
        return graph;
    }

    private static List<Object> longs(int[] xs) {
        List<Object> out = new ArrayList<>(xs.length);
        for (int x : xs) out.add((long) x);
        return out;
    }

    /** The confined network's per-node scores (null: -inf at a leaf), as DraftZero's graph server sends them. */
    static GraphNet.Out scores(Map<String, Object> reply, FeatureGraph.GraphArrays a) {
        if (reply == null) throw new IllegalArgumentException("graph network returned no scores");
        float[] priority = heads(reply.get("priority"), a.ids.length, true);
        float[] target = heads(reply.get("target"), a.ids.length, true);
        float[] use = heads(reply.get("use"), 2, false);
        Object value = reply.get("value");
        if (!(value instanceof Number) || !Double.isFinite(((Number) value).doubleValue())) {
            throw new IllegalArgumentException("graph network value is not finite");
        }
        return GraphNet.out(((Number) value).floatValue(), priority, target, use, a.localIndex);
    }

    private static float[] heads(Object raw, int width, boolean leaves) {
        if (!(raw instanceof List) || ((List<?>) raw).size() != width) {
            throw new IllegalArgumentException("graph network head has the wrong width");
        }
        float[] out = new float[width];
        for (int i = 0; i < width; i++) {
            Object x = ((List<?>) raw).get(i);
            if (x == null && leaves) {
                out[i] = Float.NEGATIVE_INFINITY;
            } else if (x instanceof Number && Double.isFinite(((Number) x).doubleValue())) {
                out[i] = ((Number) x).floatValue();
            } else {
                throw new IllegalArgumentException("graph network score is not finite");
            }
        }
        return out;
    }
}
