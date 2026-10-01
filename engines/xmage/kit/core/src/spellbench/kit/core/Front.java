package spellbench.kit.core;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;
import java.io.PrintStream;
import java.io.Writer;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * The kit's front process (design Section 2.1): speaks the protocol v2 agent role over stdio (Section 10), keeps the
 * permitted-input history, plans, saved anchors and the fallback, and never runs a search: every world is built and
 * searched by the runner, a child JVM with XMage. Its stdout carries only protocol lines.
 * <p>
 * Decision paths (Section 5.1, 6.2): the action's plan; single-candidate fast path; CP7's passing steps (ComputerPlayer7
 * passes without thinking outside the main phases and the declare steps, so the kit answers pass there without a
 * world, which is the bot's own answer); priority anchor (K worlds, vote); combat anchors; mulligan; saved-anchor
 * continuation, else current dialog; fallback. Every answer is tagged {@code bot}, {@code wrapper} or {@code cap}
 * (Section 6.5) in the evidence log.
 */
public final class Front {

    static final String PROTOCOL = "spellbench/v2";
    static final List<String> CP7_PASS_STEPS = Arrays.asList("untap", "upkeep", "draw", "beginning_of_combat",
            "combat_damage", "end_of_combat", "end_step", "cleanup");

    // configuration
    final String entry;
    final int worlds;
    final int skill;
    final String botName;
    final String botVersion;
    final long graceMs;
    final long overheadMs;
    final Map<String, Object> budgets = new LinkedHashMap<>();
    final long hangAt;
    final RunnerLink runner;
    final PrintStream log;

    // game state (permitted inputs only)
    Map<String, Object> gameStart;
    byte[] gameKey;
    String gameId;
    final PlanBook plans = new PlanBook();
    /** Saved anchors by stack object id (Section 5.1): the priority decision and world seeds where it was on top. */
    final Map<String, Map<String, Object>> anchors = new LinkedHashMap<>();
    /** This seat's answers with a choice source, by source object id (continuation replays earlier dialogs). */
    final Map<String, List<Map<String, Object>>> sourceAnswers = new LinkedHashMap<>();
    /** Combat and group plans: substep answers decided at substep 0. */
    Map<String, Object> groupPlan;
    long groupPlanGroupId = -1;
    /** Own history (Section 3.3): the last combat_damage observation of this turn. */
    long lastCombatDamageTurn = -1;
    int combatDamageSeen;
    final Map<String, Long> stats = new LinkedHashMap<>();

    Front(Map<String, String> opts, List<String> runnerCmd) throws IOException {
        entry = opts.getOrDefault("entry", "h1");
        worlds = Integer.parseInt(opts.getOrDefault("worlds", entry.equals("h1") ? "1" : "4"));
        skill = Integer.parseInt(opts.getOrDefault("skill", "6"));
        botName = opts.getOrDefault("name", "kit-" + (entry.equals("h3") ? "mcts" : "mad") + "-k" + worlds + "-s" + skill);
        botVersion = opts.getOrDefault("version", "0.1.0");
        graceMs = Long.parseLong(opts.getOrDefault("grace-ms", "5000"));
        overheadMs = Long.parseLong(opts.getOrDefault("overhead-ms", "1500"));
        hangAt = Long.parseLong(opts.getOrDefault("hang-at", "-1"));
        for (String b : new String[]{"nodes", "options", "operations", "iterations", "rollout"}) {
            if (opts.containsKey(b)) {
                budgets.put(b, Long.parseLong(opts.get(b)));
            }
        }
        File work = new File(opts.getOrDefault("work", "."));
        File err = new File(opts.getOrDefault("runner-log", new File(work, "runner-stderr.log").getPath()));
        runner = new RunnerLink(runnerCmd, work, err);
        String logPath = opts.get("log");
        log = logPath == null ? null : new PrintStream(new FileOutputStream(logPath, true), true, "UTF-8");
    }

    public static void main(String[] args) throws Exception {
        Map<String, String> opts = new LinkedHashMap<>();
        List<String> runnerCmd = new ArrayList<>();
        for (int i = 0; i < args.length; i++) {
            if (args[i].equals("--")) {
                runnerCmd.addAll(Arrays.asList(args).subList(i + 1, args.length));
                break;
            }
            if (args[i].startsWith("--") && i + 1 < args.length) {
                opts.put(args[i].substring(2), args[++i]);
            }
        }
        PrintStream protocol = new PrintStream(new FileOutputStream(java.io.FileDescriptor.out), true, "UTF-8");
        System.setOut(System.err);
        Front f = new Front(opts, runnerCmd);
        BufferedReader in = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        String line;
        while ((line = in.readLine()) != null) {
            if (line.trim().isEmpty()) {
                continue;
            }
            Map<String, Object> resp = f.handle(line);
            protocol.println(Json.canonical(resp));
            protocol.flush();
        }
        f.runner.close();
    }

    Map<String, Object> handle(String line) {
        Map<String, Object> req;
        try {
            req = Json.parseObject(line);
        } catch (RuntimeException e) {
            return error("", "malformed_json", e.getMessage());
        }
        Object rid = req.get("request_id");
        String requestId = rid instanceof String ? (String) rid : "";
        if (!PROTOCOL.equals(req.get("protocol"))) {
            return error(requestId, "protocol_mismatch", "protocol is not " + PROTOCOL);
        }
        String type = Json.str(req, "request_type");
        try {
            switch (type == null ? "" : type) {
                case "hello":
                    return Json.map("response_type", "hello_ok", "protocol", PROTOCOL, "request_id", requestId,
                            "bot", Json.map("name", botName, "version", botVersion),
                            "requires", Json.map("observation", Arrays.asList("passed_seats", "keywords"), "extensions", new ArrayList<>()),
                            "extensions_accepted", new ArrayList<>());
                case "game_start":
                    return gameStart(req, requestId);
                case "choose":
                    return choose(req, requestId);
                case "game_over":
                    gameOver(req);
                    return Json.map("response_type", "ack", "protocol", PROTOCOL, "request_id", requestId);
                default:
                    return error(requestId, "malformed_request", "unknown request_type " + type);
            }
        } catch (RuntimeException e) {
            e.printStackTrace(System.err);
            return error(requestId, "internal_error", e.toString());
        }
    }

    static Map<String, Object> error(String requestId, String code, String message) {
        return Json.map("response_type", "error", "protocol", PROTOCOL, "request_id", requestId,
                "error", Json.map("code", code, "message", message));
    }

    private void count(String k) {
        stats.merge(k, 1L, Long::sum);
    }

    // =============================================================================================

    Map<String, Object> gameStart(Map<String, Object> req, String requestId) {
        if (gameId != null) {
            return error(requestId, "game_already_active", "a game is active");
        }
        gameStart = req;
        gameId = Json.str(req, "game_id");
        long agentSeed = Json.num(req, "agent_seed", 0);
        gameKey = Seeds.gameKey(agentSeed);
        Map<String, Object> game = Json.map("op", "game", "game_start", stripEnvelope(req),
                "id_seed", Seeds.hex(Seeds.hmac(gameKey, "ids")));
        runner.setGame(game);
        // boot the runner now (inside game_start_ms), so the first decision does not pay for it
        try {
            runner.call(Json.map("op", "ping"), 600_000, 10_000);
        } catch (IOException | RunnerLink.Timeout e) {
            System.err.println("kit-front: runner start failed: " + e);
        }
        logLine(Json.map("event", "game_start", "seat", Json.str(req, "seat"), "boot_ms", runner.lastBootMs,
                "restart_ms", runner.lastRestartMs));
        return Json.map("response_type", "ack", "protocol", PROTOCOL, "request_id", requestId);
    }

    static Map<String, Object> stripEnvelope(Map<String, Object> req) {
        Map<String, Object> m = new LinkedHashMap<>(req);
        m.remove("request_id");
        m.remove("request_type");
        m.remove("protocol");
        return m;
    }

    void gameOver(Map<String, Object> req) {
        logLine(Json.map("event", "game_over", "terminal", req.get("terminal"), "stats", stats, "plans", plans.counters,
                "runner", Json.map("restarts", runner.restarts, "kills", runner.kills, "late_discarded", runner.lateDiscarded,
                        "kill_to_exit_ms", runner.killToExitMs, "last_restart_ms", runner.lastRestartMs)));
        plans.close();
        anchors.clear();
        sourceAnswers.clear();
        gameStart = null;
        gameId = null;
        runner.close();
    }

    // =============================================================================================
    // decisions

    /** What one answer was, for the response and the evidence log. */
    static final class Answer {
        int candidate;
        String tag = "bot";
        String path;
        Map<String, Object> detail = new LinkedHashMap<>();

        Answer(int candidate, String tag, String path) {
            this.candidate = candidate;
            this.tag = tag;
            this.path = path;
        }
    }

    Map<String, Object> choose(Map<String, Object> req, String requestId) {
        long t0 = System.nanoTime();
        Map<String, Object> d = Json.obj(req, "decision");
        Map<String, Object> clock = Json.obj(req, "clock");
        long budget = Math.min(clock == null ? 60_000 : Json.num(clock, "max_decision_ms", 60_000),
                clock == null ? 60_000 : Json.num(clock, "remaining_ms", 60_000));
        Answer a;
        try {
            a = decide(d, budget);
        } catch (RuntimeException e) {
            e.printStackTrace(System.err);
            a = fallback(d, null, "wrapper", "error:" + e.getClass().getSimpleName());
        }
        List<Object> cands = Json.arr(d, "candidates");
        if (a.candidate < 0 || a.candidate >= cands.size()) {
            a = fallback(d, null, "wrapper", "out_of_range");
        }
        recordAnswer(d, a);
        long ms = (System.nanoTime() - t0) / 1_000_000;
        count("tag:" + a.tag);
        count("path:" + a.path);
        Map<String, Object> line = Json.map("event", "decision", "seat_step", d.get("seat_step"),
                "kind", firstKind(d), "candidates", (long) cands.size(), "candidate", (long) a.candidate,
                "tag", a.tag, "path", a.path, "ms", ms, "budget_ms", budget);
        line.putAll(a.detail);
        logLine(line);
        return Json.map("response_type", "choice", "protocol", PROTOCOL, "request_id", requestId,
                "selection", Json.map("candidate_id", (long) a.candidate),
                "x_kit", Json.map("tag", a.tag, "path", a.path));
    }

    static String firstKind(Map<String, Object> d) {
        List<Object> c = Json.arr(d, "candidates");
        String k = null;
        for (Object o : c) {
            String kind = Json.str(Json.obj(Json.obj(o), "semantic"), "kind");
            if (!kind.startsWith("finish_") && !kind.equals("pass")) {
                return kind;
            }
            if (k == null) {
                k = kind;
            }
        }
        return k;
    }

    private void recordAnswer(Map<String, Object> d, Answer a) {
        Map<String, Object> ctx = Json.obj(d, "context");
        Map<String, Object> src = ctx == null ? null : Json.obj(ctx, "source");
        if (src != null && !"priority".equals(Json.str(ctx, "kind"))) {
            String id = Json.str(src, "object_id");
            List<Map<String, Object>> l = sourceAnswers.get(id);
            if (l == null) {
                l = new ArrayList<>();
                sourceAnswers.put(id, l);
            }
            l.add(Json.map("seat_step", d.get("seat_step"), "candidate", (long) a.candidate,
                    "semantic", Json.obj(Json.obj(Json.arr(d, "candidates").get(a.candidate)), "semantic")));
        }
    }

    Answer decide(Map<String, Object> d, long budget) {
        Map<String, Object> ctx = Json.obj(d, "context");
        Map<String, Object> obs = Json.obj(d, "observation");
        List<Object> cands = Json.arr(d, "candidates");
        boolean priority = ctx != null && "priority".equals(Json.str(ctx, "kind"));
        long seatStep = Json.num(d, "seat_step", 0);
        dropStaleAnchors(obs);
        trackCombatDamage(obs, priority);

        // rewind (Section 5.1 and 8): roll back every provisional record of the abandoned action
        if (priority && Json.bool(ctx, "rewind")) {
            String abandoned = plans.active == null ? null : plans.active.actionId();
            long since = plans.active == null ? seatStep : plans.active.seatStep;
            plans.rollback();
            int dropped = 0;
            for (String k : new ArrayList<>(anchors.keySet())) {
                if (Json.num(anchors.get(k), "seat_step", 0) >= since) {
                    anchors.remove(k);
                    dropped++;
                }
            }
            int answersDropped = 0;
            for (List<Map<String, Object>> l : sourceAnswers.values()) {
                int before = l.size();
                l.removeIf(m -> Json.num(m, "seat_step", 0) >= since);
                answersDropped += before - l.size();
            }
            groupPlan = null;
            count("rewinds");
            logLine(Json.map("event", "rewind", "seat_step", seatStep, "abandoned_action", abandoned,
                    "anchors_dropped", (long) dropped, "answers_dropped", (long) answersDropped));
        }

        // the action's plan (Section 6.1)
        if (!priority && plans.active != null) {
            if (cands.size() == 1) {
                plans.forced(d);
                return new Answer(0, "bot", "plan_forced");
            }
            int c = plans.claim(d);
            if (c >= 0) {
                return new Answer(c, "bot", "plan");
            }
            if (c == -1) {
                return fallback(d, null, "wrapper", "plan_missing_value");
            }
        } else if (priority) {
            plans.close();
        }

        // fast path: one candidate
        if (cands.size() == 1) {
            return new Answer(0, "bot", "single");
        }

        if (priority) {
            String step = Json.str(obs, "phase_step");
            boolean passFirst = "pass".equals(Json.str(Json.obj(Json.obj(cands.get(0)), "semantic"), "kind"));
            if (passFirst && CP7_PASS_STEPS.contains(step)) {
                return new Answer(0, "bot", "cp7_passes_in_step");
            }
            return priorityAnchor(d, budget);
        }
        String kind = firstKind(d);
        Map<String, Object> group = Json.obj(d, "group");
        long groupId = group == null ? -1 : Json.num(group, "group_id", -1);
        switch (kind) {
            case "declare_attack":
            case "declare_block":
                return combat(d, budget, kind, groupId);
            case "mulligan":
                return mulligan(d, budget);
            default:
                break;
        }
        if ("order_pick".equals(kind) && "mulligan_bottom".equals(Json.str(firstSemantic(d, "order_pick"), "purpose"))) {
            return groupDialog(d, budget, "mulligan_bottom", groupId);
        }
        // saved-anchor continuation, else the current dialog
        String src = PlanBook.sourceId(d);
        if (src != null && anchors.containsKey(src)) {
            Answer cont = continuation(d, budget, src);
            if (cont != null) {
                return cont;
            }
        }
        return groupDialog(d, budget, "dialog", groupId);
    }

    static Map<String, Object> firstSemantic(Map<String, Object> d, String kind) {
        for (Object o : Json.arr(d, "candidates")) {
            Map<String, Object> sem = Json.obj(Json.obj(o), "semantic");
            if (kind.equals(Json.str(sem, "kind"))) {
                return sem;
            }
        }
        return null;
    }

    // ---------------------------------------------------------------------------------------------

    private List<Object> worldSeeds(long seatStep, int k) {
        List<Object> out = new ArrayList<>();
        for (int i = 0; i < k; i++) {
            out.add(Seeds.hex(Seeds.worldSeed(gameKey, seatStep, i)));
        }
        return out;
    }

    private Map<String, Object> request(String path, Map<String, Object> d, int k, long budget) {
        long seatStep = Json.num(d, "seat_step", 0);
        Map<String, Object> decision = new LinkedHashMap<>(d);
        Map<String, Object> profile = Json.obj(gameStart, "engine_profile");
        if (profile != null && profile.get("observation") != null) {
            decision.put("x_observation_flags", profile.get("observation"));
        }
        Map<String, Object> r = Json.map("op", "decide", "path", path, "decision", decision,
                "world_seeds", worldSeeds(seatStep, k), "budgets", budgets,
                "bot", Json.map("kind", entry.equals("h3") ? "mcts" : "mad", "skill", (long) skill),
                "deadline_ms", runnerDeadline(budget), "combat_damage_step", combatDamageStep(d));
        if (seatStep == hangAt) {
            r.put("hang", true);
        }
        return r;
    }

    /** The runner's safety deadline: the decision budget minus the grace period and the response overhead. */
    long runnerDeadline(long budget) {
        return Math.max(100, budget - graceMs - overheadMs);
    }

    /** Calls the runner; null on a timeout (the runner was killed), recorded in {@code a}'s detail. */
    private Map<String, Object> call(Map<String, Object> request, long budget, Map<String, Object> detail) {
        long deadline = Json.num(request, "deadline_ms", 1000);
        try {
            Map<String, Object> r = runner.call(request, deadline, graceMs);
            if (!Json.bool(r, "ok")) {
                detail.put("runner_error", r.get("error"));
                return null;
            }
            if (Json.bool(r, "interrupted")) {
                detail.put("cap", "deadline_interrupt");
            }
            return r;
        } catch (RunnerLink.Timeout e) {
            detail.put("cap", "runner_killed");
            detail.put("exit_confirmed", e.exitConfirmed);
            detail.put("waited_ms", e.waitedMs);
            return null;
        } catch (IOException e) {
            detail.put("runner_error", e.toString());
            return null;
        }
    }

    Answer priorityAnchor(Map<String, Object> d, long budget) {
        Map<String, Object> detail = new LinkedHashMap<>();
        if (budget < graceMs + overheadMs + 200) {
            Answer a = fallback(d, null, "cap", "clock_low");
            return a;
        }
        Map<String, Object> req = request("priority", d, worlds, budget);
        Map<String, Object> r = call(req, budget, detail);
        if (r == null) {
            Answer a = fallback(d, null, detail.containsKey("cap") ? "cap" : "wrapper", "priority_failed");
            a.detail.putAll(detail);
            return a;
        }
        List<Object> results = Json.arr(r, "worlds");
        Map<String, Integer> candidateOf = candidateKeys(d);
        List<Aggregate.WorldVote> votes = new ArrayList<>();
        List<Object> flags = new ArrayList<>();
        long nodes = 0;
        for (Object o : results) {
            Map<String, Object> w = Json.obj(o);
            votes.add(Aggregate.fromRunner(w));
            flags.addAll(Json.arr(w, "flags"));
            nodes += Json.num(w, "nodes", 0);
            mergeCounters(detail, Json.obj(w, "counters"));
        }
        Aggregate.Result agg;
        if (entry.equals("h3")) {
            List<Map<String, Object>> ws = new ArrayList<>();
            for (Object o : results) {
                ws.add(Json.obj(o));
            }
            agg = Aggregate.visits(ws, candidateOf);
        } else {
            agg = Aggregate.vote(votes, candidateOf);
        }
        detail.put("worlds", (long) results.size());
        detail.put("world_flags", dedupe(flags));
        detail.put("runner_ms", r.get("ms"));
        detail.put("nodes", nodes);
        if (!results.isEmpty()) {
            Map<String, Object> w0 = Json.obj(results.get(0));
            detail.put("build_ms", w0.get("build_ms"));
            detail.put("search_ms", w0.get("search_ms"));
        }
        String tag = detail.containsKey("cap") ? "cap" : "bot";
        Integer c = agg.winner == null ? null : candidateOf.get(agg.winner);
        if (c == null) {
            detail.put("unmapped_winner", agg.winner);
            Answer a = rankedFallback(d, agg, candidateOf, "wrapper", "priority_unmapped");
            a.detail.putAll(detail);
            return a;
        }
        // save an anchor for the stack's top object (continuation, Section 5.1)
        List<Object> stack = Json.arr(Json.obj(d, "observation"), "stack");
        if (!stack.isEmpty()) {
            String top = Json.str(Json.obj(stack.get(stack.size() - 1)), "object_id");
            anchors.put(top, Json.map("decision", d, "world_seeds", req.get("world_seeds"), "seat_step", d.get("seat_step")));
        }
        Map<String, Object> sem = Json.obj(Json.obj(Json.arr(d, "candidates").get(c)), "semantic");
        if (!"pass".equals(Json.str(sem, "kind"))) {
            List<Map<String, Object>> answers = new ArrayList<>();
            if (agg.planWorld >= 0) {
                for (Object o : Json.arr(Json.obj(results.get(agg.planWorld)), "answers")) {
                    answers.add(Json.obj(o));
                }
            }
            plans.open(Json.num(d, "seat_step", 0), sem, Json.obj(d, "observation"), agg.planPayload, answers);
            detail.put("plan_payload", agg.planPayload);
        }
        Answer a = new Answer(c, tag, "priority_anchor");
        a.detail.putAll(detail);
        return a;
    }

    static List<Object> dedupe(List<Object> l) {
        List<Object> out = new ArrayList<>();
        for (Object o : l) {
            if (!out.contains(o)) {
                out.add(o);
            }
        }
        return out;
    }

    @SuppressWarnings("unchecked")
    static void mergeCounters(Map<String, Object> detail, Map<String, Object> counters) {
        if (counters == null || counters.isEmpty()) {
            return;
        }
        Map<String, Object> m = (Map<String, Object>) detail.get("counters");
        if (m == null) {
            m = new LinkedHashMap<>();
            detail.put("counters", m);
        }
        for (Map.Entry<String, Object> e : counters.entrySet()) {
            long before = m.get(e.getKey()) instanceof Number ? ((Number) m.get(e.getKey())).longValue() : 0;
            m.put(e.getKey(), before + ((Number) e.getValue()).longValue());
        }
    }

    static Map<String, Integer> candidateKeys(Map<String, Object> d) {
        Map<String, Integer> out = new LinkedHashMap<>();
        List<Object> cands = Json.arr(d, "candidates");
        for (int i = 0; i < cands.size(); i++) {
            out.put(Aggregate.key(Json.obj(Json.obj(cands.get(i)), "semantic")), i);
        }
        return out;
    }

    // ---------------------------------------------------------------------------------------------
    // combat (Section 5.5.4: a vote per combat key; the winning assignment is the plan of every substep)

    @SuppressWarnings("unchecked")
    Answer combat(Map<String, Object> d, long budget, String kind, long groupId) {
        Map<String, Object> detail = new LinkedHashMap<>();
        if (groupPlan == null || groupPlanGroupId != groupId) {
            groupPlan = null;
            Map<String, Object> r = budget < graceMs + overheadMs + 200 ? null
                    : call(request(kind.equals("declare_attack") ? "attack" : "block", d, worlds, budget), budget, detail);
            if (r != null) {
                Map<String, Integer> votes = new LinkedHashMap<>();
                Map<String, Object> byKey = new LinkedHashMap<>();
                for (Object o : Json.arr(r, "worlds")) {
                    List<Object> pairs = Json.arr(Json.obj(o), "pairs");
                    String key = Json.canonical(sortPairs(pairs));
                    votes.merge(key, 1, Integer::sum);
                    if (!byKey.containsKey(key)) {
                        byKey.put(key, pairs);
                    }
                }
                String best = null;
                for (Map.Entry<String, Integer> e : votes.entrySet()) {
                    if (best == null || e.getValue() > votes.get(best)) {
                        best = e.getKey(); // ties: the lowest world index, which entered first
                    }
                }
                groupPlan = Json.map("pairs", byKey.get(best), "votes", votes.size());
                groupPlanGroupId = groupId;
            }
        }
        if (groupPlan == null) {
            Answer a = fallback(d, null, detail.containsKey("cap") ? "cap" : "wrapper", "combat_failed");
            a.detail.putAll(detail);
            return a;
        }
        List<Object> cands = Json.arr(d, "candidates");
        Map<String, Object> s0 = Json.obj(Json.obj(cands.get(0)), "semantic");
        String self = Json.str(Json.obj(s0, kind.equals("declare_attack") ? "attacker" : "blocker"), "object_id");
        Object want = null;
        for (Object p : Json.arr(groupPlan, "pairs")) {
            Map<String, Object> pm = Json.obj(p);
            if (self.equals(pm.get(kind.equals("declare_attack") ? "attacker" : "blocker"))) {
                want = kind.equals("declare_attack") ? pm.get("defender") : pm.get("attacker");
                break;
            }
        }
        for (int i = 0; i < cands.size(); i++) {
            Map<String, Object> sem = Json.obj(Json.obj(cands.get(i)), "semantic");
            if (kind.equals("declare_attack")) {
                Object def = sem.get("defender");
                if (want == null ? def == null : (def != null && PlanBook.sameTarget(Json.obj(def), want))) {
                    return new Answer(i, "bot", "combat_anchor");
                }
            } else {
                Object atk = sem.get("attacker");
                if (want == null ? atk == null
                        : (atk != null && want.equals(Json.str(Json.obj(atk), "object_id")))) {
                    return new Answer(i, "bot", "combat_anchor");
                }
            }
        }
        Answer a = fallback(d, null, "wrapper", "combat_pair_not_offered");
        a.detail.putAll(detail);
        return a;
    }

    static List<Object> sortPairs(List<Object> pairs) {
        List<String> keys = new ArrayList<>();
        for (Object p : pairs) {
            keys.add(Json.canonical(p));
        }
        java.util.Collections.sort(keys);
        List<Object> out = new ArrayList<>();
        for (String k : keys) {
            out.add(Json.parse(k));
        }
        return out;
    }

    Answer mulligan(Map<String, Object> d, long budget) {
        Map<String, Object> detail = new LinkedHashMap<>();
        Map<String, Object> r = call(request("mulligan", d, 1, budget), budget, detail);
        if (r == null || Json.arr(r, "worlds").isEmpty()) {
            Answer a = fallback(d, null, detail.containsKey("cap") ? "cap" : "wrapper", "mulligan_failed");
            a.detail.putAll(detail);
            return a;
        }
        boolean keep = Json.bool(Json.obj(Json.arr(r, "worlds").get(0)), "keep");
        List<Object> cands = Json.arr(d, "candidates");
        for (int i = 0; i < cands.size(); i++) {
            Map<String, Object> sem = Json.obj(Json.obj(cands.get(i)), "semantic");
            if (Boolean.valueOf(keep).equals(sem.get("keep"))) {
                return new Answer(i, "bot", "pregame_anchor");
            }
        }
        return fallback(d, null, "wrapper", "mulligan_not_offered");
    }

    /**
     * A choice through the current dialog (or the London bottom on the pregame anchor): substep 0 plans the whole
     * logical dialog; later substeps look the plan up and are re-checked against their actual candidates.
     */
    Answer groupDialog(Map<String, Object> d, long budget, String path, long groupId) {
        Map<String, Object> detail = new LinkedHashMap<>();
        Map<String, Object> group = Json.obj(d, "group");
        long sub = group == null ? 0 : Json.num(group, "substep_index", 0);
        if (groupPlan == null || groupPlanGroupId != groupId || sub == 0) {
            groupPlan = null;
            Map<String, Object> r = budget < graceMs + overheadMs + 200 ? null : call(request(path, d, 1, budget), budget, detail);
            List<Object> picks = r == null || Json.arr(r, "worlds").isEmpty() ? null
                    : Json.arr(Json.obj(Json.arr(r, "worlds").get(0)), "picks");
            if (r != null && !Json.arr(r, "worlds").isEmpty() && Json.obj(Json.arr(r, "worlds").get(0)).get("picks") == null) {
                picks = null;
            }
            if (picks != null) {
                groupPlan = Json.map("picks", picks, "cursor", 0L);
                groupPlanGroupId = groupId;
            }
        }
        if (groupPlan == null) {
            Answer a = fallback(d, null, detail.containsKey("cap") ? "cap" : "wrapper", "no_dialog:" + firstKind(d));
            a.detail.putAll(detail);
            return a;
        }
        List<Object> picks = Json.arr(groupPlan, "picks");
        int cursor = (int) Json.num(groupPlan, "cursor", 0);
        groupPlan.put("cursor", (long) (cursor + 1));
        List<Object> cands = Json.arr(d, "candidates");
        if (!picks.isEmpty() && picks.get(0) instanceof Map && Json.bool(Json.obj(picks.get(0)), "arrangement")) {
            // an arrangement (Section 6.3): partition from the plan; the ordering is recomputed from the actual
            // partition, since its candidates are the unplaced cards of the current destination
            Map<String, Object> plan = Json.obj(picks.get(0));
            Map<String, Object> dest = Json.obj(plan, "dest");
            List<Object> order = Json.arr(plan, "order");
            int best = -1;
            int bestRank = Integer.MAX_VALUE;
            for (int i = 0; i < cands.size(); i++) {
                Map<String, Object> sem = Json.obj(Json.obj(cands.get(i)), "semantic");
                if ("arrange_card".equals(Json.str(sem, "kind"))) {
                    String oid = Json.str(Json.obj(sem, "card"), "object_id");
                    if (Json.str(sem, "destination").equals(dest.get(oid))) {
                        return new Answer(i, "bot", path + ":arrangement");
                    }
                } else if ("order_pick".equals(Json.str(sem, "kind"))) {
                    Map<String, Object> o = Json.obj(Json.obj(sem, "item"), "object");
                    int rank = o == null ? -1 : order.indexOf(Json.str(o, "object_id"));
                    if (rank >= 0 && rank < bestRank) {
                        bestRank = rank;
                        best = i;
                    }
                }
            }
            if (best >= 0) {
                return new Answer(best, "bot", path + ":arrangement_order");
            }
            Answer a = fallback(d, null, "wrapper", path + "_arrangement_not_offered");
            a.detail.putAll(detail);
            return a;
        }
        if (cursor < picks.size()) {
            Object want = picks.get(cursor);
            for (int i = 0; i < cands.size(); i++) {
                Map<String, Object> sem = Json.obj(Json.obj(cands.get(i)), "semantic");
                if (matchesPick(sem, want)) {
                    return new Answer(i, "bot", path);
                }
            }
        } else {
            for (int i = 0; i < cands.size(); i++) {
                Map<String, Object> sem = Json.obj(Json.obj(cands.get(i)), "semantic");
                if (Json.str(sem, "kind").startsWith("finish_")) {
                    return new Answer(i, "bot", path);
                }
            }
        }
        Answer a = fallback(d, null, "wrapper", path + "_pick_not_offered");
        a.detail.putAll(detail);
        return a;
    }

    static boolean matchesPick(Map<String, Object> sem, Object want) {
        String kind = Json.str(sem, "kind");
        if (want instanceof Boolean) {
            return want.equals(sem.get("value")) || want.equals(sem.get("pay")) || want.equals(sem.get("keep"));
        }
        if (want instanceof Number) {
            return sem.get("value") instanceof Number && ((Number) sem.get("value")).longValue() == ((Number) want).longValue();
        }
        switch (kind) {
            case "select_object":
                return PlanBook.sameTarget(Json.obj(sem, "choice"), want);
            case "choose_target":
                return PlanBook.sameTarget(Json.obj(sem, "target"), want);
            case "choose_cost_target":
                return want instanceof Map && Json.str(Json.obj(sem, "candidate"), "object_id")
                        .equals(Json.str(Json.obj(want), "object_id"));
            case "order_pick": {
                Map<String, Object> item = Json.obj(sem, "item");
                Map<String, Object> o = item == null ? null : Json.obj(item, "object");
                return o != null && want instanceof Map && Json.str(o, "object_id").equals(Json.str(Json.obj(want), "object_id"));
            }
            default:
                return false;
        }
    }

    /** Saved-anchor continuation (Section 5.1); null when it does not apply, so the current dialog answers. */
    Answer continuation(Map<String, Object> d, long budget, String source) {
        Map<String, Object> anchor = anchors.get(source);
        Map<String, Object> detail = new LinkedHashMap<>();
        Map<String, Object> req = request("continuation", d, 1, budget);
        req.put("anchor", anchor);
        req.put("earlier", sourceAnswers.getOrDefault(source, new ArrayList<Map<String, Object>>()));
        Map<String, Object> r = budget < graceMs + overheadMs + 200 ? null : call(req, budget, detail);
        if (r == null || Json.arr(r, "worlds").isEmpty()) {
            count("continuation_failed");
            return null;
        }
        Map<String, Object> w = Json.obj(Json.arr(r, "worlds").get(0));
        if (!Json.bool(w, "match") || w.get("picks") == null) {
            count("continuation_mismatch");
            logLine(Json.map("event", "continuation_mismatch", "seat_step", d.get("seat_step"), "diff", w.get("diff")));
            return null;
        }
        Map<String, Object> group = Json.obj(d, "group");
        groupPlan = Json.map("picks", w.get("picks"), "cursor", 0L);
        groupPlanGroupId = group == null ? -1 : Json.num(group, "group_id", -1);
        count("continuation_used");
        Answer a = groupDialog(d, budget, "continuation", groupPlanGroupId);
        a.detail.put("continuation", true);
        a.detail.put("continuation_flags", w.get("flags"));
        return a;
    }

    // ---------------------------------------------------------------------------------------------
    // fallback (Section 6.5)

    Answer rankedFallback(Map<String, Object> d, Aggregate.Result agg, Map<String, Integer> candidateOf, String tag, String why) {
        if (agg != null) {
            for (String k : agg.ranking) {
                Integer c = candidateOf.get(k);
                if (c != null) {
                    Answer a = new Answer(c, tag, "fallback_ranked:" + why);
                    return a;
                }
            }
        }
        return fallback(d, null, tag, why);
    }

    /** (1) ranked, (2) the declining candidate, (3) the lowest candidate id. Always an offered candidate. */
    Answer fallback(Map<String, Object> d, Aggregate.Result agg, String tag, String why) {
        List<Object> cands = Json.arr(d, "candidates");
        for (int i = 0; i < cands.size(); i++) {
            Map<String, Object> sem = Json.obj(Json.obj(cands.get(i)), "semantic");
            String kind = Json.str(sem, "kind");
            boolean declining = kind.equals("pass") || kind.startsWith("finish_")
                    || Boolean.FALSE.equals(sem.get("value")) && kind.equals("choose_boolean")
                    || Boolean.FALSE.equals(sem.get("pay")) || Boolean.FALSE.equals(sem.get("cast_it"))
                    || (kind.equals("declare_attack") && sem.get("defender") == null)
                    || (kind.equals("declare_block") && sem.get("attacker") == null);
            if (declining) {
                return new Answer(i, tag, "fallback_declining:" + why);
            }
        }
        return new Answer(0, tag, "fallback_lowest:" + why);
    }

    // ---------------------------------------------------------------------------------------------
    // anchors and own history

    private void dropStaleAnchors(Map<String, Object> obs) {
        List<String> onStack = new ArrayList<>();
        for (Object o : Json.arr(obs, "stack")) {
            onStack.add(Json.str(Json.obj(o), "object_id"));
        }
        for (String k : new ArrayList<>(anchors.keySet())) {
            Map<String, Object> ad = Json.obj(Json.obj(anchors.get(k), "decision"), "observation");
            if (!onStack.contains(k) || Json.num(ad, "turn", -1) != Json.num(obs, "turn", -2)) {
                anchors.remove(k);
            }
        }
    }

    /**
     * Own history for the first-strike damage step (Section 3.3): XMage has two combat damage steps where v2 has one.
     * The first combat_damage priority decision of a turn with a first or double striker in combat is the
     * first-strike step; a later one in the same turn, after the board changed, is the regular step.
     */
    private void trackCombatDamage(Map<String, Object> obs, boolean priority) {
        long turn = Json.num(obs, "turn", -1);
        if (turn != lastCombatDamageTurn) {
            combatDamageSeen = 0;
        }
        if ("combat_damage".equals(Json.str(obs, "phase_step")) && priority) {
            if (turn != lastCombatDamageTurn) {
                lastCombatDamageTurn = turn;
            }
            String digest = Json.canonical(lifeAndDamage(obs));
            if (!digest.equals(lastDamageDigest)) {
                combatDamageSeen++;
                lastDamageDigest = digest;
            }
        }
    }

    private String lastDamageDigest;

    static List<Object> lifeAndDamage(Map<String, Object> obs) {
        List<Object> out = new ArrayList<>();
        for (Object p : Json.arr(obs, "players")) {
            Map<String, Object> pm = Json.obj(p);
            out.add(pm.get("life"));
            for (Object o : Json.arr(pm, "battlefield")) {
                Map<String, Object> perm = Json.obj(Json.obj(o), "permanent");
                out.add(perm == null ? null : perm.get("damage"));
            }
            out.add((long) Json.arr(pm, "graveyard").size());
        }
        return out;
    }

    String combatDamageStep(Map<String, Object> d) {
        Map<String, Object> obs = Json.obj(d, "observation");
        if (!"combat_damage".equals(Json.str(obs, "phase_step"))) {
            return null;
        }
        return combatDamageSeen <= 1 ? "first" : "regular";
    }

    void logLine(Map<String, Object> m) {
        if (log != null) {
            m.put("game_id", gameId);
            log.println(Json.canonical(m));
        }
    }
}
