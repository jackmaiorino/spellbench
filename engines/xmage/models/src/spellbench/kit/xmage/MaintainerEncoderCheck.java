package spellbench.kit.xmage;

import mage.player.cabt.CardResolver;
import mage.player.spellbench.Warmup;
import spellbench.kit.core.Json;
import spellbench.kit.core.Sampler;
import spellbench.kit.core.Seeds;
import spellbench.models.maintainer.EmbeddingCache;

import java.io.FileDescriptor;
import java.io.FileOutputStream;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.util.Arrays;
import java.util.List;
import java.util.Map;

/** Real active and nonactive priority views, with a powered hidden-world check. */
public final class MaintainerEncoderCheck {
    private MaintainerEncoderCheck() { }
    public static void main(String[] args) throws Exception {
        if (args.length != 5) throw new IllegalArgumentException("usage: EMBEDDINGS SHA256 STAGED_ENCODER_SHA256 STAGED_CANDIDATE_SHA256 OUTPUT");
        System.setProperty("spellbench.maintainer.embeddingFile", args[0]);
        System.setProperty("spellbench.maintainer.embeddingSha256", args[1]);
        System.setProperty("spellbench.maintainer.encoderSourceSha256", args[2]);
        System.setProperty("spellbench.maintainer.candidateSourceSha256", args[3]);
        int cacheEntries = EmbeddingCache.size();
        PrintStream out = new PrintStream(new FileOutputStream(FileDescriptor.out), true, "UTF-8");
        System.setOut(System.err);
        Runner.quietLogs();
        KitRandom.installBoot();
        Warmup.framework();
        new CardResolver().resolve("Forest");
        Slice.SeatSetup a = new Slice.SeatSetup().lib("Forest", 7);
        a.library.add("Elvish Mystic");
        a.hand.addAll(Arrays.asList("Llanowar Elves", "Forest"));
        a.battlefield.addAll(Arrays.asList("Forest", "Forest"));
        Slice.SeatSetup b = new Slice.SeatSetup().lib("Mountain", 7);
        b.library.add("Experimental Synthesizer");
        b.hand.addAll(Arrays.asList("Lightning Bolt", "Mountain"));
        b.battlefield.addAll(Arrays.asList("Mountain", "Mountain"));
        Slice.EnginePos position = Slice.EnginePos.start("maintainer-permitted-priority", a, b);
        try {
            if (!position.advance(d -> Slice.priorityOf(d, "p0", "precombat_main"), 50)) {
                throw new IllegalStateException("the maintainer's fixture did not reach the active priority");
            }
            Map<String, Object> active = check(Slice.gameStart("p0", a, b), position.decision(), "p0", "Llanowar Elves", "Lightning Bolt");
            int pass = -1;
            List<Object> offered = Json.arr(position.decision(), "candidates");
            for (int i = 0; i < offered.size(); i++) {
                if ("pass".equals(Json.str(Json.obj(Json.obj(offered.get(i)), "semantic"), "kind"))) { pass = i; break; }
            }
            if (pass < 0) throw new IllegalStateException("the maintainer's fixture has no offered priority pass");
            position.answer(pass);
            if (!position.advance(d -> Slice.priorityOf(d, "p1", "precombat_main"), 6)
                    || !"p0".equals(Json.str(Json.obj(position.decision(), "observation"), "active_seat"))) {
                throw new IllegalStateException("the maintainer's fixture did not reach nonactive priority");
            }
            Map<String, Object> nonactive = check(Slice.gameStart("p1", a, b), position.decision(), "p1", "Lightning Bolt", "Llanowar Elves");
            Map<String, Object> result = Json.map("schema", "spellbench-maintainer-priority-encoder-check/v1",
                    "active_view", active, "nonactive_view", nonactive, "embedding_count", (long) cacheEntries,
                    "encoder_source_sha256", args[2], "candidate_source_sha256", args[3], "embedding_cache_sha256", args[1],
                    "scope", "two real base-state and priority candidate fixtures; no checkpoint inference, full game or rating");
            byte[] raw = Json.canonical(result).getBytes(StandardCharsets.UTF_8);
            Files.write(Paths.get(args[4]), raw, StandardOpenOption.CREATE_NEW);
            out.println(new String(raw, StandardCharsets.UTF_8));
        } finally { position.seats.exchange.close(); }
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> check(Map<String, Object> start, Map<String, Object> decision,
                                              String viewer, String ownHand, String hiddenHand) throws Exception {
        byte[] ids = Seeds.hmac("maintainer-permitted-priority".getBytes(StandardCharsets.UTF_8), viewer);
        byte[] seed = Seeds.hmac(ids, "first world");
        Map<String, Object> first = MaintainerEncoder.encode(start, decision, seed, ids);
        List<Object> tokens = Json.arr(first, "token_ids");
        int ownId = 1 + Math.floorMod(ownHand.hashCode(), 65535);
        int hiddenId = 1 + Math.floorMod(hiddenHand.hashCode(), 65535);
        if (!tokens.contains((long) ownId) || tokens.contains((long) hiddenId)) {
            throw new IllegalStateException("the maintainer's base encoder did not use its acting viewer's hand");
        }
        List<Object> ownVector = Json.arr(Json.arr(first, "sequence").get(tokens.indexOf((long) ownId)));
        if (((Number) ownVector.get(mage.constants.Zone.values().length)).doubleValue() != 1.0) {
            throw new IllegalStateException("the maintainer's card ownership features use another player's perspective");
        }
        String baseline = features(first);
        List<Object> refs = Json.arr(first, "candidate_refs"), offered = Json.arr(decision, "candidates");
        List<Object> actionIds = Json.arr(first, "candidate_ids"), masks = Json.arr(first, "candidate_mask");
        List<Object> actionFeatures = Json.arr(first, "candidate_features");
        if (refs.size() != offered.size() || actionIds.size() != 64 || masks.size() != 64 || actionFeatures.size() != 64) {
            throw new IllegalStateException("the maintainer's candidates are not bound and padded to the original 64 slots");
        }
        boolean passChecked = false;
        for (int i = 0; i < 64; i++) {
            if (i >= offered.size()) {
                if (!Boolean.FALSE.equals(masks.get(i)) || ((Number) actionIds.get(i)).longValue() != 0) {
                    throw new IllegalStateException("the maintainer's padded candidate is legal or has a nonzero ID");
                }
                continue;
            }
            Map<String, Object> candidate = Json.obj(offered.get(i));
            if (!candidate.get("candidate_id").equals(Json.obj(refs.get(i)).get("candidate_id"))
                    || !Boolean.TRUE.equals(masks.get(i))) {
                throw new IllegalStateException("the maintainer's encoded candidate is not the corresponding offered choice");
            }
            if ("pass".equals(Json.str(Json.obj(candidate, "semantic"), "kind"))) {
                List<Object> vector = Json.arr(actionFeatures.get(i));
                if (((Number) actionIds.get(i)).longValue() != 1 + Math.floorMod("PASS".hashCode(), 65535)
                        || ((Number) vector.get(1)).doubleValue() != 1.0) {
                    throw new IllegalStateException("the maintainer's priority pass lost its original ID or feature");
                }
                passChecked = true;
            }
        }
        if (!passChecked) throw new IllegalStateException("the maintainer's fixture did not encode its offered priority pass");
        String sample = Json.canonical(Sampler.sample(start, Json.obj(decision, "observation"),
                KitRandom.install(seed, ids).stream("sampler")).json());
        int different = 0;
        for (int i = 0; i < 8; i++) {
            byte[] next = Seeds.hmac(ids, "world " + i);
            String changedSample = Json.canonical(Sampler.sample(start, Json.obj(decision, "observation"),
                    KitRandom.install(next, ids).stream("sampler")).json());
            if (!sample.equals(changedSample)) {
                different++;
                if (!baseline.equals(features(MaintainerEncoder.encode(start, decision, next, ids)))) {
                    throw new IllegalStateException("sampled hidden identities or order changed maintainer features");
                }
            }
        }
        if (different == 0) throw new IllegalStateException("the maintainer's hidden-world check lacked different hidden samples");
        Map<String, Object> changed = (Map<String, Object>) Json.copy(decision);
        for (Object value : Json.arr(Json.obj(changed, "observation"), "players")) {
            Map<String, Object> player = Json.obj(value);
            if (viewer.equals(Json.str(player, "seat"))) player.put("life", 11L);
        }
        if (baseline.equals(features(MaintainerEncoder.encode(start, changed, seed, ids)))) {
            throw new IllegalStateException("the maintainer's base features ignored the visible life change");
        }
        return Json.map("viewer", viewer, "different_hidden_samples", (long) different,
                "hidden_sample_features_identical", true, "visible_life_change_detected", true,
                "own_hand_encoded", true, "own_card_ownership_correct", true, "other_hand_excluded", true,
                "offered_priority_choices_bound", true, "original_pass_encoded", true,
                "candidate_padding_masked", true, "encoded", first);
    }

    private static String features(Map<String, Object> encoded) {
        return Json.canonical(Json.map("sequence", encoded.get("sequence"),
                "padding", encoded.get("padding"), "token_ids", encoded.get("token_ids"),
                "candidate_features", encoded.get("candidate_features"), "candidate_ids", encoded.get("candidate_ids"),
                "candidate_mask", encoded.get("candidate_mask"), "candidate_refs", encoded.get("candidate_refs")));
    }
}
