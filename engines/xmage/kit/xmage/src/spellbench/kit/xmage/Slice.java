package spellbench.kit.xmage;

import mage.abilities.Ability;
import mage.abilities.ActivatedAbility;
import mage.abilities.effects.OneShotEffect;
import mage.abilities.common.SimpleStaticAbility;
import mage.cards.Card;
import mage.cards.decks.Deck;
import mage.constants.AbilityType;
import mage.constants.Outcome;
import mage.constants.Zone;
import mage.game.Game;
import mage.game.GameOptions;
import mage.game.PutToBattlefieldInfo;
import mage.game.stack.StackAbility;
import mage.player.cabt.CardResolver;
import mage.player.spellbench.Warmup;
import mage.player.spellbench.decide.Exchange;
import mage.player.spellbench.decide.Seats;
import mage.player.spellbench.rng.GameRandom;
import mage.players.Player;
import mage.util.RandomUtil;
import spellbench.kit.core.Aggregate;
import spellbench.kit.core.Front;
import spellbench.kit.core.Json;
import spellbench.kit.core.ObsCompare;
import spellbench.kit.core.ObsIndex;
import spellbench.kit.core.PlanBook;
import spellbench.kit.core.Sampler;
import spellbench.kit.core.Seeds;

import java.io.FileOutputStream;
import java.io.PrintStream;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.function.Predicate;

/**
 * The vertical slice's XMage cases (design Section 9.1): exact fixture transitions S1 to S6 (Section 7.1) on engine
 * positions built in the X engine's own game ({@code decide.Seats}: the engine's players, mapper and observation
 * builder) with XMage's test-harness cheat for the starting zones, against kit worlds built from the received
 * observations with the oracle sample (the true hidden cards, test only); S7 (branch-local knowledge), S9 (H2 root
 * statistics and vote), the flagged-stack sentinel (addendum 4), the runaway position (E2) and behaviour
 * preservation (E7). One JSON line per check on stdout and in the output file, then a verdict.
 *
 *   java -cp kit-xmage.jar;kit-core.jar;engine/lib/* spellbench.kit.xmage.Slice OUT.jsonl [CASE ...]
 *
 * Run in a directory holding its own copy of the card database (./db).
 */
public final class Slice {

    static final Map<String, Object> FLAGS = Json.map("poison", true, "player_counters", false, "designations", false,
            "player_progress", true, "day_night", true, "passed_seats", true, "pending_triggers", true, "keywords", true,
            "full_name", true, "exiled_by", false, "stack_text", false, "permanent_details", false, "known_cards", false);

    static PrintStream out;
    static PrintStream file;
    static final List<Map<String, Object>> results = new ArrayList<>();
    static final CardResolver RESOLVER = new CardResolver();

    private Slice() {
    }

    static void check(String id, boolean pass, Object detail) {
        Map<String, Object> m = Json.map("check", id, "pass", pass, "detail", detail);
        results.add(m);
        String line = Json.canonical(m);
        out.println(line);
        if (file != null) {
            file.println(line);
        }
    }

    static void note(String id, Object detail) {
        Map<String, Object> m = Json.map("note", id, "detail", detail);
        String line = Json.canonical(m);
        out.println(line);
        if (file != null) {
            file.println(line);
        }
    }

    public static void main(String[] args) throws Exception {
        out = new PrintStream(new java.io.FileOutputStream(java.io.FileDescriptor.out), true, "UTF-8");
        System.setOut(System.err);
        Runner.quietLogs();
        file = args.length > 0 ? new PrintStream(new FileOutputStream(args[0], true), true, "UTF-8") : null;
        List<String> cases = args.length > 1 ? Arrays.asList(args).subList(1, args.length)
                : Arrays.asList("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S9", "SENTINEL", "E2", "E7MCTS");
        GameRandom.installBoot();
        int[] warm = Warmup.framework();
        RESOLVER.resolve("Plains");
        note("boot", Json.map("warmup_ok", (long) warm[0], "warmup_failed", (long) warm[1]));
        for (String c : cases) {
            long t0 = System.nanoTime();
            try {
                switch (c) {
                    case "S1": s1(); break;
                    case "S2": s2(); break;
                    case "S3": s3(); break;
                    case "S4": s4(); break;
                    case "S5": s5(); break;
                    case "S6": s6(); break;
                    case "S7": s7(); break;
                    case "S9": s9(); break;
                    case "SENTINEL": sentinel(); break;
                    case "E2": e2(); break;
                    case "E7MCTS": e7mcts(); break;
                    case "E7MAD": e7mad(); break;
                    case "DZ": dzPositions(); break;
                    case "DFC": dfcBattlefield(); break;
                    case "EMBALM": embalmToken(); break;
                    case "H3COST": h3cost(); break;
                    case "S2P": SliceProd.s2p(); break;
                    case "S3P": SliceProd.s3p(); break;
                    case "S4P": SliceProd.s4p(); break;
                    case "S10P": SliceProd.s10p(); break;
                    case "A3": SliceProd.a3(); break;
                    case "MCTSPOWER": SliceProd.mctsPowered(); break;
                    case "REG": SliceProd.reg(); break;
                    case "POOLAUDIT": SliceProd.poolAudit(); break;
                    case "UNMAPPED": SliceProd.unmapped(); break;
                    case "OPPTURN": SliceProd.oppTurn(); break;
                    case "PLAYABLE": SliceProd.playable(); break;
                    case "OFFERED": SliceProd.offered(); break;
                    default: note("unknown_case", c);
                }
            } catch (Throwable t) {
                t.printStackTrace(System.err);
                check(c + ".completed", false, t.toString());
            }
            note(c + ".integration_ms", (System.nanoTime() - t0) / 1_000_000);
        }
        boolean all = true;
        for (Map<String, Object> r : results) {
            all &= Boolean.TRUE.equals(r.get("pass"));
        }
        Map<String, Object> v = Json.map("verdict", all ? "PASS" : "FAIL", "checks", (long) results.size(),
                "failed", failedIds());
        out.println(Json.canonical(v));
        if (file != null) {
            file.println(Json.canonical(v));
        }
        System.exit(0);
    }

    static List<Object> failedIds() {
        List<Object> f = new ArrayList<>();
        for (Map<String, Object> r : results) {
            if (!Boolean.TRUE.equals(r.get("pass"))) {
                f.add(r.get("check"));
            }
        }
        return f;
    }

    // =============================================================================================
    // engine positions: the X engine's own game, zones placed by XMage's test-harness cheat

    static final class SeatSetup {
        List<String> library = new ArrayList<>();      // top first
        List<String> hand = new ArrayList<>();
        List<String> battlefield = new ArrayList<>();
        List<String> graveyard = new ArrayList<>();

        SeatSetup lib(String name, int n) {
            for (int i = 0; i < n; i++) {
                library.add(name);
            }
            return this;
        }

        List<String> all() {
            List<String> a = new ArrayList<>(library);
            a.addAll(hand);
            a.addAll(battlefield);
            a.addAll(graveyard);
            return a;
        }
    }

    static final class EnginePos {
        byte[] secret;
        GameRandom router;
        Seats seats;
        Game game;
        Exchange.Outcome cur;
        final List<Map<String, Object>> trail = new ArrayList<>();

        static EnginePos start(String label, SeatSetup s0, SeatSetup s1) {
            return start(label, s0, s1, true);
        }

        /** Keep the controlled opening zones and pose the engine's actual mulligan callbacks. */
        static EnginePos startMulligan(String label, SeatSetup s0, SeatSetup s1) {
            return start(label, s0, s1, false);
        }

        private static EnginePos start(String label, SeatSetup s0, SeatSetup s1, boolean mulliganNone) {
            return start(label, s0, s1, mulliganNone, false);
        }

        static EnginePos startPriorityMana(String label, SeatSetup s0, SeatSetup s1) {
            return start(label, s0, s1, true, true);
        }

        private static EnginePos start(String label, SeatSetup s0, SeatSetup s1, boolean mulliganNone,
                                       boolean priorityMana) {
            EnginePos e = new EnginePos();
            e.secret = Seeds.hmac("spellbench-kit-slice".getBytes(), label);
            GameRandom.installBoot();
            for (SeatSetup s : new SeatSetup[]{s0, s1}) {
                for (String n : s.all()) {
                    RESOLVER.resolve(n).createCard(UUID.nameUUIDFromBytes(new byte[]{9}));
                }
            }
            e.router = GameRandom.install(e.secret);
            e.seats = Seats.create();
            e.game = e.seats.game;
            SeatSetup[] setups = {s0, s1};
            for (int k = 0; k < 2; k++) {
                Player p = e.seats.player(k);
                List<Card> lib = new ArrayList<>();
                for (String n : setups[k].library) {
                    lib.add(RESOLVER.resolve(n).createCard(p.getId()));
                }
                Deck deck = new Deck();
                deck.getCards().addAll(lib);
                e.game.loadCards(new LinkedHashSet<>(lib), p.getId());
                e.game.addPlayer(p, deck);
            }
            GameOptions o = new GameOptions();
            o.testMode = true;
            o.skipInitShuffling = true;
            e.game.setGameOptions(o);
            e.router.assignSeat(e.seats.player(0).getId(), "p0");
            e.router.assignSeat(e.seats.player(1).getId(), "p1");
            e.game.setStartingPlayerId(e.seats.player(0).getId());
            Set<String> names = new LinkedHashSet<>(s0.all());
            names.addAll(s1.all());
            List<String> domain = new ArrayList<>(names);
            Collections.sort(domain);
            e.seats.connect(e.secret, FLAGS, 10000, 10000, domain, mulliganNone, priorityMana);
            for (int k = 0; k < 2; k++) {
                Player p = e.seats.player(k);
                List<Card> hand = new ArrayList<>();
                for (String n : setups[k].hand) {
                    hand.add(RESOLVER.resolve(n).createCard(p.getId()));
                }
                List<PutToBattlefieldInfo> bf = new ArrayList<>();
                for (String n : setups[k].battlefield) {
                    bf.add(new PutToBattlefieldInfo(RESOLVER.resolve(n).createCard(p.getId()), false));
                }
                List<Card> gy = new ArrayList<>();
                for (String n : setups[k].graveyard) {
                    gy.add(RESOLVER.resolve(n).createCard(p.getId()));
                }
                e.game.cheat(p.getId(), new ArrayList<Card>(), hand, bf, gy, new ArrayList<Card>(), new ArrayList<Card>());
            }
            final Game g = e.game;
            final UUID first = e.seats.player(0).getId();
            e.cur = e.seats.exchange.start(() -> g.start(first));
            return e;
        }

        Map<String, Object> decision() {
            return cur.seatDecision;
        }

        String acting() {
            return cur.seatDecision == null ? null : Json.str(cur.seatDecision, "acting_seat");
        }

        boolean over() {
            return cur.seatDecision == null;
        }

        void answer(int c) {
            trail.add(Json.map("seat", acting(), "seat_step", decision().get("seat_step"), "kind", Front_firstKind(decision()),
                    "candidate", (long) c));
            RandomUtil.setSource(router);
            cur = seats.exchange.answer(c);
        }

        /** Answers 0 (pass, or the first candidate) until {@code stop} holds for the pending decision. */
        boolean advance(Predicate<Map<String, Object>> stop, int max) {
            for (int i = 0; i < max && !over(); i++) {
                if (stop.test(decision())) {
                    return true;
                }
                answer(0);
            }
            return !over() && stop.test(decision());
        }

        Player player(String seat) {
            return seats.player("p0".equals(seat) ? 0 : 1);
        }
    }

    static String Front_firstKind(Map<String, Object> d) {
        for (Object o : Json.arr(d, "candidates")) {
            String k = Json.str(Json.obj(Json.obj(o), "semantic"), "kind");
            if (!k.equals("pass") && !k.startsWith("finish_")) {
                return k;
            }
        }
        return Json.str(Json.obj(Json.obj(Json.arr(d, "candidates").get(0)), "semantic"), "kind");
    }

    static boolean priorityOf(Map<String, Object> d, String seat, String step) {
        Map<String, Object> ctx = Json.obj(d, "context");
        return seat.equals(Json.str(d, "acting_seat")) && "priority".equals(Json.str(ctx, "kind"))
                && (step == null || step.equals(Json.str(Json.obj(d, "observation"), "phase_step")));
    }

    static Map<String, Object> gameStart(String viewer, SeatSetup s0, SeatSetup s1) {
        SeatSetup own = "p0".equals(viewer) ? s0 : s1;
        SeatSetup opp = "p0".equals(viewer) ? s1 : s0;
        Set<String> names = new LinkedHashSet<>(s0.all());
        names.addAll(s1.all());
        List<String> domain = new ArrayList<>(names);
        Collections.sort(domain);
        return Json.map("seat", viewer, "own_deck", deckJson(own), "opponent_deck", deckJson(opp),
                "rules", Json.map("opponent_decklist", "visible", "starting_seat", "p0",
                        "card_name_domain", Json.map("names", new ArrayList<Object>(domain))),
                "engine_profile", Json.map("observation", FLAGS));
    }

    static Map<String, Object> deckJson(SeatSetup s) {
        Map<String, Long> counts = new java.util.TreeMap<>();
        for (String n : s.all()) {
            counts.merge(n, 1L, Long::sum);
        }
        List<Object> rows = new ArrayList<>();
        for (Map.Entry<String, Long> e : counts.entrySet()) {
            rows.add(Json.map("name", e.getKey(), "count", e.getValue()));
        }
        return Json.map("name", "fixture", "decklist", rows);
    }

    /** The oracle sample (Section 7.1, test only): the engine's true hidden cards in their true order. */
    static Sampler.Sample oracle(EnginePos e, Map<String, Object> obs) {
        String viewer = Json.str(obs, "viewer");
        Sampler.Sample s = new Sampler.Sample();
        List<Map<String, Object>> known = new ArrayList<>();
        for (Object o : Json.arr(obs, "known")) {
            known.add(Json.obj(o));
        }
        for (String seat : new String[]{"p0", "p1"}) {
            Sampler.SeatSample ss = new Sampler.SeatSample(seat);
            Player p = e.player(seat);
            for (Card c : p.getLibrary().getCards(e.game)) {
                ss.library.add(new Sampler.Slot(c.getName(), claimKnown(known, seat, "library", c.getName()), false));
            }
            if (!seat.equals(viewer)) {
                for (Card c : p.getHand().getCards(e.game)) {
                    ss.hand.add(new Sampler.Slot(c.getName(), claimKnown(known, seat, "hand", c.getName()), false));
                }
            }
            s.seats.put(seat, ss);
        }
        s.flags.add("oracle_sample");
        return s;
    }

    static String claimKnown(List<Map<String, Object>> known, String seat, String zone, String name) {
        for (Map<String, Object> k : known) {
            if (seat.equals(k.get("owner_seat")) && zone.equals(k.get("zone")) && name.equals(k.get("card_name"))
                    && k.get("object_id") != null && !Boolean.TRUE.equals(k.get("_used"))) {
                k.put("_used", true);
                return (String) k.get("object_id");
            }
        }
        return null;
    }

    static final byte[] GAME_KEY = Seeds.gameKey(424242L);
    static final byte[] ID_SEED = Seeds.hmac(GAME_KEY, "ids");

    static World world(Map<String, Object> gs, Map<String, Object> d, Sampler.Sample sample, WorldBuilder.Mode mode,
                       int k, final KitMad[] decider, String combatDamage) {
        KitContext.reset();
        KitRandom random = KitRandom.install(Seeds.worldSeed(GAME_KEY, Json.num(d, "seat_step", 0), k), ID_SEED);
        Map<String, Object> obs = Json.obj(d, "observation");
        WorldBuilder.Spec spec = new WorldBuilder.Spec();
        spec.gameStart = gs;
        spec.observation = obs;
        spec.sample = sample == null ? Sampler.sample(gs, obs, random.stream("sampler")) : sample;
        spec.random = random;
        spec.mode = mode;
        spec.index = k;
        spec.combatDamageStep = combatDamage;
        spec.viewerFactory = seat -> {
            decider[0] = new KitMad(seat, 6);
            return decider[0];
        };
        spec.otherFactory = Puppet::new;
        World w = WorldBuilder.build(spec);
        decider[0].attach(w);
        return w;
    }

    static Map<String, Object> project(World w, String prioritySeat, List<Object> known) {
        try {
            return RoundTrip.project(w, FLAGS, prioritySeat, known);
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }

    /** The world's playable action whose v2 semantic is the candidate's (the kit's mapping, inverted). */
    static Ability findPlayable(World w, Player p, Map<String, Object> semantic, ObsIndex idx) {
        String want = Json.canonical(semantic);
        for (ActivatedAbility a : p.getPlayable(w.game, true)) {
            if (a.getAbilityType() == AbilityType.ACTIVATED_MANA) {
                continue;
            }
            Map<String, Object> s = Mapping.prioritySemantic(w, w.game, a, idx);
            if (s != null && want.equals(Json.canonical(s))) {
                return a;
            }
        }
        return null;
    }

    static int candidateOf(Map<String, Object> d, Map<String, Object> semantic) {
        String want = Json.canonical(semantic);
        List<Object> cands = Json.arr(d, "candidates");
        for (int i = 0; i < cands.size(); i++) {
            if (want.equals(Json.canonical(Json.obj(Json.obj(cands.get(i)), "semantic")))) {
                return i;
            }
        }
        return -1;
    }

    static int candidateWhere(Map<String, Object> d, String kind, String sourceName) {
        List<Object> cands = Json.arr(d, "candidates");
        for (int i = 0; i < cands.size(); i++) {
            Map<String, Object> sem = Json.obj(Json.obj(cands.get(i)), "semantic");
            Map<String, Object> src = Json.obj(sem, "source");
            if (kind.equals(Json.str(sem, "kind")) && src != null && sourceName.equals(Json.str(src, "card_name"))) {
                return i;
            }
        }
        return -1;
    }

    /** Answers the viewer's decisions of the current action from the plan (forced steps through the plan too). */
    static void followPlan(EnginePos e, PlanBook plans, String viewer, List<Object> trace) {
        while (!e.over() && !priorityOf(e.decision(), viewer, null)) {
            Map<String, Object> d = e.decision();
            int c;
            if (viewer.equals(e.acting())) {
                if (Json.arr(d, "candidates").size() == 1) {
                    plans.forced(d);
                    c = 0;
                } else {
                    c = plans.claim(d);
                    if (c < 0) {
                        trace.add(Json.map("unplanned", Front_firstKind(d)));
                        c = 0;
                    }
                }
                trace.add(Json.map("seat_step", d.get("seat_step"), "kind", Front_firstKind(d), "candidate", (long) c));
            } else {
                c = 0;
            }
            e.answer(c);
        }
    }

    static Map<String, Object> obsOf(Map<String, Object> d) {
        return Json.obj(d, "observation");
    }

    static Map<String, Object> playerObs(Map<String, Object> obs, String seat) {
        for (Object o : Json.arr(obs, "players")) {
            if (seat.equals(Json.str(Json.obj(o), "seat"))) {
                return Json.obj(o);
            }
        }
        return null;
    }

    static List<String> names(Map<String, Object> obs, String seat, String zone) {
        List<String> out = new ArrayList<>();
        for (Object o : Json.arr(playerObs(obs, seat), zone)) {
            out.add(Json.str(Json.obj(o), "card_name"));
        }
        return out;
    }

    static List<String> stackNames(Map<String, Object> obs) {
        List<String> out = new ArrayList<>();
        for (Object o : Json.arr(obs, "stack")) {
            out.add(Json.str(Json.obj(o), "stack_kind") + ":" + Json.str(Json.obj(o), "card_name"));
        }
        return out;
    }

    /** Compares the engine's observation with the world's projection modulo ids; one check. */
    static boolean transition(String id, Map<String, Object> oe, Map<String, Object> ow, Map<String, Object> extra) {
        List<String> diff = ObsCompare.diff(oe, ow, 30);
        Map<String, Object> detail = Json.map("diff", diff, "engine_stack", stackNames(oe), "world_stack", stackNames(ow));
        if (extra != null) {
            detail.putAll(extra);
        }
        check(id, diff.isEmpty(), detail);
        return diff.isEmpty();
    }

    // =============================================================================================
    // S1: a targeted cast with targets preselected by MAD (Stab)

    static void s1() {
        SeatSetup a = new SeatSetup().lib("Swamp", 8);
        a.hand.addAll(Arrays.asList("Stab", "Cathar Commando"));
        a.battlefield.addAll(Arrays.asList("Swamp", "Swamp"));
        SeatSetup b = new SeatSetup().lib("Island", 8);
        b.hand.addAll(Arrays.asList("Island", "Island"));
        b.battlefield.addAll(Arrays.asList("Island", "Grizzly Bears"));
        EnginePos e = EnginePos.start("S1", a, b);
        if (!e.advance(d -> priorityOf(d, "p0", "precombat_main"), 50)) {
            check("S1.reach_position", false, e.trail);
            return;
        }
        Map<String, Object> d0 = e.decision();
        Map<String, Object> gs = gameStart("p0", a, b);
        KitMad[] dec = new KitMad[1];
        World w = world(gs, d0, oracle(e, obsOf(d0)), WorldBuilder.Mode.PRIORITY, 0, dec, null);
        check("S1.rebuild_roundtrip", ObsCompare.diff(obsOf(d0), project(w, "p0", Json.arr(obsOf(d0), "known")), 30).isEmpty(),
                ObsCompare.diff(obsOf(d0), project(w, "p0", Json.arr(obsOf(d0), "known")), 30));
        ObsIndex idx = new ObsIndex(obsOf(d0));
        KitMad.PriorityOutcome o = dec[0].decidePriority(w, idx, true);
        int c = o.semantic == null ? -1 : candidateOf(d0, o.semantic);
        boolean stab = o.semantic != null && "cast_spell".equals(o.semantic.get("kind"))
                && "Stab".equals(Json.str(Json.obj(o.semantic, "source"), "card_name"));
        List<Object> payloadTargets = Json.arr(o.executedPayload, "targets");
        check("S1.mad_preselects_stab_target", stab && c >= 0 && o.activated && !payloadTargets.isEmpty()
                        && !Json.arr(payloadTargets.get(0)).isEmpty(),
                Json.map("semantic", o.semantic, "candidate", (long) c, "executed_payload", o.executedPayload,
                        "option_payload", o.optionPayload, "root_stats", (long) o.stats.size()));
        if (c < 0) {
            return;
        }
        PlanBook plans = new PlanBook();
        plans.open(Json.num(d0, "seat_step", 0), o.semantic, obsOf(d0), o.executedPayload, toAnswers(o.answers));
        e.answer(c);
        List<Object> trace = new ArrayList<>();
        followPlan(e, plans, "p0", trace);
        Map<String, Object> d1 = e.decision();
        Map<String, Object> oe1 = obsOf(d1);
        Map<String, Object> ow1 = project(w, "p0", new ArrayList<>());
        transition("S1.E1.cast_transition", oe1, ow1, Json.map("plan_trace", trace, "binding",
                plans.active == null ? null : plans.active.bindingOutcome, "plan_counters", plans.counters));
        // the stack source rebinding with a live source: the plan bound the spell's stack entry
        check("S1.rebinding_live_source", plans.counters.containsKey("rebind_bound"), plans.counters);
        // hand-written: Stab on the stack targets Grizzly Bears; one Swamp tapped
        Map<String, Object> top = Json.obj(Json.arr(oe1, "stack").get(Json.arr(oe1, "stack").size() - 1));
        Map<String, Object> tgt = Json.obj(Json.obj(Json.arr(top, "targets").get(0)), "object");
        check("S1.assert.stab_targets_bears", "Stab".equals(top.get("card_name")) && "Grizzly Bears".equals(tgt.get("card_name")),
                Json.map("top", top.get("card_name"), "target", tgt.get("card_name")));
        // resolution: both pass, Stab resolves, the Bears die
        e.answer(0); // p0 passes
        e.advance(d -> priorityOf(d, "p0", null) && Json.arr(obsOf(d), "stack").isEmpty(), 10);
        Map<String, Object> oe2 = obsOf(e.decision());
        Resolver.resolveTop(w);
        Map<String, Object> ow2 = project(w, "p0", new ArrayList<>());
        transition("S1.E1.resolution_transition", oe2, ow2, null);
        check("S1.assert.bears_died", names(oe2, "p1", "graveyard").contains("Grizzly Bears")
                        && names(oe2, "p0", "graveyard").contains("Stab"),
                Json.map("p1_graveyard", names(oe2, "p1", "graveyard"), "p0_graveyard", names(oe2, "p0", "graveyard")));
    }

    static List<Map<String, Object>> toAnswers(List<KitMad.Answer> answers) {
        List<Map<String, Object>> out = new ArrayList<>();
        for (KitMad.Answer a : answers) {
            out.add(Json.map("family", a.family, "value", a.value));
        }
        return out;
    }

    // =============================================================================================
    // S2: Burnished Hart: sacrificed as a cost, stack entry with source null, library search, shuffle

    static void s2() {
        SeatSetup a = new SeatSetup();
        a.library.addAll(Arrays.asList("Mountain", "Forest", "Plains", "Mountain", "Island", "Mountain", "Swamp", "Mountain"));
        a.hand.add("Mountain");
        a.battlefield.addAll(Arrays.asList("Burnished Hart", "Mountain", "Mountain", "Mountain"));
        SeatSetup b = new SeatSetup().lib("Island", 8);
        b.hand.add("Island");
        b.battlefield.add("Island");
        EnginePos e = EnginePos.start("S2", a, b);
        if (!e.advance(d -> priorityOf(d, "p0", "precombat_main"), 50)) {
            check("S2.reach_position", false, e.trail);
            return;
        }
        Map<String, Object> d0 = e.decision();
        Map<String, Object> gs = gameStart("p0", a, b);
        int c = candidateWhere(d0, "activate_ability", "Burnished Hart");
        Map<String, Object> sem = Json.obj(Json.obj(Json.arr(d0, "candidates").get(c)), "semantic");
        KitMad[] dec = new KitMad[1];
        World w = world(gs, d0, oracle(e, obsOf(d0)), WorldBuilder.Mode.PRIORITY, 0, dec, null);
        ObsIndex idx = new ObsIndex(obsOf(d0));
        Ability hart = findPlayable(w, w.viewerPlayer(), sem, idx);
        check("S2.mapping_inverts_candidate", hart != null, sem);
        if (hart == null) {
            return;
        }
        KitMad.PriorityOutcome o = new KitMad.PriorityOutcome();
        dec[0].execute(w, hart, o);
        PlanBook plans = new PlanBook();
        plans.open(Json.num(d0, "seat_step", 0), sem, obsOf(d0), o.executedPayload, toAnswers(o.answers));
        e.answer(c);
        List<Object> trace = new ArrayList<>();
        followPlan(e, plans, "p0", trace);
        Map<String, Object> d1 = e.decision();
        Map<String, Object> oe1 = obsOf(d1);
        // departed-source rebinding (N3): at the first decision after the pick
        PlanBook pb = new PlanBook();
        pb.open(Json.num(d0, "seat_step", 0), sem, obsOf(d0), o.executedPayload, null);
        pb.claim(Json.map("context", Json.map("kind", "choice"), "observation", oe1, "candidates", new ArrayList<>()));
        Map<String, Object> entry = Json.obj(Json.arr(oe1, "stack").get(0));
        check("S2.rebinding_departed_source", "rebind_bound".equals(firstKey(pb.counters, "rebind_"))
                        && entry.get("source") == null && "activated_ability".equals(entry.get("stack_kind")),
                Json.map("counters", pb.counters, "entry_source", entry.get("source"), "entry_name", entry.get("card_name")));
        Map<String, Object> ow1 = project(w, "p0", new ArrayList<>());
        transition("S2.E1.activation_transition", oe1, ow1, Json.map("trace", trace));
        // resolution: both pass; the search dialog is answered by the saved-anchor continuation (finish mode)
        Map<String, Object> anchor = Json.map("decision", d1, "world_seeds",
                Arrays.asList(Seeds.hex(Seeds.worldSeed(GAME_KEY, Json.num(d1, "seat_step", 0), 0))), "seat_step", d1.get("seat_step"));
        e.answer(0);
        e.advance(d -> "p0".equals(Json.str(d, "acting_seat")) && !"priority".equals(Json.str(Json.obj(d, "context"), "kind")), 10);
        Map<String, Object> dd = e.decision();
        List<Object> known = Json.arr(obsOf(dd), "known");
        boolean searching = !known.isEmpty();
        for (Object k : known) {
            searching &= "searching".equals(Json.str(Json.obj(k), "how")) && Json.obj(k).get("object_id") != null;
        }
        check("S2.searching_entries_present", searching && "select_object".equals(Front_firstKind(dd)),
                Json.map("kind", Front_firstKind(dd), "known", (long) known.size()));
        Map<String, Object> cont = Continuation.run(gameStartWithOracle(gs), ID_SEED, anchor, new ArrayList<>(), dd, 6, true);
        check("S2.continuation_matches_dialog", Boolean.TRUE.equals(cont.get("match")),
                Json.map("diff", cont.get("diff"), "picks", cont.get("picks"), "flags", cont.get("flags")));
        // the searched cards are addressable: every pick names an offered candidate
        List<Object> picks = Json.arr(cont, "picks");
        int answered = 0;
        boolean addressable = true;
        while (!e.over() && "p0".equals(e.acting()) && !"priority".equals(Json.str(Json.obj(e.decision(), "context"), "kind"))) {
            Map<String, Object> d = e.decision();
            int pick = -1;
            if (answered < picks.size()) {
                for (int i = 0; i < Json.arr(d, "candidates").size(); i++) {
                    Map<String, Object> s = Json.obj(Json.obj(Json.arr(d, "candidates").get(i)), "semantic");
                    if ("select_object".equals(s.get("kind")) && PlanBookAccess.sameTarget(Json.obj(s, "choice"), picks.get(answered))) {
                        pick = i;
                    }
                }
                addressable &= pick >= 0;
            }
            if (pick < 0) {
                for (int i = 0; i < Json.arr(d, "candidates").size(); i++) {
                    if (Json.str(Json.obj(Json.obj(Json.arr(d, "candidates").get(i)), "semantic"), "kind").startsWith("finish_")) {
                        pick = i;
                    }
                }
            }
            e.answer(Math.max(0, pick));
            answered++;
        }
        check("S2.searched_cards_addressable", addressable && !picks.isEmpty(), Json.map("picks", picks));
        e.advance(d -> priorityOf(d, "p0", null) && Json.arr(obsOf(d), "stack").isEmpty(), 10);
        Map<String, Object> oe2 = obsOf(e.decision());
        @SuppressWarnings("unchecked")
        Map<String, Object> ow2 = (Map<String, Object>) cont.get("after");
        if (ow2 != null) {
            transition("S2.E1.resolution_transition", oe2, ow2, null);
        } else {
            check("S2.E1.resolution_transition", false, "no world observation after the resolution");
        }
        long tappedLands = 0;
        for (Object o2 : Json.arr(playerObs(oe2, "p0"), "battlefield")) {
            Map<String, Object> r = Json.obj(o2);
            if (Json.bool(Json.obj(r, "permanent"), "tapped") && !"Mountain".equals(r.get("card_name"))) {
                tappedLands++;
            }
        }
        check("S2.assert.hart_sacrificed_lands_tapped", names(oe2, "p0", "graveyard").contains("Burnished Hart") && tappedLands == 2,
                Json.map("graveyard", names(oe2, "p0", "graveyard"), "new_tapped_lands", tappedLands,
                        "library_count", playerObs(oe2, "p0").get("library_count")));
        // knowledge cleared by the shuffle (5.3): a watcher in a world copy loses its library pins on LIBRARY_SHUFFLED
        KitMad[] dec2 = new KitMad[1];
        World w2 = world(gs, d0, oracle(e, obsOf(d0)), WorldBuilder.Mode.PRIORITY, 1, dec2, null);
        KnowledgeWatcher kw = KnowledgeWatcher.install(w2.game, w2.player("p0"));
        Player p0 = w2.viewerPlayer();
        kw.pinLibrary(p0.getId(), p0.getLibrary().getFromTop(w2.game).getId());
        int before = kw.libKnown(p0.getId()).size();
        p0.shuffleLibrary(null, w2.game);
        check("S2.knowledge_cleared_by_shuffle", before == 1 && KnowledgeWatcher.get(w2.game).libKnown(p0.getId()).isEmpty(),
                Json.map("pins_before", (long) before, "pins_after", (long) KnowledgeWatcher.get(w2.game).libKnown(p0.getId()).size()));
    }

    static String firstKey(Map<String, Long> m, String prefix) {
        for (String k : m.keySet()) {
            if (k.startsWith(prefix)) {
                return k;
            }
        }
        return null;
    }

    static Map<String, Object> gameStartWithOracle(Map<String, Object> gs) {
        return gs;
    }

    /** PlanBook's target comparison (package-private there). */
    static final class PlanBookAccess {
        static boolean sameTarget(Map<String, Object> target, Object want) {
            if (target == null || !(want instanceof Map)) {
                return false;
            }
            Map<String, Object> w = Json.obj(want);
            if (target.get("player") != null) {
                return target.get("player").equals(w.get("player"));
            }
            Map<String, Object> o = Json.obj(target, "object");
            return o != null && w.get("object_id") != null && w.get("object_id").equals(o.get("object_id"));
        }
    }

    // =============================================================================================
    // S3: Strix Lookout's draw-then-discard through the saved-anchor continuation

    static void s3() {
        SeatSetup a = new SeatSetup();
        a.library.addAll(Arrays.asList("Llanowar Elves", "Island", "Island", "Island", "Island", "Island"));
        a.hand.addAll(Arrays.asList("Island", "Plains"));
        a.battlefield.addAll(Arrays.asList("Strix Lookout", "Island", "Island"));
        SeatSetup b = new SeatSetup().lib("Mountain", 8);
        b.hand.add("Mountain");
        b.battlefield.add("Mountain");
        EnginePos e = EnginePos.start("S3", a, b);
        if (!e.advance(d -> priorityOf(d, "p0", "precombat_main"), 50)) {
            check("S3.reach_position", false, e.trail);
            return;
        }
        Map<String, Object> d0 = e.decision();
        Map<String, Object> gs = gameStart("p0", a, b);
        int c = candidateWhere(d0, "activate_ability", "Strix Lookout");
        Map<String, Object> sem = Json.obj(Json.obj(Json.arr(d0, "candidates").get(c)), "semantic");
        KitMad[] dec = new KitMad[1];
        World w = world(gs, d0, oracle(e, obsOf(d0)), WorldBuilder.Mode.PRIORITY, 0, dec, null);
        Ability strix = findPlayable(w, w.viewerPlayer(), sem, new ObsIndex(obsOf(d0)));
        if (strix == null) {
            check("S3.mapping_inverts_candidate", false, sem);
            return;
        }
        KitMad.PriorityOutcome o = new KitMad.PriorityOutcome();
        dec[0].execute(w, strix, o);
        PlanBook plans = new PlanBook();
        plans.open(Json.num(d0, "seat_step", 0), sem, obsOf(d0), o.executedPayload, toAnswers(o.answers));
        e.answer(c);
        List<Object> trace = new ArrayList<>();
        followPlan(e, plans, "p0", trace);
        Map<String, Object> d1 = e.decision();
        transition("S3.E1.activation_transition", obsOf(d1), project(w, "p0", new ArrayList<>()), Json.map("trace", trace));
        Map<String, Object> anchor = Json.map("decision", d1, "world_seeds",
                Arrays.asList(Seeds.hex(Seeds.worldSeed(GAME_KEY, Json.num(d1, "seat_step", 0), 0))), "seat_step", d1.get("seat_step"));
        e.answer(0);
        e.advance(d -> "p0".equals(Json.str(d, "acting_seat")) && !"priority".equals(Json.str(Json.obj(d, "context"), "kind")), 10);
        Map<String, Object> dd = e.decision();
        Map<String, Object> cont = Continuation.run(gs, ID_SEED, anchor, new ArrayList<>(), dd, 6, true);
        long handAnchor = Json.num(playerObs(obsOf(d1), "p0"), "hand_count", -1);
        check("S3.continuation_matches_dialog", Boolean.TRUE.equals(cont.get("match")),
                Json.map("diff", cont.get("diff"), "conditioned_drawn", cont.get("conditioned_drawn"), "picks", cont.get("picks")));
        // no effect repeated: one card drawn between the anchor and the dialog, in the world and in the engine
        check("S3.no_effect_repeated", Json.num(cont, "hand_at_dialog", -1) == Json.num(cont, "hand_before", -2) + 1
                        && Json.num(cont, "library_at_dialog", -1) == Json.num(cont, "library_before", -2) - 1
                        && Json.num(playerObs(obsOf(dd), "p0"), "hand_count", -1) == handAnchor + 1,
                Json.map("world_hand", Json.arr(Arrays.asList(cont.get("hand_before"), cont.get("hand_at_dialog"))),
                        "world_library", Json.arr(Arrays.asList(cont.get("library_before"), cont.get("library_at_dialog"))),
                        "engine_hand", Json.arr(Arrays.asList(handAnchor, playerObs(obsOf(dd), "p0").get("hand_count")))));
        List<Object> picks = Json.arr(cont, "picks");
        int pick = 0;
        for (int i = 0; i < Json.arr(dd, "candidates").size(); i++) {
            Map<String, Object> s = Json.obj(Json.obj(Json.arr(dd, "candidates").get(i)), "semantic");
            if (!picks.isEmpty() && PlanBookAccess.sameTarget(Json.obj(s, "choice"), picks.get(0))) {
                pick = i;
            }
        }
        e.answer(pick);
        e.advance(d -> priorityOf(d, "p0", null) && Json.arr(obsOf(d), "stack").isEmpty(), 10);
        @SuppressWarnings("unchecked")
        Map<String, Object> ow2 = (Map<String, Object>) cont.get("after");
        if (ow2 != null) {
            transition("S3.E1.resolution_transition", obsOf(e.decision()), ow2, null);
        } else {
            check("S3.E1.resolution_transition", false, "no world observation after the resolution");
        }
        Map<String, Object> oe2 = obsOf(e.decision());
        check("S3.assert.hand_unchanged_graveyard_plus_one", Json.num(playerObs(oe2, "p0"), "hand_count", -1) == handAnchor
                        && names(oe2, "p0", "graveyard").size() == 1,
                Json.map("hand", playerObs(oe2, "p0").get("hand_count"), "graveyard", names(oe2, "p0", "graveyard")));
    }

    // =============================================================================================
    // S4: Charming Prince's ETB trigger, mode scry 2; both cards kept on top, and a top/bottom split

    static void s4() {
        for (String variant : new String[]{"both_top", "split"}) {
            s4variant(variant);
        }
    }

    static void s4variant(String variant) {
        SeatSetup a = new SeatSetup();
        a.library.addAll(Arrays.asList("Llanowar Elves", "Forest", "Plains", "Plains", "Plains", "Plains"));
        a.hand.addAll(Arrays.asList("Charming Prince"));
        a.battlefield.addAll(Arrays.asList("Plains", "Plains"));
        SeatSetup b = new SeatSetup().lib("Mountain", 8);
        b.battlefield.add("Mountain");
        EnginePos e = EnginePos.start("S4" + variant, a, b);
        if (!e.advance(d -> priorityOf(d, "p0", "precombat_main"), 50)) {
            check("S4." + variant + ".reach_position", false, e.trail);
            return;
        }
        Map<String, Object> d0 = e.decision();
        Map<String, Object> gs = gameStart("p0", a, b);
        int c = candidateWhere(d0, "cast_spell", "Charming Prince");
        e.answer(c);
        e.advance(d -> priorityOf(d, "p0", null), 10);
        e.answer(0); // p0 passes with the Prince on the stack
        // the ETB trigger's mode: the kit's current dialog (the bot's ComputerPlayer.chooseMode)
        e.advance(d -> "p0".equals(Json.str(d, "acting_seat")) && !"priority".equals(Json.str(Json.obj(d, "context"), "kind")), 10);
        Map<String, Object> dm = e.decision();
        KitMad[] dec = new KitMad[1];
        World wm = world(gs, dm, oracle(e, obsOf(dm)), WorldBuilder.Mode.SNAPSHOT, 0, dec, null);
        List<Object> modePick = Dialogs.answer(wm, dec[0], dm, new ObsIndex(obsOf(dm)));
        int mc = -1;
        for (int i = 0; i < Json.arr(dm, "candidates").size(); i++) {
            Map<String, Object> s = Json.obj(Json.obj(Json.arr(dm, "candidates").get(i)), "semantic");
            if (modePick != null && !modePick.isEmpty() && "choose_spell_mode".equals(s.get("kind"))
                    && Json.num(s, "mode_index", -1) == ((Number) modePick.get(0)).longValue()) {
                mc = i;
            }
        }
        check("S4." + variant + ".mode_by_current_dialog", mc >= 0 && Json.num(Json.obj(Json.obj(Json.arr(dm, "candidates").get(mc)),
                "semantic"), "mode_index", -1) == 0, Json.map("kind", Front_firstKind(dm), "picks", modePick));
        e.answer(Math.max(0, mc));
        e.advance(d -> priorityOf(d, "p0", null), 10);
        Map<String, Object> d2 = e.decision();
        Map<String, Object> anchor = Json.map("decision", d2, "world_seeds",
                Arrays.asList(Seeds.hex(Seeds.worldSeed(GAME_KEY, Json.num(d2, "seat_step", 0), 0))), "seat_step", d2.get("seat_step"));
        e.answer(0);
        e.advance(d -> "p0".equals(Json.str(d, "acting_seat")) && !"priority".equals(Json.str(Json.obj(d, "context"), "kind")), 10);
        Map<String, Object> ds = e.decision();
        Map<String, Object> cont = Continuation.run(gs, ID_SEED, anchor, new ArrayList<>(), ds, 6, false);
        check("S4." + variant + ".continuation_matches_scry", Boolean.TRUE.equals(cont.get("match")),
                Json.map("diff", cont.get("diff"), "kind", Front_firstKind(ds)));
        // the arrangement: the variant's partition (the slice scripts it), the ordering recomputed from the actual
        // partition by the front's arrangement rule, the group's 2n - 1 decisions counted through
        List<Object> cards = new ArrayList<>();
        Map<String, String> nameOf = new LinkedHashMap<>();
        for (Object k : Json.arr(obsOf(ds), "known")) {
            cards.add(Json.obj(k).get("object_id"));
            nameOf.put(Json.str(Json.obj(k), "object_id"), Json.str(Json.obj(k), "card_name"));
        }
        Map<String, Object> dest = new LinkedHashMap<>();
        dest.put((String) cards.get(0), "top");
        dest.put((String) cards.get(1), "split".equals(variant) ? "bottom" : "top");
        List<Object> order = new ArrayList<>(Arrays.asList(cards.get(1), cards.get(0)));
        int decisions = 0;
        int orderCandidates = -1;
        boolean forcedPosed = false;
        while (!e.over() && "p0".equals(e.acting()) && !"priority".equals(Json.str(Json.obj(e.decision(), "context"), "kind"))) {
            Map<String, Object> d = e.decision();
            List<Object> cs = Json.arr(d, "candidates");
            int pick = 0;
            int bestRank = Integer.MAX_VALUE;
            for (int i = 0; i < cs.size(); i++) {
                Map<String, Object> s = Json.obj(Json.obj(cs.get(i)), "semantic");
                if ("arrange_card".equals(s.get("kind"))) {
                    if (Json.str(s, "destination").equals(dest.get(Json.str(Json.obj(s, "card"), "object_id")))) {
                        pick = i;
                    }
                } else if ("order_pick".equals(s.get("kind"))) {
                    orderCandidates = cs.size();
                    forcedPosed |= cs.size() == 1;
                    int rank = order.indexOf(Json.str(Json.obj(Json.obj(s, "item"), "object"), "object_id"));
                    if (rank >= 0 && rank < bestRank) {
                        bestRank = rank;
                        pick = i;
                    }
                }
            }
            e.answer(pick);
            decisions++;
        }
        boolean shape = "split".equals(variant) ? decisions == 3 && forcedPosed : decisions == 3 && orderCandidates == 2;
        check("S4." + variant + ".arrangement_group_shape", shape,
                Json.map("decisions", (long) decisions, "order_candidates", (long) orderCandidates, "forced_single_candidate_posed", forcedPosed));
        e.advance(d -> priorityOf(d, "p0", null) && Json.arr(obsOf(d), "stack").isEmpty(), 10);
        // the library's top after the scry, through the engine's own state (the observation hides library order)
        List<String> top = new ArrayList<>();
        for (Card card : e.player("p0").getLibrary().getTopCards(e.game, 2)) {
            top.add(card.getName());
        }
        // the planned arrangement: both on top in the planned order, or the top card alone above the rest of the library
        List<String> expect = "split".equals(variant) ? Arrays.asList(nameOf.get((String) cards.get(0)), "Plains")
                : Arrays.asList(nameOf.get((String) order.get(0)), nameOf.get((String) order.get(1)));
        check("S4." + variant + ".assert.library_order", top.equals(expect), Json.map("top", top, "expected", expect));
    }

    // =============================================================================================
    // S5: a cast whose payment fails: the rewind rolls back plan, anchors and recorded answers

    static void s5() throws Exception {
        SeatSetup a = new SeatSetup().lib("Mountain", 8);
        a.hand.addAll(Arrays.asList("Burst Lightning", "Mountain"));
        a.battlefield.addAll(Arrays.asList("Rockface Village"));
        SeatSetup b = new SeatSetup().lib("Island", 8);
        b.battlefield.addAll(Arrays.asList("Island", "Grizzly Bears"));
        EnginePos e = EnginePos.start("S5", a, b);
        if (!e.advance(d -> priorityOf(d, "p0", "precombat_main"), 50)) {
            check("S5.reach_position", false, e.trail);
            return;
        }
        Map<String, Object> d0 = e.decision();
        int c = candidateWhere(d0, "cast_spell", "Burst Lightning");
        check("S5.engine_offers_unpayable_cast", c >= 0, Json.map("candidates", (long) Json.arr(d0, "candidates").size()));
        if (c < 0) {
            return;
        }
        Map<String, String> opts = new LinkedHashMap<>();
        opts.put("grace-ms", "5000");
        opts.put("overhead-ms", "1500");
        Front front = new Front(opts, Arrays.asList("none"));
        Map<String, Object> sem = Json.obj(Json.obj(Json.arr(d0, "candidates").get(c)), "semantic");
        List<Map<String, Object>> answers = new ArrayList<>();
        answers.add(Json.map("family", "target", "value", Arrays.asList(Json.map("player", "p1"))));
        front.pickedForTest(d0, sem, Json.map("targets", new ArrayList<>()), answers, new ArrayList<>());
        e.answer(c);
        List<Object> trace = new ArrayList<>();
        Map<String, Object> mid = null;
        while (!e.over() && !priorityOf(e.decision(), "p0", null)) {
            Map<String, Object> d = e.decision();
            Map<String, Object> r = front.decideForTest(d, 1000);
            trace.add(Json.map("kind", Front_firstKind(d), "answer", r));
            if (mid == null) {
                mid = front.recordsForTest();
            }
            e.answer(((Number) r.get("candidate")).intValue());
        }
        Map<String, Object> dr = e.decision();
        boolean rewind = Json.bool(Json.obj(dr, "context"), "rewind");
        Map<String, Object> before = front.recordsForTest();
        Map<String, Object> r = front.decideForTest(dr, 1000);
        Map<String, Object> after = front.recordsForTest();
        boolean offeredAgain = candidateWhere(dr, "cast_spell", "Burst Lightning") >= 0;
        check("S5.rewind_rolls_back", rewind && !offeredAgain && before.get("plan") != null && after.get("plan") == null
                        && ((Number) after.get("source_answers")).longValue() == 0,
                Json.map("rewind", rewind, "failed_cast_offered_again", offeredAgain, "records_mid_action", mid,
                        "records_before_rewind", before, "records_after_rewind", after, "trace", trace, "answer", r));
    }

    // =============================================================================================
    // S6: first-strike combat across both damage steps; combat key and ensemble

    static void s6() throws Exception {
        SeatSetup a = new SeatSetup().lib("Plains", 8);
        a.battlefield.addAll(Arrays.asList("Inspiring Paladin", "Plains", "Plains", "Plains"));
        SeatSetup b = new SeatSetup().lib("Plains", 8);
        b.battlefield.addAll(Arrays.asList("Youthful Valkyrie", "Plains"));
        EnginePos e = EnginePos.start("S6", a, b);
        if (!e.advance(d -> "declare_attack".equals(Front_firstKind(d)) && "p0".equals(Json.str(d, "acting_seat")), 60)) {
            check("S6.reach_position", false, e.trail);
            return;
        }
        Map<String, Object> da = e.decision();
        Map<String, Object> gs = gameStart("p0", a, b);
        // combat anchor on two worlds: the attack assignment, voted per combat key
        List<String> keys = new ArrayList<>();
        List<Object> pairsSeen = new ArrayList<>();
        for (int k = 0; k < 2; k++) {
            KitMad[] dec = new KitMad[1];
            World w = world(gs, da, null, WorldBuilder.Mode.ATTACK, k, dec, null);
            dec[0].selectAttackers(w.game, w.player("p0"));
            List<Object> pairs = new ArrayList<>();
            for (mage.game.combat.CombatGroup g : w.game.getCombat().getGroups()) {
                for (UUID at : g.getAttackers()) {
                    pairs.add(Json.map("attacker", w.uuidToId.get(at), "defender", Mapping.targetRef(w, g.getDefenderId())));
                }
            }
            pairsSeen.add(pairs);
            keys.add(Json.canonical(pairs));
        }
        boolean agree = keys.get(0).equals(keys.get(1)) && !Json.arr(Json.parse(keys.get(0))).isEmpty();
        check("S6.combat_key_ensemble", agree, Json.map("worlds", pairsSeen));
        // the engine's attack group answered from the plan; the defender blocks with the Valkyrie
        Map<String, Object> plan = Json.obj(Json.arr(pairsSeen.get(0)).get(0));
        while (!e.over() && "declare_attack".equals(Front_firstKind(e.decision()))) {
            Map<String, Object> d = e.decision();
            int pick = 0;
            for (int i = 0; i < Json.arr(d, "candidates").size(); i++) {
                Map<String, Object> s = Json.obj(Json.obj(Json.arr(d, "candidates").get(i)), "semantic");
                if (s.get("defender") != null && PlanBookAccess.sameTarget(Json.obj(s, "defender"), plan.get("defender"))) {
                    pick = i;
                }
            }
            e.answer(pick);
        }
        e.advance(d -> "declare_block".equals(Front_firstKind(d)), 10);
        Map<String, Object> db = e.decision();
        int blk = 0;
        for (int i = 0; i < Json.arr(db, "candidates").size(); i++) {
            if (Json.obj(Json.obj(Json.arr(db, "candidates").get(i)), "semantic").get("attacker") != null) {
                blk = i;
            }
        }
        e.answer(blk);
        // the two combat damage steps, through the front's own history
        Front front = new Front(new LinkedHashMap<String, String>(), Arrays.asList("none"));
        List<Object> steps = new ArrayList<>();
        int n = 0;
        while (!e.over() && n < 2) {
            if (!e.advance(d -> priorityOf(d, "p0", "combat_damage"), 10)) {
                break;
            }
            Map<String, Object> d = e.decision();
            String step = front.ownHistoryStep(d);
            KitMad[] dec = new KitMad[1];
            World w = world(gs, d, oracle(e, obsOf(d)), WorldBuilder.Mode.PRIORITY, 0, dec, step);
            Map<String, Object> ow = project(w, "p0", new ArrayList<>());
            String xmageStep = String.valueOf(w.game.getTurnStepType());
            String engineStep = String.valueOf(e.game.getTurnStepType());
            boolean sameStep = xmageStep.equals(engineStep);
            transition("S6.E1.damage_step_" + (n + 1), obsOf(d), ow, Json.map("own_history_step", step,
                    "world_step", xmageStep, "engine_step", engineStep, "flags", w.flags));
            check("S6.own_history_step_" + (n + 1), sameStep, Json.map("own_history_step", step, "world_step", xmageStep,
                    "engine_step", engineStep));
            steps.add(step);
            front.answeredForTest(d, 0);
            e.answer(0);
            n++;
        }
        e.advance(d -> priorityOf(d, "p0", null) && !"combat_damage".equals(Json.str(obsOf(d), "phase_step")), 20);
        Map<String, Object> oe = obsOf(e.decision());
        check("S6.assert.valkyrie_died_first_strike", names(oe, "p1", "graveyard").contains("Youthful Valkyrie") && n == 2,
                Json.map("steps", steps, "p1_graveyard", names(oe, "p1", "graveyard")));
    }

    // =============================================================================================
    // S7: H3's branch-local knowledge (and the addendum's change 1)

    static void s7() {
        SeatSetup a = new SeatSetup();
        a.library.addAll(Arrays.asList("Llanowar Elves", "Plains", "Forest", "Plains", "Forest", "Plains", "Forest", "Plains"));
        a.hand.addAll(Arrays.asList("Helpful Hunter", "Cathar Commando"));
        a.battlefield.addAll(Arrays.asList("Plains", "Forest", "Forest"));
        SeatSetup b = new SeatSetup();
        b.library.addAll(Arrays.asList("Island", "Island", "Mountain", "Island", "Mountain", "Island", "Island", "Mountain"));
        b.hand.addAll(Arrays.asList("Refute", "Island", "Island"));
        b.battlefield.addAll(Arrays.asList("Island", "Island", "Island", "Mountain", "Mountain"));
        EnginePos e = EnginePos.start("S7", a, b);
        if (!e.advance(d -> priorityOf(d, "p0", "precombat_main"), 50)) {
            check("S7.reach_position", false, e.trail);
            return;
        }
        Map<String, Object> d0 = e.decision();
        Map<String, Object> gs = gameStart("p0", a, b);
        KitMad[] dec = new KitMad[1];
        World w = world(gs, d0, oracle(e, obsOf(d0)), WorldBuilder.Mode.PRIORITY, 0, dec, null);
        Game g = w.game;
        UUID me = w.player("p0");
        UUID opp = w.player("p1");
        KnowledgeWatcher kw = KnowledgeWatcher.install(g, me);
        Card top = g.getPlayer(me).getLibrary().getFromTop(g);
        kw.pinLibrary(me, top.getId());          // the known own top card (Llanowar Elves)
        kw.pinHand(opp, "Refute");                // an opponent hand card known by name
        Random rnd = new Random(7);
        // (a) a known own top card drawn in a branch stays in hand at descendant re-deals and leaves no library pin
        Game branch = g.copy();
        branch.getPlayer(me).drawCards(1, null, branch);
        branch.getState().handleSimultaneousEvent(branch); // the game loop delivers queued zone changes to watchers
        KitRedeal.redeal(branch, me, rnd);
        Game child = branch.copy();
        KitRedeal.redeal(child, me, rnd);
        boolean inHand = child.getPlayer(me).getHand().contains(top.getId());
        boolean noPin = KnowledgeWatcher.get(child).libKnown(me).isEmpty();
        boolean parentKept = KnowledgeWatcher.get(g).knownInLibrary(me, top.getId());
        check("S7.a.drawn_known_card_stays_no_pin", inHand && noPin && parentKept,
                Json.map("in_hand", inHand, "no_library_pin", noPin, "parent_keeps_pin", parentKept));
        // (b) an opponent's known hand card cast in a branch is never re-dealt back to hand
        Game b2 = g.copy();
        Card refute = null;
        for (Card c : b2.getPlayer(opp).getHand().getCards(b2)) {
            if (c.getName().equals("Refute")) {
                refute = c;
            }
        }
        b2.getPlayer(opp).moveCards(refute, Zone.GRAVEYARD, null, b2);
        b2.getState().handleSimultaneousEvent(b2);
        boolean countDropped = KnowledgeWatcher.get(b2).knownHandCount(opp, "Refute") == 0;
        boolean back = false;
        for (int i = 0; i < 20; i++) {
            Game x = b2.copy();
            KitRedeal.redeal(x, me, rnd);
            back |= x.getPlayer(opp).getHand().contains(refute.getId());
        }
        check("S7.b.cast_known_card_not_redealt", countDropped && !back, Json.map("known_count_dropped", countDropped, "redealt_back", back));
        // (c) a simulated shuffle clears that library's positions
        Game b3 = g.copy();
        b3.getPlayer(me).shuffleLibrary(null, b3);
        check("S7.c.shuffle_clears_positions", KnowledgeWatcher.get(b3).libKnown(me).isEmpty()
                && KnowledgeWatcher.get(g).libKnown(me).size() == 1, null);
        // (d) zone sizes and multisets conserved at every re-deal (the hook's own check), pins honored
        KitContext.reset();
        boolean pinsHonored = true;
        for (int i = 0; i < 50; i++) {
            Game x = g.copy();
            KitRedeal.redeal(x, me, rnd);
            pinsHonored &= x.getPlayer(me).getLibrary().getFromTop(x).getId().equals(top.getId());
            int refutes = 0;
            for (Card c : x.getPlayer(opp).getHand().getCards(x)) {
                refutes += c.getName().equals("Refute") ? 1 : 0;
            }
            pinsHonored &= refutes >= 1;
        }
        Map<String, Long> ctr = KitContext.counters();
        check("S7.d.conservation_and_pins", pinsHonored && !ctr.containsKey("redeal_conservation_violation"), ctr);
        // addendum 1: a reveal (no GameEvent) notifies knowledge; duplicate names count; sibling copies independent
        Game b4 = g.copy();
        Game sib = g.copy();
        mage.cards.Cards revealed = new mage.cards.CardsImpl();
        int islands = 0;
        for (Card c : b4.getPlayer(opp).getHand().getCards(b4)) {
            revealed.add(c);
            islands += c.getName().equals("Island") ? 1 : 0;
        }
        KnowledgeWatcher.looked(b4, opp, revealed, true);
        int knownIslands = KnowledgeWatcher.get(b4).knownHandCount(opp, "Island");
        boolean sibUnaffected = KnowledgeWatcher.get(sib).knownHandCount(opp, "Island") == 0;
        // one Island leaves to a public zone: one count goes, the other stays known
        for (Card c : b4.getPlayer(opp).getHand().getCards(b4)) {
            if (c.getName().equals("Island")) {
                b4.getPlayer(opp).moveCards(c, Zone.GRAVEYARD, null, b4);
                b4.getState().handleSimultaneousEvent(b4);
                break;
            }
        }
        int afterOne = KnowledgeWatcher.get(b4).knownHandCount(opp, "Island");
        check("S7.addendum1.reveal_duplicates_siblings", knownIslands == islands && islands == 2 && afterOne == 1 && sibUnaffected,
                Json.map("revealed_islands", (long) islands, "known_islands", (long) knownIslands, "after_one_left", (long) afterOne,
                        "sibling_unaffected", sibUnaffected));
        // look at library cards (scry-like choice by the decider) is knowledge; by the opponent it is not
        Game b5 = g.copy();
        mage.cards.Cards looked = new mage.cards.CardsImpl();
        for (Card c : b5.getPlayer(me).getLibrary().getTopCards(b5, 2)) {
            looked.add(c);
        }
        KnowledgeWatcher.looked(b5, me, looked, false);
        int pinsMine = KnowledgeWatcher.get(b5).libKnown(me).size();
        Game b6 = g.copy();
        mage.cards.Cards oppLooked = new mage.cards.CardsImpl();
        for (Card c : b6.getPlayer(opp).getLibrary().getTopCards(b6, 2)) {
            oppLooked.add(c);
        }
        KnowledgeWatcher.looked(b6, opp, oppLooked, false);
        check("S7.addendum1.looks", pinsMine == 2 && KnowledgeWatcher.get(b6).libKnown(opp).isEmpty(),
                Json.map("decider_look_pins", (long) pinsMine, "opponent_look_pins", (long) KnowledgeWatcher.get(b6).libKnown(opp).size()));
        // (e) the hook counter covers every simulate, with bounded iterations: an H3 search on the cantrip position
        for (String mode : new String[]{"kit", "oracle"}) {
            KitContext.reset();
            KitContext.mctsIterations = 60;
            KitContext.rolloutCap = 400;
            KitMcts[] m = new KitMcts[1];
            KitRandom random = KitRandom.install(Seeds.worldSeed(GAME_KEY, Json.num(d0, "seat_step", 0), 2), ID_SEED);
            WorldBuilder.Spec spec = new WorldBuilder.Spec();
            spec.gameStart = gs;
            spec.observation = obsOf(d0);
            spec.sample = "oracle".equals(mode) ? oracle(e, obsOf(d0)) : Sampler.sample(gs, obsOf(d0), random.stream("sampler"));
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
            long ms = (System.nanoTime() - t0) / 1_000_000;
            Map<String, Long> cc = KitContext.counters();
            long sims = cc.getOrDefault("simulate", 0L);
            long redeals = cc.getOrDefault("redeal", 0L);
            long iters = cc.getOrDefault("mcts:iterations", 0L);
            check("S7.e.hook_covers_every_simulate:" + mode, sims > 0 && redeals >= sims && iters <= 60
                            && !cc.containsKey("redeal_conservation_violation"),
                    Json.map("simulate", sims, "redeal", redeals, "iterations", iters, "ms", ms, "counters", cc,
                            "best", res.get("semantic"), "root_stats", res.get("root_stats")));
        }
        KitContext.mctsIterations = 300;
        KitContext.rolloutCap = 2000;
    }

    static final class Random extends java.util.Random {
        private static final long serialVersionUID = 1L;

        Random(long seed) {
            super(seed);
        }
    }

    // =============================================================================================
    // S9: H2 on a position where worlds may disagree: RootStat for every option, the vote and its plan

    static void s9() {
        SeatSetup a = new SeatSetup();
        a.library.addAll(Arrays.asList("Llanowar Elves", "Plains", "Forest", "Llanowar Elves", "Plains", "Forest", "Plains", "Forest",
                "Llanowar Elves", "Plains"));
        a.hand.addAll(Arrays.asList("Helpful Hunter", "Cathar Commando"));
        a.battlefield.addAll(Arrays.asList("Plains", "Forest", "Forest"));
        SeatSetup b = new SeatSetup().lib("Island", 8);
        b.hand.addAll(Arrays.asList("Island", "Island"));
        b.battlefield.addAll(Arrays.asList("Island", "Island", "Grizzly Bears"));
        EnginePos e = EnginePos.start("S9", a, b);
        if (!e.advance(d -> priorityOf(d, "p0", "precombat_main"), 50)) {
            check("S9.reach_position", false, e.trail);
            return;
        }
        Map<String, Object> d0 = e.decision();
        Map<String, Object> gs = gameStart("p0", a, b);
        List<Aggregate.WorldVote> votes = new ArrayList<>();
        List<Object> perWorld = new ArrayList<>();
        boolean statsComplete = true;
        for (int k = 0; k < 4; k++) {
            KitMad[] dec = new KitMad[1];
            World w = world(gs, d0, null, WorldBuilder.Mode.PRIORITY, k, dec, null);
            KitMad.PriorityOutcome o = dec[0].decidePriority(w, new ObsIndex(obsOf(d0)), true);
            List<Object> stats = new ArrayList<>();
            for (int i = 0; i < o.stats.size(); i++) {
                RootStat rs = o.stats.get(i);
                statsComplete &= rs.raw != null ? rs.bound != null : rs.reason != null;
                stats.add(Json.map("index", (long) rs.index, "semantic", o.statSemantics.get(i), "raw", rs.raw, "adjusted", rs.adjusted,
                        "alpha_before", rs.alphaBefore == null || rs.alphaBefore == Integer.MIN_VALUE ? null : rs.alphaBefore,
                        "bound", rs.bound, "tie", rs.tie, "reason", rs.reason, "best", rs.best));
            }
            Map<String, Object> wr = Json.map("index", (long) k, "semantic", o.semantic, "executed_payload", o.executedPayload,
                    "root_stats", stats, "library_top", w.viewerPlayer().getLibrary().getFromTop(w.game) == null ? null
                            : w.viewerPlayer().getLibrary().getFromTop(w.game).getName());
            perWorld.add(wr);
            votes.add(Aggregate.fromRunner(wr));
        }
        Map<String, Integer> cand = new LinkedHashMap<>();
        for (int i = 0; i < Json.arr(d0, "candidates").size(); i++) {
            cand.put(Aggregate.key(Json.obj(Json.obj(Json.arr(d0, "candidates").get(i)), "semantic")), i);
        }
        Aggregate.Result r = Aggregate.vote(votes, cand);
        Set<String> distinct = new LinkedHashSet<>();
        for (Aggregate.WorldVote v : votes) {
            distinct.add(v.key);
        }
        check("S9.root_stats_complete", statsComplete, perWorld);
        check("S9.vote_and_plan", r.winner != null && cand.get(r.winner) != null && r.planWorld >= 0,
                Json.map("winner_candidate", cand.get(r.winner), "plan_world", (long) r.planWorld, "plan_payload", r.planPayload,
                        "votes", new ArrayList<Object>(r.votes.values()), "distinct_world_choices", (long) distinct.size()));
        note("S9.worlds_disagree", distinct.size() > 1);
    }

    // =============================================================================================
    // the flagged-stack sentinel (addendum 4): neither MAD nor MCTS (expansion or rollouts) resolves it

    static volatile int sentinelResolutions;

    static final class SentinelEffect extends OneShotEffect {
        private static final long serialVersionUID = 1L;

        SentinelEffect() {
            super(Outcome.Damage);
            staticText = "spellbench kit sentinel";
        }

        private SentinelEffect(final SentinelEffect e) {
            super(e);
        }

        @Override
        public SentinelEffect copy() {
            return new SentinelEffect(this);
        }

        @Override
        public boolean apply(Game game, Ability source) {
            sentinelResolutions++;
            Player p = game.getPlayer(source.getControllerId());
            for (UUID opp : game.getOpponents(source.getControllerId())) {
                game.getPlayer(opp).loseLife(10, game, source, false);
            }
            return true;
        }
    }

    static void sentinel() {
        SeatSetup a = new SeatSetup().lib("Swamp", 8);
        a.hand.addAll(Arrays.asList("Stab", "Swamp"));
        a.battlefield.addAll(Arrays.asList("Swamp", "Swamp"));
        SeatSetup b = new SeatSetup().lib("Island", 8);
        b.hand.addAll(Arrays.asList("Island", "Island"));
        b.battlefield.addAll(Arrays.asList("Island", "Grizzly Bears"));
        EnginePos e = EnginePos.start("SENTINEL", a, b);
        e.advance(d -> priorityOf(d, "p0", "precombat_main"), 50);
        Map<String, Object> d0 = e.decision();
        Map<String, Object> gs = gameStart("p0", a, b);
        for (String bot : new String[]{"mad", "mcts"}) {
            sentinelResolutions = 0;
            KitMad[] dec = new KitMad[1];
            KitMcts[] m = new KitMcts[1];
            KitContext.reset();
            KitRandom random = KitRandom.install(Seeds.worldSeed(GAME_KEY, 1, 9), ID_SEED);
            WorldBuilder.Spec spec = new WorldBuilder.Spec();
            spec.gameStart = gs;
            spec.observation = obsOf(d0);
            spec.sample = oracle(e, obsOf(d0));
            spec.random = random;
            spec.mode = WorldBuilder.Mode.PRIORITY;
            spec.viewerFactory = seat -> {
                if ("mcts".equals(bot)) {
                    m[0] = new KitMcts(seat, 6);
                    return m[0];
                }
                dec[0] = new KitMad(seat, 6);
                return dec[0];
            };
            spec.otherFactory = Puppet::new;
            World w = WorldBuilder.build(spec);
            // the opponent's sentinel on the stack, flagged approximate: resolving it costs the viewer 10 life
            Ability sa = new SimpleStaticAbility(Zone.ALL, new SentinelEffect());
            sa.setControllerId(w.player("p1"));
            sa.setSourceId(w.player("p1"));
            sa.newId();
            StackAbility st = new StackAbility(sa, w.player("p1"));
            w.game.getStack().push(w.game, st);
            KitContext.horizon.add(st.getId());
            Map<String, Object> res;
            if ("mcts".equals(bot)) {
                KitContext.mctsIterations = 80;
                KitContext.rolloutCap = 400;
                KnowledgeWatcher.install(w.game, w.player("p0"));
                res = m[0].decidePriority(w, new ObsIndex(obsOf(d0)));
                KitContext.mctsIterations = 300;
                KitContext.rolloutCap = 2000;
            } else {
                dec[0].attach(w);
                KitMad.PriorityOutcome o = dec[0].decidePriority(w, new ObsIndex(obsOf(d0)), false);
                res = Json.map("semantic", o.semantic);
            }
            Map<String, Long> cc = KitContext.counters();
            long stops = cc.getOrDefault("horizon:mad", 0L) + cc.getOrDefault("horizon:mcts_expansion", 0L)
                    + cc.getOrDefault("horizon:mcts_rollout", 0L);
            check("ADDENDUM4.sentinel_never_resolved:" + bot, sentinelResolutions == 0 && stops > 0,
                    Json.map("sentinel_resolutions", (long) sentinelResolutions, "horizon_stops", stops, "counters", cc,
                            "decision", res.get("semantic")));
        }
    }

    // =============================================================================================
    // E2: a constructed runaway position (a large target space): each cap fires, the answer stays fast

    static void e2() {
        SeatSetup a = new SeatSetup().lib("Mountain", 8);
        a.hand.addAll(Arrays.asList("Arc Lightning", "Shock", "Mountain"));
        a.battlefield.addAll(Arrays.asList("Mountain", "Mountain", "Mountain"));
        SeatSetup b = new SeatSetup().lib("Island", 8);
        for (int i = 0; i < 30; i++) {
            b.battlefield.add("Grizzly Bears");
        }
        EnginePos e = EnginePos.start("E2", a, b);
        if (!e.advance(d -> priorityOf(d, "p0", "precombat_main"), 50)) {
            check("E2.reach_position", false, e.trail);
            return;
        }
        Map<String, Object> d0 = e.decision();
        Map<String, Object> gs = gameStart("p0", a, b);
        Object[][] configs = {
                {"options", 2000, 20000, 5000},
                {"operations", 2000, 1, 5000},
                {"nodes", 2000, 20000, 3},
        };
        for (Object[] cfg : configs) {
            KitContext.optionBudget = (Integer) cfg[1];
            KitContext.opCap = (Integer) cfg[2];
            KitContext.nodeBudget = (Integer) cfg[3];
            KitMad[] dec = new KitMad[1];
            long t0 = System.nanoTime();
            World w = world(gs, d0, oracle(e, obsOf(d0)), WorldBuilder.Mode.PRIORITY, 0, dec, null);
            KitContext.optionBudget = (Integer) cfg[1];
            KitContext.opCap = (Integer) cfg[2];
            KitContext.nodeBudget = (Integer) cfg[3];
            KitMad.PriorityOutcome o;
            Map<String, Long> cc;
            try {
                o = dec[0].decidePriority(w, new ObsIndex(obsOf(d0)), false);
                cc = KitContext.counters();
            } catch (Throwable t) {
                check("E2.cap_" + cfg[0], false, t.toString());
                continue;
            }
            long ms = (System.nanoTime() - t0) / 1_000_000;
            boolean fired;
            switch ((String) cfg[0]) {
                case "options":
                    fired = cc.containsKey("cap:options_skipped") || cc.containsKey("cap:options_truncated");
                    break;
                case "operations":
                    fired = cc.containsKey("cap:operations");
                    break;
                default:
                    boolean cut = false;
                    for (RootStat rs : o.stats) {
                        cut |= "cut_nodes".equals(rs.reason);
                    }
                    fired = cut || mage.player.ai.KitNodes.count() > (Integer) cfg[3];
            }
            List<Object> reasons = new ArrayList<>();
            for (RootStat rs : o.stats) {
                reasons.add(rs.reason);
            }
            long thrown = cc.getOrDefault("budget_thrown", 0L);
            long caught = 0;
            for (Map.Entry<String, Long> en : cc.entrySet()) {
                if (en.getKey().startsWith("budget_caught:")) {
                    caught += en.getValue();
                }
            }
            check("E2.cap_" + cfg[0], fired && ms < 60_000 && thrown == caught, Json.map("ms", ms, "counters", cc,
                    "nodes", (long) mage.player.ai.KitNodes.count(), "decision", o.semantic, "root_reasons", reasons,
                    "budget_thrown", thrown, "budget_caught_at_boundary", caught));
        }
        KitContext.optionBudget = 2000;
        KitContext.opCap = 20000;
        KitContext.nodeBudget = 5000;
        // MCTS: completed iterations and the rollout cap
        KitContext.reset();
        KitContext.mctsIterations = 40;
        KitContext.rolloutCap = 30;
        KitMcts[] m = new KitMcts[1];
        KitRandom random = KitRandom.install(Seeds.worldSeed(GAME_KEY, 3, 3), ID_SEED);
        WorldBuilder.Spec spec = new WorldBuilder.Spec();
        spec.gameStart = gs;
        spec.observation = obsOf(d0);
        spec.sample = oracle(e, obsOf(d0));
        spec.random = random;
        spec.viewerFactory = seat -> {
            m[0] = new KitMcts(seat, 6);
            return m[0];
        };
        spec.otherFactory = Puppet::new;
        World w = WorldBuilder.build(spec);
        KnowledgeWatcher.install(w.game, w.player("p0"));
        long t0 = System.nanoTime();
        Map<String, Object> res = m[0].decidePriority(w, new ObsIndex(obsOf(d0)));
        long ms = (System.nanoTime() - t0) / 1_000_000;
        Map<String, Long> cc = KitContext.counters();
        check("E2.cap_mcts_iterations_and_rollout", cc.getOrDefault("mcts:iterations", 0L) <= 40 && cc.containsKey("cap:rollout") && ms < 60_000,
                Json.map("ms", ms, "counters", cc, "decision", res.get("semantic")));
        KitContext.mctsIterations = 300;
        KitContext.rolloutCap = 2000;
    }

    // =============================================================================================
    // E7 (MCTS part): with no knowledge, the re-deal hook keeps upstream's re-deal semantics

    static void e7mcts() {
        SeatSetup a = new SeatSetup();
        a.library.addAll(Arrays.asList("Llanowar Elves", "Plains", "Forest", "Plains", "Forest", "Plains"));
        a.hand.addAll(Arrays.asList("Helpful Hunter", "Cathar Commando"));
        a.battlefield.addAll(Arrays.asList("Plains", "Forest"));
        SeatSetup b = new SeatSetup();
        b.library.addAll(Arrays.asList("Island", "Mountain", "Island", "Mountain", "Island", "Refute"));
        b.hand.addAll(Arrays.asList("Refute", "Island", "Mountain"));
        b.battlefield.add("Island");
        EnginePos e = EnginePos.start("E7MCTS", a, b);
        e.advance(d -> priorityOf(d, "p0", "precombat_main"), 50);
        Map<String, Object> d0 = e.decision();
        Map<String, Object> gs = gameStart("p0", a, b);
        KitMad[] dec = new KitMad[1];
        World w = world(gs, d0, oracle(e, obsOf(d0)), WorldBuilder.Mode.PRIORITY, 0, dec, null);
        Game g = w.game;
        UUID me = w.player("p0");
        UUID opp = w.player("p1");
        KnowledgeWatcher.install(g, me);
        List<String> myHand = handNames(g, me);
        Map<String, Integer> oppAll = multiset(g, opp);
        Map<String, Integer> myLib = libMultiset(g, me);
        Set<String> reachedHand = new LinkedHashSet<>();
        boolean ok = true;
        Random rnd = new Random(11);
        for (int i = 0; i < 200; i++) {
            Game x = g.copy();
            KitRedeal.redeal(x, me, rnd);
            ok &= handNames(x, me).equals(myHand);
            ok &= x.getPlayer(opp).getHand().size() == g.getPlayer(opp).getHand().size();
            ok &= multiset(x, opp).equals(oppAll);
            ok &= libMultiset(x, me).equals(myLib);
            reachedHand.addAll(handNames(x, opp));
        }
        boolean everyNameReaches = reachedHand.containsAll(oppAll.keySet());
        check("E7.mcts_redeal_semantics_without_pins", ok && everyNameReaches,
                Json.map("decider_hand_untouched_and_sizes_and_multisets", ok, "names_reaching_opponent_hand",
                        new ArrayList<Object>(reachedHand), "opponent_names", new ArrayList<Object>(oppAll.keySet())));
    }

    // =============================================================================================
    // E4 and the C-MAD / C-MCTS pilots on DraftZero's two positions (doc 009 Section 3.4), rebuilt with FDN cards:
    // the counterspell pair (world R: Refute in hand, world N: Island) and the cantrip pair (world E: Llanowar Elves
    // on top, world L: Plains on top). Horizon and truncation counts for E4; kit-sample versus oracle decisions for
    // the sensitivity controls.

    /**
     * A transforming double-faced card observed on the battlefield on either face (the first pauper-kernel smoke
     * games: CawGates' The Modern Age // Vector Glider never entered a world). Each face enters as itself, the back
     * face transformed, and the sampler counts both against the list's front-face row.
     */
    static void dfcBattlefield() {
        SeatSetup a = new SeatSetup().lib("Island", 8);
        a.battlefield.addAll(Arrays.asList("Island", "Island"));
        SeatSetup b = new SeatSetup().lib("Island", 8);
        b.battlefield.addAll(Arrays.asList("Island", "Island"));
        EnginePos e = EnginePos.start("DFC", a, b);
        if (!e.advance(d -> priorityOf(d, "p0", "precombat_main"), 50)) {
            check("DFC.reach_position", false, e.trail);
            return;
        }
        Map<String, Object> d0 = e.decision();
        a.library.add("The Modern Age");
        a.library.add("The Modern Age");
        Map<String, Object> gs = gameStart("p0", a, b);
        Map<String, Object> obs = obsOf(d0);
        Map<String, Object> p0 = null;
        for (Object o : Json.arr(obs, "players")) {
            if ("p0".equals(Json.str(Json.obj(o), "seat"))) {
                p0 = Json.obj(o);
            }
        }
        @SuppressWarnings("unchecked")
        List<Object> bf = (List<Object>) p0.get("battlefield");
        String[][] faces = {{"o-dfc-front", "The Modern Age"}, {"o-dfc-back", "Vector Glider"}};
        for (String[] f : faces) {
            Map<String, Object> rec = new LinkedHashMap<>(Json.obj(bf.get(0)));
            rec.put("object_id", f[0]);
            rec.put("card_name", f[1]);
            rec.put("full_name", "The Modern Age // Vector Glider");
            rec.put("characteristics", null);
            rec.put("permanent", new LinkedHashMap<>(Json.obj(Json.obj(bf.get(0)), "permanent")));
            bf.add(rec);
        }
        KitMad[] dec = new KitMad[1];
        World w = world(gs, d0, null, WorldBuilder.Mode.PRIORITY, 0, dec, null);
        Map<String, Object> got = new LinkedHashMap<>();
        boolean ok = true;
        for (String[] f : faces) {
            java.util.UUID id = w.idToUuid.get(f[0]);
            mage.game.permanent.Permanent perm = id == null ? null : w.game.getPermanent(id);
            got.put(f[0], perm == null ? null : Json.map("name", perm.getName(), "transformed", perm.isTransformed()));
            ok &= perm != null && f[1].equals(perm.getName()) && perm.isTransformed() == f[1].equals("Vector Glider");
        }
        boolean clean = true;
        for (String fl : w.flags) {
            clean &= !fl.contains("did_not_enter") && !fl.contains("public_exceeds_list") && !fl.contains("pool_surplus");
        }
        check("DFC.both_faces_enter", ok && clean, Json.map("permanents", got, "flags", new ArrayList<Object>(w.flags)));
    }

    /**
     * An embalmed Sacred Cat token observed on the battlefield (the pauper-kernel panel games: the token repository
     * has no such token, so every CawGates world with one went unsearched). It enters as XMage's embalm copy.
     */
    static void embalmToken() {
        SeatSetup a = new SeatSetup().lib("Plains", 8);
        a.battlefield.addAll(Arrays.asList("Plains", "Plains"));
        SeatSetup b = new SeatSetup().lib("Island", 8);
        b.battlefield.addAll(Arrays.asList("Island", "Island"));
        EnginePos e = EnginePos.start("EMBALM", a, b);
        if (!e.advance(d -> priorityOf(d, "p0", "precombat_main"), 50)) {
            check("EMBALM.reach_position", false, e.trail);
            return;
        }
        Map<String, Object> d0 = e.decision();
        a.graveyard.add("Sacred Cat");
        Map<String, Object> gs = gameStart("p0", a, b);
        Map<String, Object> obs = obsOf(d0);
        Map<String, Object> p0 = null;
        for (Object o : Json.arr(obs, "players")) {
            if ("p0".equals(Json.str(Json.obj(o), "seat"))) {
                p0 = Json.obj(o);
            }
        }
        @SuppressWarnings("unchecked")
        List<Object> bf = (List<Object>) p0.get("battlefield");
        @SuppressWarnings("unchecked")
        List<Object> gy = (List<Object>) p0.get("graveyard");
        Map<String, Object> land = Json.obj(bf.get(0));
        Map<String, Object> cat = new LinkedHashMap<>(land);
        cat.put("object_id", "o-cat-gy");
        cat.put("card_name", "Sacred Cat");
        cat.put("zone", "graveyard");
        cat.put("permanent", null);
        cat.put("characteristics", null);
        gy.add(cat);
        Map<String, Object> tok = new LinkedHashMap<>(land);
        tok.put("object_id", "o-cat-token");
        tok.put("card_name", "Sacred Cat Embalmed Token");
        tok.put("token", true);
        tok.put("characteristics", Json.map("power", 1L, "toughness", 1L));
        tok.put("permanent", new LinkedHashMap<>(Json.obj(land, "permanent")));
        bf.add(tok);
        KitMad[] dec = new KitMad[1];
        World w = world(gs, d0, null, WorldBuilder.Mode.PRIORITY, 0, dec, null);
        java.util.UUID id = w.idToUuid.get("o-cat-token");
        mage.game.permanent.Permanent perm = id == null ? null : w.game.getPermanent(id);
        boolean ok = perm != null && "Sacred Cat".equals(perm.getName()) && perm.getColor(w.game).isWhite()
                && perm.hasSubtype(mage.constants.SubType.ZOMBIE, w.game) && perm.getManaCost().isEmpty()
                && perm instanceof mage.game.permanent.PermanentToken;
        boolean clean = true;
        for (String fl : w.flags) {
            clean &= !fl.startsWith("unsupported");
        }
        check("EMBALM.token_enters", ok && clean, Json.map("permanent", perm == null ? null
                : Json.map("name", perm.getName(), "zombie", perm.hasSubtype(mage.constants.SubType.ZOMBIE, w.game)),
                "flags", new ArrayList<Object>(w.flags)));
    }

    static void dzPositions() {
        for (String world : new String[]{"R", "N"}) {
            SeatSetup a = new SeatSetup().lib("Plains", 8);
            a.hand.addAll(Arrays.asList("Serra Angel"));
            a.battlefield.addAll(Arrays.asList("Plains", "Plains", "Plains", "Forest", "Forest", "Forest"));
            SeatSetup b = new SeatSetup();
            b.library.addAll(Arrays.asList("Island", "Mountain", "Island", "Refute", "Island", "Mountain", "Island", "Island"));
            b.hand.addAll("R".equals(world) ? Arrays.asList("Refute", "Island") : Arrays.asList("Island", "Island"));
            b.battlefield.addAll(Arrays.asList("Island", "Island", "Island", "Mountain", "Mountain"));
            dzRun("counterspell_" + world, a, b);
        }
        for (String world : new String[]{"E", "L"}) {
            SeatSetup a = new SeatSetup();
            a.library.addAll(Arrays.asList("E".equals(world) ? "Llanowar Elves" : "Plains", "Plains", "Forest", "Plains", "Forest",
                    "Llanowar Elves", "Plains", "Forest"));
            a.hand.addAll(Arrays.asList("Helpful Hunter", "Cathar Commando"));
            a.battlefield.addAll(Arrays.asList("Plains", "Forest", "Forest"));
            SeatSetup b = new SeatSetup().lib("Island", 8);
            b.hand.addAll(Arrays.asList("Island", "Island"));
            b.battlefield.addAll(Arrays.asList("Island", "Island"));
            dzRun("cantrip_" + world, a, b);
        }
    }

    static void dzRun(String label, SeatSetup a, SeatSetup b) {
        EnginePos e = EnginePos.start("DZ" + label, a, b);
        if (!e.advance(d -> priorityOf(d, "p0", "precombat_main"), 50)) {
            check("DZ." + label + ".reach_position", false, e.trail);
            return;
        }
        Map<String, Object> d0 = e.decision();
        Map<String, Object> gs = gameStart("p0", a, b);
        Map<String, Object> rows = new LinkedHashMap<>();
        for (String mode : new String[]{"kit", "oracle"}) {
            KitMad[] dec = new KitMad[1];
            World w = world(gs, d0, "oracle".equals(mode) ? oracle(e, obsOf(d0)) : null, WorldBuilder.Mode.PRIORITY, 0, dec, null);
            KitMad.PriorityOutcome o = dec[0].decidePriority(w, new ObsIndex(obsOf(d0)), false);
            Map<String, Object> scores = new LinkedHashMap<>();
            for (int i = 0; i < o.stats.size(); i++) {
                Map<String, Object> ss = o.statSemantics.get(i);
                String option = ss == null ? "?" : ss.get("source") == null ? Json.str(ss, "kind") : Json.str(Json.obj(ss, "source"), "card_name");
                scores.put(option, o.stats.get(i).adjusted == null ? o.stats.get(i).reason : o.stats.get(i).adjusted);
            }
            rows.put("mad_" + mode, Json.map("decision", o.semantic == null || o.semantic.get("source") == null
                            ? (o.semantic == null ? null : o.semantic.get("kind")) : Json.str(Json.obj(o.semantic, "source"), "card_name"),
                    "root_scores", scores, "counters", KitContext.counters(), "nodes", (long) mage.player.ai.KitNodes.count()));
            KitContext.reset();
            KitContext.mctsIterations = 30;
            KitContext.rolloutCap = 2000;
            KitMcts[] m = new KitMcts[1];
            KitRandom random = KitRandom.install(Seeds.worldSeed(GAME_KEY, Json.num(d0, "seat_step", 0), 5), ID_SEED);
            WorldBuilder.Spec spec = new WorldBuilder.Spec();
            spec.gameStart = gs;
            spec.observation = obsOf(d0);
            spec.sample = "oracle".equals(mode) ? oracle(e, obsOf(d0)) : Sampler.sample(gs, obsOf(d0), random.stream("sampler"));
            spec.random = random;
            spec.viewerFactory = seat -> {
                m[0] = new KitMcts(seat, 6);
                return m[0];
            };
            spec.otherFactory = Puppet::new;
            World mw = WorldBuilder.build(spec);
            KnowledgeWatcher.install(mw.game, mw.player("p0"));
            long t0 = System.nanoTime();
            Map<String, Object> res = m[0].decidePriority(mw, new ObsIndex(obsOf(d0)));
            Map<String, Object> sem = Json.obj(res, "semantic");
            rows.put("mcts_" + mode, Json.map("decision", sem == null || sem.get("source") == null ? (sem == null ? null : sem.get("kind"))
                            : Json.str(Json.obj(sem, "source"), "card_name"), "ms", (System.nanoTime() - t0) / 1_000_000,
                    "counters", KitContext.counters(), "root_stats", res.get("root_stats")));
            KitContext.mctsIterations = 300;
        }
        note("DZ." + label, rows);
    }

    /** H3's cost per completed iteration at several rollout caps, on the cantrip position (E2, E4, E8). */
    static void h3cost() {
        SeatSetup a = new SeatSetup();
        a.library.addAll(Arrays.asList("Llanowar Elves", "Plains", "Forest", "Plains", "Forest", "Llanowar Elves", "Plains", "Forest"));
        a.hand.addAll(Arrays.asList("Helpful Hunter", "Cathar Commando"));
        a.battlefield.addAll(Arrays.asList("Plains", "Forest", "Forest"));
        SeatSetup b = new SeatSetup().lib("Island", 8);
        b.hand.addAll(Arrays.asList("Island", "Island"));
        b.battlefield.addAll(Arrays.asList("Island", "Island"));
        EnginePos e = EnginePos.start("H3COST", a, b);
        e.advance(d -> priorityOf(d, "p0", "precombat_main"), 50);
        Map<String, Object> d0 = e.decision();
        Map<String, Object> gs = gameStart("p0", a, b);
        List<Object> rows = new ArrayList<>();
        for (int cap : new int[]{200, 1000, 5000}) {
            KitContext.reset();
            KitContext.mctsIterations = 30;
            KitContext.rolloutCap = cap;
            KitMcts[] m = new KitMcts[1];
            KitRandom random = KitRandom.install(Seeds.worldSeed(GAME_KEY, 7, cap), ID_SEED);
            WorldBuilder.Spec spec = new WorldBuilder.Spec();
            spec.gameStart = gs;
            spec.observation = obsOf(d0);
            spec.sample = Sampler.sample(gs, obsOf(d0), random.stream("sampler"));
            spec.random = random;
            spec.viewerFactory = seat -> {
                m[0] = new KitMcts(seat, 6);
                return m[0];
            };
            spec.otherFactory = Puppet::new;
            World mw = WorldBuilder.build(spec);
            KnowledgeWatcher.install(mw.game, mw.player("p0"));
            long t0 = System.nanoTime();
            m[0].decidePriority(mw, new ObsIndex(obsOf(d0)));
            long ms = (System.nanoTime() - t0) / 1_000_000;
            Map<String, Long> cc = KitContext.counters();
            long it = cc.getOrDefault("mcts:iterations", 0L);
            rows.add(Json.map("rollout_cap", (long) cap, "iterations", it, "ms", ms, "ms_per_iteration", it == 0 ? null : ms / it,
                    "truncated_rollouts", cc.getOrDefault("mcts:truncated_rollouts", 0L), "simulations", cc.getOrDefault("simulate", 0L)));
        }
        KitContext.mctsIterations = 300;
        KitContext.rolloutCap = 2000;
        note("H3COST.cantrip", rows);
    }

    // =============================================================================================
    // E7 (MAD part): on identical worlds and seeds, with no cap firing and no horizon, KitMad chooses what upstream
    // ComputerPlayer7 (pristine sources, the same X-P4 build, kit-upstream.jar) chooses

    static void e7mad() throws Exception {
        String dir = System.getProperty("kit.e7.dir");
        java.io.File[] files = dir == null ? null : new java.io.File(dir).listFiles((d, n) -> n.startsWith("decision-") && n.endsWith(".json"));
        Class<?> probeClass;
        try {
            probeClass = Class.forName("mage.player.ai.upstream.E7Probe");
        } catch (ClassNotFoundException e) {
            check("E7.mad_reference_available", false, "kit-upstream.jar not on the classpath");
            return;
        }
        if (files == null || files.length == 0) {
            check("E7.mad_positions_available", false, dir);
            return;
        }
        java.util.Arrays.sort(files);
        int compared = 0;
        int equal = 0;
        int skippedCaps = 0;
        List<Object> differ = new ArrayList<>();
        final java.lang.reflect.Method decide = probeClass.getMethod("decide", Game.class);
        final java.lang.reflect.Constructor<?> ctor = probeClass.getConstructor(String.class, int.class);
        int errors = 0;
        for (java.io.File f : files) {
          try {
            Map<String, Object> rec = Json.parseObject(new String(java.nio.file.Files.readAllBytes(f.toPath()), "UTF-8"));
            Map<String, Object> gs = Json.obj(rec, "game_start");
            Map<String, Object> d = Json.obj(rec, "decision");
            byte[] gameKey = Seeds.gameKey(Json.num(gs, "agent_seed", 0));
            byte[] idSeed = Seeds.hmac(gameKey, "ids");
            byte[] seed = Seeds.worldSeed(gameKey, Json.num(d, "seat_step", 0), 0);
            ObsIndex idx = new ObsIndex(obsOf(d));
            // the kit's decision
            KitContext.reset();
            KitRandom random = KitRandom.install(seed, idSeed);
            WorldBuilder.Spec spec = new WorldBuilder.Spec();
            spec.gameStart = gs;
            spec.observation = obsOf(d);
            spec.sample = Sampler.sample(gs, obsOf(d), random.stream("sampler"));
            spec.random = random;
            spec.mode = WorldBuilder.Mode.PRIORITY;
            final KitMad[] kit = new KitMad[1];
            spec.viewerFactory = seat -> {
                kit[0] = new KitMad(seat, 6);
                return kit[0];
            };
            spec.otherFactory = Puppet::new;
            World wk = WorldBuilder.build(spec);
            kit[0].attach(wk);
            KitMad.PriorityOutcome ok = kit[0].decidePriority(wk, idx, false);
            Map<String, Long> cc = KitContext.counters();
            boolean capsOrHorizon = !KitContext.horizon.isEmpty() || cc.containsKey("cap:options_skipped")
                    || cc.containsKey("cap:options_truncated") || cc.containsKey("cap:operations")
                    || cc.containsKey("horizon:mad");
            for (RootStat rs : ok.stats) {
                capsOrHorizon |= "cut_nodes".equals(rs.reason) || "cut_interrupt".equals(rs.reason);
            }
            if (capsOrHorizon) {
                skippedCaps++;
                continue;
            }
            // upstream's decision on the same world and seeds
            KitContext.reset();
            KitRandom random2 = KitRandom.install(seed, idSeed);
            WorldBuilder.Spec spec2 = new WorldBuilder.Spec();
            spec2.gameStart = gs;
            spec2.observation = obsOf(d);
            spec2.sample = Sampler.sample(gs, obsOf(d), random2.stream("sampler"));
            spec2.random = random2;
            spec2.mode = WorldBuilder.Mode.PRIORITY;
            final Player[] up = new Player[1];
            spec2.viewerFactory = seat -> {
                try {
                    up[0] = (Player) ctor.newInstance(seat, 6);
                } catch (ReflectiveOperationException e) {
                    throw new IllegalStateException(e);
                }
                return up[0];
            };
            spec2.otherFactory = Puppet::new;
            World wu = WorldBuilder.build(spec2);
            Ability ua = (Ability) decide.invoke(up[0], wu.game);
            Map<String, Object> us = ua == null ? Json.map("kind", "pass") : Mapping.prioritySemantic(wu, wu.game, ua, idx);
            Map<String, Object> ks = ok.semantic == null ? Json.map("kind", "pass") : ok.semantic;
            compared++;
            if (Json.canonical(us).equals(Json.canonical(ks))) {
                equal++;
            } else {
                List<Object> roots = new ArrayList<>();
                for (int i = 0; i < ok.stats.size(); i++) {
                    roots.add(Json.map("semantic", ok.statSemantics.get(i), "adjusted", ok.stats.get(i).adjusted,
                            "tie", ok.stats.get(i).tie, "reason", ok.stats.get(i).reason));
                }
                differ.add(Json.map("file", f.getName(), "kit", ks, "upstream", us, "kit_counters", cc, "flags", wk.flags,
                        "kit_root", roots));
            }
          } catch (RuntimeException ex) {
            errors++;
            differ.add(Json.map("file", f.getName(), "error", ex.toString()));
          }
        }
        check("E7.mad_same_choice_caps_and_horizon_inactive", compared > 0 && equal == compared,
                Json.map("positions", (long) files.length, "compared", (long) compared, "equal", (long) equal,
                        "skipped_cap_or_horizon", (long) skippedCaps, "errors", (long) errors, "differ", differ));
    }

    static List<String> handNames(Game g, UUID p) {
        List<String> out = new ArrayList<>();
        for (Card c : g.getPlayer(p).getHand().getCards(g)) {
            out.add(c.getName());
        }
        Collections.sort(out);
        return out;
    }

    static Map<String, Integer> multiset(Game g, UUID p) {
        Map<String, Integer> m = new java.util.TreeMap<>();
        for (Card c : g.getPlayer(p).getHand().getCards(g)) {
            m.merge(c.getName(), 1, Integer::sum);
        }
        for (Card c : g.getPlayer(p).getLibrary().getCards(g)) {
            m.merge(c.getName(), 1, Integer::sum);
        }
        return m;
    }

    static Map<String, Integer> libMultiset(Game g, UUID p) {
        Map<String, Integer> m = new java.util.TreeMap<>();
        for (Card c : g.getPlayer(p).getLibrary().getCards(g)) {
            m.merge(c.getName(), 1, Integer::sum);
        }
        return m;
    }
}
