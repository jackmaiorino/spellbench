package spellbench.kit.xmage;

import mage.player.cabt.CardResolver;
import mage.player.spellbench.Warmup;
import spellbench.kit.core.Json;
import spellbench.models.magezero.v02.search.GameAccess;
import spellbench.models.magezero.v02.search.GnnSearch;
import spellbench.models.magezero.v02.search.MCTSDefaults;
import spellbench.models.magezero.v02.search.SearchPlayer;

import java.io.BufferedReader;
import java.io.FileDescriptor;
import java.io.FileOutputStream;
import java.io.InputStreamReader;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Map;

/**
 * Serial private RPC for the DraftZero FDN graph network's search on one warm JVM. Each
 * request binds its explicit settings and its own graph pipe before any player is built;
 * search and combat roots then run the MageZero v0.2 replay and combat paths unchanged.
 */
public final class GnnBridgeMain {
    /**
     * Refusals raised before any search: the kit's no-search policy for horizon and unsupported worlds, and (as the
     * kit's continuation does) for a callback whose replay does not reproduce the received observation.
     */
    private static final String[] UNSUPPORTED = {"search world is unsupported: ", "callback anchor is unsupported: ",
            "combat world is unsupported: ", "callback replay observation differs: "};

    static String unsupported(RuntimeException e) {
        if (!(e instanceof IllegalArgumentException) || e.getMessage() == null) return null;
        for (String prefix : UNSUPPORTED) if (e.getMessage().startsWith(prefix)) return e.getMessage();
        return null;
    }

    public static void main(String[] args) throws Exception {
        if (args.length != 0) throw new IllegalArgumentException("private graph NDJSON pipe takes no arguments");
        PrintStream out = new PrintStream(new FileOutputStream(FileDescriptor.out), true, "UTF-8");
        System.setOut(System.err); Runner.quietLogs(); KitRandom.installBoot(); Warmup.framework();
        new CardResolver().resolve("Plains");
        BufferedReader in = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        MageZeroSearchMain.bindPipe(in, out); MageZeroSearchCombatMain.bindPipe(in, out);
        out.println(Json.canonical(Json.map("ready", true, "search", "draftzero-gnn-pimc-mixed",
                "operations", Arrays.asList("search", "combat"), "profile", GnnSearch.PROFILE)));
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
                operation = MageZeroSearchBridgeMain.operation(record);
                boolean combat = "combat".equals(operation);
                SearchPlayer.GRAPH = new GnnSearch(Json.obj(record, "settings"),
                        combat ? MageZeroSearchCombatMain::inferGraph : MageZeroSearchMain::inferGraph);
                started = true;
                Map<String, Object> result = combat ? MageZeroSearchCombatMain.execute(record) : MageZeroSearchMain.execute(record);
                out.println(Json.canonical(Json.map("id", id, "operation", operation,
                        "event", "result", "ok", true, "result", result)));
            } catch (RuntimeException e) {
                long calls = !started ? 0 : "combat".equals(operation)
                        ? MageZeroSearchCombatMain.neuralCalls() : MageZeroSearchMain.neuralCalls();
                String refusal = unsupported(e);
                if (started && calls == 0 && refusal != null) {
                    // The kit does not search such a world. No network call was made, so the pipe is in step;
                    // the frontend answers the kit's declining candidate.
                    out.println(Json.canonical(Json.map("id", record.get("id"), "operation", operation,
                            "event", "result", "ok", true, "result", Json.map("unsupported", refusal, "neural_calls", 0L))));
                    continue;
                }
                out.println(Json.canonical(Json.map("id", record == null ? null : record.get("id"),
                        "operation", operation, "event", "result", "ok", false,
                        "error", e.toString(), "neural_calls", calls)));
                // An inference error can leave an unread response. Never
                // resynchronize a failed session onto a later request.
                break;
            } finally {
                SearchPlayer.GRAPH = null;
                GameAccess.reset();
                MCTSDefaults.CURRENT = new MCTSDefaults();
            }
        }
    }
}
