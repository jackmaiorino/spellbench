package spellbench.kit.xmage;

import mage.game.Game;
import mage.game.turn.Step;
import mage.constants.PhaseStep;
import mage.player.ai.encoder.ActionEncoder;
import mage.player.cabt.CardResolver;
import mage.player.spellbench.Warmup;
import spellbench.kit.core.Json;
import spellbench.kit.core.Sampler;
import spellbench.kit.core.Seeds;
import spellbench.models.exp1.GameAccess;
import spellbench.models.exp1.MCTSNode;
import spellbench.models.exp1.MCTSNode2;
import spellbench.models.exp1.RemoteModelEvaluator;
import spellbench.models.exp1.SearchPlayer;

import java.io.BufferedReader;
import java.io.FileDescriptor;
import java.io.FileOutputStream;
import java.io.InputStreamReader;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

/** Original Exp1 per-creature combat loops, with private neural RPC and work receipts. */
public final class ModelCombatMain {
    private static BufferedReader in;
    private static PrintStream out;
    private static Object requestId;
    private static long calls;

    static void bindPipe(BufferedReader input, PrintStream output) { in = input; out = output; }
    static long neuralCalls() { return calls; }
    static Map<String, Object> execute(Map<String, Object> record) {
        requestId = record.get("id"); calls = 0;
        if (!(requestId instanceof String)) throw new IllegalArgumentException("combat request id must be a string");
        return plan(record);
    }

    private static byte[] seed(String value) {
        if (value == null || !value.matches("[a-f0-9]{64}")) throw new IllegalArgumentException("combat seed envelope");
        return Seeds.unhex(value);
    }
    private static float[] head(Map<String, Object> scores, String name) {
        List<Object> values = Json.arr(scores, name);
        float[] result = new float[values.size()];
        for (int i = 0; i < values.size(); i++) {
            if (!(values.get(i) instanceof Number)) throw new IllegalArgumentException("neural head is not numeric");
            result[i] = ((Number) values.get(i)).floatValue();
        }
        return result;
    }
    private static RemoteModelEvaluator.InferenceResult infer(long[] features) {
        long call = ++calls;
        List<Object> ids = new ArrayList<>();
        for (long feature : features) ids.add(feature);
        out.println(Json.canonical(Json.map("id", requestId, "event", "infer", "call", call, "features", ids)));
        try {
            String line = in.readLine();
            if (line == null) throw new IllegalStateException("combat neural transport EOF");
            Map<String, Object> reply = Json.parseObject(line);
            if (!requestId.equals(reply.get("id")) || !(reply.get("call") instanceof Number)
                    || ((Number) reply.get("call")).doubleValue() != call || !Boolean.TRUE.equals(reply.get("ok"))) {
                throw new IllegalArgumentException("stale or failed neural transport response");
            }
            Map<String, Object> scores = Json.obj(reply, "scores");
            Object value = scores.get("value");
            if (!(value instanceof Number)) throw new IllegalArgumentException("neural value is not numeric");
            return new RemoteModelEvaluator.InferenceResult(head(scores, "priority"), head(scores, "opponent_priority"),
                    head(scores, "target"), head(scores, "binary"), ((Number) value).floatValue());
        } catch (java.io.IOException e) { throw new IllegalStateException("combat neural transport failed", e); }
    }
    private static String hash(Object value) {
        try { return Seeds.hex(MessageDigest.getInstance("SHA-256").digest(Json.canonical(value).getBytes(StandardCharsets.UTF_8))); }
        catch (java.security.NoSuchAlgorithmException e) { throw new IllegalStateException(e); }
    }
    private static String family(Map<String, Object> decision) {
        String kind = null;
        for (Object item : Json.arr(decision, "candidates")) {
            String next = Json.str(Json.obj(Json.obj(item), "semantic"), "kind");
            if (!("declare_attack".equals(next) || "declare_block".equals(next)) || kind != null && !kind.equals(next)) {
                throw new IllegalArgumentException("combat root must have one declaration family");
            }
            kind = next;
        }
        if (kind == null) throw new IllegalArgumentException("combat root has no offered choices");
        return "declare_attack".equals(kind) ? "attack" : "block";
    }
    private static void supported(World world) {
        for (String flag : world.flags) if (flag.startsWith("unsupported:") || flag.startsWith("horizon:")) {
            throw new IllegalArgumentException("combat world is unsupported: " + flag);
        }
    }
    static final class CombatPlayer extends SearchPlayer {
        private Game liveGame;
        private World world;
        private int visits;
        private final List<Object> roots = new ArrayList<>();
        CombatPlayer(String seat) { super(seat); }
        private CombatPlayer(CombatPlayer player) { super(player); }
        @Override public CombatPlayer copy() { return new CombatPlayer(this); }
        void begin(World built, RemoteModelEvaluator model, int budget) {
            world = built; liveGame = built.game; visits = budget;
            configure(model, budget);
        }
        @Override protected Game createMCTSGame(Game anchor) {
            if (anchor.getStep() == null || anchor.getStep().getStepPart() != Step.StepPart.PRE
                    || !(anchor.getTurnStepType() == PhaseStep.DECLARE_ATTACKERS
                         || anchor.getTurnStepType() == PhaseStep.DECLARE_BLOCKERS)) {
                throw new IllegalArgumentException("combat search requires its initial declaration anchor");
            }
            Game simulation = super.createMCTSGame(anchor);
            // createMCTSGame pauses its copy. This reconstructed anchor precedes
            // declarations, so resume must run beginStep rather than finalize
            // declarations through resumeBeginStep. Later saved priority states
            // keep their normal paused status in the original tree.
            simulation.getState().resume();
            return simulation;
        }
        private Object action(MCTSNode child, ActionEncoder.ActionType type) {
            if (type == ActionEncoder.ActionType.CHOOSE_USE) return child.getUseAction();
            if (type != ActionEncoder.ActionType.CHOOSE_TARGET) throw new IllegalArgumentException("unexpected original combat search root");
            UUID target = child.getTargetAction();
            if (GameAccess.STOP_CHOOSING.equals(target)) return null;
            String id = world.uuidToId.get(target);
            if (id == null) throw new IllegalArgumentException("combat target is not a permitted visible object");
            return id;
        }
        @Override protected MCTSNode2 getNextAction(Game game, ActionEncoder.ActionType type) {
            if (game != liveGame) return super.getNextAction(game, type);
            // Match the existing play variant: a fresh tree at each real root.
            resetSearchTree();
            long before = calls;
            MCTSNode2 chosen = super.getNextAction(game, type);
            requireRootType(type);
            MCTSNode2 tree = tree();
            if (chosen == null || tree == null || tree.getVisits() < visits || calls <= before) {
                throw new IllegalStateException("original combat root did not complete real neural work");
            }
            Set<MCTSNode> retained = new HashSet<>(tree.getChildren());
            List<Object> children = new ArrayList<>();
            Set<String> keys = new HashSet<>();
            for (MCTSNode child : initialRootChildren()) {
                Object pick = action(child, type);
                if (!keys.add(Json.canonical(pick))) throw new IllegalArgumentException("aliased combat root action");
                boolean pruned = !retained.contains(child), masked = !pruned && selectionMasked(child);
                children.add(Json.map("action", pick, "visits", pruned ? 0L : (long) child.getVisits(),
                        "value", pruned || masked ? null : child.getMeanScore(), "pruned", pruned,
                        "selection_masked", masked, "discarded_visits", masked ? (long) discardedSelectionVisits(child) : 0L));
            }
            roots.add(Json.map("index", (long) roots.size(), "type", type.name(), "selected", action(chosen, type),
                    "root_visits", (long) tree.getVisits(), "requested_minimum", (long) visits,
                    "neural_calls", calls - before, "children", children));
            return chosen;
        }
    }
    static Map<String, Object> plan(Map<String, Object> record) {
        if (!ActionEncoder.vocabLoaded() || ActionEncoder.ACTION_DIM != 1024) throw new IllegalArgumentException("Exp1 action vocabulary");
        Object count = record.get("visits");
        if (!(count instanceof Number) || ((Number) count).doubleValue() != ((Number) count).intValue()) {
            throw new IllegalArgumentException("integer combat visit budget required");
        }
        Map<String, Object> decision = Json.obj(record, "decision");
        String path = family(decision);
        Map<String, Object> obs = Json.obj(Json.copy(decision.get("observation")));
        String viewer = Json.str(obs, "viewer"), active = Json.str(obs, "active_seat");
        if ("attack".equals(path) != viewer.equals(active)) throw new IllegalArgumentException("combat root belongs to another seat");
        String expectedStep = "attack".equals(path) ? "declare_attackers" : "declare_blockers";
        if (!expectedStep.equals(Json.str(obs, "phase_step"))) throw new IllegalArgumentException("combat phase differs");
        // A complete plan starts before this seat's declarations. Later wire
        // substeps must bind to the retained plan, rather than silently restart.
        for (Object item : Json.arr(obs, "players")) {
            Map<String, Object> player = Json.obj(item);
            if (!viewer.equals(Json.str(player, "seat"))) continue;
            for (Object object : Json.arr(player, "battlefield")) {
                Map<String, Object> permanent = Json.obj(Json.obj(object), "permanent");
                if (permanent != null && Json.bool(permanent, "attack".equals(path) ? "attacking" : "blocking")) {
                    throw new IllegalArgumentException("combat plan needs its initial declaration root");
                }
            }
        }
        KitContext.reset(); GameAccess.reset(); KitRandom.installBoot();
        List<String> nameFlags = WorldBuilder.restoreVisibleNames(obs, Json.obj(decision, "x_history"));
        KitRandom random = KitRandom.install(seed(Json.str(record, "world_seed")), seed(Json.str(record, "id_seed")));
        CombatPlayer[] player = new CombatPlayer[1];
        WorldBuilder.Spec spec = new WorldBuilder.Spec();
        spec.gameStart = Json.obj(record, "game_start"); spec.observation = obs; spec.random = random;
        spec.sample = Sampler.sample(spec.gameStart, obs, random.stream("sampler"));
        spec.mode = "attack".equals(path) ? WorldBuilder.Mode.ATTACK : WorldBuilder.Mode.BLOCK;
        spec.history = Json.obj(decision, "x_history");
        spec.viewerFactory = seat -> player[0] = new CombatPlayer(seat); spec.otherFactory = Puppet::new;
        World world = WorldBuilder.build(spec); world.flags.addAll(nameFlags); supported(world);
        player[0].begin(world, new RemoteModelEvaluator(ModelCombatMain::infer), ((Number) count).intValue());
        Game game = world.game;
        if (game.isSimulation()) throw new IllegalArgumentException("initial combat plan must execute original decision callbacks");
        GameAccess.setLastPriority(game, player[0].getId());
        if ("attack".equals(path)) player[0].selectAttackers(game, player[0].getId());
        else player[0].selectBlockers(null, game, player[0].getId());
        supported(world);
        long accounted = 0;
        for (Object value : player[0].roots) accounted += Json.num(Json.obj(value), "neural_calls", -1L);
        if (accounted != calls) throw new IllegalStateException("combat neural work is unaccounted");
        world.flags.add("approximate:initial_combat_anchor_resume");
        world.flags.add("approximate:exp1_combat_simulation_flag_port");
        return Json.map("decision_sha256", hash(decision), "combat", path, "pairs", Runner.combatPairs(world, game, "attack".equals(path)),
                "roots", player[0].roots, "neural_calls", calls, "world_flags", world.flags,
                "variant", "original Exp1 per-creature binary attacks and target blocks; sampled permitted world; fresh tree per callback; all priors; original minimum visits and legal-future stopping; no noise",
                "scope", "combat plan and callback receipts; complete-game agent and fork simulation-flag parity unfinished");
    }
    public static void main(String[] args) throws Exception {
        if (args.length != 0) throw new IllegalArgumentException("private NDJSON combat pipe takes no arguments");
        out = new PrintStream(new FileOutputStream(FileDescriptor.out), true, "UTF-8");
        System.setOut(System.err); Runner.quietLogs(); KitRandom.installBoot(); Warmup.framework();
        new CardResolver().resolve("Plains");
        in = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        out.println(Json.canonical(Json.map("ready", true, "search", "draftzero-exp1-original-combat")));
        String line;
        while ((line = in.readLine()) != null) {
            Map<String, Object> record = null;
            try {
                record = Json.parseObject(line);
                Map<String, Object> result = execute(record);
                out.println(Json.canonical(Json.map("id", requestId, "event", "result", "ok", true, "result", result)));
            } catch (RuntimeException e) {
                e.printStackTrace(System.err);
                out.println(Json.canonical(Json.map("id", record == null ? null : record.get("id"), "event", "result", "ok", false,
                        "error", e.toString(), "neural_calls", calls)));
            } finally { GameAccess.reset(); }
        }
    }
}
