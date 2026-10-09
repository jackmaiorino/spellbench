package spellbench.kit.xmage;

import mage.player.cabt.CardResolver;
import mage.player.spellbench.Warmup;
import spellbench.kit.core.Json;
import spellbench.kit.core.ObsIndex;
import spellbench.kit.core.Sampler;
import spellbench.kit.core.Seeds;
import spellbench.models.magezero.v02.search.GameAccess;
import spellbench.models.magezero.v02.search.MCTSDefaults;
import spellbench.models.magezero.v02.search.MCTSNode;
import spellbench.models.magezero.v02.search.MCTSNode2;
import spellbench.models.magezero.v02.search.RemoteModelEvaluator;
import spellbench.models.magezero.v02.search.SearchPlayer;

import java.io.BufferedReader;
import java.io.FileDescriptor;
import java.io.FileOutputStream;
import java.io.InputStreamReader;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** Original 128-slot MageZero search and public callback replay over permitted sampled worlds. */
public final class MageZeroSearchMain {
    private static BufferedReader in;
    private static PrintStream out;
    private static long calls;
    private static Object requestId;
    static void bindPipe(BufferedReader input, PrintStream output) { in = input; out = output; }
    static long neuralCalls() { return calls; }
    static Map<String, Object> execute(Map<String, Object> record) {
        calls = 0; requestId = record.get("id");
        if (!(requestId instanceof String)) throw new IllegalArgumentException("search request id must be a string");
        return search(record);
    }
    private static final Set<String> SETTING_KEYS = new HashSet<>(Arrays.asList(
            "profile", "searchBudget", "searchTimeout", "backpropDiscount", "priorTemp", "priorBonus",
            "noNoise", "dirichletNoiseEps", "selectionTemperature", "noPolicyPriority", "noPolicyTarget",
            "noPolicyUse", "noPolicyOpponent"));

    private static double decimal(Map<String, Object> values, String key, double max, boolean positive) {
        Object value = values.get(key);
        if (!(value instanceof String) || !((String) value).matches("(?:0|[1-9][0-9]*)(?:\\.[0-9]+)?")) {
            throw new IllegalArgumentException("explicit decimal search setting required: " + key);
        }
        double number = Double.parseDouble((String) value);
        if (!Double.isFinite(number) || number < 0 || number > max || positive && number == 0) {
            throw new IllegalArgumentException("search setting is outside its envelope: " + key);
        }
        return number;
    }
    private static boolean bool(Map<String, Object> values, String key) {
        Object value = values.get(key);
        if (!(value instanceof Boolean)) throw new IllegalArgumentException("explicit boolean search setting required: " + key);
        return (Boolean) value;
    }
    public static MCTSDefaults settings(Map<String, Object> values) {
        if (values == null || !values.keySet().equals(SETTING_KEYS)) {
            throw new IllegalArgumentException("MageZero needs every explicit original search setting");
        }
        String profile = Json.str(values, "profile");
        if (!("original-source-time-or-visits".equals(profile) || "minimum-visits-diagnostic".equals(profile))) {
            throw new IllegalArgumentException("unsupported MageZero stopping profile");
        }
        Object count = values.get("searchBudget");
        if (!(count instanceof Long) || (Long) count < 2 || (Long) count > 1000) {
            throw new IllegalArgumentException("MageZero visit budget must be 2..1000");
        }
        MCTSDefaults result = new MCTSDefaults();
        result.searchBudget = ((Long) count).intValue();
        result.searchTimeout = decimal(values, "searchTimeout", 600, true);
        result.backpropDiscount = decimal(values, "backpropDiscount", 1, false);
        result.priorTemp = decimal(values, "priorTemp", Double.MAX_VALUE, true);
        result.priorBonus = decimal(values, "priorBonus", Double.MAX_VALUE, false);
        result.dirichletNoiseEps = decimal(values, "dirichletNoiseEps", 0, false);
        result.selectionTemperature = decimal(values, "selectionTemperature", 0, false);
        result.noNoise = bool(values, "noNoise");
        if (!result.noNoise) throw new IllegalArgumentException("MageZero search bridge requires no-noise selection");
        result.noPolicyPriority = bool(values, "noPolicyPriority");
        result.noPolicyTarget = bool(values, "noPolicyTarget");
        result.noPolicyUse = bool(values, "noPolicyUse");
        result.noPolicyOpponent = bool(values, "noPolicyOpponent");
        if ("minimum-visits-diagnostic".equals(profile) && (
                !"600".equals(values.get("searchTimeout")) || !"0.99".equals(values.get("backpropDiscount"))
                || !"1.5".equals(values.get("priorTemp")) || !"0.1".equals(values.get("priorBonus"))
                || !"0".equals(values.get("dirichletNoiseEps")) || !"0".equals(values.get("selectionTemperature"))
                || result.noPolicyPriority || result.noPolicyTarget || result.noPolicyUse || result.noPolicyOpponent)) {
            throw new IllegalArgumentException("MageZero diagnostic profile requires its exact declared settings");
        }
        return result;
    }
    private static float[] head(Map<String, Object> scores, String name) {
        List<Object> values = Json.arr(scores, name);
        float[] result = new float[values.size()];
        for (int i = 0; i < values.size(); i++) {
            if (!(values.get(i) instanceof Number)) throw new IllegalArgumentException("neural head element is not numeric");
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
            if (line == null) throw new IllegalStateException("neural transport EOF");
            Map<String, Object> reply = Json.parseObject(line);
            if (!requestId.equals(reply.get("id")) || !(reply.get("call") instanceof Long)
                    || (Long) reply.get("call") != call || !Boolean.TRUE.equals(reply.get("ok"))) {
                throw new IllegalArgumentException("stale or failed neural transport response");
            }
            Map<String, Object> scores = Json.obj(reply, "scores");
            Object value = scores.get("value");
            if (!(value instanceof Number)) throw new IllegalArgumentException("neural value is not numeric");
            return new RemoteModelEvaluator.InferenceResult(head(scores, "priority"), head(scores, "opponent_priority"),
                    head(scores, "target"), head(scores, "binary"), ((Number) value).floatValue());
        } catch (java.io.IOException e) { throw new IllegalStateException("neural transport failed", e); }
    }
    /** One encoded state for a bound graph search (SearchPlayer.GRAPH) on this request's pipe. */
    static Map<String, Object> inferGraph(Map<String, Object> graph) {
        long call = ++calls;
        out.println(Json.canonical(Json.map("id", requestId, "event", "infer", "call", call, "graph", graph)));
        try {
            String line = in.readLine();
            if (line == null) throw new IllegalStateException("graph network transport EOF");
            Map<String, Object> reply = Json.parseObject(line);
            if (!requestId.equals(reply.get("id")) || !(reply.get("call") instanceof Long)
                    || (Long) reply.get("call") != call || !Boolean.TRUE.equals(reply.get("ok"))) {
                throw new IllegalArgumentException("stale or failed graph network transport response");
            }
            return Json.obj(reply, "scores");
        } catch (java.io.IOException e) { throw new IllegalStateException("graph network transport failed", e); }
    }
    /** Valid original defaults for the bound graph search: its own settings drive the tree. */
    static MCTSDefaults graphDefaults(Map<String, Object> values, SearchPlayer.GraphSearch graph) {
        if (values == null || !Json.canonical(values).equals(Json.canonical(graph.settings()))) {
            throw new IllegalArgumentException("graph search request differs from its bound settings");
        }
        MCTSDefaults result = new MCTSDefaults();
        result.searchBudget = 2; result.searchTimeout = 600; result.noNoise = true;
        return result;
    }
    private static byte[] seed(String value) {
        if (value == null || !value.matches("[a-f0-9]{64}")) throw new IllegalArgumentException("search seed envelope");
        return Seeds.unhex(value);
    }
    private static Map<String, Object> search(Map<String, Object> record) {
        Map<String, Object> decision = Json.obj(record, "decision");
        Map<String, Object> context = Json.obj(decision, "context");
        Map<String, Object> start = Json.obj(record, "game_start");
        String viewer = Json.str(Json.obj(decision, "observation"), "viewer");
        if (!Boolean.FALSE.equals(context.get("rewind"))
                || !("p0".equals(viewer) || "p1".equals(viewer)) || !viewer.equals(Json.str(start, "seat"))
                || !viewer.equals(Json.str(decision, "acting_seat"))) {
            throw new IllegalArgumentException("MageZero search needs a non-rewound own decision");
        }
        boolean priority = "priority".equals(Json.str(context, "kind"));
        Map<String, Object> values = Json.obj(record, "settings");
        SearchPlayer.GraphSearch graph = SearchPlayer.GRAPH;
        MCTSDefaults configured = graph == null ? settings(values) : graphDefaults(values, graph);
        boolean diagnostic = graph == null && "minimum-visits-diagnostic".equals(Json.str(values, "profile"));
        // Original constructors and copy field initializers read CURRENT.
        // Bind the explicit settings before building or replaying the world.
        MCTSDefaults.CURRENT = configured;
        seed(Json.str(record, "world_seed")); seed(Json.str(record, "id_seed"));
        RemoteModelEvaluator evaluator = new RemoteModelEvaluator(MageZeroSearchMain::infer);
        SearchPlayer active;
        World world;
        MCTSNode2 chosen;
        Map<String, Object> replayProof = null;
        MageZeroSearchReplay.Result callback = null;
        boolean libraryFailToFindExcluded = false;
        Map<String, Object> obs = Json.obj(Json.copy(decision.get("observation")));
        if (!priority) {
            MageZeroSearchReplay.Result replay = MageZeroSearchReplay.run(record, evaluator, configured, diagnostic);
            callback = replay;
            world = replay.world; active = replay.player; chosen = replay.chosen;
            libraryFailToFindExcluded = replay.libraryFailToFindExcluded;
            replayProof = Json.map("earlier", (long) replay.replayed, "priority_passes",
                    (long) Json.arr(Json.obj(record, "replay"), "priority_passes").size(), "observation_identical", true);
        } else {
        KitContext.reset(); GameAccess.reset(); KitRandom.installBoot();
        List<String> nameFlags = WorldBuilder.restoreVisibleNames(obs, Json.obj(decision, "x_history"));
        KitRandom random = KitRandom.install(seed(Json.str(record, "world_seed")), seed(Json.str(record, "id_seed")));
        SearchPlayer[] player = new SearchPlayer[1];
        WorldBuilder.Spec spec = new WorldBuilder.Spec();
        spec.gameStart = Json.obj(record, "game_start"); spec.observation = obs;
        spec.sample = Sampler.sample(spec.gameStart, obs, random.stream("sampler")); spec.random = random;
        spec.mode = WorldBuilder.Mode.PRIORITY; spec.history = Json.obj(decision, "x_history");
        spec.viewerFactory = seat -> player[0] = new SearchPlayer(seat); spec.otherFactory = Puppet::new;
        world = WorldBuilder.build(spec);
        world.flags.addAll(nameFlags);
        for (String flag : world.flags) {
            if (flag.startsWith("unsupported:") || flag.startsWith("horizon:")) {
                throw new IllegalArgumentException("search world is unsupported: " + flag);
            }
        }
        if (diagnostic) player[0].configureDiagnostic(evaluator, configured.searchBudget);
        else player[0].configure(evaluator, configured);
        chosen = player[0].searchPriority(world.game);
        active = player[0];
        }
        ObsIndex index = new ObsIndex(obs);
        Map<String, Object> semantic = semantic(decision, world, chosen, index, priority, callback);
        Map<String, Object> offered = null;
        for (Object c : Json.arr(decision, "candidates")) {
            Map<String, Object> candidate = Json.obj(c);
            if (Json.canonical(candidate.get("semantic")).equals(Json.canonical(semantic))) {
                if (offered != null) throw new IllegalArgumentException("aliased priority candidate");
                offered = candidate;
            }
        }
        if (offered == null) throw new IllegalArgumentException("search chose an action outside the offered candidates");
        List<Object> children = new ArrayList<>();
        List<Object> unofferedModes = new ArrayList<>();
        Set<String> branchKeys = new HashSet<>();
        MCTSNode2 tree = active.tree();
        for (MCTSNode child : active.initialRootChildren()) {
            boolean pruned = active.pruned(child);
            boolean masked = !pruned && active.selectionMasked(child);
            if (callback != null && callback.modeActions != null
                    && !callback.modeActions.actions.containsKey(child.getAmountAction())) {
                if (!pruned && !masked || pruned && child.getVisits() != 0) {
                    throw new IllegalArgumentException("original search retained an unoffered mode branch with a legal future");
                }
                int ordinal = child.getAmountAction();
                if (ordinal < 0 || ordinal >= callback.modeActions.publicIndices.size()) {
                    throw new IllegalArgumentException("original mode branch exceeds its callback ordinal range");
                }
                unofferedModes.add(Json.map("ordinal", (long) ordinal,
                        "mode_index", (long) callback.modeActions.publicIndices.get(ordinal),
                        "visits", 0L, "pruned", pruned, "selection_masked", masked,
                        "discarded_visits", masked ? (long) active.discardedSelectionVisits(child) : 0L,
                        "reason", "original mode branch is unoffered and has no legal future"));
                continue;
            }
            Map<String, Object> action = semantic(decision, world, child, index, priority, callback);
            if (action == null || !branchKeys.add(Json.canonical(action))) {
                throw new IllegalArgumentException("search root has an unmapped or aliased action");
            }
            children.add(Json.map("semantic", action, "visits", pruned ? 0L : (long) active.visits(child),
                    "value", pruned || masked ? null : active.meanScore(child), "pruned", pruned,
                    "selection_masked", masked,
                    "discarded_visits", masked ? (long) active.discardedSelectionVisits(child) : 0L,
                    "mask_reason", masked ? "original MageZero bestChild resets branches without a legal future" : null));
        }
        Set<String> offeredKeys = new HashSet<>();
        for (Object c : Json.arr(decision, "candidates")) {
            Map<String, Object> action = Json.obj(Json.obj(c), "semantic");
            String key = Json.canonical(action);
            if (!offeredKeys.add(key)) throw new IllegalArgumentException("aliased MageZero candidate");
            if (!branchKeys.contains(key) && libraryFailToFindExcluded
                    && "finish_selection".equals(Json.str(action, "kind")) && "search".equals(Json.str(action, "purpose"))) {
                branchKeys.add(key);
                children.add(Json.map("semantic", action, "visits", 0L, "value", null, "pruned", false,
                        "excluded", true, "reason", "original MageZero library target expansion requires its minimum before finishing"));
            }
        }
        if (!offeredKeys.equals(branchKeys)) throw new IllegalArgumentException("search root does not cover the offered actions");
        String decisionHash;
        try { decisionHash = Seeds.hex(MessageDigest.getInstance("SHA-256").digest(Json.canonical(decision).getBytes(StandardCharsets.UTF_8))); }
        catch (java.security.NoSuchAlgorithmException e) { throw new IllegalStateException(e); }
        Map<String, Object> result = Json.map("selection", Json.map("candidate_id", offered.get("candidate_id"), "semantic_echo", offered.get("semantic")),
                "decision_sha256", decisionHash,
                "children", children, "root_visits", (long) active.rootVisits(), "neural_calls", calls,
                "policy_width", 128L, "settings", Json.copy(values),
                "search_budget", Json.map("kind", diagnostic ? "minimum_root_visits_until_legal_future"
                        : "original_source_time_or_visits_until_legal_future", "requested", values.get("searchBudget"),
                        "timeout_seconds", values.get("searchTimeout")),
                "world_flags", world.flags, "replay", replayProof,
                "policy_restrictions", libraryFailToFindExcluded ? java.util.Collections.singletonList("library_fail_to_find_before_minimum")
                        : java.util.Collections.emptyList(),
                "variant", "original MageZero 128-slot tree and dialog scripts; numeric roots use the legal offered range; explicit head flags and stopping rule; permitted sampled world; fresh tree; synchronous neural transport; no noise",
                "scope", "priority and replayed target/binary/numeric/named/mode roots; combat, trained weights, full games and ratings unfinished");
        if (callback != null && callback.modeActions != null) {
            result.put("unoffered_mode_branches", unofferedModes);
            result.put("scope", "original MageZero numeric spell-mode callback; trained weights, combat, complete games and ratings unfinished");
        }
        if (graph != null) {
            result.remove("policy_width");
            result.put("settings", Json.copy(graph.settings()));
            result.put("search_budget", graph.searchBudget());
            result.put("variant", graph.variant());
            result.put("graph_search", new ArrayList<>(graph.receipts()));
            result.put("scope", "graph network search on priority and replayed callback roots; complete-game qualification and ratings unfinished");
        }
        return result;
    }
    private static Map<String, Object> semantic(Map<String, Object> decision, World world, MCTSNode child,
                                                ObsIndex index, boolean priority, MageZeroSearchReplay.Result callback) {
        if (priority) return Mapping.prioritySemantic(world, world.game, child.getPriorityAction(), index);
        if (callback.modeActions != null) {
            Map<String, Object> action = callback.modeActions.actions.get(child.getAmountAction());
            if (action == null) throw new IllegalArgumentException("original search chose an unoffered mode branch");
            return action;
        }
        if (callback.namedActions != null) {
            Map<String, Object> action = callback.namedActions.get(child.getChoiceAction());
            if (action == null) throw new IllegalArgumentException("unmapped original named branch");
            return action;
        }
        Map<String, Object> match = null;
        for (Object item : Json.arr(decision, "candidates")) {
            Map<String, Object> sem = Json.obj(Json.obj(item), "semantic");
            String kind = Json.str(sem, "kind");
            boolean found = false;
            if (callback.numericMinimum != null) {
                found = "choose_number".equals(kind)
                        && Json.num(sem, "value", Long.MIN_VALUE) == (long) child.getAmountAction() + callback.numericMinimum;
            } else if (child.getTargetAction() != null) {
                boolean finish = "finish_target_selection".equals(kind) || "finish_selection".equals(kind);
                found = finish ? GameAccess.STOP_CHOOSING.equals(child.getTargetAction())
                        : child.getTargetAction().equals(Dialogs.uuidOf(world, sem));
            } else if (MageZeroSearchReplay.booleanValue(sem) instanceof Boolean) {
                found = Boolean.valueOf(child.getUseAction()).equals(MageZeroSearchReplay.booleanValue(sem));
            }
            if (found) {
                if (match != null) throw new IllegalArgumentException("aliased callback branch");
                match = sem;
            }
        }
        if (match == null) throw new IllegalArgumentException("unmapped callback branch");
        return match;
    }
    public static void main(String[] args) throws Exception {
        if (args.length != 0) throw new IllegalArgumentException("private MageZero pipe takes no arguments");
        out = new PrintStream(new FileOutputStream(FileDescriptor.out), true, "UTF-8");
        System.setOut(System.err); Runner.quietLogs(); KitRandom.installBoot(); Warmup.framework();
        new CardResolver().resolve("Plains");
        in = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        out.println(Json.canonical(Json.map("ready", true, "search", "magezero-v02-original-search", "policy_width", 128L)));
        String line;
        while ((line = in.readLine()) != null) {
            Map<String, Object> record = null;
            calls = 0;
            try {
                record = Json.parseObject(line); requestId = record.get("id");
                if (!(requestId instanceof String)) throw new IllegalArgumentException("search request id must be a string");
                Map<String, Object> result = search(record);
                out.println(Json.canonical(Json.map("id", requestId, "event", "result", "ok", true, "result", result)));
            } catch (RuntimeException e) {
                out.println(Json.canonical(Json.map("id", record == null ? null : record.get("id"), "event", "result",
                        "ok", false, "error", e.toString(), "neural_calls", calls)));
            } finally { GameAccess.reset(); MCTSDefaults.CURRENT = new MCTSDefaults(); }
        }
    }
}
