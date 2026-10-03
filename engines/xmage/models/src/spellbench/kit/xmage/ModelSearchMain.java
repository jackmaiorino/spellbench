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
        if (!"priority".equals(Json.str(context, "kind"))) throw new IllegalArgumentException("priority search bridge only");
        Object count = record.get("visits");
        if (!(count instanceof Number) || ((Number) count).doubleValue() != ((Number) count).intValue()) {
            throw new IllegalArgumentException("integer visit budget required");
        }
        Map<String, Object> obs = Json.obj(Json.copy(decision.get("observation")));
        KitContext.reset(); GameAccess.reset(); KitRandom.installBoot();
        List<String> nameFlags = WorldBuilder.restoreVisibleNames(obs, Json.obj(decision, "x_history"));
        KitRandom random = KitRandom.install(seed(Json.str(record, "world_seed")), seed(Json.str(record, "id_seed")));
        SearchPlayer[] player = new SearchPlayer[1];
        WorldBuilder.Spec spec = new WorldBuilder.Spec();
        spec.gameStart = Json.obj(record, "game_start"); spec.observation = obs;
        spec.sample = Sampler.sample(spec.gameStart, obs, random.stream("sampler")); spec.random = random;
        spec.mode = WorldBuilder.Mode.PRIORITY; spec.history = Json.obj(decision, "x_history");
        spec.viewerFactory = seat -> player[0] = new SearchPlayer(seat); spec.otherFactory = Puppet::new;
        World world = WorldBuilder.build(spec);
        world.flags.addAll(nameFlags);
        for (String flag : world.flags) {
            if (flag.startsWith("unsupported:") || flag.startsWith("horizon:")) {
                throw new IllegalArgumentException("search world is unsupported: " + flag);
            }
        }
        player[0].configure(new RemoteModelEvaluator(ModelSearchMain::infer), ((Number) count).intValue());
        MCTSNode2 chosen = player[0].searchPriority(world.game);
        ObsIndex index = new ObsIndex(obs);
        Map<String, Object> semantic = Mapping.prioritySemantic(world, world.game, chosen.getPriorityAction(), index);
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
        MCTSNode2 tree = player[0].tree();
        for (MCTSNode child : tree.getChildren()) {
            Map<String, Object> action = Mapping.prioritySemantic(world, world.game, child.getPriorityAction(), index);
            if (action == null || !branchKeys.add(Json.canonical(action))) {
                throw new IllegalArgumentException("search root has an unmapped or aliased action");
            }
            children.add(Json.map("semantic", action, "visits", (long) child.getVisits(), "value", child.getMeanScore()));
        }
        Set<String> offeredKeys = new HashSet<>();
        for (Object c : Json.arr(decision, "candidates")) offeredKeys.add(Json.canonical(Json.obj(c).get("semantic")));
        if (!offeredKeys.equals(branchKeys)) throw new IllegalArgumentException("search root does not cover the offered actions");
        String decisionHash;
        try { decisionHash = Seeds.hex(MessageDigest.getInstance("SHA-256").digest(Json.canonical(decision).getBytes(StandardCharsets.UTF_8))); }
        catch (java.security.NoSuchAlgorithmException e) { throw new IllegalStateException(e); }
        return Json.map("selection", Json.map("candidate_id", offered.get("candidate_id"), "semantic_echo", offered.get("semantic")),
                "decision_sha256", decisionHash,
                "children", children, "root_visits", (long) tree.getVisits(), "neural_calls", calls,
                "world_flags", world.flags, "variant", "Exp1 original PUCT and dialog scripts; sampled permitted world; fresh tree per priority; synchronous neural transport; all priors; fixed visits; no noise",
                "scope", "priority bridge; remaining root callbacks, full games and ratings unfinished");
    }
    public static void main(String[] args) throws Exception {
        if (args.length != 0) throw new IllegalArgumentException("private NDJSON search pipe takes no arguments");
        out = new PrintStream(new FileOutputStream(FileDescriptor.out), true, "UTF-8");
        System.setOut(System.err); Runner.quietLogs(); KitRandom.installBoot(); Warmup.framework();
        new CardResolver().resolve("Plains");
        in = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        out.println(Json.canonical(Json.map("ready", true, "search", "draftzero-exp1-original-priority")));
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
