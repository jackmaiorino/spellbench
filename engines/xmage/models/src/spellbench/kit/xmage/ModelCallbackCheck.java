package spellbench.kit.xmage;

import mage.player.ai.encoder.ActionEncoder;
import mage.player.cabt.CardResolver;
import mage.player.spellbench.Warmup;
import spellbench.kit.core.Json;
import spellbench.kit.core.Seeds;

import java.io.FileDescriptor;
import java.io.FileOutputStream;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Arrays;
import java.util.List;
import java.util.Map;

/** Real target and optional library-search decisions, including hidden-world variation. */
public final class ModelCallbackCheck {
    public static void main(String[] args) throws Exception {
        PrintStream out = new PrintStream(new FileOutputStream(FileDescriptor.out), true, "UTF-8");
        System.setOut(System.err);
        Runner.quietLogs();
        KitRandom.installBoot();
        Warmup.framework();
        new CardResolver().resolve("Plains");
        check(out, false, args.length == 1 ? Paths.get(args[0]) : null);
        check(out, true, args.length == 1 ? Paths.get(args[0]) : null);
    }

    @SuppressWarnings("unchecked")
    private static void check(PrintStream out, boolean binary, Path output) throws Exception {
        String family = binary ? "binary" : "target";
        String spell = binary ? "Campus Guide" : "Stab";
        String land = binary ? "Forest" : "Swamp";
        Slice.SeatSetup a = new Slice.SeatSetup().lib(land, 8);
        a.hand.addAll(Arrays.asList(spell, land));
        a.battlefield.addAll(Arrays.asList(land, land, land, land, land));
        Slice.SeatSetup b = new Slice.SeatSetup().lib("Island", 7);
        b.library.add("Cancel");
        b.hand.addAll(Arrays.asList("Island", "Essence Scatter"));
        b.battlefield.addAll(Arrays.asList("Island", "Grizzly Bears"));
        if (!binary) b.battlefield.add("Llanowar Elves");
        Slice.EnginePos position = Slice.EnginePos.start("model-callback-" + family, a, b);
        try {
            if (!position.advance(d -> Slice.priorityOf(d, "p0", "precombat_main"), 50)) {
                throw new IllegalStateException("fixture did not reach precombat priority");
            }
            Map<String, Object> start = Slice.gameStart("p0", a, b);
            int spellIndex = Slice.candidateWhere(position.decision(), "cast_spell", spell);
            if (spellIndex < 0) throw new IllegalStateException("fixture spell unavailable");
            position.answer(spellIndex);
            String expectedKind = binary ? "choose_boolean" : "choose_target";
            if (!position.advance(d -> "p0".equals(Json.str(d, "acting_seat"))
                    && expectedKind.equals(Slice.Front_firstKind(d)), 12)) {
                throw new IllegalStateException("fixture did not reach " + expectedKind);
            }
            Map<String, Object> decision = position.decision();
            byte[] ids = Seeds.hmac("model-callback".getBytes(StandardCharsets.UTF_8), family);
            byte[] seed = Seeds.hmac(ids, "first world");
            Map<String, Object> first = ModelEncoder.decision(start, decision, seed, ids);
            if (!family.equals(first.get("head"))) throw new IllegalStateException("wrong policy head");
            List<Object> slots = Json.arr(first, "policy_slots");
            ActionEncoder actions = new ActionEncoder();
            for (int i = 0; i < slots.size(); i++) {
                Map<String, Object> semantic = Json.obj(Json.obj(Json.arr(decision, "candidates").get(i)), "semantic");
                String targetName = null;
                if (!binary) {
                    String objectId = Json.str(Json.obj(Json.obj(semantic, "target"), "object"), "object_id");
                    Map<String, Object> object = new spellbench.kit.core.ObsIndex(Json.obj(decision, "observation")).record(objectId);
                    targetName = Json.str(object, "card_name");
                }
                long expected = binary ? (Json.bool(semantic, "value") ? 1 : 0) : actions.getTargetIndex(targetName);
                if (expected != Json.num(Json.obj(slots.get(i)), "policy_slot", -1)) {
                    throw new IllegalStateException("offered callback has the wrong policy slot");
                }
            }
            boolean varied = false;
            String firstSample = Json.canonical(spellbench.kit.core.Sampler.sample(start,
                    Json.obj(decision, "observation"), KitRandom.install(seed, ids).stream("sampler")).json());
            for (int i = 0; i < 16; i++) {
                byte[] next = Seeds.hmac(ids, "world " + i);
                String sample = Json.canonical(spellbench.kit.core.Sampler.sample(start,
                        Json.obj(decision, "observation"), KitRandom.install(next, ids).stream("sampler")).json());
                if (!firstSample.equals(sample)) {
                    varied = true;
                    Map<String, Object> second = ModelEncoder.decision(start, decision, next, ids);
                    if (!first.get("features").equals(second.get("features")) || !slots.equals(second.get("policy_slots"))) {
                        throw new IllegalStateException("hidden world changed callback encoding");
                    }
                }
            }
            if (!varied) throw new IllegalStateException("hidden-world callback check was not powered");
            Map<String, Object> changed = (Map<String, Object>) Json.copy(decision);
            for (Object player : Json.arr(Json.obj(changed, "observation"), "players")) {
                Map<String, Object> p = Json.obj(player);
                if ("p0".equals(Json.str(p, "seat"))) p.put("life", 11L);
            }
            if (first.get("features").equals(ModelEncoder.decision(start, changed, seed, ids).get("features"))) {
                throw new IllegalStateException("visible life change did not change callback features");
            }
            first.put("checks", Json.map("real_callback", expectedKind, "hidden_sample_varied", true,
                    "hidden_encoding_identical", true, "visible_life_change_detected", true));
            out.println(Json.canonical(first));
            if (output != null) {
                Files.write(output.resolve(family + "-record.json"), Json.canonical(Json.map("game_start", start,
                        "decision", decision, "world_seed", Seeds.hex(seed), "id_seed", Seeds.hex(ids)))
                        .getBytes(StandardCharsets.UTF_8), java.nio.file.StandardOpenOption.CREATE_NEW);
                Files.write(output.resolve(family + "-encoded.json"), Json.canonical(first).getBytes(StandardCharsets.UTF_8),
                        java.nio.file.StandardOpenOption.CREATE_NEW);
            }
        } finally {
            position.seats.exchange.close();
        }
    }
}
