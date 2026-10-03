package spellbench.kit.xmage;

import mage.player.cabt.CardResolver;
import mage.player.spellbench.Warmup;
import spellbench.kit.core.Json;
import spellbench.kit.core.Sampler;
import spellbench.kit.core.Seeds;

import java.io.FileDescriptor;
import java.io.FileOutputStream;
import java.io.PrintStream;
import java.util.Arrays;
import java.util.List;
import java.util.Map;

/** A real priority fixture and a powered hidden-world encoder check. */
public final class ModelEncoderCheck {
    @SuppressWarnings("unchecked")
    public static void main(String[] args) throws Exception {
        PrintStream out = new PrintStream(new FileOutputStream(FileDescriptor.out), true, "UTF-8");
        System.setOut(System.err);
        Runner.quietLogs();
        KitRandom.installBoot();
        Warmup.framework();
        new CardResolver().resolve("Plains");
        Slice.SeatSetup a = new Slice.SeatSetup().lib("Swamp", 8);
        a.hand.addAll(Arrays.asList("Stab", "Swamp"));
        a.battlefield.addAll(Arrays.asList("Swamp", "Swamp"));
        Slice.SeatSetup b = new Slice.SeatSetup().lib("Island", 7);
        b.library.add("Cancel");
        b.hand.addAll(Arrays.asList("Island", "Essence Scatter"));
        b.battlefield.addAll(Arrays.asList("Island", "Grizzly Bears"));
        Slice.EnginePos position = Slice.EnginePos.start("model-priority-slice", a, b);
        try {
            if (!position.advance(d -> Slice.priorityOf(d, "p0", "precombat_main"), 50)) {
                throw new IllegalStateException("fixture did not reach its priority decision");
            }
            Map<String, Object> start = Slice.gameStart("p0", a, b);
            Map<String, Object> decision = position.decision();
            byte[] ids = Seeds.hmac("model-priority-slice".getBytes("UTF-8"), "ids");
            byte[] seed = Seeds.hmac(ids, "first world");
            Map<String, Object> first = ModelEncoder.priority(start, decision, seed, ids);
            Sampler.Sample firstSample = Sampler.sample(start, Json.obj(decision, "observation"),
                    KitRandom.install(seed, ids).stream("sampler"));
            boolean powered = false;
            for (int i = 0; i < 16; i++) {
                byte[] nextSeed = Seeds.hmac(ids, "world " + i);
                Sampler.Sample nextSample = Sampler.sample(start, Json.obj(decision, "observation"),
                        KitRandom.install(nextSeed, ids).stream("sampler"));
                if (!Json.canonical(firstSample.json()).equals(Json.canonical(nextSample.json()))) {
                    powered = true;
                    Map<String, Object> second = ModelEncoder.priority(start, decision, nextSeed, ids);
                    if (!first.get("features").equals(second.get("features"))
                            || !first.get("priority_slots").equals(second.get("priority_slots"))) {
                        throw new IllegalStateException("hidden sample changed the priority encoding or action mapping");
                    }
                }
            }
            if (!powered) throw new IllegalStateException("hidden-world check did not vary the hidden sample");
            Map<String, Object> changed = (Map<String, Object>) Json.copy(decision);
            List<Object> players = Json.arr(Json.obj(changed, "observation"), "players");
            for (Object p : players) {
                Map<String, Object> player = Json.obj(p);
                if ("p0".equals(Json.str(player, "seat"))) player.put("life", 11L);
            }
            Map<String, Object> visible = ModelEncoder.priority(start, changed, seed, ids);
            if (first.get("features").equals(visible.get("features"))) {
                throw new IllegalStateException("visible life change did not alter the feature vector");
            }
            first.put("checks", Json.map("hidden_sample_varied", powered, "hidden_sample_encoding_identical", true,
                    "visible_life_change_detected", true, "scope", "priority fixture only; no full-game qualification"));
            out.println(Json.canonical(first));
        } finally {
            position.seats.exchange.close();
        }
    }
}
