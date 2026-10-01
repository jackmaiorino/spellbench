package spellbench.kit.xmage;

import mage.abilities.Ability;
import mage.cards.Cards;
import mage.constants.Outcome;
import mage.game.Game;
import mage.game.stack.StackObject;
import mage.players.Player;
import mage.players.PlayerImpl;
import mage.target.Target;
import mage.target.TargetCard;
import spellbench.kit.core.Json;
import spellbench.kit.core.ObsCompare;
import spellbench.kit.core.Sampler;

import java.io.Serializable;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

/**
 * Saved-anchor continuation (design Section 5.1). The anchor is the priority decision at which the resolving object
 * S was on top of the stack; the front keeps its inputs (observation and world seed), so an anchor survives a runner
 * restart (it is rebuilt, never held in runner memory). Steps:
 * <ol>
 * <li>condition the anchor's hidden zones on the current observation: cards that entered the viewer's hand since the
 * anchor are pinned on top of its library, in order (the effect drew them from there);</li>
 * <li>rebuild the anchor world, let both seats pass, and resolve S (nothing is re-executed from a later snapshot, so no
 * effect is repeated);</li>
 * <li>at the first dialog of the resolution, compare the world's projected observation with the received one modulo
 * ids; on equality the bot answers there, else the caller takes the current-dialog path.</li>
 * </ol>
 * This release continues only at the first dialog of a resolution (earlier dialogs would be replayed from the
 * recorded answers; with none recorded the case does not arise for the slice's cards).
 */
public final class Continuation {

    private Continuation() {
    }

    /** Ends the resolution once the current dialog is answered or found different. */
    static final class Stop extends Error {
        private static final long serialVersionUID = 1L;

        Stop() {
            super("continuation stop", null, false, false);
        }
    }

    /** The decider during a continuation: intercepts the first dialog of the resolution. */
    static final class Continuer extends KitMad {
        private static final long serialVersionUID = 1L;
        transient boolean armed;
        transient boolean finish;
        transient Map<String, Object> current;
        transient Map<String, Object> flags;
        transient World w;
        transient Map<String, Object> result;

        Continuer(String name, int skill) {
            super(name, skill);
        }

        private Continuer(final Continuer c) {
            super(c);
        }

        @Override
        public Continuer copy() {
            return new Continuer(this);
        }

        private void intercept(Target target, Game game) {
            armed = false;
            result.put("hand_at_dialog", (long) w.viewerPlayer().getHand().size());
            result.put("library_at_dialog", (long) w.viewerPlayer().getLibrary().size());
            bindLooks(game);
            Map<String, Object> projected;
            try {
                projected = RoundTrip.project(w, flags, Json.str(current, "priority_seat"), Json.arr(current, "known"));
            } catch (Exception e) {
                result.put("match", false);
                result.put("diff", java.util.Collections.singletonList("projection failed: " + e));
                throw new Stop();
            }
            List<String> diff = ObsCompare.diff(current, projected, 40);
            result.put("diff", new ArrayList<Object>(diff));
            if (!diff.isEmpty()) {
                result.put("match", false);
                throw new Stop();
            }
            result.put("match", true);
            result.put("align", ObsCompare.alignIds(projected, current));
            result.put("projected", projected);
        }

        /**
         * The cards the current decision shows (known entries with ids) are the world's cards at those places: a
         * positional library entry is the card at that position, a searched one the first unbound card of that name
         * in that library, another seat's hand entry the first unbound card of that name in that hand.
         */
        private void bindLooks(Game game) {
            java.util.Set<UUID> used = new java.util.HashSet<>(w.idToUuid.values());
            for (Object o : Json.arr(current, "known")) {
                Map<String, Object> k = Json.obj(o);
                String oid = Json.str(k, "object_id");
                if (oid == null || w.idToUuid.containsKey(oid)) {
                    continue;
                }
                Player owner = game.getPlayer(w.player(Json.str(k, "owner_seat")));
                List<mage.cards.Card> zone = "library".equals(Json.str(k, "zone"))
                        ? owner.getLibrary().getCards(game) : new ArrayList<>(owner.getHand().getCards(game));
                mage.cards.Card pick = null;
                Object top = k.get("position_from_top");
                Object bottom = k.get("position_from_bottom");
                if (top instanceof Number && ((Number) top).intValue() < zone.size()) {
                    pick = zone.get(((Number) top).intValue());
                } else if (bottom instanceof Number && ((Number) bottom).intValue() < zone.size()) {
                    pick = zone.get(zone.size() - 1 - ((Number) bottom).intValue());
                } else {
                    for (mage.cards.Card c : zone) {
                        if (!used.contains(c.getId()) && c.getName().equals(Json.str(k, "card_name"))) {
                            pick = c;
                            break;
                        }
                    }
                }
                if (pick != null && pick.getName().equals(Json.str(k, "card_name"))) {
                    w.bind(oid, pick.getId());
                    used.add(pick.getId());
                }
            }
        }

        private List<Object> picks(Target target, Game game) {
            @SuppressWarnings("unchecked")
            Map<String, String> align = (Map<String, String>) result.get("align");
            @SuppressWarnings("unchecked")
            Map<String, Object> projected = (Map<String, Object>) result.get("projected");
            List<Object> out = new ArrayList<>();
            for (UUID id : target.getTargets()) {
                Map<String, Object> ref = Mapping.targetRef(w, id);
                if (ref != null && ref.get("object_id") != null) {
                    out.add(ref); // an object the world bound to a current id (visible since the anchor)
                    continue;
                }
                // an object the world created as hidden: find it through the projection
                String projectedId = projectedIdOf(game, id);
                String currentId = projectedId == null ? null : align.get(projectedId);
                out.add(currentId == null ? null : Json.map("object_id", currentId));
            }
            return out;
        }

        private String projectedIdOf(Game game, UUID id) {
            try {
                mage.player.spellbench.observe.ObservationBuilder b = mage.player.spellbench.observe.ObservationBuilder
                        .forSession(game, new byte[32], flags);
                return Json.str(b.build(w.viewer, Json.str(current, "priority_seat"), new ArrayList<>()).reference(id), "object_id");
            } catch (Exception e) {
                return null;
            }
        }

        @Override
        public boolean choose(Outcome outcome, Target target, Ability source, Game game, Map<String, Serializable> options) {
            if (!armed || game.isSimulation()) {
                return super.choose(outcome, target, source, game, options);
            }
            intercept(target, game);
            boolean r = super.choose(outcome, target, source, game, options);
            result.put("picks", picks(target, game));
            if (!finish) {
                throw new Stop();
            }
            return true;
        }

        @Override
        public boolean choose(Outcome outcome, Cards cards, TargetCard target, Ability source, Game game) {
            if (!armed || game.isSimulation()) {
                return super.choose(outcome, cards, target, source, game);
            }
            intercept(target, game);
            super.choose(outcome, cards, target, source, game);
            result.put("picks", picks(target, game));
            if (!finish) {
                throw new Stop();
            }
            return true;
        }

        @Override
        public boolean chooseTarget(Outcome outcome, Cards cards, TargetCard target, Ability source, Game game) {
            if (!armed || game.isSimulation()) {
                return super.chooseTarget(outcome, cards, target, source, game);
            }
            intercept(target, game);
            super.chooseTarget(outcome, cards, target, source, game);
            result.put("picks", picks(target, game));
            if (!finish) {
                throw new Stop();
            }
            return true;
        }

        @Override
        public boolean chooseTarget(Outcome outcome, Target target, Ability source, Game game) {
            if (!armed || game.isSimulation()) {
                return super.chooseTarget(outcome, target, source, game);
            }
            intercept(target, game);
            super.chooseTarget(outcome, target, source, game);
            result.put("picks", picks(target, game));
            if (!finish) {
                throw new Stop();
            }
            return true;
        }
    }

    /**
     * Runs one continuation. {@code anchor} = {decision, world_seeds, seat_step}; {@code earlier} = this seat's answers
     * with this source so far; returns {match, picks, diff, flags}.
     */
    public static Map<String, Object> run(Map<String, Object> gameStart, byte[] idSeed, Map<String, Object> anchor,
                                          List<Object> earlier, Map<String, Object> decision, int skill) {
        return run(gameStart, idSeed, anchor, earlier, decision, skill, false);
    }

    /**
     * With {@code finish}, the bot's answer at the current dialog does not end the resolution: it completes (later
     * dialogs answered by the bot), and the result carries the world's observation after it ("after"), with priority
     * to the active seat: the fixtures' resolution transition (design Section 7.1).
     */
    public static Map<String, Object> run(Map<String, Object> gameStart, byte[] idSeed, Map<String, Object> anchor,
                                          List<Object> earlier, Map<String, Object> decision, int skill, boolean finish) {
        Map<String, Object> out = new LinkedHashMap<>();
        if (!earlier.isEmpty()) {
            out.put("match", false);
            out.put("diff", java.util.Collections.singletonList("unsupported: a later dialog of the same resolution"));
            return out;
        }
        Map<String, Object> anchorDecision = Json.obj(anchor, "decision");
        @SuppressWarnings("unchecked")
        Map<String, Object> aobs = (Map<String, Object>) Json.copy(Json.obj(anchorDecision, "observation"));
        Map<String, Object> current = Json.obj(decision, "observation");
        String viewer = Json.str(current, "viewer");
        String source = Json.str(Json.obj(Json.obj(decision, "context"), "source"), "object_id");
        // 1. conditioning: cards new in the viewer's hand were drawn from the top of its library
        Set<String> before = new LinkedHashSet<>();
        for (Object p : Json.arr(aobs, "players")) {
            Map<String, Object> pm = Json.obj(p);
            if (viewer.equals(Json.str(pm, "seat"))) {
                for (Object o : Json.arr(pm, "hand")) {
                    before.add(Json.str(Json.obj(o), "object_id"));
                }
            }
        }
        List<String> drawn = new ArrayList<>();
        for (Object p : Json.arr(current, "players")) {
            Map<String, Object> pm = Json.obj(p);
            if (viewer.equals(Json.str(pm, "seat"))) {
                for (Object o : Json.arr(pm, "hand")) {
                    Map<String, Object> rec = Json.obj(o);
                    if (!before.contains(Json.str(rec, "object_id"))) {
                        drawn.add(Json.str(rec, "card_name"));
                    }
                }
            }
        }
        List<Object> known = new ArrayList<>(Json.arr(aobs, "known"));
        for (int i = 0; i < drawn.size(); i++) {
            known.add(Json.map("owner_seat", viewer, "zone", "library", "card_name", drawn.get(i), "object_id", null,
                    "position_from_top", (long) i, "position_from_bottom", null, "how", "looked_at"));
        }
        // what the current decision shows of the viewer's library is pinned too, at the anchor's positions (the
        // drawn cards were above it then), with its current ids so the world's cards answer to them
        for (Object o : Json.arr(current, "known")) {
            Map<String, Object> k = Json.obj(o);
            if (!"library".equals(Json.str(k, "zone")) || !viewer.equals(Json.str(k, "owner_seat"))) {
                continue;
            }
            Object top = k.get("position_from_top");
            Map<String, Object> pin = new LinkedHashMap<>(k);
            if (top instanceof Number) {
                pin.put("position_from_top", ((Number) top).longValue() + drawn.size());
            }
            known.add(pin);
        }
        aobs.put("known", known);
        out.put("conditioned_drawn", new ArrayList<Object>(drawn));
        // 2. the anchor world
        byte[] seed = spellbench.kit.core.Seeds.unhex((String) Json.arr(anchor, "world_seeds").get(0));
        KitContext.reset();
        KitRandom random = KitRandom.install(seed, idSeed);
        Sampler.Sample sample = Sampler.sample(gameStart, aobs, random.stream("sampler"));
        WorldBuilder.Spec spec = new WorldBuilder.Spec();
        spec.gameStart = gameStart;
        spec.observation = aobs;
        spec.sample = sample;
        spec.random = random;
        spec.mode = WorldBuilder.Mode.PRIORITY;
        final Continuer[] decider = new Continuer[1];
        spec.viewerFactory = seat -> {
            decider[0] = new Continuer(seat, skill);
            return decider[0];
        };
        spec.otherFactory = Puppet::new;
        World w = WorldBuilder.build(spec);
        decider[0].attach(w);
        out.put("flags", new ArrayList<Object>(w.flags));
        Game game = w.game;
        UUID s = w.idToUuid.get(source);
        StackObject top = game.getStack().getFirstOrNull();
        if (s == null || top == null || !top.getId().equals(s)) {
            out.put("match", false);
            out.put("diff", java.util.Collections.singletonList("the anchor's top object is not the source"));
            return out;
        }
        Continuer c = decider[0];
        c.w = w;
        c.current = current;
        c.flags = RoundTrip.flagsFrom(decision);
        c.result = out;
        c.armed = true;
        c.finish = finish;
        // 3. both seats pass; S resolves (ComputerPlayer6.resolve, without the search hints)
        for (UUID pid : w.seatPlayer.values()) {
            Player p = game.getPlayer(pid);
            p.pass(game);
            Reflect.set(PlayerImpl.class, p, "passed", true);
        }
        int handBefore = w.viewerPlayer().getHand().size();
        int libraryBefore = w.viewerPlayer().getLibrary().size();
        try {
            top.resolve(game);
            if (!out.containsKey("match")) {
                out.put("match", false);
                out.put("diff", java.util.Collections.singletonList("resolution ended without a dialog"));
            }
            if (finish && Boolean.TRUE.equals(out.get("match"))) {
                out.put("after", Resolver.finishAndProject(w, top, RoundTrip.flagsFrom(decision)));
            }
        } catch (Stop stop) {
            // the current dialog was reached
        }
        out.put("hand_before", (long) handBefore);
        out.put("library_before", (long) libraryBefore);
        out.remove("align");
        out.remove("projected");
        return out;
    }
}
