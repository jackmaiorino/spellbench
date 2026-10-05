package spellbench.kit.xmage;

import mage.game.permanent.Permanent;
import mage.player.cabt.CardResolver;
import mage.player.spellbench.Warmup;
import spellbench.kit.core.Json;
import spellbench.kit.core.Sampler;
import spellbench.kit.core.VisibleNames;

import java.io.FileDescriptor;
import java.io.FileOutputStream;
import java.io.PrintStream;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Witness Protection through two real front/runner pairs and the live engine. */
public final class RenameCheck {
    private static PrintStream output;
    private static final String RENAMED = "Legitimate Businessperson";

    private static void require(String name, boolean condition, Object detail) {
        output.println(Json.canonical(Json.map("check", name, "pass", condition, "detail", detail)));
        if (!condition) throw new AssertionError(name);
    }

    static String renamedId(Map<String, Object> decision) {
        Map<String, Object> observation = Json.obj(decision, "observation");
        for (Object player : Json.arr(observation, "players")) {
            for (Object item : Json.arr(Json.obj(player), "battlefield")) {
                Map<String, Object> card = Json.obj(item);
                if (RENAMED.equals(Json.str(card, "card_name"))) return Json.str(card, "object_id");
            }
        }
        return null;
    }

    @SuppressWarnings("unchecked")
    public static void main(String[] args) throws Exception {
        output = new PrintStream(new FileOutputStream(FileDescriptor.out), true, "UTF-8");
        System.setOut(System.err);
        Runner.quietLogs();
        KitRandom.installBoot();
        Warmup.framework();
        new CardResolver().resolve("Plains");
        Slice.SeatSetup a = new Slice.SeatSetup().lib("Island", 8);
        a.hand.addAll(Arrays.asList("Witness Protection", "Island"));
        a.battlefield.addAll(Arrays.asList("Island", "Island", "Island"));
        Slice.SeatSetup b = new Slice.SeatSetup().lib("Forest", 8);
        b.hand.addAll(Arrays.asList("Forest", "Grizzly Bears"));
        b.battlefield.addAll(Arrays.asList("Forest", "Forest", "Grizzly Bears"));
        Slice.EnginePos engine = Slice.EnginePos.start("native-rename-repair", a, b);
        SliceProd.FrontSeat[] agents = new SliceProd.FrontSeat[2];
        Map<String, String> origins = new LinkedHashMap<>();
        try {
            require("RENAME.fixture.priority", engine.advance(d -> Slice.priorityOf(d, "p0", "precombat_main"), 80), "live engine");
            for (int seat = 0; seat < 2; seat++) {
                agents[seat] = new SliceProd.FrontSeat("rename-" + seat, "h1", Slice.gameStart("p" + seat, a, b));
            }
            require("RENAME.fixture.cast_offered", SliceProd.forceFirst(engine, agents[0], "cast_spell", "Witness Protection"), "fixture forces only the first cast");
            VisibleNames.observe(Json.obj(engine.decision(), "observation"), origins);
            engine.answer(((Number) agents[0].choose(engine.decision()).get("candidate")).intValue());
            boolean[] checked = {false, false};
            boolean combatChecked = false;
            for (int step = 0; step < 180 && !engine.over() && !(checked[0] && checked[1] && combatChecked); step++) {
                Map<String, Object> decision = engine.decision();
                int seat = "p0".equals(engine.acting()) ? 0 : 1;
                boolean renamedPriority = renamedId(decision) != null && Slice.priorityOf(decision, "p" + seat, "precombat_main")
                        && ("p" + seat).equals(Json.str(Json.obj(decision, "observation"), "active_seat"))
                        && Json.arr(Json.obj(decision, "observation"), "stack").isEmpty()
                        && Json.arr(decision, "candidates").size() > 1;
                Map<String, Object> answer = agents[seat].choose(decision);
                if (!combatChecked && renamedId(decision) != null
                        && "declare_attack".equals(Slice.Front_firstKind(decision))
                        && Json.arr(decision, "candidates").size() > 1) {
                    Map<String, Object> line = Json.obj(answer, "line");
                    require("RENAME.combat.searched_with_observed_origin", "combat_anchor".equals(answer.get("path"))
                            && "bot".equals(answer.get("tag")) && line != null
                            && Json.canonical(line.get("world_flags")).contains("approximate:renamed_object"), answer);
                    combatChecked = true;
                }
                if (renamedPriority && !checked[seat]) {
                    Map<String, Object> line = Json.obj(answer, "line");
                    require("RENAME.p" + seat + ".searched_with_observed_origin", "priority_anchor".equals(answer.get("path"))
                            && "bot".equals(answer.get("tag")) && line != null
                            && Json.canonical(line.get("world_flags")).contains("approximate:renamed_object"), answer);
                    checked[seat] = true;
                    if (seat == 0) {
                        Map<String, Object> obs = Json.obj(Json.copy(decision.get("observation")));
                        Map<String, Object> history = Json.map("card_origins", VisibleNames.changed(obs, origins));
                        KitRandom.installBoot();
                        List<String> flags = WorldBuilder.restoreVisibleNames(obs, history);
                        KitRandom random = KitRandom.install(Slice.ID_SEED, Slice.ID_SEED);
                        WorldBuilder.Spec spec = new WorldBuilder.Spec();
                        spec.gameStart = Slice.gameStart("p0", a, b);
                        spec.observation = obs;
                        spec.sample = Sampler.sample(spec.gameStart, obs, random.stream("sampler"));
                        spec.random = random;
                        spec.viewerFactory = name -> new KitMad(name, 6);
                        spec.otherFactory = Puppet::new;
                        World world = WorldBuilder.build(spec);
                        Permanent card = world.game.getPermanent(world.idToUuid.get(renamedId(decision)));
                        require("RENAME.world.aura_reapplies_name_and_characteristics", card != null && RENAMED.equals(card.getName())
                                        && card.getPower().getValue() == 1 && card.getToughness().getValue() == 1
                                        && flags.contains("approximate:renamed_object"), flags);
                        SliceProd.FrontSeat late = new SliceProd.FrontSeat("rename-unobserved", "h1", Slice.gameStart("p0", a, b));
                        try {
                            Map<String, Object> refused = late.choose(decision);
                            require("RENAME.unobserved_origin_not_guessed", "wrapper".equals(refused.get("tag"))
                                    && String.valueOf(refused.get("path")).endsWith("priority_failed"), refused);
                        } finally {
                            late.close();
                        }
                    }
                }
                engine.answer(((Number) answer.get("candidate")).intValue());
            }
            require("RENAME.both_seats_and_combat_checked", checked[0] && checked[1] && combatChecked,
                    Arrays.asList(checked[0], checked[1], combatChecked));
        } finally {
            for (SliceProd.FrontSeat agent : agents) if (agent != null) agent.close();
            engine.seats.exchange.close();
        }
    }
}
