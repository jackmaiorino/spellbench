package spellbench.kit.xmage;

import mage.cards.Card;
import mage.game.permanent.token.Token;
import spellbench.kit.core.Front;
import spellbench.kit.core.Json;
import spellbench.kit.core.ObsIndex;
import spellbench.kit.core.Sampler;
import spellbench.kit.core.Seeds;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.function.BiPredicate;
import java.util.stream.Stream;

import static spellbench.kit.xmage.Slice.EnginePos;
import static spellbench.kit.xmage.Slice.SeatSetup;
import static spellbench.kit.xmage.Slice.candidateWhere;
import static spellbench.kit.xmage.Slice.check;
import static spellbench.kit.xmage.Slice.names;
import static spellbench.kit.xmage.Slice.note;
import static spellbench.kit.xmage.Slice.obsOf;
import static spellbench.kit.xmage.Slice.playerObs;
import static spellbench.kit.xmage.Slice.priorityOf;

/**
 * The A1 build-out's production-path cases (A1 result review, changes 1, 3, 6 and 7): engine positions whose viewer
 * seat is answered by a real front ({@link Front}, the agent role) with its real runner child process, exactly as in a
 * game, the other seat by the fixture. The only fixture hook is the kit's own first action (the front's
 * {@code forceForTest}: the runner executes that action on world 0 instead of searching), so the plan, the anchors,
 * continuation, the current dialog, forced steps and finish handling are the production code.
 * <ul>
 * <li>S2P, S3P, S4P: Burnished Hart, Strix Lookout and Charming Prince through the front (change 1);</li>
 * <li>S10P: Cultivate, a resolution with two dialogs: the second is continued after replaying the first;</li>
 * <li>A3: identical permitted inputs across hidden worlds give identical answers, for kit-mad-1, kit-mad-k and
 * kit-mcts (change 7); MCTSPOWER: the powered C-MCTS pilot (every root child at least 40 visits);</li>
 * <li>REG: the register's state conditions (change 3): trigger event data, optional-cost state, incomplete stack
 * targets (all with the search horizon, so a priority search is skipped), emblem rebuild;</li>
 * <li>POOLAUDIT: every pool card resolves, every token class it creates resolves by name, every emblem rebuilds;</li>
 * <li>UNMAPPED: dumped decisions (with their own history) through MAD with the mapping diagnostics (change 5).</li>
 * </ul>
 */
final class SliceProd {

    private SliceProd() {
    }

    // =============================================================================================
    // harness: a real front and runner for the viewer seat

    static List<String> runnerCommand() {
        String java = Paths.get(System.getProperty("java.home"), "bin", "java").toString();
        List<String> cp = new ArrayList<>();
        for (String p : System.getProperty("java.class.path").split(File.pathSeparator)) {
            if (!p.contains("kit-upstream")) { // the E7 reference is never on an entry's classpath
                cp.add(p);
            }
        }
        return Arrays.asList(java, "-Xmx1536m", "-XX:+UseSerialGC", "-cp", String.join(File.pathSeparator, cp),
                "spellbench.kit.xmage.Runner");
    }

    static void copyTree(Path from, Path to) throws IOException {
        try (Stream<Path> s = Files.walk(from)) {
            for (Path p : (Iterable<Path>) s::iterator) {
                Path t = to.resolve(from.relativize(p).toString());
                if (Files.isDirectory(p)) {
                    Files.createDirectories(t);
                } else if (!p.getFileName().toString().endsWith(".lock.db")) {
                    Files.copy(p, t, StandardCopyOption.REPLACE_EXISTING);
                }
            }
        }
    }

    static void deleteTree(File f) {
        try (Stream<Path> s = Files.walk(f.toPath())) {
            List<Path> all = new ArrayList<>();
            s.forEach(all::add);
            all.sort(Comparator.reverseOrder());
            for (Path p : all) {
                p.toFile().delete();
            }
        } catch (IOException | RuntimeException ignored) {
            // best effort
        }
    }

    /** One kit agent (front plus runner) for the viewer seat of an engine position. */
    static final class FrontSeat {
        final Front front;
        final File work;
        final String gameId;
        int n;

        FrontSeat(String label, String entry, Map<String, Object> gs, String... extra) throws Exception {
            work = new File(System.getProperty("kit.front.work", System.getProperty("java.io.tmpdir")),
                    "kit-slice-" + label + "-" + System.nanoTime());
            work.mkdirs();
            // each runner gets its own copy of the template database (this JVM holds ./db open)
            copyTree(Paths.get(System.getProperty("kit.db.template", "db")), work.toPath().resolve("db"));
            Map<String, String> opts = new LinkedHashMap<>();
            opts.put("entry", entry);
            opts.put("work", work.getPath());
            opts.put("keep-lines", "1");
            for (int i = 0; i + 1 < extra.length; i += 2) {
                opts.put(extra[i], extra[i + 1]);
            }
            front = new Front(opts, runnerCommand());
            gameId = "g-slice-" + label;
            Map<String, Object> req = new LinkedHashMap<>(gs);
            req.put("protocol", "spellbench/v2");
            req.put("request_type", "game_start");
            req.put("request_id", "gs");
            req.put("game_id", gameId);
            req.put("agent_seed", 424242L);
            front.handle(Json.canonical(req));
        }

        /** Sends one choose as the host would; returns {candidate, path, tag, line}. */
        Map<String, Object> choose(Map<String, Object> d) {
            Map<String, Object> req = Json.map("protocol", "spellbench/v2", "request_type", "choose", "request_id", "r" + (n++),
                    "game_id", gameId, "decision", d, "clock", Json.map("max_decision_ms", 120_000L, "remaining_ms", 3_600_000L));
            Map<String, Object> resp = front.handle(Json.canonical(req));
            front.afterAnswer();
            Map<String, Object> line = null;
            for (int i = front.keptLines.size() - 1; i >= 0; i--) {
                if ("decision".equals(front.keptLines.get(i).get("event"))) {
                    line = front.keptLines.get(i);
                    break;
                }
            }
            Map<String, Object> sel = Json.obj(resp, "selection");
            return Json.map("candidate", sel == null ? -1L : sel.get("candidate_id"), "path", line == null ? null : line.get("path"),
                    "tag", line == null ? null : line.get("tag"), "line", line, "response", sel == null ? resp : null);
        }

        void close() {
            front.handle(Json.canonical(Json.map("protocol", "spellbench/v2", "request_type", "game_over", "request_id", "go")));
            deleteTree(work);
        }
    }

    /**
     * Plays the position: the viewer's decisions through the front, the other seat's by candidate 0, until
     * {@code stop} holds for the pending decision (given the trace so far). Returns the viewer's trace.
     */
    static List<Map<String, Object>> drive(EnginePos e, FrontSeat f, String viewer,
                                           BiPredicate<Map<String, Object>, List<Map<String, Object>>> stop, int max) {
        List<Map<String, Object>> trace = new ArrayList<>();
        for (int i = 0; i < max && !e.over(); i++) {
            Map<String, Object> d = e.decision();
            if (stop.test(d, trace)) {
                break;
            }
            if (viewer.equals(e.acting())) {
                Map<String, Object> r = f.choose(d);
                Map<String, Object> line = Json.obj(r, "line");
                Map<String, Object> t = Json.map("seat_step", d.get("seat_step"), "kind", Slice.Front_firstKind(d),
                        "context", Json.str(Json.obj(d, "context"), "kind"), "candidates", (long) Json.arr(d, "candidates").size(),
                        "candidate", r.get("candidate"), "path", r.get("path"), "tag", r.get("tag"));
                if (line != null) {
                    for (String k : new String[]{"continuation", "continuation_replayed", "continuation_failed", "picks", "cap",
                            "world_flags"}) {
                        if (line.get(k) != null) {
                            t.put(k, line.get(k));
                        }
                    }
                }
                t.put("semantic", Json.obj(Json.obj(Json.arr(d, "candidates").get(((Number) r.get("candidate")).intValue())), "semantic"));
                trace.add(t);
                e.answer(((Number) r.get("candidate")).intValue());
            } else {
                e.answer(0);
            }
        }
        return trace;
    }

    /** Stops at the viewer's priority with an empty stack once a resolution dialog of the viewer has been answered. */
    static BiPredicate<Map<String, Object>, List<Map<String, Object>>> afterResolution(String viewer) {
        return (d, trace) -> {
            boolean dialogSeen = false;
            for (Map<String, Object> t : trace) {
                dialogSeen |= !"priority".equals(t.get("context"));
            }
            return dialogSeen && priorityOf(d, viewer, null) && Json.arr(obsOf(d), "stack").isEmpty();
        };
    }

    static List<Map<String, Object>> resolutionSteps(List<Map<String, Object>> trace) {
        List<Map<String, Object>> out = new ArrayList<>();
        for (Map<String, Object> t : trace) {
            if (!"priority".equals(t.get("context"))) {
                out.add(t);
            }
        }
        return out;
    }

    static boolean allPaths(List<Map<String, Object>> steps, String prefix) {
        boolean ok = !steps.isEmpty();
        for (Map<String, Object> t : steps) {
            String p = String.valueOf(t.get("path"));
            ok &= p.startsWith(prefix) || p.equals("single");
        }
        return ok;
    }

    static long countWith(List<Map<String, Object>> steps, String key) {
        long k = 0;
        for (Map<String, Object> t : steps) {
            if (Boolean.TRUE.equals(t.get(key))) {
                k++;
            }
        }
        return k;
    }

    /** Forces the viewer's first action at the pending priority decision; false when the candidate is missing. */
    static boolean forceFirst(EnginePos e, FrontSeat f, String kind, String name) {
        Map<String, Object> d0 = e.decision();
        int c = candidateWhere(d0, kind, name);
        if (c < 0) {
            return false;
        }
        f.front.forceForTest(Json.num(d0, "seat_step", 0),
                Json.obj(Json.obj(Json.arr(d0, "candidates").get(c)), "semantic"));
        return true;
    }

    // =============================================================================================
    // S2P: Burnished Hart through the front: a library search continued from the saved anchor

    static void s2p() throws Exception {
        SeatSetup a = new SeatSetup();
        a.library.addAll(Arrays.asList("Mountain", "Forest", "Plains", "Mountain", "Island", "Mountain", "Swamp", "Mountain"));
        a.hand.add("Mountain");
        a.battlefield.addAll(Arrays.asList("Burnished Hart", "Mountain", "Mountain", "Mountain"));
        SeatSetup b = new SeatSetup().lib("Island", 8);
        b.hand.add("Island");
        b.battlefield.add("Island");
        EnginePos e = EnginePos.start("S2P", a, b);
        if (!e.advance(d -> priorityOf(d, "p0", "precombat_main"), 50)) {
            check("S2P.reach_position", false, e.trail);
            return;
        }
        FrontSeat f = new FrontSeat("S2P", "h1", Slice.gameStart("p0", a, b));
        try {
            if (!forceFirst(e, f, "activate_ability", "Burnished Hart")) {
                check("S2P.activation_offered", false, null);
                return;
            }
            List<Map<String, Object>> trace = drive(e, f, "p0", afterResolution("p0"), 80);
            List<Map<String, Object>> res = resolutionSteps(trace);
            check("S2P.forced_action_through_front", !trace.isEmpty() && "priority_forced".equals(trace.get(0).get("path")),
                    Json.map("first", trace.isEmpty() ? null : trace.get(0)));
            boolean anchored = false;
            for (Map<String, Object> t : trace) {
                anchored |= "priority".equals(t.get("context")) && t != trace.get(0);
            }
            check("S2P.resolution_by_continuation", anchored && allPaths(res, "continuation") && countWith(res, "continuation") == 1
                            && "continuation".equals(res.get(0).get("path")),
                    Json.map("resolution", res, "priority_with_object_on_top_seen", anchored));
            Map<String, Object> oe = e.over() ? null : obsOf(e.decision());
            long tapped = 0;
            if (oe != null) {
                for (Object o : Json.arr(playerObs(oe, "p0"), "battlefield")) {
                    Map<String, Object> r = Json.obj(o);
                    if (Json.bool(Json.obj(r, "permanent"), "tapped") && !"Mountain".equals(r.get("card_name"))) {
                        tapped++;
                    }
                }
            }
            check("S2P.assert.hart_sacrificed_two_lands", oe != null && names(oe, "p0", "graveyard").contains("Burnished Hart")
                            && tapped == 2,
                    Json.map("graveyard", oe == null ? null : names(oe, "p0", "graveyard"), "new_tapped_lands", tapped));
        } finally {
            f.close();
        }
    }

    // =============================================================================================
    // S3P: Strix Lookout through the front: the discard after the draw, conditioned on the drawn card

    static void s3p() throws Exception {
        SeatSetup a = new SeatSetup();
        a.library.addAll(Arrays.asList("Llanowar Elves", "Island", "Island", "Island", "Island", "Island"));
        a.hand.addAll(Arrays.asList("Island", "Plains"));
        a.battlefield.addAll(Arrays.asList("Strix Lookout", "Island", "Island"));
        SeatSetup b = new SeatSetup().lib("Mountain", 8);
        b.hand.add("Mountain");
        b.battlefield.add("Mountain");
        EnginePos e = EnginePos.start("S3P", a, b);
        if (!e.advance(d -> priorityOf(d, "p0", "precombat_main"), 50)) {
            check("S3P.reach_position", false, e.trail);
            return;
        }
        long handBefore = Json.num(playerObs(obsOf(e.decision()), "p0"), "hand_count", -1);
        FrontSeat f = new FrontSeat("S3P", "h1", Slice.gameStart("p0", a, b));
        try {
            if (!forceFirst(e, f, "activate_ability", "Strix Lookout")) {
                check("S3P.activation_offered", false, null);
                return;
            }
            List<Map<String, Object>> trace = drive(e, f, "p0", afterResolution("p0"), 80);
            List<Map<String, Object>> res = resolutionSteps(trace);
            check("S3P.discard_by_continuation", allPaths(res, "continuation") && countWith(res, "continuation") == 1,
                    Json.map("resolution", res));
            Map<String, Object> oe = e.over() ? null : obsOf(e.decision());
            String planned = null;
            if (!res.isEmpty()) {
                Map<String, Object> sem = Json.obj(res.get(0), "semantic");
                Map<String, Object> ch = sem == null ? null : Json.obj(sem, "choice");
                Map<String, Object> obj = ch == null ? null : Json.obj(ch, "object");
                planned = obj == null ? null : Json.str(obj, "card_name");
            }
            check("S3P.assert.planned_card_discarded", oe != null && Json.num(playerObs(oe, "p0"), "hand_count", -1) == handBefore
                            && names(oe, "p0", "graveyard").size() == 1 && names(oe, "p0", "graveyard").contains(planned),
                    Json.map("hand", oe == null ? null : playerObs(oe, "p0").get("hand_count"), "hand_before", handBefore,
                            "graveyard", oe == null ? null : names(oe, "p0", "graveyard"), "planned", planned));
        } finally {
            f.close();
        }
    }

    // =============================================================================================
    // S4P: Charming Prince through the front: mode by the current dialog, scry by continuation (arrangement plan)

    static void s4p() throws Exception {
        SeatSetup a = new SeatSetup();
        a.library.addAll(Arrays.asList("Llanowar Elves", "Forest", "Plains", "Plains", "Plains", "Plains"));
        a.hand.add("Charming Prince");
        a.battlefield.addAll(Arrays.asList("Plains", "Plains"));
        SeatSetup b = new SeatSetup().lib("Mountain", 8);
        b.battlefield.add("Mountain");
        EnginePos e = EnginePos.start("S4P", a, b);
        if (!e.advance(d -> priorityOf(d, "p0", "precombat_main"), 50)) {
            check("S4P.reach_position", false, e.trail);
            return;
        }
        FrontSeat f = new FrontSeat("S4P", "h1", Slice.gameStart("p0", a, b));
        try {
            if (!forceFirst(e, f, "cast_spell", "Charming Prince")) {
                check("S4P.cast_offered", false, null);
                return;
            }
            List<Map<String, Object>> trace = drive(e, f, "p0", (d, t) -> {
                boolean arranged = false;
                for (Map<String, Object> x : t) {
                    arranged |= "arrange_card".equals(x.get("kind")) || String.valueOf(x.get("path")).contains("arrangement");
                }
                return arranged && priorityOf(d, "p0", null) && Json.arr(obsOf(d), "stack").isEmpty();
            }, 80);
            List<Map<String, Object>> res = resolutionSteps(trace);
            Map<String, Object> modeStep = null;
            List<Map<String, Object>> arrangement = new ArrayList<>();
            for (Map<String, Object> t : res) {
                if ("choose_spell_mode".equals(t.get("kind"))) {
                    modeStep = t;
                } else if ("arrange_card".equals(t.get("kind")) || "order_pick".equals(t.get("kind"))) {
                    arrangement.add(t);
                }
            }
            check("S4P.mode_by_current_dialog", modeStep != null && "dialog".equals(modeStep.get("path")),
                    Json.map("mode_step", modeStep));
            check("S4P.scry_by_continuation", arrangement.size() == 3 && allPaths(arrangement, "continuation")
                            && countWith(arrangement, "continuation") == 1,
                    Json.map("arrangement_steps", arrangement));
            // the plan's top cards, in the front's order rule (the first order pick is the topmost), against the
            // engine's library after the resolution
            Map<String, Object> plan = null;
            Map<String, String> nameOf = new LinkedHashMap<>();
            for (Map<String, Object> t : arrangement) {
                if (t.get("picks") != null && !Json.arr(t.get("picks")).isEmpty()) {
                    plan = Json.obj(Json.arr(t.get("picks")).get(0));
                }
                Map<String, Object> sem = Json.obj(t, "semantic");
                Map<String, Object> card = sem == null ? null : Json.obj(sem, "card");
                if (card == null && sem != null && sem.get("item") != null) {
                    card = Json.obj(Json.obj(sem, "item"), "object");
                }
                if (card != null) {
                    nameOf.put(Json.str(card, "object_id"), Json.str(card, "card_name"));
                }
            }
            List<String> expect = new ArrayList<>();
            List<String> expectBottom = new ArrayList<>();
            if (plan != null) {
                for (Object id : Json.arr(plan, "order")) {
                    String dest = String.valueOf(Json.obj(plan, "dest").get(id));
                    (dest.equals("top") ? expect : expectBottom).add(nameOf.get(String.valueOf(id)));
                }
            }
            List<Card> lib = e.player("p0").getLibrary().getCards(e.game);
            List<String> top = new ArrayList<>();
            List<String> bottom = new ArrayList<>();
            for (int i = 0; i < expect.size() && i < lib.size(); i++) {
                top.add(lib.get(i).getName());
            }
            for (int i = Math.max(0, lib.size() - expectBottom.size()); i < lib.size(); i++) {
                bottom.add(lib.get(i).getName());
            }
            List<String> sb = new ArrayList<>(bottom);
            List<String> se = new ArrayList<>(expectBottom);
            java.util.Collections.sort(sb);
            java.util.Collections.sort(se);
            check("S4P.assert.library_follows_plan", plan != null && expect.size() + expectBottom.size() == 2
                            && top.equals(expect) && sb.equals(se),
                    Json.map("plan", plan, "names", nameOf, "expected_top", expect, "engine_top", top,
                            "expected_bottom", expectBottom, "engine_bottom", bottom));
        } finally {
            f.close();
        }
    }

    // =============================================================================================
    // S10P: Cultivate through the front: two dialogs in one resolution; the second is continued after the first is
    // replayed from the seat's own answers

    static void s10p() throws Exception {
        SeatSetup a = new SeatSetup();
        a.library.addAll(Arrays.asList("Forest", "Plains", "Island", "Swamp", "Mountain", "Forest", "Plains", "Island"));
        a.hand.add("Cultivate");
        a.battlefield.addAll(Arrays.asList("Forest", "Forest", "Forest"));
        SeatSetup b = new SeatSetup().lib("Island", 8);
        b.battlefield.add("Island");
        EnginePos e = EnginePos.start("S10P", a, b);
        if (!e.advance(d -> priorityOf(d, "p0", "precombat_main"), 50)) {
            check("S10P.reach_position", false, e.trail);
            return;
        }
        FrontSeat f = new FrontSeat("S10P", "h1", Slice.gameStart("p0", a, b));
        try {
            if (!forceFirst(e, f, "cast_spell", "Cultivate")) {
                check("S10P.cast_offered", false, null);
                return;
            }
            List<Map<String, Object>> trace = drive(e, f, "p0", afterResolution("p0"), 80);
            List<Map<String, Object>> res = resolutionSteps(trace);
            Map<String, Object> second = null;
            for (Map<String, Object> t : res) {
                if (Boolean.TRUE.equals(t.get("continuation")) && Json.num(t, "continuation_replayed", 0) == 1) {
                    second = t;
                }
            }
            check("S10P.later_dialog_after_replay", second != null && allPaths(res, "continuation")
                            && countWith(res, "continuation") == 2,
                    Json.map("resolution", res));
            Map<String, Object> oe = e.over() ? null : obsOf(e.decision());
            check("S10P.assert.one_land_each_way", oe != null && names(oe, "p0", "battlefield").size() == 4
                            && Json.num(playerObs(oe, "p0"), "hand_count", -1) == 1,
                    Json.map("battlefield", oe == null ? null : names(oe, "p0", "battlefield"),
                            "hand_count", oe == null ? null : playerObs(oe, "p0").get("hand_count")));
        } finally {
            f.close();
        }
    }

    // =============================================================================================
    // A3 (change 7): identical permitted inputs across hidden worlds; the powered C-MCTS pilot

    static SeatSetup[] counterspell(String world) {
        SeatSetup a = new SeatSetup().lib("Plains", 8);
        a.hand.add("Serra Angel");
        a.battlefield.addAll(Arrays.asList("Plains", "Plains", "Plains", "Forest", "Forest", "Forest"));
        SeatSetup b = new SeatSetup();
        if ("R".equals(world)) {
            b.library.addAll(Arrays.asList("Island", "Mountain", "Island", "Refute", "Island", "Mountain", "Island", "Island"));
            b.hand.addAll(Arrays.asList("Refute", "Island"));
        } else {
            b.library.addAll(Arrays.asList("Island", "Mountain", "Island", "Refute", "Island", "Mountain", "Island", "Refute"));
            b.hand.addAll(Arrays.asList("Island", "Island"));
        }
        b.battlefield.addAll(Arrays.asList("Island", "Island", "Island", "Mountain", "Mountain"));
        return new SeatSetup[]{a, b};
    }

    static SeatSetup[] cantrip(String world) {
        SeatSetup a = new SeatSetup();
        if ("E".equals(world)) {
            a.library.addAll(Arrays.asList("Llanowar Elves", "Plains", "Forest", "Plains", "Forest", "Llanowar Elves", "Plains", "Forest"));
        } else {
            a.library.addAll(Arrays.asList("Plains", "Plains", "Forest", "Llanowar Elves", "Forest", "Llanowar Elves", "Plains", "Forest"));
        }
        a.hand.addAll(Arrays.asList("Helpful Hunter", "Cathar Commando"));
        a.battlefield.addAll(Arrays.asList("Plains", "Forest", "Forest"));
        SeatSetup b = new SeatSetup().lib("Island", 8);
        b.hand.addAll(Arrays.asList("Island", "Island"));
        b.battlefield.addAll(Arrays.asList("Island", "Island"));
        return new SeatSetup[]{a, b};
    }

    static SeatSetup[] position(String pair, String world) {
        return "counterspell".equals(pair) ? counterspell(world) : cantrip(world);
    }

    static void a3() throws Exception {
        String[][] pairs = {{"counterspell", "R", "N"}, {"cantrip", "E", "L"}};
        for (String[] p : pairs) {
            for (String entry : new String[]{"h1", "h2", "h3"}) {
                Map<String, Object> answers = new LinkedHashMap<>();
                List<String> inputs = new ArrayList<>();
                List<Map<String, Object>> decisions = new ArrayList<>();
                List<String> starts = new ArrayList<>();
                for (int w = 1; w <= 2; w++) {
                    SeatSetup[] s = position(p[0], p[w]);
                    EnginePos e = EnginePos.start("A3-" + p[0], s[0], s[1]); // one secret per pair: same ids
                    if (!e.advance(d -> priorityOf(d, "p0", "precombat_main"), 50)) {
                        check("A3." + p[0] + ".reach_position", false, e.trail);
                        return;
                    }
                    Map<String, Object> gs = Slice.gameStart("p0", s[0], s[1]);
                    inputs.add(Json.canonical(Json.map("game_start", gs, "decision", e.decision())));
                    decisions.add(e.decision());
                    starts.add(Json.canonical(gs));
                    FrontSeat f = new FrontSeat("A3-" + p[0] + p[w] + entry, entry, gs);
                    try {
                        Map<String, Object> r = f.choose(e.decision());
                        answers.put(p[w], Json.map("candidate", r.get("candidate"), "path", r.get("path"), "tag", r.get("tag"),
                                "semantic", Json.obj(Json.obj(Json.arr(e.decision(), "candidates")
                                        .get(((Number) r.get("candidate")).intValue())), "semantic")));
                    } finally {
                        f.close();
                    }
                }
                // the engine mints object ids from its own UUIDs, which the hidden cards shift, so the two inputs
                // may differ in ids only: identical, or equal modulo ids (same game_start, observations equal modulo
                // ids, same candidate list modulo ids); answers are compared as semantics modulo ids
                boolean identical = inputs.get(0).equals(inputs.get(1));
                List<String> obsDiff = spellbench.kit.core.ObsCompare.diff(obsOf(decisions.get(0)), obsOf(decisions.get(1)), 20);
                boolean sameCands = Json.canonical(stripIds(Json.arr(decisions.get(0), "candidates")))
                        .equals(Json.canonical(stripIds(Json.arr(decisions.get(1), "candidates"))));
                boolean moduloIds = starts.get(0).equals(starts.get(1)) && obsDiff.isEmpty() && sameCands;
                Object s1 = stripIds(Json.obj(answers.get(p[1])).get("semantic"));
                Object s2 = stripIds(Json.obj(answers.get(p[2])).get("semantic"));
                boolean sameAnswer = Json.canonical(s1).equals(Json.canonical(s2));
                check("A3." + p[0] + "." + entry + ".identical_inputs_identical_answer", (identical || moduloIds) && sameAnswer,
                        Json.map("permitted_inputs", identical ? "identical" : moduloIds ? "equal_modulo_ids" : "different",
                                "observation_diff_modulo_ids", obsDiff, "answers", answers));
            }
        }
    }

    /** A copy without object ids (fields named object_id), for comparisons modulo ids. */
    static Object stripIds(Object v) {
        if (v instanceof Map) {
            Map<String, Object> out = new LinkedHashMap<>();
            for (Map.Entry<String, Object> e : Json.obj(v).entrySet()) {
                if (!"object_id".equals(e.getKey())) {
                    out.put(e.getKey(), stripIds(e.getValue()));
                }
            }
            return out;
        }
        if (v instanceof List) {
            List<Object> out = new ArrayList<>();
            for (Object o : Json.arr(v)) {
                out.add(stripIds(o));
            }
            return out;
        }
        return v;
    }

    /** The powered C-MCTS pilot: kit and oracle MCTS on each world with every root child at 40 or more visits. */
    static void mctsPowered() {
        String[][] pairs = {{"counterspell", "R", "N"}, {"cantrip", "E", "L"}};
        for (String[] p : pairs) {
            Map<String, Object> rows = new LinkedHashMap<>();
            boolean powered = true;
            for (int w = 1; w <= 2; w++) {
                SeatSetup[] s = position(p[0], p[w]);
                EnginePos e = EnginePos.start("A3-" + p[0], s[0], s[1]);
                e.advance(d -> priorityOf(d, "p0", "precombat_main"), 50);
                Map<String, Object> d0 = e.decision();
                Map<String, Object> gs = Slice.gameStart("p0", s[0], s[1]);
                for (String mode : new String[]{"kit", "oracle"}) {
                    KitContext.reset();
                    KitContext.mctsIterations = 400;
                    KitContext.rolloutCap = 1000; // the frozen kit-mcts cap (cap 300 rejected by the E4 clause 2 threshold)
                    KitMcts[] m = new KitMcts[1];
                    KitRandom random = KitRandom.install(Seeds.worldSeed(Slice.GAME_KEY, Json.num(d0, "seat_step", 0), 0), Slice.ID_SEED);
                    WorldBuilder.Spec spec = new WorldBuilder.Spec();
                    spec.gameStart = gs;
                    spec.observation = obsOf(d0);
                    spec.sample = "oracle".equals(mode) ? Slice.oracle(e, obsOf(d0)) : Sampler.sample(gs, obsOf(d0), random.stream("sampler"));
                    spec.random = random;
                    spec.mode = WorldBuilder.Mode.PRIORITY;
                    spec.viewerFactory = seat -> {
                        m[0] = new KitMcts(seat, 6);
                        return m[0];
                    };
                    spec.otherFactory = Puppet::new;
                    World mw = WorldBuilder.build(spec);
                    KnowledgeWatcher.install(mw.game, mw.player("p0"));
                    long t0 = System.nanoTime();
                    Map<String, Object> res = m[0].decidePriority(mw, new ObsIndex(obsOf(d0)));
                    long minVisits = Long.MAX_VALUE;
                    for (Object o : Json.arr(res, "root_stats")) {
                        minVisits = Math.min(minVisits, Json.num(Json.obj(o), "visits", 0));
                    }
                    powered &= minVisits != Long.MAX_VALUE && minVisits >= 40;
                    Map<String, Object> sem = Json.obj(res, "semantic");
                    rows.put(p[w] + "_" + mode, Json.map("decision", sem == null ? null : sem.get("source") == null ? sem.get("kind")
                                    : Json.str(Json.obj(sem, "source"), "card_name"), "min_root_visits", minVisits,
                            "ms", (System.nanoTime() - t0) / 1_000_000, "root_stats", res.get("root_stats"),
                            "counters", KitContext.counters()));
                }
            }
            KitContext.mctsIterations = 300;
            KitContext.rolloutCap = 2000;
            Object kit1 = Json.obj(rows.get(p[1] + "_kit")).get("decision");
            Object kit2 = Json.obj(rows.get(p[2] + "_kit")).get("decision");
            check("MCTSPOWER." + p[0] + ".powered_and_kit_identical", powered && kit1 != null && kit1.equals(kit2), rows);
        }
    }

    // =============================================================================================
    // REG (change 3): the register's state conditions on engine positions

    static World worldAt(Map<String, Object> gs, Map<String, Object> d) {
        KitMad[] dec = new KitMad[1];
        return Slice.world(gs, d, null, WorldBuilder.Mode.PRIORITY, 0, dec, null);
    }

    /** Answers the pending decision with the first candidate matching; false when none matches. */
    static boolean answerWhere(EnginePos e, java.util.function.Predicate<Map<String, Object>> sem) {
        List<Object> cands = Json.arr(e.decision(), "candidates");
        for (int i = 0; i < cands.size(); i++) {
            if (sem.test(Json.obj(Json.obj(cands.get(i)), "semantic"))) {
                e.answer(i);
                return true;
            }
        }
        return false;
    }

    static boolean namesTarget(Map<String, Object> sem, String name) {
        Map<String, Object> t = Json.obj(sem, "target");
        Map<String, Object> o = t == null ? null : Json.obj(t, "object");
        return o != null && name.equals(o.get("card_name"));
    }

    static void reg() throws Exception {
        // 1. a trigger whose card the register lists as reading event data: Youthful Valkyrie's Angel trigger
        {
            SeatSetup a = new SeatSetup().lib("Plains", 8);
            a.hand.add("Serra Angel");
            a.battlefield.addAll(Arrays.asList("Youthful Valkyrie", "Plains", "Plains", "Plains", "Plains", "Plains"));
            SeatSetup b = new SeatSetup().lib("Island", 8);
            b.battlefield.add("Island");
            EnginePos e = EnginePos.start("REG1", a, b);
            e.advance(d -> priorityOf(d, "p0", "precombat_main"), 50);
            boolean cast = answerWhere(e, s -> "cast_spell".equals(s.get("kind")) && "Serra Angel".equals(Json.str(Json.obj(s, "source"), "card_name")));
            boolean reached = cast && e.advance(d -> priorityOf(d, "p0", null) && !Json.arr(obsOf(d), "stack").isEmpty()
                    && "triggered_ability".equals(Json.str(Json.obj(Json.arr(obsOf(d), "stack").get(Json.arr(obsOf(d), "stack").size() - 1)), "stack_kind")), 30);
            World w = reached ? worldAt(Slice.gameStart("p0", a, b), e.decision()) : null;
            check("REG.trigger_event_data_horizon", w != null && w.flags.contains("approximate:trigger_event_data")
                            && w.flags.contains("horizon:stack_object") && Runner.skipReason(w, "priority") != null,
                    Json.map("reached", reached, "flags", w == null ? null : w.flags, "register", Register.card("Youthful Valkyrie")));
        }
        // 2. a spell with an optional cost on the stack: Burst Lightning (kicker)
        {
            SeatSetup a = new SeatSetup().lib("Mountain", 8);
            a.hand.add("Burst Lightning");
            a.battlefield.add("Mountain");
            SeatSetup b = new SeatSetup().lib("Island", 8);
            b.battlefield.addAll(Arrays.asList("Island", "Grizzly Bears"));
            EnginePos e = EnginePos.start("REG2", a, b);
            e.advance(d -> priorityOf(d, "p0", "precombat_main"), 50);
            boolean cast = answerWhere(e, s -> "cast_spell".equals(s.get("kind")) && "Burst Lightning".equals(Json.str(Json.obj(s, "source"), "card_name")));
            boolean reached = cast && e.advance(d -> priorityOf(d, "p0", null) && !Json.arr(obsOf(d), "stack").isEmpty(), 20);
            World w = reached ? worldAt(Slice.gameStart("p0", a, b), e.decision()) : null;
            check("REG.optional_cost_state_horizon", w != null && w.flags.contains("approximate:optional_cost_state")
                            && w.flags.contains("horizon:stack_object") && Runner.skipReason(w, "priority") != null,
                    Json.map("reached", reached, "flags", w == null ? null : w.flags));
        }
        // 3. a spell whose target left: Shock on Grizzly Bears, then Stab on the Bears resolves first
        {
            SeatSetup a = new SeatSetup().lib("Swamp", 8);
            a.hand.addAll(Arrays.asList("Shock", "Stab"));
            a.battlefield.addAll(Arrays.asList("Mountain", "Swamp"));
            SeatSetup b = new SeatSetup().lib("Island", 8);
            b.battlefield.addAll(Arrays.asList("Island", "Grizzly Bears"));
            EnginePos e = EnginePos.start("REG3", a, b);
            e.advance(d -> priorityOf(d, "p0", "precombat_main"), 50);
            boolean ok = answerWhere(e, s -> "cast_spell".equals(s.get("kind")) && "Shock".equals(Json.str(Json.obj(s, "source"), "card_name")));
            ok = ok && e.advance(d -> "choose_target".equals(Slice.Front_firstKind(d)), 10)
                    && answerWhere(e, s -> namesTarget(s, "Grizzly Bears"));
            ok = ok && e.advance(d -> priorityOf(d, "p0", null) && Json.arr(obsOf(d), "stack").size() == 1, 10)
                    && answerWhere(e, s -> "cast_spell".equals(s.get("kind")) && "Stab".equals(Json.str(Json.obj(s, "source"), "card_name")));
            ok = ok && e.advance(d -> "choose_target".equals(Slice.Front_firstKind(d)), 10)
                    && answerWhere(e, s -> namesTarget(s, "Grizzly Bears"));
            ok = ok && e.advance(d -> priorityOf(d, "p0", null) && Json.arr(obsOf(d), "stack").size() == 2, 10);
            if (ok) {
                e.answer(0); // p0 passes; p1 passes in advance; Stab resolves
            }
            ok = ok && e.advance(d -> priorityOf(d, "p0", null) && Json.arr(obsOf(d), "stack").size() == 1, 10);
            World w = ok ? worldAt(Slice.gameStart("p0", a, b), e.decision()) : null;
            check("REG.incomplete_targets_horizon", w != null && w.flags.contains("approximate:stack_targets_incomplete")
                            && w.flags.contains("horizon:stack_object") && Runner.skipReason(w, "priority") != null,
                    Json.map("reached", ok, "flags", w == null ? null : w.flags,
                            "stack", ok ? Json.arr(obsOf(e.decision()), "stack") : null));
        }
        // 4. an emblem in the command zone, rebuilt from the register: Kaito, Bane of Nightmares
        {
            SeatSetup a = new SeatSetup().lib("Island", 8);
            a.battlefield.addAll(Arrays.asList("Kaito, Bane of Nightmares", "Island", "Swamp"));
            SeatSetup b = new SeatSetup().lib("Island", 8);
            b.battlefield.add("Island");
            EnginePos e = EnginePos.start("REG4", a, b);
            e.advance(d -> priorityOf(d, "p0", "precombat_main"), 50);
            boolean ok = false;
            Map<String, Object> d0 = e.decision();
            long best = Long.MAX_VALUE;
            int pick = -1;
            List<Object> cands = Json.arr(d0, "candidates");
            for (int i = 0; i < cands.size(); i++) {
                Map<String, Object> s = Json.obj(Json.obj(cands.get(i)), "semantic");
                if ("activate_ability".equals(s.get("kind")) && "Kaito, Bane of Nightmares".equals(Json.str(Json.obj(s, "source"), "card_name"))
                        && Json.num(s, "ability_index", 99) < best) {
                    best = Json.num(s, "ability_index", 99);
                    pick = i;
                }
            }
            Map<String, Object> dEmblem = null;
            if (pick >= 0) {
                e.answer(pick);
                ok = e.advance(d -> priorityOf(d, "p0", null) && Json.arr(obsOf(d), "stack").isEmpty()
                        && !Json.arr(playerObs(obsOf(d), "p0"), "command").isEmpty(), 30);
                dEmblem = ok ? e.decision() : null;
            }
            World w = dEmblem == null ? null : Slice.world(Slice.gameStart("p0", a, b), dEmblem, Slice.oracle(e, obsOf(dEmblem)),
                    WorldBuilder.Mode.PRIORITY, 0, new KitMad[1], null);
            Map<String, Object> ow = w == null ? null : Slice.project(w, "p0", new ArrayList<>());
            boolean rebuilt = w != null && w.flags.contains("rebuilt:emblem") && Runner.skipReason(w, "priority") == null;
            List<Object> ownCommand = dEmblem == null ? null : Json.arr(playerObs(obsOf(dEmblem), "p0"), "command");
            List<Object> worldCommand = ow == null ? null : Json.arr(playerObs(ow, "p0"), "command");
            check("REG.emblem_rebuilt", rebuilt && worldCommand != null && ownCommand.size() == worldCommand.size()
                            && Json.str(Json.obj(ownCommand.get(0)), "card_name").equals(Json.str(Json.obj(worldCommand.get(0)), "card_name")),
                    Json.map("reached", ok, "flags", w == null ? null : w.flags, "engine_command", ownCommand,
                            "world_command", worldCommand));
        }
        regNonStack();
    }

    /** Review change 4: a non-stack action that asks a dialog while it executes is detected (and then declined). */
    static void regNonStack() {
        SeatSetup a = new SeatSetup().lib("Mountain", 8);
        a.hand.add("Thriving Bluff");
        a.battlefield.add("Mountain");
        SeatSetup b = new SeatSetup().lib("Island", 8);
        b.battlefield.add("Island");
        EnginePos e = EnginePos.start("REG5", a, b);
        e.advance(d -> priorityOf(d, "p0", "precombat_main"), 50);
        Map<String, Object> d = e.decision();
        int c = candidateWhere(d, "play_land", "Thriving Bluff");
        if (c < 0) {
            check("REG.non_stack_dialog_detected", false, "no land play offered");
            return;
        }
        KitMad[] dec = new KitMad[1];
        World w = Slice.world(Slice.gameStart("p0", a, b), d, null, WorldBuilder.Mode.PRIORITY, 0, dec, null);
        KitMad.PriorityOutcome o = Runner.forced(w, dec[0],
                Json.obj(Json.obj(Json.arr(d, "candidates").get(c)), "semantic"), new ObsIndex(obsOf(d)));
        List<Object> families = new ArrayList<>();
        for (KitMad.Answer x : o.answers) {
            families.add(x.family);
        }
        check("REG.non_stack_dialog_detected", o.activated && o.nonStack && !o.answers.isEmpty(),
                Json.map("activated", o.activated, "non_stack", o.nonStack, "families", families));
    }

    // =============================================================================================
    // POOLAUDIT (change 3): the register's run-time facts for every listed card

    static void poolAudit() {
        Map<String, Object> bad = new LinkedHashMap<>();
        long cardsChecked = 0;
        long tokensChecked = 0;
        long emblemsChecked = 0;
        java.util.Set<String> names = new java.util.TreeSet<>();
        try (java.io.InputStream in = Register.class.getResourceAsStream("/spellbench/kit/xmage/register.json")) {
            java.io.ByteArrayOutputStream b = new java.io.ByteArrayOutputStream();
            byte[] buf = new byte[65536];
            int n;
            while ((n = in.read(buf)) > 0) {
                b.write(buf, 0, n);
            }
            names.addAll(Json.obj(Json.parseObject(new String(b.toByteArray(), java.nio.charset.StandardCharsets.UTF_8)), "cards").keySet());
        } catch (IOException | RuntimeException ex) {
            check("POOLAUDIT.register_loaded", false, ex.toString());
            return;
        }
        for (String name : names) {
            Map<String, Object> c = Register.card(name);
            List<String> problems = new ArrayList<>();
            try {
                Slice.RESOLVER.resolve(name).createCard(java.util.UUID.nameUUIDFromBytes(new byte[]{3}));
                cardsChecked++;
            } catch (RuntimeException ex) {
                problems.add("card: " + ex);
            }
            for (Object t : Json.arr(c, "tokens")) {
                String cls = String.valueOf(t);
                tokensChecked++;
                try {
                    Token tok = (Token) Class.forName("mage.game.permanent.token." + cls).getConstructor().newInstance();
                    boolean found = false;
                    for (Token cand : WorldBuilder.tokenCandidates(tok.getName())) {
                        found |= cand.getClass().equals(tok.getClass());
                    }
                    if (!found) {
                        problems.add("token " + cls + " (" + tok.getName() + ") does not resolve by name");
                    }
                } catch (ReflectiveOperationException | RuntimeException | LinkageError ex) {
                    problems.add("token " + cls + ": " + ex.getClass().getSimpleName());
                }
            }
            for (Object em : Json.arr(c, "emblems")) {
                emblemsChecked++;
                try {
                    Class.forName(Json.str(Json.obj(em), "class")).getConstructor().newInstance();
                } catch (ReflectiveOperationException | RuntimeException | LinkageError ex) {
                    problems.add("emblem " + Json.str(Json.obj(em), "class") + ": " + ex.getClass().getSimpleName());
                }
            }
            if (!problems.isEmpty()) {
                bad.put(name, problems);
            }
        }
        note("POOLAUDIT.findings", Json.map("cards", cardsChecked, "token_classes", tokensChecked, "emblem_classes", emblemsChecked,
                "problems", bad));
        check("POOLAUDIT.completed", cardsChecked > 0, Json.map("cards", cardsChecked, "cards_with_problems", (long) bad.size()));
    }

    // =============================================================================================
    // UNMAPPED (change 5): dumped decisions through MAD with the mapping diagnostics

    static void unmapped() throws Exception {
        String dir = System.getProperty("kit.unmapped.dir");
        File[] files = dir == null ? null : new File(dir).listFiles((d, n) -> n.startsWith("decision-") && n.endsWith(".json"));
        if (files == null || files.length == 0) {
            check("UNMAPPED.positions_available", false, dir);
            return;
        }
        Arrays.sort(files);
        List<Object> rows = new ArrayList<>();
        for (File f : files) {
            Map<String, Object> rec = Json.parseObject(new String(Files.readAllBytes(f.toPath()), "UTF-8"));
            Map<String, Object> gs = Json.obj(rec, "game_start");
            Map<String, Object> d = Json.obj(rec, "decision");
            byte[] gameKey = Seeds.gameKey(Json.num(gs, "agent_seed", 0));
            byte[] idSeed = Seeds.hmac(gameKey, "ids");
            ObsIndex idx = new ObsIndex(obsOf(d));
            KitContext.reset();
            KitRandom random = KitRandom.install(Seeds.worldSeed(gameKey, Json.num(d, "seat_step", 0), 0), idSeed);
            WorldBuilder.Spec spec = new WorldBuilder.Spec();
            spec.gameStart = gs;
            spec.observation = obsOf(d);
            spec.sample = Sampler.sample(gs, obsOf(d), random.stream("sampler"));
            spec.random = random;
            spec.mode = WorldBuilder.Mode.PRIORITY;
            spec.history = Json.obj(d, "x_history");
            final KitMad[] kit = new KitMad[1];
            spec.viewerFactory = seat -> {
                kit[0] = new KitMad(seat, 6);
                return kit[0];
            };
            spec.otherFactory = Puppet::new;
            World w = WorldBuilder.build(spec);
            kit[0].attach(w);
            KitMad.PriorityOutcome o = kit[0].decidePriority(w, idx, false);
            boolean offered = false;
            String key = o.semantic == null ? null : Json.canonical(o.semantic);
            for (Object cnd : Json.arr(d, "candidates")) {
                offered |= key != null && key.equals(Json.canonical(Json.obj(Json.obj(cnd), "semantic")));
            }
            List<Object> offeredFromSource = new ArrayList<>();
            for (Object cnd : Json.arr(d, "candidates")) {
                Map<String, Object> s = Json.obj(Json.obj(cnd), "semantic");
                Map<String, Object> src = Json.obj(s, "source");
                if (o.chosen != null && src != null && w.uuidToId.get(o.chosen.getSourceId()) != null
                        && w.uuidToId.get(o.chosen.getSourceId()).equals(src.get("object_id"))) {
                    offeredFromSource.add(s);
                }
            }
            rows.add(Json.map("file", f.getName(), "seat_step", d.get("seat_step"), "chosen", Mapping.describe(w, w.game, o.chosen),
                    "semantic", o.semantic, "offered", offered, "mapping_failure", Mapping.failure(w, w.game, o.chosen, idx),
                    "offered_from_same_source", offeredFromSource, "flags", w.flags, "x_history", d.get("x_history")));
        }
        note("UNMAPPED.diagnosis", rows);
        check("UNMAPPED.completed", !rows.isEmpty(), Json.map("positions", (long) rows.size()));
    }
}
