package spellbench.kit.xmage;

import mage.game.permanent.Permanent;
import mage.player.cabt.CardResolver;
import mage.player.spellbench.Warmup;
import mage.player.spellbench.rng.GameRandom;
import spellbench.kit.core.Json;

import java.io.FileDescriptor;
import java.io.FileOutputStream;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;

/** Actual mapper transitions. Requires a guarded native launch and a private ./db copy. */
public final class PriorityManaCheck {
    private static void require(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }

    private static Permanent permanent(Slice.EnginePos position, String name) {
        for (Permanent p : position.game.getBattlefield().getAllActivePermanents()) {
            if (p.getControllerId().equals(position.player("p0").getId()) && name.equals(p.getName())) return p;
        }
        throw new AssertionError("missing own permanent: " + name);
    }

    private static int colorGreen(Map<String, Object> decision) {
        List<Object> candidates = Json.arr(decision, "candidates");
        for (int i = 0; i < candidates.size(); i++) {
            Map<String, Object> semantic = Json.obj(Json.obj(candidates.get(i)), "semantic");
            if ("choose_color".equals(semantic.get("kind")) && "green".equals(semantic.get("color"))) return i;
        }
        return -1;
    }

    private static Map<String, Object> run(String family) {
        boolean enabled = !"default".equals(family);
        String source = "color".equals(family) ? "Mana Confluence"
                : "cost".equals(family) ? "Springleaf Drum" : "Forest";
        Slice.SeatSetup own = new Slice.SeatSetup().lib("Forest", 12);
        own.battlefield.add(source);
        own.battlefield.add("Llanowar Elves");
        if ("default".equals(family) || "float-and-cast".equals(family)) {
            own.battlefield.add("Forest");
            own.hand.add("Grizzly Bears");
        }
        Slice.SeatSetup opponent = new Slice.SeatSetup().lib("Island", 12);
        opponent.hand.add("Island");
        opponent.battlefield.add("Island");
        Slice.EnginePos position = enabled
                ? Slice.EnginePos.startPriorityMana("priority-mana-" + family, own, opponent)
                : Slice.EnginePos.start("priority-mana-" + family, own, opponent);
        List<Object> frames = new ArrayList<>();
        try {
            require(position.advance(d -> Slice.priorityOf(d, "p0", "precombat_main"), 50), "priority unavailable");
            Map<String, Object> initial = position.decision();
            int mana = Slice.candidateWhere(initial, "activate_mana_ability", source);
            require((mana >= 0) == enabled, "declaration/mapper setting mismatch");
            require(Slice.candidateWhere(initial, "activate_mana_ability", "Llanowar Elves") < 0,
                    "summoning-sick creature offered as a mana producer");
            int initialLife = position.player("p0").getLife();
            if (enabled) {
                Map<String, Object> context = Json.obj(initial, "context");
                require("priority".equals(context.get("kind")) && context.get("purpose") == null, "wrong context");
                Map<String, Object> semantic = Json.obj(Json.obj(Json.arr(initial, "candidates").get(mana)), "semantic");
                require(Json.num(semantic, "ability_index", -1L) == 0L, "wrong Oracle mana index");
                require(semantic.containsKey("mana_choice") && semantic.get("mana_choice") == null
                        && semantic.containsKey("cost_target") && semantic.get("cost_target") == null,
                        "follow-up choice fields missing");
                frames.add(Json.map("decision", initial, "index", (long) mana));
                position.answer(mana);
                for (int step = 0; step < 12 && !position.over()
                        && !Slice.priorityOf(position.decision(), "p0", "precombat_main"); step++) {
                    int green = colorGreen(position.decision());
                    int pick = green >= 0 ? green : 0;
                    frames.add(Json.map("decision", position.decision(), "index", (long) pick));
                    position.answer(pick);
                }
                require(!position.over() && Slice.priorityOf(position.decision(), "p0", "precombat_main"),
                        "mana activation did not return priority");
                require(permanent(position, source).isTapped(), "selected producer did not tap");
                require(position.player("p0").getManaPool().getGreen() == 1, "selected producer did not float green");
                require(Slice.candidateWhere(position.decision(), "activate_mana_ability", source) < 0
                        || "Forest".equals(source) && "float-and-cast".equals(family), "tapped producer reoffered");
                if ("color".equals(family)) require(position.player("p0").getLife() == initialLife - 1, "life cost skipped");
                if ("cost".equals(family)) require(permanent(position, "Llanowar Elves").isTapped(), "creature cost skipped");
            }
            if ("default".equals(family) || "float-and-cast".equals(family)) {
                int cast = Slice.candidateWhere(position.decision(), "cast_spell", "Grizzly Bears");
                require(cast >= 0, "spell unavailable after mana activation");
                frames.add(Json.map("decision", position.decision(), "index", (long) cast));
                position.answer(cast);
                require(position.advance(d -> Slice.names(Slice.obsOf(d), "p0", "battlefield").contains("Grizzly Bears"), 20),
                        "automatic cost payment did not resolve the spell");
                require(position.player("p0").getManaPool().isEmpty(), "floating mana was not spent");
            }
            return Json.map("family", family, "enabled", enabled, "frames", frames,
                    "final_decision", position.decision(), "passed", true);
        } finally {
            position.seats.exchange.close();
        }
    }

    public static void main(String[] args) throws Exception {
        PrintStream out = new PrintStream(new FileOutputStream(FileDescriptor.out), true, "UTF-8");
        System.setOut(System.err);
        Runner.quietLogs();
        GameRandom.installBoot();
        Warmup.framework();
        new CardResolver().resolve("Forest");
        List<Object> results = new ArrayList<>();
        for (String family : Arrays.asList("default", "float-and-cast", "color", "cost")) results.add(run(family));
        String result = Json.canonical(Json.map("cases", results, "passed", true));
        if (args.length > 0) Files.write(Paths.get(args[0]), result.getBytes(StandardCharsets.UTF_8));
        out.println(result);
    }
}
