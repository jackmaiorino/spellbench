package spellbench.kit.xmage;

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
import java.nio.file.StandardOpenOption;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;

/** Saves actual callbacks and only the public priority passes used to reach them. */
public final class ModelSearchCallbackCheck {
    public static void main(String[] args) throws Exception {
        if (args.length != 1 && !(args.length == 2 && "mode".equals(args[1]))
                && !(args.length == 3 && "mode-wire".equals(args[1]))) {
            throw new IllegalArgumentException("callback output directory; mode, or mode-wire with a saved result");
        }
        PrintStream out = new PrintStream(new FileOutputStream(FileDescriptor.out), true, "UTF-8");
        System.setOut(System.err); Runner.quietLogs(); KitRandom.installBoot(); Warmup.framework();
        new CardResolver().resolve("Plains");
        if (args.length == 2) { save("mode", Paths.get(args[0]), out); return; }
        if (args.length == 3) {
            Map<String, Object> result = Json.obj(Json.parse(new String(Files.readAllBytes(Paths.get(args[2])), StandardCharsets.UTF_8)));
            save("mode", Paths.get(args[0]), out, Json.obj(result, "selection"));
            return;
        }
        save("target", Paths.get(args[0]), out);
        save("binary", Paths.get(args[0]), out);
        save("library", Paths.get(args[0]), out);
        save("numeric", Paths.get(args[0]), out);
        save("named", Paths.get(args[0]), out);
    }
    private static void save(String family, Path output, PrintStream out) throws Exception {
        save(family, output, out, null);
    }
    private static void save(String family, Path output, PrintStream out,
                             Map<String, Object> modeSelection) throws Exception {
        boolean binary = "binary".equals(family) || "library".equals(family), library = "library".equals(family);
        boolean numeric = "numeric".equals(family), named = "named".equals(family), mode = "mode".equals(family);
        String spell = mode ? "Abrade" : named ? "Shifting Sky" : numeric ? "Fireball" : binary ? "Campus Guide" : "Stab";
        String land = named ? "Island" : numeric || mode ? "Mountain" : binary ? "Forest" : "Swamp";
        Slice.SeatSetup own = new Slice.SeatSetup().lib(land, 8);
        own.hand.addAll(Arrays.asList(spell, land));
        own.battlefield.addAll(Arrays.asList(land, land, land, land, land));
        Slice.SeatSetup opponent = new Slice.SeatSetup().lib("Island", 7);
        opponent.library.add("Cancel"); opponent.hand.addAll(Arrays.asList("Island", "Essence Scatter"));
        opponent.battlefield.addAll(Arrays.asList("Island", "Grizzly Bears", "Llanowar Elves"));
        if (mode) opponent.battlefield.add("Ornithopter");
        Slice.EnginePos position = Slice.EnginePos.start("model-search-callback-" + family, own, opponent);
        try {
            if (!position.advance(d -> Slice.priorityOf(d, "p0", "precombat_main"), 50)) {
                throw new IllegalStateException("callback fixture did not reach priority");
            }
            Map<String, Object> anchor = Json.obj(Json.copy(position.decision()));
            int cast = Slice.candidateWhere(anchor, "cast_spell", spell);
            if (cast < 0) throw new IllegalStateException("callback fixture spell is not offered");
            Map<String, Object> candidate = Json.obj(Json.arr(anchor, "candidates").get(cast));
            Map<String, Object> selection = Json.map("candidate_id", candidate.get("candidate_id"),
                    "semantic_echo", candidate.get("semantic"));
            position.answer(cast);
            List<Object> passes = new ArrayList<>();
            List<Object> earlier = new ArrayList<>();
            String kind = mode ? "choose_spell_mode" : named ? "choose_color" : numeric ? "choose_number" : library ? "select_object" : binary ? "choose_boolean" : "choose_target";
            for (int steps = 0; steps < 16 && !position.over(); steps++) {
                Map<String, Object> decision = position.decision();
                if ("p0".equals(position.acting()) && kind.equals(Slice.Front_firstKind(decision))) {
                    byte[] ids = Seeds.hmac("original-search-callback".getBytes(StandardCharsets.UTF_8), family);
                    Map<String, Object> record = Json.map("game_start", Slice.gameStart("p0", own, opponent),
                            "decision", decision, "anchor", Json.map("decision", anchor, "selection", selection),
                            "replay", Json.map("priority_passes", passes, "earlier", earlier),
                            "world_seed", Seeds.hex(Seeds.hmac(ids, "world")), "id_seed", Seeds.hex(ids));
                    Files.write(output.resolve(family + "-record.json"), Json.canonical(record).getBytes(StandardCharsets.UTF_8),
                            StandardOpenOption.CREATE_NEW);
                    if (modeSelection != null) {
                        Map<String, Object> picked = ModelReplay.selectedSemantic(decision, modeSelection);
                        if (!"choose_spell_mode".equals(Json.str(picked, "kind"))) {
                            throw new IllegalArgumentException("wire fixture needs an offered spell mode");
                        }
                        int selected = Slice.candidateOf(decision, picked);
                        if (selected < 0) throw new IllegalArgumentException("wire mode was not offered");
                        position.answer(selected);
                        Map<String, Object> next = position.decision();
                        if (!"p0".equals(position.acting()) || !"choose_target".equals(Slice.Front_firstKind(next))) {
                            throw new IllegalStateException("applied mode did not reach its actual target callback");
                        }
                        List<Object> prefix = new ArrayList<>(earlier);
                        prefix.add(Json.map("decision", Json.copy(decision), "selection", Json.copy(modeSelection)));
                        Map<String, Object> target = Json.map("game_start", record.get("game_start"), "decision", next,
                                "anchor", record.get("anchor"), "replay", Json.map("priority_passes", passes, "earlier", prefix),
                                "world_seed", record.get("world_seed"), "id_seed", record.get("id_seed"));
                        Files.write(output.resolve("mode-target-record.json"), Json.canonical(target).getBytes(StandardCharsets.UTF_8),
                                StandardOpenOption.CREATE_NEW);
                        out.println(Json.canonical(Json.map("family", "mode-wire", "mode_selection_accepted", true,
                                "selected_mode_index", picked.get("mode_index"), "earlier_callbacks", (long) prefix.size(),
                                "next_callback", "choose_target", "target_candidates", (long) Json.arr(next, "candidates").size())));
                        return;
                    }
                    if (mode) checkModeSourceRefusals(record);
                    Map<String, Object> status = Json.map("family", family, "passes", passes,
                            "candidates", (long) Json.arr(decision, "candidates").size(), "real_callback", kind);
                    if (mode) status.put("mode_source_refusal_checks", 3L);
                    out.println(Json.canonical(status));
                    return;
                }
                if (library && "p0".equals(position.acting()) && "choose_boolean".equals(Slice.Front_firstKind(decision))) {
                    int yes = -1;
                    for (int i = 0; i < Json.arr(decision, "candidates").size(); i++) {
                        Map<String, Object> c = Json.obj(Json.arr(decision, "candidates").get(i));
                        if (Json.bool(Json.obj(c, "semantic"), "value")) yes = i;
                    }
                    if (yes < 0) throw new IllegalStateException("fixture search acceptance not offered");
                    Map<String, Object> c = Json.obj(Json.arr(decision, "candidates").get(yes));
                    earlier.add(Json.map("decision", Json.copy(decision), "selection",
                            Json.map("candidate_id", c.get("candidate_id"), "semantic_echo", c.get("semantic"))));
                    position.answer(yes);
                    continue;
                }
                if (!"priority".equals(Json.str(Json.obj(decision, "context"), "kind"))) {
                    throw new IllegalStateException("unexpected callback before fixture root: " + Slice.Front_firstKind(decision));
                }
                int pass = Slice.candidateOf(decision, Json.map("kind", "pass"));
                if (pass < 0) throw new IllegalStateException("fixture pass unavailable");
                if ((binary || named) && "p0".equals(position.acting())) {
                    // The latest public priority preserves actual mana payment
                    // and the trigger already on the stack. Earlier mana replay
                    // can tap different copies of otherwise identical lands.
                    anchor = Json.obj(Json.copy(decision));
                    Map<String, Object> offered = Json.obj(Json.arr(anchor, "candidates").get(pass));
                    selection = Json.map("candidate_id", offered.get("candidate_id"), "semantic_echo", offered.get("semantic"));
                    passes.clear();
                } else {
                    passes.add(position.acting());
                }
                position.answer(pass);
            }
            throw new IllegalStateException("fixture callback was not reached");
        } finally { position.seats.exchange.close(); }
    }

    private static void checkModeSourceRefusals(Map<String, Object> record) {
        Map<String, Object> decision = Json.obj(record, "decision");
        Map<String, Object> own = Json.obj(Json.arr(Json.obj(decision, "observation"), "players").get(0));
        Map<String, Object> land = Json.obj(Json.arr(own, "battlefield").get(0));
        Map<String, Object> wrong = new spellbench.kit.core.ObsIndex(Json.obj(decision, "observation"))
                .ref(Json.str(land, "object_id"));
        refuseModeSource(record, wrong, true);
        Map<String, Object> absent = Json.obj(Json.copy(Json.obj(Json.obj(decision, "context"), "source")));
        absent.put("object_id", "absent-mode-source");
        refuseModeSource(record, absent, true);
        refuseModeSource(record, wrong, false);
    }

    private static void refuseModeSource(Map<String, Object> record, Map<String, Object> source, boolean context) {
        Map<String, Object> bad = Json.obj(Json.copy(record));
        Map<String, Object> decision = Json.obj(bad, "decision");
        if (context) Json.obj(decision, "context").put("source", Json.copy(source));
        Json.obj(Json.obj(Json.arr(decision, "candidates").get(0)), "semantic").put("source", Json.copy(source));
        if (context) for (Object item : Json.arr(decision, "candidates")) {
            Json.obj(Json.obj(item), "semantic").put("source", Json.copy(source));
        }
        spellbench.models.exp1.RemoteModelEvaluator evaluator = new spellbench.models.exp1.RemoteModelEvaluator(features -> {
            throw new IllegalStateException("Mode source checks must refuse before neural inference");
        });
        try {
            ModelReplay.run(bad, evaluator, 6);
            throw new IllegalStateException("Mode callback accepted an unrelated source");
        } catch (IllegalArgumentException refused) {
            if (!refused.getMessage().contains("mode") || !refused.getMessage().contains("source")) throw refused;
        }
    }
}
