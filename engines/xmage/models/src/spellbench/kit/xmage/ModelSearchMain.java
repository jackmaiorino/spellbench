package spellbench.kit.xmage;

import mage.player.ai.encoder.ActionEncoder;
import mage.player.cabt.CardResolver;
import mage.player.spellbench.Warmup;
import spellbench.kit.core.Json;
import spellbench.kit.core.ObsIndex;
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
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.HashSet;
import java.util.Set;
import java.security.MessageDigest;

/** Original Exp1 search on permitted records, with private neural NDJSON RPC. */
public final class ModelSearchMain {
    private static BufferedReader in;
    private static PrintStream out;
    private static long calls;
    private static Object requestId;

    private static byte[] seed(String value) {
        if (value == null || !value.matches("[a-f0-9]{64}")) throw new IllegalArgumentException("search seed envelope");
        return Seeds.unhex(value);
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
            if (!requestId.equals(reply.get("id")) || !(reply.get("call") instanceof Number)
                    || ((Number) reply.get("call")).doubleValue() != call || !Boolean.TRUE.equals(reply.get("ok"))) {
                throw new IllegalArgumentException("stale or failed neural transport response");
            }
            Map<String, Object> scores = Json.obj(reply, "scores");
            Object value = scores.get("value");
            if (!(value instanceof Number)) throw new IllegalArgumentException("neural value is not numeric");
            return new RemoteModelEvaluator.InferenceResult(head(scores, "priority"), head(scores, "opponent_priority"),
                    head(scores, "target"), head(scores, "binary"), ((Number) value).floatValue());
        } catch (java.io.IOException e) { throw new IllegalStateException("neural transport failed", e); }
    }
    static Map<String, Object> search(Map<String, Object> record) {
        if (!ActionEncoder.vocabLoaded() || ActionEncoder.ACTION_DIM != 1024) throw new IllegalArgumentException("Exp1 action vocabulary");
        Map<String, Object> decision = Json.obj(record, "decision");
        Map<String, Object> context = Json.obj(decision, "context");
        boolean priority = "priority".equals(Json.str(context, "kind"));
        seed(Json.str(record, "world_seed")); seed(Json.str(record, "id_seed"));
        Object count = record.get("visits");
        if (!(count instanceof Number) || ((Number) count).doubleValue() != ((Number) count).intValue()) {
            throw new IllegalArgumentException("integer visit budget required");
        }
        RemoteModelEvaluator evaluator = new RemoteModelEvaluator(ModelSearchMain::infer);
        SearchPlayer active;
        World world;
        MCTSNode2 chosen;
        Map<String, Object> replayProof = null;
        ModelReplay.Result callback = null;
        boolean libraryFailToFindExcluded = false;
        Map<String, Object> obs = Json.obj(Json.copy(decision.get("observation")));
        if (!priority) {
            ModelReplay.Result replay = ModelReplay.run(record, evaluator, ((Number) count).intValue());
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
        player[0].configure(evaluator, ((Number) count).intValue());
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
        Set<String> branchKeys = new HashSet<>();
        MCTSNode2 tree = active.tree();
        Set<MCTSNode> retained = new HashSet<>(tree.getChildren());
        for (MCTSNode child : active.initialRootChildren()) {
            Map<String, Object> action = semantic(decision, world, child, index, priority, callback);
            if (action == null || !branchKeys.add(Json.canonical(action))) {
                throw new IllegalArgumentException("search root has an unmapped or aliased action");
            }
            boolean pruned = !retained.contains(child);
            children.add(Json.map("semantic", action, "visits", pruned ? 0L : (long) child.getVisits(),
                    "value", pruned ? null : child.getMeanScore(), "pruned", pruned));
        }
        Set<String> offeredKeys = new HashSet<>();
        for (Object c : Json.arr(decision, "candidates")) {
            Map<String, Object> action = Json.obj(Json.obj(c), "semantic");
            String key = Json.canonical(action);
            offeredKeys.add(key);
            if (!branchKeys.contains(key) && libraryFailToFindExcluded
                    && "finish_selection".equals(Json.str(action, "kind")) && "search".equals(Json.str(action, "purpose"))) {
                branchKeys.add(key);
                children.add(Json.map("semantic", action, "visits", 0L, "value", null, "pruned", false,
                        "excluded", true, "reason", "original Exp1 library target expansion requires its minimum before finishing"));
            }
        }
        if (!offeredKeys.equals(branchKeys)) throw new IllegalArgumentException("search root does not cover the offered actions");
        String decisionHash;
        try { decisionHash = Seeds.hex(MessageDigest.getInstance("SHA-256").digest(Json.canonical(decision).getBytes(StandardCharsets.UTF_8))); }
        catch (java.security.NoSuchAlgorithmException e) { throw new IllegalStateException(e); }
        return Json.map("selection", Json.map("candidate_id", offered.get("candidate_id"), "semantic_echo", offered.get("semantic")),
                "decision_sha256", decisionHash,
                "children", children, "root_visits", (long) tree.getVisits(), "neural_calls", calls,
                "world_flags", world.flags, "replay", replayProof,
                "policy_restrictions", libraryFailToFindExcluded ? java.util.Collections.singletonList("library_fail_to_find_before_minimum")
                        : java.util.Collections.emptyList(),
                "variant", "Exp1 original PUCT and dialog scripts; numeric roots use the legal offered range; sampled permitted world; fresh tree per root; synchronous neural transport; all priors; fixed visits; no noise",
                "scope", "priority and saved-anchor target/binary/numeric/named roots; complete history, other callbacks, full games and ratings unfinished");
    }
    private static Map<String, Object> semantic(Map<String, Object> decision, World world, MCTSNode child,
                                                ObsIndex index, boolean priority, ModelReplay.Result callback) {
        if (priority) return Mapping.prioritySemantic(world, world.game, child.getPriorityAction(), index);
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
            } else if (ModelReplay.booleanValue(sem) instanceof Boolean) {
                found = Boolean.valueOf(child.getUseAction()).equals(ModelReplay.booleanValue(sem));
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
        if (args.length != 0) throw new IllegalArgumentException("private NDJSON search pipe takes no arguments");
        out = new PrintStream(new FileOutputStream(FileDescriptor.out), true, "UTF-8");
        System.setOut(System.err); Runner.quietLogs(); KitRandom.installBoot(); Warmup.framework();
        new CardResolver().resolve("Plains");
        in = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        out.println(Json.canonical(Json.map("ready", true, "search", "draftzero-exp1-original-search")));
        String line;
        while ((line = in.readLine()) != null) {
            Map<String, Object> record = null;
            try {
                record = Json.parseObject(line); requestId = record.get("id");
                if (!(requestId instanceof String)) throw new IllegalArgumentException("search request id must be a string");
                calls = 0;
                Map<String, Object> result = search(record);
                out.println(Json.canonical(Json.map("id", requestId, "event", "result", "ok", true, "result", result)));
            } catch (RuntimeException e) {
                out.println(Json.canonical(Json.map("id", record == null ? null : record.get("id"), "event", "result", "ok", false, "error", e.toString(), "neural_calls", calls)));
            } finally { GameAccess.reset(); }
        }
    }
}
