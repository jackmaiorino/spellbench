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
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;

/** Real initial attack and block decisions from the reviewed engine. */
public final class ModelCombatCheck {
    public static void main(String[] args) throws Exception {
        if (args.length < 1 || args.length > 2) throw new IllegalArgumentException("combat fixture directory and optional saved plans required");
        PrintStream out = new PrintStream(new FileOutputStream(FileDescriptor.out), true, "UTF-8");
        System.setOut(System.err); Runner.quietLogs(); KitRandom.installBoot(); Warmup.framework();
        new CardResolver().resolve("Plains");
        Map<String, Object> plans = args.length == 2
                ? Json.parseObject(new String(Files.readAllBytes(Paths.get(args[1])), StandardCharsets.UTF_8)) : null;
        save("attack", Paths.get(args[0]), out, plans);
        save("block", Paths.get(args[0]), out, plans);
    }
    private static boolean sameTarget(Object offered, Object wanted) {
        if (offered == null || wanted == null) return offered == wanted;
        Map<String, Object> left = Json.obj(offered), right = Json.obj(wanted);
        if (left.get("player") != null || right.get("player") != null) return left.get("player") != null && left.get("player").equals(right.get("player"));
        if (left.get("object") != null) left = Json.obj(left, "object");
        return left.get("object_id") != null && left.get("object_id").equals(right.get("object_id"));
    }
    private static int select(String family, Map<String, Object> decision, Map<String, Object> plan) {
        String name = "attack".equals(family) ? "attacker" : "blocker";
        String reference = "attack".equals(family) ? "defender" : "attacker";
        List<Object> candidates = Json.arr(decision, "candidates");
        String id = Json.str(Json.obj(Json.obj(Json.obj(candidates.get(0)), "semantic"), name), "object_id");
        if (id == null) throw new IllegalArgumentException("wire declaration has no creature reference");
        Object wanted = null;
        int assigned = 0;
        for (Object value : Json.arr(plan, "pairs")) {
            Map<String, Object> pair = Json.obj(value);
            if (id.equals(Json.str(pair, name))) { wanted = pair.get(reference); assigned++; }
        }
        if (assigned > 1) throw new IllegalArgumentException("saved plan aliases a creature");
        int index = -1;
        for (int i = 0; i < candidates.size(); i++) {
            Map<String, Object> semantic = Json.obj(Json.obj(candidates.get(i)), "semantic");
            if (!id.equals(Json.str(Json.obj(semantic, name), "object_id"))) throw new IllegalArgumentException("wire declaration changed creature");
            Object target = semantic.get(reference);
            boolean same = "attack".equals(family) ? sameTarget(target, wanted)
                    : target == null || wanted == null ? target == wanted : wanted.equals(Json.str(Json.obj(target), "object_id"));
            if (same) {
                if (index >= 0) throw new IllegalArgumentException("saved assignment is aliased on the wire");
                index = i;
            }
        }
        if (index < 0) throw new IllegalArgumentException("saved assignment is not offered");
        return index;
    }
    private static void save(String family, Path directory, PrintStream out, Map<String, Object> plans) throws Exception {
        Slice.SeatSetup own = new Slice.SeatSetup().lib("Plains", 8);
        own.hand.add("Plains"); own.battlefield.addAll(Arrays.asList("Plains", "Grizzly Bears", "Llanowar Elves"));
        Slice.SeatSetup other = new Slice.SeatSetup().lib("Island", 7);
        other.library.add("Cancel"); other.hand.addAll(Arrays.asList("Island", "Essence Scatter"));
        other.battlefield.addAll(Arrays.asList("Island", "Grizzly Bears", "Llanowar Elves"));
        Slice.EnginePos position = Slice.EnginePos.start("model-combat-" + family, own, other);
        try {
            if (!position.advance(d -> "declare_attack".equals(Slice.Front_firstKind(d)) && "p0".equals(position.acting()), 60)) {
                throw new IllegalStateException("combat fixture did not reach attack declarations");
            }
            if ("block".equals(family)) {
                while (!position.over() && "declare_attack".equals(Slice.Front_firstKind(position.decision()))) {
                    int choice = -1;
                    for (int i = 0; i < Json.arr(position.decision(), "candidates").size(); i++) {
                        Map<String, Object> semantic = Json.obj(Json.obj(Json.arr(position.decision(), "candidates").get(i)), "semantic");
                        if (semantic.get("defender") != null) { choice = i; break; }
                    }
                    if (choice < 0) throw new IllegalStateException("fixture creature has no offered attack");
                    position.answer(choice);
                }
                if (!position.advance(d -> "declare_block".equals(Slice.Front_firstKind(d)) && "p1".equals(position.acting()), 30)) {
                    throw new IllegalStateException("combat fixture did not reach block declarations");
                }
            }
            byte[] ids = Seeds.hmac("original-combat-check".getBytes(StandardCharsets.UTF_8), family);
            Map<String, Object> record = Json.map("game_start", Slice.gameStart(position.acting(), own, other),
                    "decision", position.decision(), "world_seed", Seeds.hex(Seeds.hmac(ids, "world")), "id_seed", Seeds.hex(ids));
            Files.write(directory.resolve(family + "-record.json"), Json.canonical(record).getBytes(StandardCharsets.UTF_8),
                    StandardOpenOption.CREATE_NEW);
            out.println(Json.canonical(Json.map("family", family, "viewer", position.acting(), "real_declaration", true)));
            if (plans != null) {
                Map<String, Object> plan = Json.obj(Json.obj(plans, family), "result");
                String digest = Seeds.hex(MessageDigest.getInstance("SHA-256").digest(Json.canonical(position.decision()).getBytes(StandardCharsets.UTF_8)));
                if (!digest.equals(Json.str(plan, "decision_sha256"))) throw new IllegalArgumentException("regenerated combat root differs from saved plan");
                long count = Json.num(Json.obj(position.decision(), "group"), "substep_count", -1);
                List<Object> declarations = new ArrayList<>();
                while (!position.over() && ("declare_" + family).equals(Slice.Front_firstKind(position.decision()))) {
                    Map<String, Object> decision = Json.obj(Json.copy(position.decision()));
                    int index = select(family, decision, plan);
                    Map<String, Object> candidate = Json.obj(Json.arr(decision, "candidates").get(index));
                    declarations.add(Json.map("decision", decision, "selection", Json.map("candidate_id", candidate.get("candidate_id"), "semantic_echo", candidate.get("semantic"))));
                    position.answer(index);
                    if (declarations.size() > count) throw new IllegalArgumentException("wire combat repeated its declaration group");
                }
                if (declarations.size() != count) throw new IllegalArgumentException("wire combat ended before all substeps");
                Files.write(directory.resolve(family + "-wire-declarations.json"), Json.canonical(declarations).getBytes(StandardCharsets.UTF_8),
                        StandardOpenOption.CREATE_NEW);
                out.println(Json.canonical(Json.map("family", family, "wire_declarations_accepted", (long) declarations.size())));
            }
        } finally { position.seats.exchange.close(); }
    }
}
