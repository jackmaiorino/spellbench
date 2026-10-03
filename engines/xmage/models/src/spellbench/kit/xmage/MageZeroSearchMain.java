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

/** Original 128-slot MageZero priority tree over permitted sampled worlds. */
public final class MageZeroSearchMain {
    private static BufferedReader in;
    private static PrintStream out;
    private static long calls;
    private static Object requestId;
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
        if (!result.noNoise) throw new IllegalArgumentException("MageZero priority bridge requires no-noise selection");
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
    private static byte[] seed(String value) {
        if (value == null || !value.matches("[a-f0-9]{64}")) throw new IllegalArgumentException("search seed envelope");
        return Seeds.unhex(value);
    }
    private static Map<String, Object> search(Map<String, Object> record) {
        Map<String, Object> decision = Json.obj(record, "decision");
        Map<String, Object> context = Json.obj(decision, "context");
        Map<String, Object> start = Json.obj(record, "game_start");
        Map<String, Object> obs = Json.obj(Json.copy(decision.get("observation")));
        String viewer = Json.str(obs, "viewer");
        if (!"priority".equals(Json.str(context, "kind")) || !Boolean.FALSE.equals(context.get("rewind"))
                || !("p0".equals(viewer) || "p1".equals(viewer)) || !viewer.equals(Json.str(start, "seat"))
                || !viewer.equals(Json.str(decision, "acting_seat"))) {
            throw new IllegalArgumentException("MageZero search needs a non-rewound own priority decision");
        }
        Map<String, Object> values = Json.obj(record, "settings");
        MCTSDefaults configured = settings(values);
        boolean diagnostic = "minimum-visits-diagnostic".equals(Json.str(values, "profile"));
        // Original constructors and copy field initializers read CURRENT.
        // Bind it before building the world so copied players retain the
        // supplied play configuration as they do in the original launcher.
        MCTSDefaults.CURRENT = configured;
        byte[] worldSeed = seed(Json.str(record, "world_seed")), idSeed = seed(Json.str(record, "id_seed"));
        KitContext.reset(); GameAccess.reset(); KitRandom.installBoot();
        List<String> nameFlags = WorldBuilder.restoreVisibleNames(obs, Json.obj(decision, "x_history"));
        KitRandom random = KitRandom.install(worldSeed, idSeed);
        SearchPlayer[] player = new SearchPlayer[1];
        WorldBuilder.Spec spec = new WorldBuilder.Spec();
        spec.gameStart = start; spec.observation = obs; spec.random = random;
        spec.sample = Sampler.sample(start, obs, random.stream("sampler"));
        spec.mode = WorldBuilder.Mode.PRIORITY; spec.history = Json.obj(decision, "x_history");
        spec.viewerFactory = seat -> player[0] = new SearchPlayer(seat); spec.otherFactory = Puppet::new;
        World world = WorldBuilder.build(spec);
        world.flags.addAll(nameFlags);
        for (String flag : world.flags) {
            if (flag.startsWith("unsupported:") || flag.startsWith("horizon:")) {
                throw new IllegalArgumentException("MageZero search world is unsupported: " + flag);
            }
        }
        RemoteModelEvaluator evaluator = new RemoteModelEvaluator(MageZeroSearchMain::infer);
        if (diagnostic) player[0].configureDiagnostic(evaluator, configured.searchBudget);
        else player[0].configure(evaluator, configured);
        MCTSNode2 chosen = player[0].searchPriority(world.game);
        ObsIndex index = new ObsIndex(obs);
        Map<String, Object> selected = Mapping.prioritySemantic(world, world.game, chosen.getPriorityAction(), index);
        Map<String, Object> offered = null;
        Set<String> offeredKeys = new HashSet<>();
        for (Object item : Json.arr(decision, "candidates")) {
            Map<String, Object> candidate = Json.obj(item);
            String key = Json.canonical(candidate.get("semantic"));
            if (!offeredKeys.add(key)) throw new IllegalArgumentException("aliased MageZero priority candidate");
            if (key.equals(Json.canonical(selected))) offered = candidate;
        }
        if (offered == null) throw new IllegalArgumentException("MageZero selected an unoffered priority action");
        MCTSNode2 tree = player[0].tree();
        Set<MCTSNode> retained = new HashSet<>(tree.getChildren());
        Set<String> branchKeys = new HashSet<>();
        List<Object> children = new ArrayList<>();
        for (MCTSNode child : player[0].initialRootChildren()) {
            boolean pruned = !retained.contains(child), masked = !pruned && player[0].selectionMasked(child);
            Map<String, Object> semantic = Mapping.prioritySemantic(world, world.game, child.getPriorityAction(), index);
            if (semantic == null || !branchKeys.add(Json.canonical(semantic))) {
                throw new IllegalArgumentException("MageZero root has an unmapped or aliased priority action");
            }
            children.add(Json.map("semantic", semantic, "visits", pruned ? 0L : (long) child.getVisits(),
                    "value", pruned || masked ? null : child.getMeanScore(), "pruned", pruned,
                    "selection_masked", masked, "discarded_visits", masked ? (long) player[0].discardedSelectionVisits(child) : 0L,
                    "mask_reason", masked ? "original MageZero bestChild resets branches without a legal future" : null));
        }
        if (!offeredKeys.equals(branchKeys)) throw new IllegalArgumentException("MageZero root does not cover the offered actions");
        String digest;
        try { digest = Seeds.hex(MessageDigest.getInstance("SHA-256").digest(Json.canonical(decision).getBytes(StandardCharsets.UTF_8))); }
        catch (java.security.NoSuchAlgorithmException e) { throw new IllegalStateException(e); }
        return Json.map("selection", Json.map("candidate_id", offered.get("candidate_id"), "semantic_echo", offered.get("semantic")),
                "decision_sha256", digest, "children", children, "root_visits", (long) tree.getVisits(),
                "neural_calls", calls, "policy_width", 128L, "settings", Json.copy(values),
                "search_budget", Json.map("kind", diagnostic ? "minimum_root_visits_until_legal_future"
                        : "original_source_time_or_visits_until_legal_future", "requested", values.get("searchBudget"),
                        "timeout_seconds", values.get("searchTimeout")), "world_flags", world.flags,
                "variant", "original MageZero 128-slot priority tree; explicit head flags and stopping rule; permitted sampled world; fresh tree; synchronous neural transport; no noise",
                "scope", "priority component only; other callbacks, pretrained native checks, complete games and ratings unfinished");
    }
    public static void main(String[] args) throws Exception {
        if (args.length != 0) throw new IllegalArgumentException("private MageZero pipe takes no arguments");
        out = new PrintStream(new FileOutputStream(FileDescriptor.out), true, "UTF-8");
        System.setOut(System.err); Runner.quietLogs(); KitRandom.installBoot(); Warmup.framework();
        new CardResolver().resolve("Plains");
        in = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        out.println(Json.canonical(Json.map("ready", true, "search", "magezero-v02-original-priority", "policy_width", 128L)));
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
