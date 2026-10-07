package spellbench.kit.xmage;

import mage.player.cabt.CardResolver;
import mage.player.spellbench.Warmup;
import spellbench.kit.core.Json;
import spellbench.models.exp1.GameAccess;
import spellbench.models.exp1.PlaySettings;
import spellbench.models.maintainer.EmbeddingCache;

import java.io.BufferedReader;
import java.io.FileDescriptor;
import java.io.FileOutputStream;
import java.io.InputStreamReader;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.util.Map;

/** Serial original inherited card choices; no inference or selection RNG. */
public final class MaintainerParentCardEncoderMain {
    private MaintainerParentCardEncoderMain() { }
    public static void main(String[] args) throws Exception {
        if (args.length != 15) throw new IllegalArgumentException("usage: EMBEDDINGS EMBEDDINGS_SHA ENCODER_SHA CANDIDATE_SHA TARGET_RULES_SHA MODE_RULES_SHA DIALOG_RULES_SHA PAYMENT_RULES_SHA CARD_SET_RULES_SHA PARENT_RULES_SHA PARENT_SELECTOR_SHA PARENT_COMPARATOR_SHA PARENT_PERMANENT_SHA PARENT_SCORING_SHA PARENT_MAGIC_ABILITY_SHA");
        System.setProperty("spellbench.maintainer.embeddingFile", args[0]);
        String[] names = {"embeddingSha256", "encoderSourceSha256", "candidateSourceSha256", "targetRulesSourceSha256",
                "modeRulesSourceSha256", "dialogRulesSourceSha256", "manaPaymentRulesSourceSha256", "cardSetRulesSourceSha256",
                "parentCardRulesSourceSha256", "parentSelectorSourceSha256", "parentComparatorSourceSha256", "parentPermanentSourceSha256", "parentScoringSourceSha256", "parentMagicAbilitySourceSha256"};
        String[] fields = {"embedding_cache_sha256", "encoder_source_sha256", "candidate_source_sha256", "target_rules_source_sha256",
                "mode_rules_source_sha256", "dialog_rules_source_sha256", "mana_payment_rules_source_sha256", "card_set_rules_source_sha256",
                "parent_card_rules_source_sha256", "parent_selector_source_sha256", "parent_comparator_source_sha256", "parent_permanent_source_sha256", "parent_scoring_source_sha256", "parent_magic_ability_source_sha256"};
        for (int i = 0; i < names.length; i++) {
            if (!args[i+1].matches("[a-f0-9]{64}")) throw new IllegalArgumentException("parent sources must be SHA-256");
            System.setProperty("spellbench.maintainer." + names[i], args[i+1]);
        }
        for (String name : new String[]{"CandidateEncoder", "ModeRules", "TargetRules", "CardSetRules"}) MaintainerTargetEncoder.original(name);
        MaintainerDialogEncoder.rulesClass(); new MaintainerManaReplay(args[7]);
        int embeddings = EmbeddingCache.size();
        PrintStream out = new PrintStream(new FileOutputStream(FileDescriptor.out), true, "UTF-8");
        System.setOut(System.err); Runner.quietLogs(); KitRandom.installBoot(); Warmup.framework();
        // Original ability-score initialization creates abilities under the fixed boot stream.
        MaintainerParentCardEncoder.parentRules();
        new CardResolver().resolve("Plains");
        Map<String, Object> ready = Json.map("ready", true, "encoder", "maintainer-permitted-parent-card",
                "original_callback_sha256", MaintainerModeEncoder.SOURCE, "variant", MaintainerParentCardEncoder.VARIANT,
                "mana_payment_variant", MaintainerManaReplay.VARIANT, "embedding_count", (long) embeddings);
        for (int i = 0; i < fields.length; i++) ready.put(fields[i], args[i+1]);
        out.println(Json.canonical(ready));
        BufferedReader input = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        String line; long last = 0;
        while ((line = input.readLine()) != null) {
            Map<String, Object> record = null;
            try {
                record = Json.parseObject(line); Object id = record.get("id");
                if (!(id instanceof String) || !((String) id).matches("[1-9][0-9]*")) throw new IllegalArgumentException("parent requests need increasing decimal-string IDs");
                long current = Long.parseLong((String) id);
                if (current <= last) throw new IllegalArgumentException("stale parent request ID"); last = current;
                for (String name : new String[]{"world_seed", "id_seed"}) {
                    String seed = Json.str(record, name);
                    if (seed == null || !seed.matches("[a-f0-9]{64}")) throw new IllegalArgumentException("parent seeds must be 32-byte hex");
                }
                ModelReplay.Result replay = ModelReplay.runTarget(record,
                        new MaintainerParentCardEncoder(Json.obj(record, "game_start"), new MaintainerManaReplay(args[7])));
                replay.encoded.put("request_sha256", MaintainerModeEncoder.hash(record));
                out.println(Json.canonical(Json.map("id", id, "ok", true, "encoded", replay.encoded)));
            } catch (Exception | LinkageError e) {
                out.println(Json.canonical(Json.map("id", record == null ? "invalid" : record.get("id"), "ok", false,
                        "error", e.getClass().getSimpleName() + ": " + e.getMessage())));
                break;
            } finally { GameAccess.reset(); PlaySettings.reset(); }
        }
    }
}
