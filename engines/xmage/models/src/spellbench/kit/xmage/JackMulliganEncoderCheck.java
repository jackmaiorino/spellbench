package spellbench.kit.xmage;

import mage.player.cabt.CardResolver;
import mage.player.spellbench.Warmup;
import spellbench.kit.core.Json;
import spellbench.kit.core.Sampler;
import spellbench.kit.core.Seeds;

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

/** Original mulligan features from an actual pregame callback; no trained model. */
public final class JackMulliganEncoderCheck {
    private JackMulliganEncoderCheck() { }
    public static void main(String[] args) throws Exception {
        if (args.length != 2) throw new IllegalArgumentException("usage: STAGED_ENCODER_SHA256 NEW_OUTPUT_DIRECTORY");
        System.setProperty("spellbench.jack.mulliganEncoderSourceSha256", args[0]);
        PrintStream out = new PrintStream(new FileOutputStream(FileDescriptor.out), true, "UTF-8");
        System.setOut(System.err); Runner.quietLogs(); KitRandom.installBoot(); Warmup.framework();
        new CardResolver().resolve("Forest");
        Files.createDirectory(Paths.get(args[1]));
        Slice.SeatSetup a = new Slice.SeatSetup().lib("Forest", 7).lib("Mountain", 3)
                .lib("Elvish Mystic", 2).lib("Shock", 2);
        a.hand.addAll(Arrays.asList("Forest", "Forest", "Mountain", "Llanowar Elves",
                "Lightning Bolt", "Abrade", "Runeclaw Bear"));
        Slice.SeatSetup b = new Slice.SeatSetup().lib("Mountain", 8).lib("Lightning Bolt", 2);
        b.hand.addAll(Arrays.asList("Mountain", "Mountain", "Mountain", "Fireball", "Shock", "Shock", "Shock"));
        Slice.EnginePos position = Slice.EnginePos.start("jack-permitted-mulligan", a, b);
        try {
            if (!position.advance(d -> "p0".equals(Json.str(d, "acting_seat"))
                    && "mulligan".equals(Slice.Front_firstKind(d)), 20)) {
                throw new IllegalStateException("native fixture did not reach its actual mulligan callback");
            }
            Map<String, Object> start = Slice.gameStart("p0", a, b), decision = position.decision();
            byte[] ids = Seeds.hmac("jack-permitted-mulligan".getBytes(StandardCharsets.UTF_8), "ids");
            byte[] seed = Seeds.hmac(ids, "first world");
            Map<String, Object> first = JackMulliganEncoder.encode(start, decision, seed, ids);
            List<Object> values = Json.arr(first, "values");
            if (!Long.valueOf(3).equals(values.get(1)) || !Long.valueOf(2).equals(values.get(2))
                    || ((Number) values.get(3)).doubleValue() != 1.5 || values.size() != 71) {
                throw new IllegalStateException("source hand land, creature, mana-value or width features changed");
            }
            int hidden = 1+Math.floorMod("Fireball".hashCode(), 65535);
            if (values.subList(4, 71).contains((long) hidden)) {
                throw new IllegalStateException("mulligan encoded an opponent-only card");
            }
            String baseline = Json.canonical(values);
            String sample = Json.canonical(Sampler.sample(start, Json.obj(decision, "observation"),
                    KitRandom.install(seed, ids).stream("sampler")).json());
            int different = 0;
            for (int i = 0; i < 8; i++) {
                byte[] next = Seeds.hmac(ids, "world "+i);
                String changed = Json.canonical(Sampler.sample(start, Json.obj(decision, "observation"),
                        KitRandom.install(next, ids).stream("sampler")).json());
                if (!sample.equals(changed)) different++;
                if (!baseline.equals(Json.canonical(JackMulliganEncoder.encode(start, decision, next, ids).get("values")))) {
                    throw new IllegalStateException("hidden sample or library order changed mulligan features");
                }
            }
            if (different == 0) throw new IllegalStateException("hidden-world test had no distinct samples");
            Map<String, Object> changed = Json.obj(Json.copy(decision));
            for (Object p : Json.arr(Json.obj(changed, "observation"), "players")) {
                Map<String, Object> player = Json.obj(p);
                if ("p0".equals(Json.str(player, "seat"))) player.put("mulligans_taken", 1L);
            }
            for (Object c : Json.arr(changed, "candidates")) Json.obj(Json.obj(c), "semantic").put("mulligans_taken", 1L);
            List<Object> advanced = Json.arr(JackMulliganEncoder.encode(start, changed, seed, ids), "values");
            if (!Long.valueOf(1).equals(advanced.get(0)) || !values.subList(1, 71).equals(advanced.subList(1, 71))) {
                throw new IllegalStateException("visible mulligan count failed to update exactly its original scalar");
            }
            Map<String, Object> record = Json.map("game_start", start, "decision", decision,
                    "world_seed", Seeds.hex(seed), "id_seed", Seeds.hex(ids));
            write(args[1], "RECORD.json", record); write(args[1], "ENCODED.json", first);
            write(args[1], "CHECK.json", Json.map("schema", "spellbench-jack-mulligan-encoder-check/v1",
                    "actual_pregame_callback", true, "different_hidden_samples", (long) different,
                    "hidden_sample_features_identical", true, "original_hand_features_checked", true,
                    "other_hand_excluded", true, "visible_mulligan_count_changes_only_scalar", true,
                    "original_source_sha256", JackMulliganEncoder.SOURCE_SHA256,
                    "staged_source_sha256", args[0], "checkpoint_inference", false,
                    "rated_games", 0L, "full_game_qualified", false));
            out.println(Json.canonical(Json.map("passed", true, "different_hidden_samples", (long) different)));
        } finally { position.seats.exchange.close(); }
    }
    private static void write(String root, String name, Map<String, Object> value) throws Exception {
        Files.write(Paths.get(root, name), Json.canonical(value).getBytes(StandardCharsets.UTF_8), StandardOpenOption.CREATE_NEW);
    }
}
