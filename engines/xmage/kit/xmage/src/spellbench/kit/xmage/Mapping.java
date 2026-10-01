package spellbench.kit.xmage;

import mage.abilities.Ability;
import mage.abilities.ActivatedAbility;
import mage.abilities.Mode;
import mage.abilities.Modes;
import mage.abilities.SpellAbility;
import mage.abilities.common.PassAbility;
import mage.abilities.costs.Cost;
import mage.cards.Card;
import mage.cards.DoubleFacedCard;
import mage.game.Game;
import mage.game.stack.Spell;
import mage.game.stack.StackAbility;
import mage.game.stack.StackObject;
import mage.player.spellbench.decide.KitBridge;
import mage.target.Target;
import mage.target.TargetAmount;
import spellbench.kit.core.Json;
import spellbench.kit.core.ObsIndex;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * From world actions back to v2 (design Section 6): the priority semantic of an XMage action computed on the world
 * with the engine's own functions ({@code KitBridge}: {@code ability_index}, cast {@code method}), its key (Section
 * 5.5.2: the canonical JSON of the full semantic), and the executed payload of an activation (Section 5.5.3).
 */
public final class Mapping {

    private Mapping() {
    }

    /** {"player": seat}, {"object_id": id} or null for a world UUID. */
    public static Map<String, Object> targetRef(World w, UUID id) {
        if (id == null) {
            return null;
        }
        String seat = w.seatOf(id);
        if (seat != null) {
            return Json.map("player", seat);
        }
        String oid = w.uuidToId.get(id);
        return oid == null ? null : Json.map("object_id", oid);
    }

    /**
     * The v2 priority semantic of {@code a} on the world (Section 7.2), with references taken from the observation,
     * or null when the action has no v2 form (an unmapped source).
     */
    public static Map<String, Object> prioritySemantic(World w, Game game, Ability a, ObsIndex obs) {
        if (a == null || a instanceof PassAbility) {
            return Json.map("kind", "pass");
        }
        UUID src = a.getSourceId();
        String oid = src == null ? null : w.uuidToId.get(src);
        Map<String, Object> ref = obs.ref(oid);
        if (ref == null) {
            return null;
        }
        switch (a.getAbilityType()) {
            case PLAY_LAND: {
                long face = isBackFace(game, src) ? 1 : 0;
                return Json.map("kind", "play_land", "source", ref, "face", face);
            }
            case SPELL:
                return Json.map("kind", "cast_spell", "source", ref, "method", KitBridge.castMethod((SpellAbility) a));
            case ACTIVATED_NONMANA: {
                long index = KitBridge.abilityIndex(game, a);
                if (index < 0) {
                    index = 1000;
                }
                return Json.map("kind", "activate_ability", "source", ref, "ability_index", index);
            }
            case SPECIAL_ACTION:
                return Json.map("kind", "special_action", "source", ref, "action", specialAction(a));
            default:
                return null;
        }
    }

    public static String key(Map<String, Object> semantic) {
        return semantic == null ? null : Json.canonical(semantic);
    }

    static boolean isBackFace(Game game, UUID sourceId) {
        Card card = game.getCard(sourceId);
        if (card == null) {
            return false;
        }
        Card main = card.getMainCard();
        return main instanceof DoubleFacedCard && !main.getId().equals(sourceId)
                && ((DoubleFacedCard) main).getRightHalfCard().getId().equals(sourceId);
    }

    /** Copied from the engine's {@code SeatPlayer.specialAction} (private there). */
    static String specialAction(Ability a) {
        String cls = a.getClass().getSimpleName();
        if (cls.contains("TurnFaceUp")) {
            return "turn_face_up";
        }
        if (cls.contains("Plot")) {
            return "plot";
        }
        if (cls.contains("Foretell")) {
            return "foretell";
        }
        if (cls.contains("Suspend")) {
            return "suspend";
        }
        if (cls.contains("Unlock") || cls.contains("Door")) {
            return "unlock_door";
        }
        return "other";
    }

    /**
     * The choices an ability carries (targets per requirement across the selected modes, modes, X, divided amounts,
     * cost targets), read from {@code executed}: the spell or stack ability the activation put on the stack, or an
     * option of the search (which carries its preselected targets).
     */
    public static Map<String, Object> payload(World w, Ability executed, Game game) {
        Map<String, Object> out = new LinkedHashMap<>();
        if (executed == null) {
            return out;
        }
        List<Object> slots = new ArrayList<>();
        List<Object> divided = new ArrayList<>();
        Modes modes = executed.getModes();
        for (UUID modeId : modes.getSelectedModes()) {
            Mode mode = modes.get(modeId);
            if (mode == null) {
                continue;
            }
            for (Target t : mode.getTargets()) {
                List<Object> slot = new ArrayList<>();
                for (UUID id : t.getTargets()) {
                    slot.add(targetRef(w, id));
                    if (t instanceof TargetAmount) {
                        divided.add((long) t.getTargetAmount(id));
                    }
                }
                slots.add(slot);
            }
        }
        out.put("targets", slots);
        if (!divided.isEmpty()) {
            out.put("divided", divided);
        }
        if (modes.size() > 1) {
            List<Object> chosen = new ArrayList<>();
            int index = 0;
            for (Mode mode : modes.values()) {
                for (int n = modes.getSelectedStats(mode.getId()); n > 0; n--) {
                    chosen.add((long) index);
                }
                index++;
            }
            out.put("modes", chosen);
        }
        Map<String, Object> tags = executed.getCostsTagMap();
        Object x = tags == null ? null : tags.get("X");
        if (x instanceof Integer) {
            out.put("x", ((Integer) x).longValue());
        }
        List<Object> costTargets = new ArrayList<>();
        for (Cost c : executed.getCosts()) {
            for (Target t : c.getTargets()) {
                for (UUID id : t.getTargets()) {
                    costTargets.add(targetRef(w, id));
                }
            }
        }
        if (!costTargets.isEmpty()) {
            out.put("cost_targets", costTargets);
        }
        return out;
    }

    /** The executed object of the activation that just put {@code top} on the stack (N1: never the option object). */
    public static Ability executedAbility(StackObject top) {
        if (top instanceof Spell) {
            return ((Spell) top).getSpellAbility();
        }
        if (top instanceof StackAbility) {
            return ((StackAbility) top).getStackAbility(); // its own getCosts() is empty; the underlying ability holds them
        }
        return null;
    }

    public static boolean isActivated(Ability a) {
        return a instanceof ActivatedAbility;
    }
}
