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

/** Serial original provided-card encoding; paired inference and seeded physical-copy choice stay owned. */
public final class JackCardSetEncoderMain {
    private JackCardSetEncoderMain() { }
    public static void main(String[] args) throws Exception {
        if (args.length != 9) throw new IllegalArgumentException("usage: EMBEDDINGS EMBEDDINGS_SHA ENCODER_SHA CANDIDATE_SHA TARGET_RULES_SHA MODE_RULES_SHA DIALOG_RULES_SHA PAYMENT_RULES_SHA CARD_SET_RULES_SHA");
        System.setProperty("spellbench.jack.embeddingFile", args[0]);
        String[] names = {"embeddingSha256", "encoderSourceSha256", "candidateSourceSha256", "targetRulesSourceSha256",
                "modeRulesSourceSha256", "dialogRulesSourceSha256", "manaPaymentRulesSourceSha256", "cardSetRulesSourceSha256"};
        for (int i = 0; i < names.length; i++) {
            if (!args[i+1].matches("[a-f0-9]{64}")) throw new IllegalArgumentException("target sources must be SHA-256");
            System.setProperty("spellbench.jack." + names[i], args[i+1]);
        }
        for (String name : new String[]{"CandidateEncoder", "ModeRules", "TargetRules", "CardSetRules"}) JackTargetEncoder.original(name);
        JackDialogEncoder.rulesClass(); new JackManaReplay(args[7]);
        int embeddings = EmbeddingCache.size();
        PrintStream out = new PrintStream(new FileOutputStream(FileDescriptor.out), true, "UTF-8");
        System.setOut(System.err); Runner.quietLogs(); KitRandom.installBoot(); Warmup.framework();
        new CardResolver().resolve("Plains");
        out.println(Json.canonical(Json.map("ready", true, "encoder", "jack-permitted-card-set",
                "encoder_source_sha256", args[2], "candidate_source_sha256", args[3], "target_rules_source_sha256", args[4],
                "mode_rules_source_sha256", args[5], "dialog_rules_source_sha256", args[6], "mana_payment_rules_source_sha256", args[7],
                "card_set_rules_source_sha256", args[8], "embedding_cache_sha256", args[1], "original_callback_sha256", JackModeEncoder.SOURCE,
                "variant", JackCardSetEncoder.VARIANT, "mana_payment_variant", JackManaReplay.VARIANT, "embedding_count", (long) embeddings)));
        BufferedReader input = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        String line; long last = 0;
        while ((line = input.readLine()) != null) {
            Map<String, Object> record = null;
            try {
                record = Json.parseObject(line); Object id = record.get("id");
                if (!(id instanceof String) || !((String) id).matches("[1-9][0-9]*")) throw new IllegalArgumentException("target requests need increasing decimal-string IDs");
                long current = Long.parseLong((String) id);
                if (current <= last) throw new IllegalArgumentException("stale target request ID"); last = current;
                for (String name : new String[]{"world_seed", "id_seed"}) {
                    String seed = Json.str(record, name);
                    if (seed == null || !seed.matches("[a-f0-9]{64}")) throw new IllegalArgumentException("target seeds must be 32-byte hex");
                }
                ModelReplay.Result replay = ModelReplay.runTarget(record,
                        new JackCardSetEncoder(Json.obj(record, "game_start"), new JackManaReplay(args[7])));
                replay.encoded.put("request_sha256", JackModeEncoder.hash(record));
                out.println(Json.canonical(Json.map("id", id, "ok", true, "encoded", replay.encoded)));
            } catch (Exception | LinkageError e) {
                out.println(Json.canonical(Json.map("id", record == null ? null : record.get("id"), "ok", false, "error", e.toString()))); break;
            } finally { GameAccess.reset(); PlaySettings.reset(); }
        }
    }
}
