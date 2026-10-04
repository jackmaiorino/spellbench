package spellbench.kit.xmage;

import mage.player.cabt.CardResolver;
import mage.player.spellbench.Warmup;
import mage.player.spellbench.rng.GameRandom;
import mage.player.spellbench.server.EngineProfile;
import spellbench.kit.core.Json;
import spellbench.kit.core.Seeds;
import spellbench.kit.core.Sampler;
import spellbench.models.jack.EmbeddingCache;

import java.io.FileDescriptor;
import java.io.FileOutputStream;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;

/** Actual priority mana feature encoding and sampled-world invariance. Requires a guarded native launch. */
public final class JackManaEncoderCheck {
    private static void require(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    private static String features(Map<String, Object> encoded) {
        return Json.canonical(Json.map("sequence", encoded.get("sequence"), "padding", encoded.get("padding"),
                "token_ids", encoded.get("token_ids"), "candidate_features", encoded.get("candidate_features"),
                "candidate_ids", encoded.get("candidate_ids"), "candidate_mask", encoded.get("candidate_mask"),
                "candidate_refs", encoded.get("candidate_refs")));
    }

    @SuppressWarnings("unchecked")
    public static void main(String[] args) throws Exception {
        if (args.length != 5) throw new IllegalArgumentException("usage: EMBEDDINGS SHA STAGED_ENCODER_SHA STAGED_CANDIDATE_SHA OUTPUT");
        System.setProperty("spellbench.priorityMana", "true");
        System.setProperty("spellbench.jack.embeddingFile", args[0]);
        System.setProperty("spellbench.jack.embeddingSha256", args[1]);
        System.setProperty("spellbench.jack.encoderSourceSha256", args[2]);
        System.setProperty("spellbench.jack.candidateSourceSha256", args[3]);
        EmbeddingCache.size();
        PrintStream out = new PrintStream(new FileOutputStream(FileDescriptor.out), true, "UTF-8");
        System.setOut(System.err); Runner.quietLogs(); GameRandom.installBoot(); Warmup.framework();
        new CardResolver().resolve("Forest");
        Slice.SeatSetup own = new Slice.SeatSetup().lib("Forest", 7);
        own.library.add("Elvish Mystic"); own.hand.addAll(Arrays.asList("Llanowar Elves", "Forest"));
        own.battlefield.addAll(Arrays.asList("Forest", "Forest"));
        Slice.SeatSetup opponent = new Slice.SeatSetup().lib("Forest", 7);
        opponent.library.add("Llanowar Elves"); opponent.hand.addAll(Arrays.asList("Elvish Mystic", "Forest"));
        opponent.battlefield.add("Forest");
        Slice.EnginePos position = Slice.EnginePos.startPriorityMana("jack-mana-encoder", own, opponent);
        try {
            require(position.advance(d -> Slice.priorityOf(d, "p0", "precombat_main"), 50), "priority not reached");
            Map<String, Object> decision = Json.parseObject(Json.canonical(position.decision()));
            Map<String, Object> start = Slice.gameStart("p0", own, opponent);
            Map<String, Object> hello = EngineProfile.load().helloOk("native", 0);
            start.put("engine_profile", Json.map("observation", hello.get("observation"),
                    "decision_kinds", hello.get("decision_kinds")));
            byte[] ids = Seeds.hmac("jack-mana-encoder".getBytes(StandardCharsets.UTF_8), "ids");
            byte[] seed = Seeds.hmac(ids, "world");
            Map<String, Object> encoded = JackEncoder.encode(start, decision, seed, ids);
            List<Object> candidates = Json.arr(decision, "candidates"), refs = Json.arr(encoded, "candidate_refs");
            require(refs.size() == candidates.size(), "encoded offered choices changed");
            List<Object> sources = new ArrayList<>();
            for (int i = 0; i < candidates.size(); i++) {
                Map<String, Object> semantic = Json.obj(Json.obj(candidates.get(i)), "semantic");
                if ("activate_mana_ability".equals(semantic.get("kind"))) {
                    sources.add(semantic.get("source"));
                    require(Boolean.TRUE.equals(Json.arr(encoded, "candidate_mask").get(i)), "mana candidate masked");
                    require(Json.obj(candidates.get(i)).get("candidate_id").equals(Json.obj(refs.get(i)).get("candidate_id")),
                            "mana feature slot lost public binding");
                }
            }
            require(sources.size() == 2 && !sources.get(0).equals(sources.get(1)), "equal-text sources collapsed");
            String baseline = features(encoded);
            String firstSample = Json.canonical(Sampler.sample(start, Json.obj(decision, "observation"),
                    KitRandom.install(seed, ids).stream("sampler")).json());
            int different = 0;
            for (int i = 0; i < 8; i++) {
                byte[] next = Seeds.hmac(ids, "hidden " + i);
                String nextSample = Json.canonical(Sampler.sample(start, Json.obj(decision, "observation"),
                        KitRandom.install(next, ids).stream("sampler")).json());
                if (!firstSample.equals(nextSample)) different++;
                require(baseline.equals(features(JackEncoder.encode(start, decision, next, ids))),
                        "hidden sample changed mana features or public source binding");
            }
            require(different > 0, "hidden-world check lacked different hidden samples");
            Map<String, Object> changed = (Map<String, Object>) Json.copy(start);
            Json.obj(changed, "engine_profile").put("decision_kinds", Arrays.asList("pass", "play_land", "cast_spell"));
            try {
                JackEncoder.encode(changed, decision, seed, ids);
                throw new AssertionError("undeclared mana feature request accepted");
            } catch (IllegalArgumentException expected) {
                require(expected.getMessage().contains("declared opt-in"), "wrong refusal");
            }
            Map<String, Object> result = Json.map("passed", true, "decision", decision, "game_start", start,
                    "encoded", encoded, "mana_sources", sources, "hidden_worlds", 8L,
                    "different_hidden_samples", (long) different,
                    "scope", "priority mana feature encoding only; original priority chooser and full games unfinished");
            byte[] raw = Json.canonical(result).getBytes(StandardCharsets.UTF_8);
            Files.write(Paths.get(args[4]), raw, StandardOpenOption.CREATE_NEW);
            out.println(Json.canonical(Json.map("passed", true, "mana_sources", 2L, "hidden_worlds", 8L)));
        } finally { position.seats.exchange.close(); }
    }
}
