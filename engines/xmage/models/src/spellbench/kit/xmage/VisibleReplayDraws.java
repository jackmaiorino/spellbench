package spellbench.kit.xmage;

import spellbench.kit.core.Json;
import spellbench.kit.core.Sampler;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Random;
import java.util.HashSet;
import java.util.Set;

/** Condition an earlier sampled world on cards the viewer has since drawn and can now see. */
final class VisibleReplayDraws {
    private VisibleReplayDraws() { }

    /** Returns an earlier own draw count only when a public second-draw trigger proves it. */
    static int condition(Sampler.Sample sample, Map<String, Object> anchor,
                          Map<String, Object> current, List<Object> earlier, Random random) {
        List<Object> stack = Json.arr(anchor, "stack");
        if (stack.size() != 1) return 0;
        Map<String, Object> top = Json.obj(stack.get(0));
        String text = Json.str(top, "text");
        int count;
        if ("Kiora, the Rising Tide".equals(Json.str(top, "card_name"))
                && text != null && text.contains("draw two cards, then discard two cards")) count = 2;
        else if ("Icewind Elemental".equals(Json.str(top, "card_name"))
                && "When {this} enters, draw a card, then discard a card.".equals(text)) count = 1;
        else return 0;
        if (!"triggered_ability".equals(Json.str(top, "stack_kind"))) return 0;
        String viewer = Json.str(anchor, "viewer");
        if (!viewer.equals(Json.str(top, "controller_seat"))) return 0;
        Map<String, Object> first = null;
        for (Object entry : earlier) {
            Map<String, Object> decision = Json.obj(Json.obj(entry), "decision");
            if (firstDiscard(decision, Json.str(top, "object_id"), viewer, count)) {
                first = decision;
                break;
            }
        }
        if (first == null && firstDiscard(current, Json.str(top, "object_id"), viewer, count)) first = current;
        if (first == null) return 0;
        Map<String, Object> after = Json.obj(first, "observation");
        if (!viewer.equals(Json.str(after, "viewer"))
                || Json.num(anchor, "turn", -1) != Json.num(after, "turn", -2)
                || !Json.str(anchor, "phase_step").equals(Json.str(after, "phase_step"))) {
            throw new IllegalArgumentException("visible draw replay crossed its viewer, turn or phase");
        }
        Map<String, Object> beforePlayer = player(anchor, viewer);
        Map<String, Object> afterPlayer = player(after, viewer);
        List<Object> before = Json.arr(beforePlayer, "hand");
        List<Object> hand = Json.arr(afterPlayer, "hand");
        if (hand.size() != before.size() + count
                || Json.num(beforePlayer, "hand_count", -1) != before.size()
                || Json.num(afterPlayer, "hand_count", -1) != hand.size()
                || Json.num(beforePlayer, "library_count", -1) != Json.num(afterPlayer, "library_count", -2) + count) {
            throw new IllegalArgumentException("visible draw replay needs exactly the declared observed own draws");
        }
        // This engine emits the viewer's hand in insertion order. Preserve its
        // already-visible prefix and the order of the newly received cards.
        // Neither a hidden card nor the remaining library order is consulted.
        for (int i = 0; i < before.size(); i++) {
            Map<String, Object> old = Json.obj(before.get(i));
            Map<String, Object> now = Json.obj(hand.get(i));
            if (!Json.str(old, "object_id").equals(Json.str(now, "object_id"))
                    || !Json.str(old, "card_name").equals(Json.str(now, "card_name"))) {
                throw new IllegalArgumentException("visible draw replay changed the previous hand prefix");
            }
        }
        Sampler.SeatSample own = sample.seats.get(viewer);
        if (own == null || own.library.size() != Json.num(beforePlayer, "library_count", -1)
                || own.deficit != 0 || own.surplus != 0 || own.unknownSlots < count || own.poolSize < count) {
            throw new IllegalArgumentException("visible draw replay needs an exact sampled own library");
        }
        for (Sampler.Slot slot : own.library) {
            if (slot.pinned) throw new IllegalArgumentException("visible draw replay cannot reorder existing library pins");
        }
        List<Sampler.Slot> remaining = new ArrayList<>(own.library);
        List<Sampler.Slot> drawn = new ArrayList<>();
        Set<String> ids = new HashSet<>();
        for (Object old : before) ids.add(Json.str(Json.obj(old), "object_id"));
        for (int i = before.size(); i < hand.size(); i++) {
            Map<String, Object> card = Json.obj(hand.get(i));
            String name = Json.str(card, "card_name"), id = Json.str(card, "object_id");
            if (name == null || name.isEmpty() || id == null || id.isEmpty() || !ids.add(id)
                    || !viewer.equals(Json.str(card, "owner_seat"))
                    || !viewer.equals(Json.str(card, "controller_seat"))
                    || !"hand".equals(Json.str(card, "zone"))) {
                throw new IllegalArgumentException("visible draw replay accepts only named own-hand cards");
            }
            List<Integer> matches = new ArrayList<>();
            for (int j = 0; j < remaining.size(); j++) {
                if (name.equals(remaining.get(j).name)) matches.add(j);
            }
            if (matches.isEmpty()) throw new IllegalArgumentException("visible drawn card is absent from the sampled pool");
            // Choosing a physical copy uniformly avoids biasing the remaining
            // permutation when several copies have the same card name.
            remaining.remove((int) matches.get(random.nextInt(matches.size())));
            drawn.add(new Sampler.Slot(name, id, true));
        }
        int priorOwnDraws = count == 1 && publicSecondDraw(anchor, after, viewer) ? 1 : 0;
        own.library.clear();
        own.library.addAll(drawn);
        own.library.addAll(remaining);
        own.unknownSlots -= count;
        own.poolSize -= count;
        own.pinned += count;
        sample.flags.add("replay:visible_own_draw_conditioning");
        return priorOwnDraws;
    }

    private static boolean publicSecondDraw(Map<String, Object> before, Map<String, Object> after, String viewer) {
        if (!Json.arr(before, "pending_triggers").isEmpty()) return false;
        List<Object> pending = Json.arr(after, "pending_triggers");
        if (pending.size() != 1) return false;
        Map<String, Object> trigger = Json.obj(pending.get(0));
        Map<String, Object> source = Json.obj(trigger, "source");
        if (source == null || !Boolean.FALSE.equals(trigger.get("optional"))
                || !viewer.equals(Json.str(trigger, "controller_seat"))
                || !"Mischievous Mystic".equals(Json.str(source, "card_name"))
                || !viewer.equals(Json.str(source, "owner_seat"))
                || !viewer.equals(Json.str(source, "controller_seat"))
                || !"battlefield".equals(Json.str(source, "zone"))) return false;
        String id = Json.str(source, "object_id");
        if (id == null || id.isEmpty()) return false;
        for (Object item : Json.arr(player(before, viewer), "battlefield")) {
            Map<String, Object> card = Json.obj(item);
            if (id.equals(Json.str(card, "object_id"))
                    && "Mischievous Mystic".equals(Json.str(card, "card_name"))
                    && Boolean.FALSE.equals(card.get("face_down"))
                    && viewer.equals(Json.str(card, "owner_seat"))
                    && viewer.equals(Json.str(card, "controller_seat"))) return true;
        }
        return false;
    }

    private static Map<String, Object> player(Map<String, Object> observation, String seat) {
        for (Object item : Json.arr(observation, "players")) {
            Map<String, Object> player = Json.obj(item);
            if (seat.equals(Json.str(player, "seat"))) return player;
        }
        throw new IllegalArgumentException("visible draw replay lacks its viewer player");
    }

    private static boolean firstDiscard(Map<String, Object> decision, String sourceId, String viewer, int count) {
        if (decision == null || !viewer.equals(Json.str(decision, "acting_seat"))) return false;
        Map<String, Object> context = Json.obj(decision, "context");
        if (!"choice".equals(Json.str(context, "kind")) || !"discard".equals(Json.str(context, "purpose"))
                || !sourceId.equals(Json.str(Json.obj(context, "source"), "object_id"))) return false;
        List<Object> candidates = Json.arr(decision, "candidates");
        if (candidates.isEmpty()) return false;
        for (Object item : candidates) {
            Map<String, Object> semantic = Json.obj(Json.obj(item), "semantic");
            if (!"select_object".equals(Json.str(semantic, "kind"))
                    || !"discard".equals(Json.str(semantic, "purpose"))
                    || Json.num(semantic, "minimum", -1) != count || Json.num(semantic, "maximum", -1) != count
                    || Json.num(semantic, "selected_count", -1) != 0) return false;
        }
        return true;
    }
}
