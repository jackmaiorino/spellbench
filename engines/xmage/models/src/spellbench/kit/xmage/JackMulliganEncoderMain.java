package spellbench.kit.xmage;

import mage.player.cabt.CardResolver;
import mage.player.spellbench.Warmup;
import spellbench.kit.core.Json;
import spellbench.kit.core.Seeds;

import java.io.BufferedReader;
import java.io.FileDescriptor;
import java.io.FileOutputStream;
import java.io.InputStreamReader;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.util.Map;

/** Increasing private requests for the original permitted mulligan feature port. */
public final class JackMulliganEncoderMain {
    private JackMulliganEncoderMain() { }
    public static void main(String[] args) throws Exception {
        if (args.length != 1 || !args[0].matches("[a-f0-9]{64}")) {
            throw new IllegalArgumentException("private mulligan pipe requires its staged encoder SHA-256");
        }
        System.setProperty("spellbench.jack.mulliganEncoderSourceSha256", args[0]);
        Class<?> codec = Class.forName("spellbench.models.jack.MulliganEncoder");
        if (!JackMulliganEncoder.SOURCE_SHA256.equals(codec.getField("SOURCE_SHA256").get(null))) {
            throw new IllegalArgumentException("wrong original mulligan codec");
        }
        PrintStream out = new PrintStream(new FileOutputStream(FileDescriptor.out), true, "UTF-8");
        System.setOut(System.err); Runner.quietLogs(); KitRandom.installBoot(); Warmup.framework();
        new CardResolver().resolve("Plains");
        out.println(Json.canonical(Json.map("ready", true, "encoder", "jack-permitted-mulligan",
                "original_mulligan_encoder_sha256", JackMulliganEncoder.SOURCE_SHA256,
                "mulligan_encoder_source_sha256", args[0], "variant", JackMulliganEncoder.VARIANT)));
        BufferedReader in = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        String line; long last = 0;
        while ((line = in.readLine()) != null) {
            Map<String, Object> record = null;
            try {
                record = Json.parseObject(line);
                Object id = record.get("id");
                if (!(id instanceof String) || !((String) id).matches("[1-9][0-9]*")) {
                    throw new IllegalArgumentException("mulligan request ID must be an increasing decimal string");
                }
                long current = Long.parseLong((String) id);
                if (current <= last) throw new IllegalArgumentException("stale mulligan request ID");
                last = current;
                Map<String, Object> encoded = JackMulliganEncoder.encode(Json.obj(record, "game_start"),
                        Json.obj(record, "decision"), seed(Json.str(record, "world_seed")), seed(Json.str(record, "id_seed")));
                out.println(Json.canonical(Json.map("id", id, "ok", true, "encoded", encoded)));
            } catch (Exception | LinkageError e) {
                out.println(Json.canonical(Json.map("id", record == null ? null : record.get("id"),
                        "ok", false, "error", e.toString())));
                break;
            }
        }
    }
    private static byte[] seed(String value) {
        if (value == null || !value.matches("[a-f0-9]{64}")) {
            throw new IllegalArgumentException("mulligan seeds must be 32-byte hexadecimal strings");
        }
        return Seeds.unhex(value);
    }
}
