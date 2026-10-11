package spellbench.kit.xmage;

import mage.player.cabt.CardResolver;
import mage.player.spellbench.Warmup;
import spellbench.kit.core.Json;
import spellbench.kit.core.Seeds;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;

/** Reach actual scry/surveil callbacks and run original target searches with fixed synthetic scores. */
public final class ModelArrangementCheck {
    private static void require(boolean test, String message) { if (!test) throw new AssertionError(message); }
    private static Map<String, Object> copy(Map<String, Object> value) { return Json.obj(Json.copy(value)); }
    private static Map<String, Object> selected(Map<String, Object> decision, int index) {
        Map<String, Object> candidate = Json.obj(Json.arr(decision, "candidates").get(index));
        return Json.map("candidate_id", candidate.get("candidate_id"), "semantic_echo", candidate.get("semantic"));
    }
    private static Map<String, Object> run(Map<String, Object> record) {
        final List<Object> head = new ArrayList<>(); for (int i = 0; i < 1024; i++) head.add(0.0);
        BufferedReader model = new BufferedReader(new StringReader("")) {
            @Override public String readLine() {
                return Json.canonical(Json.map("id", "1", "call", ModelSearchMain.neuralCalls(), "ok", true,
                        "scores", Json.map("priority", head, "opponent_priority", head, "target", head,
                                "binary", Arrays.asList(0.0, 0.0), "value", 0.0)));
            }
        };
        ModelSearchMain.bindPipe(model, new PrintStream(new ByteArrayOutputStream()));
        Map<String, Object> request = copy(record); request.put("id", "1"); request.put("visits", 2L);
        return ModelSearchMain.execute(request);
    }
    private static void refused(Map<String, Object> record, String label) {
        try { run(record); throw new AssertionError("accepted changed " + label); }
        catch (IllegalArgumentException expected) { }
    }
    private static void replayedPrefix(Map<String, Object> record, List<Object> earlier) {
        Map<String, Object> saved = copy(record);
        Json.obj(saved, "replay").put("earlier", earlier);
        spellbench.models.exp1.RemoteModelEvaluator evaluator = new spellbench.models.exp1.RemoteModelEvaluator(features -> {
            throw new AssertionError("retained arrangement repeated neural inference");
        });
        try {
            ModelReplay.run(saved, evaluator, 2);
            throw new AssertionError("fixture unexpectedly reached a fresh callback after its retained group");
        } catch (IllegalArgumentException expected) {
            // These spells finish their native operation before the next priority.
            // Reaching it proves every recorded native choice and the resulting
            // physical plan were checked, with no fresh search for wire substeps.
            require("unrecorded or reordered priority during callback replay".equals(expected.getMessage()),
                    "retained arrangement did not finish its original operation: " + expected.getMessage());
        }
    }
    private static Map<String, Object> check(String spell, String purpose, int count, Path output,
                                             Boolean opponentTop) throws Exception {
        Slice.SeatSetup own = new Slice.SeatSetup().lib("Island", 12);
        own.library.set(1, "Think Twice"); own.library.set(2, "Essence Scatter");
        own.hand.add(spell); own.battlefield.addAll(Arrays.asList("Island", "Island", "Island", "Island", "Island"));
        Slice.SeatSetup other = new Slice.SeatSetup().lib("Forest", 12);
        other.battlefield.add("Grizzly Bears");
        Slice.EnginePos pos = Slice.EnginePos.start("arrangement-original-" + spell, own, other);
        try {
            require(pos.advance(d -> Slice.priorityOf(d, "p0", "precombat_main"), 50), "fixture priority missing");
            Map<String, Object> anchor = copy(pos.decision());
            int cast = Slice.candidateWhere(anchor, "cast_spell", spell);
            require(cast >= 0, "fixture spell is not offered");
            Map<String, Object> action = selected(anchor, cast);
            pos.answer(cast);
            List<Object> passes = new ArrayList<>(), earlier = new ArrayList<>();
            int opponentChoices = 0;
            for (int step = 0; step < 40 && !pos.over(); step++) {
                Map<String, Object> current = pos.decision();
                String kind = Slice.Front_firstKind(current);
                if ("p0".equals(pos.acting()) && "arrange_card".equals(kind)) {
                    Map<String, Object> decision = copy(current);
                    require(Json.num(Json.obj(Json.obj(Json.arr(decision, "candidates").get(0)), "semantic"), "card_count", -1) == count,
                            "fixture arrangement cardinality changed");
                    byte[] ids = Seeds.hmac("arrangement-original-check".getBytes(StandardCharsets.UTF_8), spell);
                    Map<String, Object> record = Json.map("game_start", Slice.gameStart("p0", own, other), "decision", decision,
                            "anchor", Json.map("decision", anchor, "selection", action),
                            "replay", Json.map("priority_passes", passes, "earlier", earlier),
                            "world_seed", Seeds.hex(Seeds.hmac(ids, "world")), "id_seed", Seeds.hex(ids));
                    Map<String, Object> result = run(record);
                    require(opponentChoices == (opponentTop == null ? 0 : 1), "fixture lost the real owner destination choice");
                    require(Json.arr(result, "world_flags").contains("approximate:unobserved_opponent_library_destination")
                            == (opponentTop != null), "latent owner destination was not classified honestly");
                    require(purpose.equals(Json.str(result, "arrangement")), "wrong original arrangement");
                    require(Json.arr(result, "cards").size() == count && Json.arr(result, "order").size() == count, "incomplete original plan");
                    require(!Json.arr(result, "target_script").isEmpty(), "original target history was lost");
                    require(Json.num(result, "neural_calls", 0) > 0, "original search did no neural work");
                    Map<String, Object> repeated = run(record);
                    require(Json.canonical(result).equals(Json.canonical(repeated)), "fixed original arrangement did not replay identically");
                    Map<String, Object> changed = copy(record);
                    Json.obj(Json.obj(changed, "decision"), "group").put("substep_index", 1L);
                    refused(changed, "group index");
                    changed = copy(record);
                    for (Object item : Json.arr(Json.obj(changed, "decision"), "candidates")) {
                        Json.obj(Json.obj(item), "semantic").put("card_count", (long) count + 1);
                    }
                    refused(changed, "card count");
                    changed = copy(record);
                    Json.obj(Json.obj(Json.obj(changed, "decision"), "context"), "source").put("object_id", "unobserved-source");
                    refused(changed, "source");
                    if (opponentTop != null) {
                        changed = copy(record);
                        for (Object player : Json.arr(Json.obj(Json.obj(changed, "decision"), "observation"), "players")) {
                            Map<String, Object> p = Json.obj(player);
                            if ("p1".equals(Json.str(p, "seat"))) p.put("library_count", Json.num(p, "library_count", -1) + 1L);
                        }
                        refused(changed, "owner library count");
                        changed = copy(record);
                        Json.arr(Json.obj(Json.obj(changed, "decision"), "observation"), "known").add(Json.map(
                                "object_id", "visible-owner-library-pin", "owner_seat", "p1", "zone", "library",
                                "card_name", "Grizzly Bears", "position_from_top", 0L, "position_from_bottom", null,
                                "how", "revealed"));
                        refused(changed, "visible owner library position");
                    }
                    // Apply the native plan through the real wire, including forced order substeps.
                    List<Object> retained = new ArrayList<>(earlier);
                    for (int wireStep = 0; wireStep < 2 * count - 1; wireStep++) {
                        Map<String, Object> d = pos.decision(); int choice = -1;
                        for (int i = 0; i < Json.arr(d, "candidates").size(); i++) {
                            Map<String, Object> semantic = Json.obj(Json.obj(Json.arr(d, "candidates").get(i)), "semantic");
                            if (wireStep < count) {
                                String id = Json.str(Json.obj(semantic, "card"), "object_id");
                                if (Json.str(semantic, "destination").equals(Json.str(Json.obj(result, "destinations"), id))) choice = i;
                            } else {
                                String id = Json.str(Json.obj(Json.obj(semantic, "item"), "object"), "object_id");
                                if (id.equals(Json.arr(result, "order").get(wireStep - count))) choice = i;
                            }
                        }
                        require(choice >= 0, "native plan is unoffered by real wire");
                        Map<String, Object> saved = copy(d);
                        if (wireStep == 0) {
                            Map<String, Object> plan = new LinkedHashMap<>();
                            for (String key : Arrays.asList("arrangement", "cards", "destinations", "order", "target_script")) {
                                plan.put(key, Json.copy(result.get(key)));
                            }
                            saved.put("x_arrangement_plan", plan);
                        }
                        retained.add(Json.map("decision", saved, "selection", selected(d, choice)));
                        pos.answer(choice);
                    }
                    replayedPrefix(record, retained);
                    String stem = spell.replace(' ', '-') + (opponentTop == null ? "" : opponentTop ? "-owner-top" : "-owner-bottom");
                    Files.write(output.resolve(stem + "-record.json"), Json.canonical(record).getBytes(StandardCharsets.UTF_8), StandardOpenOption.CREATE_NEW);
                    Files.write(output.resolve(stem + "-result.json"), Json.canonical(result).getBytes(StandardCharsets.UTF_8), StandardOpenOption.CREATE_NEW);
                    return Json.map("spell", spell, "purpose", purpose, "cards", (long) count,
                            "roots", (long) Json.arr(result, "roots").size(), "neural_calls", result.get("neural_calls"),
                            "complete_plan_repeated", true, "actual_wire_group_applied", true,
                            "original_history_replayed_without_inference", true, "changed_inputs_refused", opponentTop == null ? 3L : 5L,
                            "permitted_record", Json.canonical(record), "complete_result", Json.canonical(result));
                }
                if ("priority".equals(Json.str(Json.obj(current, "context"), "kind"))) {
                    int pass = Slice.candidateOf(current, Json.map("kind", "pass")); require(pass >= 0, "fixture pass missing");
                    if ("p0".equals(pos.acting())) { anchor = copy(current); action = selected(current, pass); passes.clear(); earlier.clear(); }
                    else passes.add(pos.acting());
                    pos.answer(pass);
                } else {
                    if (!"p0".equals(pos.acting())) {
                        require(opponentTop != null && opponentChoices++ == 0 && "p1".equals(pos.acting())
                                && "choose_boolean".equals(kind)
                                && "Uncharted Voyage".equals(Json.str(Json.obj(Json.obj(current, "context"), "source"), "card_name")),
                                "unexpected opposing fixture callback: " + kind);
                        int choice = -1;
                        for (int i = 0; i < Json.arr(current, "candidates").size(); i++) {
                            Map<String, Object> semantic = Json.obj(Json.obj(Json.arr(current, "candidates").get(i)), "semantic");
                            if (opponentTop.equals(semantic.get("value"))) choice = i;
                        }
                        require(choice >= 0, "fixture owner destination is not offered");
                        // This is the fixture opponent's private decision. It
                        // is never put into p0's record or replay history.
                        pos.answer(choice);
                        continue;
                    }
                    Map<String, Object> selection = selected(current, 0);
                    earlier.add(Json.map("decision", copy(current), "selection", selection)); pos.answer(0);
                }
            }
            throw new AssertionError("fixture did not reach original arrangement " + spell);
        } finally { pos.seats.exchange.close(); }
    }
    public static void main(String[] args) throws Exception {
        if (args.length != 1) throw new IllegalArgumentException("new output directory required");
        Path output = Paths.get(args[0]); Files.createDirectory(output);
        PrintStream out = new PrintStream(new FileOutputStream(FileDescriptor.out), true, "UTF-8");
        System.setOut(System.err); Runner.quietLogs(); KitRandom.installBoot(); Warmup.framework(); new CardResolver().resolve("Plains");
        Map<String, Object> top = check("Uncharted Voyage", "surveil", 1, output, true);
        Map<String, Object> bottom = check("Uncharted Voyage", "surveil", 1, output, false);
        require(top.get("permitted_record").equals(bottom.get("permitted_record"))
                && top.get("complete_result").equals(bottom.get("complete_result")),
                "opponent private destination changed the permitted search input or result");
        top.remove("permitted_record"); top.remove("complete_result");
        top.put("both_owner_destinations_preserve_permitted_result", true);
        out.println(Json.canonical(top));
        for (String spell : Arrays.asList("Lightshell Duo", "Opt", "Preordain")) {
            boolean surveil = spell.equals("Lightshell Duo");
            Map<String, Object> result = check(spell, surveil ? "surveil" : "scry", spell.equals("Opt") ? 1 : 2, output, null);
            result.remove("permitted_record"); result.remove("complete_result");
            out.println(Json.canonical(result));
        }
    }
}
