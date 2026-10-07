package spellbench.kit.xmage;

import spellbench.kit.core.Json;
import spellbench.kit.core.Sampler;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.Random;

/** Public own-hand conditioning and refusal regressions. No game, database, model or hidden-state input. */
public final class VisibleReplayDrawsCheck {
    private static final String RULE = "When {this} enters, draw two cards, then discard two cards.";

    private static void require(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }

    private static Map<String, Object> card(String id, String name) {
        return Json.map("object_id", id, "card_name", name, "zone", "hand",
                "owner_seat", "p0", "controller_seat", "p0");
    }

    private static Map<String, Object> observation(boolean after) {
        List<Object> hand = new ArrayList<>();
        hand.add(card("old", "Essence Scatter"));
        if (after) {
            hand.add(card("drawn-island", "Island"));
            hand.add(card("drawn-mystic", "Mischievous Mystic"));
        }
        return Json.map("viewer", "p0", "turn", 8L, "phase_step", "precombat_main",
                "stack", Arrays.asList(Json.map("card_name", "Kiora, the Rising Tide", "object_id", "trigger",
                        "stack_kind", "triggered_ability", "controller_seat", "p0", "text", RULE)),
                "players", Arrays.asList(Json.map("seat", "p0", "hand", hand, "hand_count", (long) hand.size(),
                                "library_count", after ? 2L : 4L),
                        Json.map("seat", "p1", "hand", null, "hand_count", 2L, "library_count", 5L)));
    }

    private static Map<String, Object> decision() {
        return Json.map("acting_seat", "p0", "observation", observation(true),
                "context", Json.map("kind", "choice", "purpose", "discard", "source", Json.map("object_id", "trigger")),
                "candidates", Arrays.asList(Json.map("semantic", Json.map("kind", "select_object", "purpose", "discard",
                        "minimum", 2L, "maximum", 2L, "selected_count", 0L))));
    }

    private static Sampler.Sample sample() {
        Sampler.Sample sample = new Sampler.Sample();
        Sampler.SeatSample own = new Sampler.SeatSample("p0");
        for (String name : new String[]{"Island", "Mountain", "Island", "Mischievous Mystic"}) {
            own.library.add(new Sampler.Slot(name, null, false));
        }
        own.unknownSlots = own.poolSize = 4;
        own.publicCards = 1;
        Sampler.SeatSample other = new Sampler.SeatSample("p1");
        other.hand.add(new Sampler.Slot("sampled opponent card", null, false));
        other.library.add(new Sampler.Slot("sampled opponent library", null, false));
        sample.seats.put("p0", own);
        sample.seats.put("p1", other);
        return sample;
    }

    private static Map<String, Object> icewindObservation(boolean after) {
        Map<String, Object> observation = observation(after);
        Map<String, Object> top = Json.obj(Json.arr(observation, "stack").get(0));
        top.put("card_name", "Icewind Elemental");
        top.put("text", "When {this} enters, draw a card, then discard a card.");
        Map<String, Object> own = Json.obj(Json.arr(observation, "players").get(0));
        if (after) {
            Json.arr(own, "hand").remove(2);
            own.put("hand_count", 2L);
            own.put("library_count", 3L);
        }
        Map<String, Object> mystic = card("mystic", "Mischievous Mystic");
        mystic.put("zone", "battlefield"); mystic.put("face_down", false);
        mystic.put("copy", false); mystic.put("token", false);
        own.put("battlefield", Arrays.asList(mystic));
        observation.put("pending_triggers", after ? Arrays.asList(Json.map("controller_seat", "p0",
                "optional", false, "source", Json.copy(mystic))) : new ArrayList<>());
        return observation;
    }

    private static Map<String, Object> icewindDecision() {
        Map<String, Object> decision = decision();
        decision.put("observation", icewindObservation(true));
        Map<String, Object> semantic = Json.obj(Json.obj(Json.arr(decision, "candidates").get(0)), "semantic");
        semantic.put("minimum", 1L); semantic.put("maximum", 1L);
        return decision;
    }

    private static void icewind() {
        Sampler.Sample sample = sample();
        Map<String, Object> anchor = icewindObservation(false), decision = icewindDecision();
        int prior = VisibleReplayDraws.condition(sample, anchor, decision, Collections.emptyList(), new Random(3));
        require(prior == 1, "public second-draw trigger did not prove the earlier own draw");
        Sampler.SeatSample own = sample.seats.get("p0");
        require(own.library.size() == 4 && own.unknownSlots == 3 && own.poolSize == 3 && own.pinned == 1,
                "single-draw conditioning changed physical counts");
        require("drawn-island".equals(own.library.get(0).objectId), "single visible draw was not conditioned");
        for (String fault : new String[]{"no-trigger", "opponent", "wrong-source", "absent-source", "face-down", "copy", "token"}) {
            Map<String, Object> before = icewindObservation(false), current = icewindDecision();
            Map<String, Object> after = Json.obj(current, "observation");
            Map<String, Object> trigger = Json.obj(Json.arr(after, "pending_triggers").get(0));
            if (fault.equals("no-trigger")) after.put("pending_triggers", new ArrayList<>());
            if (fault.equals("opponent")) trigger.put("controller_seat", "p1");
            if (fault.equals("wrong-source")) Json.obj(trigger, "source").put("card_name", "other card");
            if (fault.equals("absent-source")) Json.obj(Json.arr(before, "players").get(0)).put("battlefield", new ArrayList<>());
            if (fault.equals("face-down")) Json.obj(Json.arr(Json.obj(Json.arr(before, "players").get(0)), "battlefield").get(0)).put("face_down", true);
            if (fault.equals("copy") || fault.equals("token")) Json.obj(Json.arr(Json.obj(Json.arr(before, "players").get(0)), "battlefield").get(0)).put(fault, true);
            require(VisibleReplayDraws.condition(sample(), before, current, Collections.emptyList(), new Random(3)) == 0,
                    "unproven watcher history was restored: " + fault);
        }
    }

    private static void refuse(String fault) {
        Sampler.Sample sample = sample();
        Map<String, Object> current = decision();
        Map<String, Object> observation = Json.obj(current, "observation");
        Map<String, Object> player = Json.obj(Json.arr(observation, "players").get(0));
        List<Object> hand = Json.arr(player, "hand");
        if (fault.equals("viewer")) observation.put("viewer", "p1");
        if (fault.equals("turn")) observation.put("turn", 9L);
        if (fault.equals("count")) player.put("library_count", 1L);
        if (fault.equals("prefix")) Json.obj(hand.get(0)).put("card_name", "Mountain");
        if (fault.equals("opponent")) Json.obj(hand.get(1)).put("owner_seat", "p1");
        if (fault.equals("duplicate")) Json.obj(hand.get(1)).put("object_id", "old");
        if (fault.equals("absent")) Json.obj(hand.get(1)).put("card_name", "unavailable card");
        if (fault.equals("pin")) sample.seats.get("p0").library.set(0, new Sampler.Slot("Island", "existing-pin", true));
        String before = Json.canonical(sample.json());
        try {
            VisibleReplayDraws.condition(sample, observation(false), current, Collections.emptyList(), new Random(3));
            throw new AssertionError("invalid public draw accepted: " + fault);
        } catch (IllegalArgumentException expected) {
            require(before.equals(Json.canonical(sample.json())), "failed conditioning mutated the sample: " + fault);
        }
    }

    public static void main(String[] args) {
        Sampler.Sample sample = sample(), repeat = sample();
        Map<String, Object> opponentBefore = Json.obj(Json.obj(sample.json(), "seats"), "p1");
        VisibleReplayDraws.condition(sample, observation(false), decision(), Collections.emptyList(), new Random(3));
        VisibleReplayDraws.condition(repeat, observation(false), decision(), Collections.emptyList(), new Random(3));
        Sampler.SeatSample own = sample.seats.get("p0");
        require(own.library.size() == 4 && own.unknownSlots == 2 && own.poolSize == 2 && own.pinned == 2,
                "conditioning changed physical counts");
        require(own.publicCards + own.unknownSlots + own.pinned == 5, "physical partition changed");
        require("drawn-island".equals(own.library.get(0).objectId)
                && "drawn-mystic".equals(own.library.get(1).objectId), "drawn public identities/order were not retained");
        require(own.library.get(0).pinned && own.library.get(1).pinned, "drawn facts were not conditioned");
        require(Json.canonical(sample.json()).equals(Json.canonical(repeat.json())), "conditioning is nondeterministic");
        require(Json.canonical(opponentBefore).equals(Json.canonical(Json.obj(Json.obj(sample.json(), "seats"), "p1"))),
                "conditioning changed an opponent sample");
        Map<String, Object> second = decision();
        Json.obj(Json.obj(Json.arr(second, "candidates").get(0)), "semantic").put("selected_count", 1L);
        Sampler.Sample later = sample();
        VisibleReplayDraws.condition(later, observation(false), second,
                Arrays.asList(Json.map("decision", decision())), new Random(3));
        require(Json.canonical(sample.json()).equals(Json.canonical(later.json())), "earlier first discard was lost");
        Sampler.Sample unchanged = sample();
        String unchangedBefore = Json.canonical(unchanged.json());
        Map<String, Object> noText = observation(false);
        Json.obj(Json.arr(noText, "stack").get(0)).put("text", null);
        VisibleReplayDraws.condition(unchanged, noText, decision(), Collections.emptyList(), new Random(3));
        require(unchangedBefore.equals(Json.canonical(unchanged.json())), "default no-text replay changed");
        Sampler.Sample firstCopy = sample(), lastCopy = sample();
        VisibleReplayDraws.condition(firstCopy, observation(false), decision(), Collections.emptyList(),
                new Random() { @Override public int nextInt(int bound) { return 0; } });
        VisibleReplayDraws.condition(lastCopy, observation(false), decision(), Collections.emptyList(),
                new Random() { @Override public int nextInt(int bound) { return bound - 1; } });
        require("Mountain".equals(firstCopy.seats.get("p0").library.get(2).name)
                && "Island".equals(lastCopy.seats.get("p0").library.get(2).name),
                "duplicate-name removal always selected the first physical copy");
        for (String fault : new String[]{"viewer", "turn", "count", "prefix", "opponent", "duplicate", "absent", "pin"}) refuse(fault);
        icewind();
        System.out.println("public own-draw replay conditioning: PASS");
    }
}
