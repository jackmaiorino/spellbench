package spellbench.kit.xmage;

import mage.player.cabt.CardResolver;
import mage.player.spellbench.Warmup;
import spellbench.kit.core.Json;
import spellbench.kit.core.Seeds;

import java.io.FileDescriptor;
import java.io.FileOutputStream;
import java.io.PrintStream;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.Map;

/** Encoder from recorded permitted decisions, or a persistent private NDJSON pipe. */
public final class ModelEncoderMain {
    public static void main(String[] args) throws Exception {
        boolean stdio = args.length == 1 && "--stdio".equals(args[0]);
        if (!stdio && args.length != 3) {
            throw new IllegalArgumentException("usage: DECISION.json WORLD_SEED ID_SEED, or --stdio");
        }
        PrintStream out = new PrintStream(new FileOutputStream(FileDescriptor.out), true, "UTF-8");
        System.setOut(System.err);
        Runner.quietLogs();
        KitRandom.installBoot();
        Warmup.framework();
        new CardResolver().resolve("Plains");
        if (stdio) {
            out.println(Json.canonical(Json.map("ready", true, "encoder", "draftzero-exp1-decision")));
            BufferedReader in = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
            String line;
            while ((line = in.readLine()) != null) {
                Map<String, Object> record = null;
                try {
                    record = Json.parseObject(line);
                    Map<String, Object> result = ModelEncoder.decision(Json.obj(record, "game_start"),
                            Json.obj(record, "decision"), seed(Json.str(record, "world_seed")),
                            seed(Json.str(record, "id_seed")));
                    out.println(Json.canonical(Json.map("id", record.get("id"), "ok", true, "encoded", result)));
                } catch (RuntimeException e) {
                    out.println(Json.canonical(Json.map("id", record == null ? null : record.get("id"),
                            "ok", false, "error", e.toString())));
                }
            }
            return;
        }
        Map<String, Object> record = Json.parseObject(new String(Files.readAllBytes(Paths.get(args[0])), StandardCharsets.UTF_8));
        Map<String, Object> decision = Json.obj(record, "decision");
        out.println(Json.canonical(ModelEncoder.decision(Json.obj(record, "game_start"), decision,
                seed(args[1]), seed(args[2]))));
    }

    private static byte[] seed(String value) {
        if (value == null || !value.matches("[a-f0-9]{64}")) {
            throw new IllegalArgumentException("encoder seeds require 32-byte lowercase hexadecimal strings");
        }
        return Seeds.unhex(value);
    }
}
