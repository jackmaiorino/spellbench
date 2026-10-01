package spellbench.kit.xmage;

import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.UUID;

/**
 * The budgets, horizon and counters of the world the runner is working on (design Sections 5.4 and 5.6). One world
 * at a time per runner process (Section 5.4 item 1: {@code SimulationNode2.nodeCount} is static as well), so this is
 * process-wide state, reset before each world. The vendored bots (kit diffs of MAD and MCTS) read it.
 */
public final class KitContext {

    private KitContext() {
    }

    // ------------------------------------------------------------------ budgets (slice exit criterion E2)

    /** MAD node budget per decision (replaces MAX_SIMULATED_NODES_PER_CALC); error threshold is this + 100. */
    public static int nodeBudget = 5000;
    /** Options generated per playable ability (targets, modes, cost targets, X values). */
    public static int optionBudget = 2000;
    /** Callbacks of the simulated players per simulation (one root alternative of MAD, one MCTS iteration). */
    public static int opCap = 20000;
    /** MCTS completed iterations per world. */
    public static int mctsIterations = 300;
    /** MCTS rollout length cap (priority callbacks in one rollout). */
    public static int rolloutCap = 2000;

    // ------------------------------------------------------------------ horizon (Section 5.6)

    /** UUIDs of stack objects the rebuild flagged approximate: no simulated game may resolve them. */
    public static final Set<UUID> horizon = new HashSet<>();

    // ------------------------------------------------------------------ counters

    private static final Map<String, Long> counters = new TreeMap<>();
    private static long ops;
    private static boolean exceeded;
    /** A test hook for E3: when set, the next search never returns (it ignores interruption). */
    public static volatile boolean hangHook;

    /** Thrown past the operation cap; an Error so XMage's catch(Exception) blocks do not swallow it. */
    public static final class BudgetExceeded extends Error {
        private static final long serialVersionUID = 1L;

        public BudgetExceeded(String kind) {
            super("kit budget exceeded: " + kind, null, false, false);
        }
    }

    public static synchronized void reset() {
        horizon.clear();
        counters.clear();
        ops = 0;
        exceeded = false;
    }

    public static synchronized void count(String key) {
        counters.merge(key, 1L, Long::sum);
    }

    public static synchronized void count(String key, long n) {
        counters.merge(key, n, Long::sum);
    }

    public static synchronized Map<String, Long> counters() {
        return new LinkedHashMap<>(counters);
    }

    /** Starts one simulation (a root alternative of MAD, an MCTS iteration): the operation counter restarts. */
    public static synchronized void beginSimulation() {
        ops = 0;
        exceeded = false;
    }

    /**
     * One callback of a simulated player. Past the cap the simulation is stopped by {@link BudgetExceeded}; the
     * stop is sticky until the next {@link #beginSimulation}, so a path that swallows it is stopped again at its next
     * callback.
     */
    public static void op(String where) {
        boolean stop;
        synchronized (KitContext.class) {
            ops++;
            stop = exceeded || ops > opCap;
            if (stop) {
                if (!exceeded) {
                    counters.merge("cap:operations", 1L, Long::sum);
                }
                exceeded = true;
                counters.merge("budget_thrown", 1L, Long::sum);
            }
        }
        if (stop) {
            throw new BudgetExceeded("operations at " + where);
        }
    }

    /** The kit's boundary caught a stop. */
    public static synchronized void caught(String where) {
        counters.merge("budget_caught:" + where, 1L, Long::sum);
    }

    public static synchronized boolean isExceeded() {
        return exceeded;
    }

    // ------------------------------------------------------------------ H3 (MCTS) support

    /** The world being searched (payload witness mapping) and the decider's score at the decision. */
    public static World world;
    public static int baseline;
    /** Set when the current rollout stopped at the horizon or a cap. */
    public static boolean rolloutTruncated;
    private static int rolloutSteps;

    /** One priority callback of a rollout; past the rollout cap the rollout stops. */
    public static void rolloutStep() {
        boolean stop;
        synchronized (KitContext.class) {
            rolloutSteps++;
            stop = rolloutSteps > rolloutCap;
        }
        if (stop) {
            count("cap:rollout");
            throw new BudgetExceeded("rollout");
        }
    }

    public static synchronized void beginRollout() {
        rolloutSteps = 0;
        rolloutTruncated = false;
    }

    /**
     * Design 5.6 truncation result: a win when the decider's evaluation at this point exceeds its evaluation in the
     * world at the decision, else not a win.
     */
    public static int truncationResult(mage.game.Game sim, UUID decider) {
        int score = mage.player.ai.score.GameStateEvaluator2.evaluate(decider, sim).getTotalScore();
        return score > baseline ? 1 : -1;
    }

    /** The executed payload of the activation that took the stack from {@code before} objects (5.5.3). */
    public static Map<String, Object> witness(mage.game.Game sim, int before) {
        if (world == null || sim.getStack().size() <= before) {
            return new LinkedHashMap<>();
        }
        return Mapping.payload(world, Mapping.executedAbility(sim.getStack().getFirstOrNull()), sim);
    }

    /**
     * True when a pass by {@code playerId} (or the pass it just made) would let the stack's top object resolve and
     * that object is flagged: every other player has passed and the top is in {@link #horizon}.
     */
    public static boolean passWouldResolveFlagged(mage.game.Game game, UUID playerId, mage.abilities.Ability ability) {
        if (ability != null && !(ability instanceof mage.abilities.common.PassAbility)) {
            return false;
        }
        mage.game.stack.StackObject top = game.getStack().getFirstOrNull();
        if (top == null || !horizon.contains(top.getId())) {
            return false;
        }
        for (mage.players.Player p : game.getPlayers().values()) {
            if (!p.getId().equals(playerId) && !p.isPassed() && p.canRespond()) {
                return false;
            }
        }
        return true;
    }
}
