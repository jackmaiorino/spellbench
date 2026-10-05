package spellbench.kit.xmage;

import mage.player.cabt.CardResolver;
import mage.player.spellbench.Warmup;
import spellbench.kit.core.Json;
import spellbench.models.exp1.GameAccess;
import spellbench.models.exp1.PlaySettings;

import java.io.BufferedReader;
import java.io.FileDescriptor;
import java.io.FileOutputStream;
import java.io.InputStreamReader;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Map;

/** Serial private RPC for original search and combat on one warm JVM. */
public final class ModelBridgeMain {
    static String operation(Map<String, Object> record) {
        String operation = Json.str(record, "operation");
        if (!("search".equals(operation) || "combat".equals(operation))) {
            throw new IllegalArgumentException("unsupported original bridge operation");
        }
        Map<String, Object> decision = Json.obj(record, "decision");
        boolean combat = false, other = false;
        for (Object item : Json.arr(decision, "candidates")) {
            String kind = Json.str(Json.obj(Json.obj(item), "semantic"), "kind");
            if ("declare_attack".equals(kind) || "declare_block".equals(kind)) combat = true;
            else other = true;
        }
        if (combat && other || combat != "combat".equals(operation)) {
            throw new IllegalArgumentException("bridge operation differs from its offered decision family");
        }
        return operation;
    }

    public static void main(String[] args) throws Exception {
        if (args.length != 0) throw new IllegalArgumentException("private mixed NDJSON pipe takes no arguments");
        PrintStream out = new PrintStream(new FileOutputStream(FileDescriptor.out), true, "UTF-8");
        System.setOut(System.err); Runner.quietLogs(); KitRandom.installBoot(); Warmup.framework();
        new CardResolver().resolve("Plains");
        BufferedReader in = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        ModelSearchMain.bindPipe(in, out); ModelCombatMain.bindPipe(in, out);
        out.println(Json.canonical(Json.map("ready", true, "search", "draftzero-exp1-original-mixed",
                "operations", Arrays.asList("search", "combat"))));
        String line;
        long lastId = 0;
        while ((line = in.readLine()) != null) {
            Map<String, Object> record = null;
            String operation = null;
            boolean started = false;
            try {
                record = Json.parseObject(line);
                Object id = record.get("id");
                if (!(id instanceof String) || !((String) id).matches("[1-9][0-9]*")) {
                    throw new IllegalArgumentException("bridge request id must be an increasing decimal string");
                }
                long sequence = Long.parseLong((String) id);
                if (sequence <= lastId) throw new IllegalArgumentException("stale bridge request id");
                lastId = sequence;
                operation = operation(record);
                started = true;
                Map<String, Object> result = "combat".equals(operation)
                        ? ModelCombatMain.execute(record) : ModelSearchMain.execute(record);
                out.println(Json.canonical(Json.map("id", id, "operation", operation,
                        "event", "result", "ok", true, "result", result)));
            } catch (RuntimeException e) {
                long calls = !started ? 0 : "combat".equals(operation)
                        ? ModelCombatMain.neuralCalls() : ModelSearchMain.neuralCalls();
                out.println(Json.canonical(Json.map("id", record == null ? null : record.get("id"),
                        "operation", operation, "event", "result", "ok", false,
                        "error", e.toString(), "neural_calls", calls)));
                // An inference error can leave an unread response. Never
                // resynchronize a failed mixed session onto a later request.
                break;
            } finally { GameAccess.reset(); PlaySettings.reset(); }
        }
    }
}
