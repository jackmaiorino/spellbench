package spellbench.kit.xmage;

import spellbench.kit.core.Json;
import java.io.BufferedReader;
import java.io.FileDescriptor;
import java.io.FileOutputStream;
import java.io.InputStreamReader;
import java.io.PrintStream;
import java.lang.reflect.InvocationTargetException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/** Private choice pipe. Original selection code is staged outside public Git. */
public final class JackSelectionMain {
    private static final String CALLBACK = "b45257a66fc3914506fca4dd83461b6c8853d129b3e1f38b2d3aeba6137bd0c6";
    private static final String GREEDY = "jack-april-eval-greedy-fair-v1";
    private static final String SAMPLED = "jack-april-no-training-sampled-fair-v1";
    private JackSelectionMain() { }

    public static void main(String[] args) throws Exception {
        if (args.length != 2 || !(GREEDY.equals(args[0]) || SAMPLED.equals(args[0])))
            throw new IllegalArgumentException("usage: original no-training selection profile and nonnegative game seed");
        long seed = Long.parseLong(args[1]);
        if (seed < 0 || seed > 9007199254740991L) throw new IllegalArgumentException("invalid protocol game seed");
        Class<?> original = Class.forName("spellbench.models.jack.PolicySelector");
        if (!CALLBACK.equals(original.getField("SOURCE_SHA256").get(null)))
            throw new IllegalArgumentException("selection source differs from the pinned April callback");
        Object selector = original.getConstructor(boolean.class, long.class).newInstance(GREEDY.equals(args[0]), seed);
        PrintStream out = new PrintStream(new FileOutputStream(FileDescriptor.out), true, "UTF-8");
        System.setOut(System.err);
        BufferedReader in = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        out.println(Json.canonical(Json.map("ready", true, "selection", "jack-original-no-training",
                "profile", args[0], "seed", seed, "callback_source_sha256", CALLBACK)));
        long lastId = 0;
        String line;
        while ((line = in.readLine()) != null) {
            Map<String, Object> request = null;
            try {
                request = Json.parseObject(line);
                String id = Json.str(request, "id");
                if (id == null || !id.matches("[1-9][0-9]*") || Long.parseLong(id) <= lastId)
                    throw new IllegalArgumentException("stale selection request ID");
                lastId = Long.parseLong(id);
                if (!"choose".equals(Json.str(request, "operation")))
                    throw new IllegalArgumentException("unsupported original selection operation");
                List<Object> rawScores = Json.arr(request, "probabilities"), rawMask = Json.arr(request, "mask");
                if (rawScores == null || rawMask == null || rawScores.size() != 64 || rawMask.size() != 64)
                    throw new IllegalArgumentException("original selection requires 64 probability and mask slots");
                float[] scores = new float[64];
                int[] mask = new int[64];
                for (int i = 0; i < 64; i++) {
                    if (!(rawScores.get(i) instanceof Number) || !(rawMask.get(i) instanceof Boolean))
                        throw new IllegalArgumentException("selection needs numeric probabilities and boolean masks");
                    double probability = ((Number) rawScores.get(i)).doubleValue();
                    if (!Double.isFinite(probability) || probability < 0 || probability > 1)
                        throw new IllegalArgumentException("invalid candidate probability");
                    scores[i] = (float) probability;
                    mask[i] = (Boolean) rawMask.get(i) ? 1 : 0;
                }
                Object count = request.get("count"), picks = request.get("picks"), sequential = request.get("sequential");
                if (!(count instanceof Long) || !(picks instanceof Long) || !(sequential instanceof Boolean)
                        || (Long) count < 1 || (Long) count > 64 || (Long) picks < 1 || (Long) picks > 64)
                    throw new IllegalArgumentException("invalid original candidate or pick count");
                int[] selected;
                try {
                    selected = (int[]) original.getMethod("choose", float[].class, int[].class, int.class,
                            int.class, boolean.class).invoke(selector, scores, mask, ((Long) count).intValue(),
                                    ((Long) picks).intValue(), sequential);
                } catch (InvocationTargetException e) {
                    if (e.getCause() instanceof RuntimeException) throw (RuntimeException) e.getCause();
                    throw new IllegalStateException("original selection failed", e.getCause());
                }
                List<Object> indices = new ArrayList<>();
                for (int index : selected) indices.add((long) index);
                out.println(Json.canonical(Json.map("id", id, "ok", true, "indices", indices)));
            } catch (RuntimeException e) {
                out.println(Json.canonical(Json.map("id", request == null ? null : request.get("id"),
                        "ok", false, "error", e.toString())));
                break;
            }
        }
    }
}
