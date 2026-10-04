package spellbench.kit.xmage;

import mage.player.cabt.CardResolver;
import mage.player.spellbench.Warmup;
import spellbench.kit.core.Json;
import spellbench.models.exp1.GameAccess;
import spellbench.models.exp1.PlaySettings;
import spellbench.models.jack.EmbeddingCache;

import java.io.BufferedReader;
import java.io.FileDescriptor;
import java.io.FileOutputStream;
import java.io.InputStreamReader;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.util.Map;

/** Private serial pipe; original networks are owned separately by the caller. */
public final class JackModeEncoderMain {
    private JackModeEncoderMain() { }
    public static void main(String[] args) throws Exception {
        if (args.length != 5 && args.length != 6) throw new IllegalArgumentException("usage: EMBEDDINGS EMBEDDINGS_SHA ENCODER_SHA CANDIDATE_SHA MODE_RULES_SHA [DIALOG_RULES_SHA]");
        boolean originalMana = args.length == 6;
        System.setProperty("spellbench.jack.embeddingFile", args[0]);
        String[] names = originalMana
                ? new String[]{"embeddingSha256", "encoderSourceSha256", "candidateSourceSha256", "modeRulesSourceSha256", "dialogRulesSourceSha256"}
                : new String[]{"embeddingSha256", "encoderSourceSha256", "candidateSourceSha256", "modeRulesSourceSha256"};
        for (int i = 0; i < names.length; i++) {
            if (!args[i + 1].matches("[a-f0-9]{64}")) throw new IllegalArgumentException("mode sources must be SHA-256");
            System.setProperty("spellbench.jack." + names[i], args[i + 1]);
        }
        for (String name : new String[]{"CandidateEncoder", "ModeRules"}) {
            if (!JackModeEncoder.SOURCE.equals(Class.forName("spellbench.models.jack." + name).getField("SOURCE_SHA256").get(null))) {
                throw new IllegalArgumentException("mode pipe has the wrong original callback source");
            }
        }
        if (originalMana) JackDialogEncoder.rulesClass();
        int embeddings = EmbeddingCache.size();
        PrintStream out = new PrintStream(new FileOutputStream(FileDescriptor.out), true, "UTF-8");
        System.setOut(System.err); Runner.quietLogs(); KitRandom.installBoot(); Warmup.framework();
        new CardResolver().resolve("Plains");
        Map<String, Object> ready = Json.map("ready", true, "encoder", originalMana ? "jack-permitted-mode-mana" : "jack-permitted-mode",
                "encoder_source_sha256", args[2], "candidate_source_sha256", args[3], "mode_rules_source_sha256", args[4],
                "embedding_cache_sha256", args[1], "original_callback_sha256", JackModeEncoder.SOURCE,
                "variant", originalMana ? JackModeEncoder.MANA_VARIANT : JackModeEncoder.VARIANT, "embedding_count", (long) embeddings);
        if (originalMana) ready.put("dialog_rules_source_sha256", args[5]);
        out.println(Json.canonical(ready));
        BufferedReader in = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        String line; long last = 0;
        while ((line = in.readLine()) != null) {
            Map<String, Object> record = null;
            try {
                record = Json.parseObject(line);
                Object id = record.get("id");
                if (!(id instanceof String) || !((String) id).matches("[1-9][0-9]*")) {
                    throw new IllegalArgumentException("mode requests need increasing decimal-string IDs");
                }
                long current = Long.parseLong((String) id);
                if (current <= last) throw new IllegalArgumentException("stale mode request ID");
                last = current;
                for (String name : new String[]{"world_seed", "id_seed"}) {
                    String seed = Json.str(record, name);
                    if (seed == null || !seed.matches("[a-f0-9]{64}")) throw new IllegalArgumentException("mode seeds must be 32-byte hex");
                }
                ModelReplay.Result replay = ModelReplay.runMode(record, new JackModeEncoder(Json.obj(record, "game_start"), originalMana));
                replay.encoded.put("request_sha256", JackModeEncoder.hash(record));
                out.println(Json.canonical(Json.map("id", id, "ok", true, "encoded", replay.encoded)));
            } catch (Exception | LinkageError e) {
                out.println(Json.canonical(Json.map("id", record == null ? null : record.get("id"), "ok", false, "error", e.toString())));
                break;
            } finally { GameAccess.reset(); PlaySettings.reset(); }
        }
    }
}
