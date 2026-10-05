package spellbench.kit.xmage;

import mage.abilities.Ability;
import mage.abilities.Mode;
import mage.abilities.Modes;
import mage.game.Game;
import mage.game.stack.StackObject;
import spellbench.kit.core.Json;
import spellbench.kit.core.ObsIndex;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Iterator;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

/** Binds the original numeric mode ordinals to the public engine's mode indices. */
final class ModelModes {
    final List<Mode> options = new ArrayList<>();
    final Map<Integer, Map<String, Object>> actions = new HashMap<>();
    final List<Integer> publicIndices = new ArrayList<>();

    ModelModes(World world, Map<String, Object> decision, Modes modes, Ability source, Game game) {
        this(world, decision, modes, source, game, true);
    }

    ModelModes(World world, Map<String, Object> decision, Modes modes, Ability source, Game game,
               boolean includeStop) {
        if (source == null || !world.player(world.viewer).equals(source.getControllerId())) {
            throw new IllegalArgumentException("mode callback needs the viewer's actual source ability");
        }
        Map<String, Object> reference = Json.obj(Json.obj(decision, "context"), "source");
        UUID id = visibleSource(world, decision, reference, game);
        if (id == null || !(id.equals(source.getSourceId())
                || game.getStack().getStackObject(id) != null
                && source.getSourceId().equals(game.getStack().getStackObject(id).getSourceId()))) {
            throw new IllegalArgumentException("mode candidate belongs to a different source");
        }
        List<Mode> all = new ArrayList<>(modes.values());
        // Exp1 always prepends stop. MageZero v0.2 prepends it only when its
        // minimum is met. Preserve the resulting original numeric ordinals.
        if (includeStop) options.add(null);
        for (Mode mode : modes.getAvailableModes(source, game)) {
            if (!modes.getSelectedModes().contains(mode.getId())
                    && mode.getTargets().canChoose(source.getControllerId(), source, game)) {
                options.add(mode);
            }
        }
        if (options.size() > 65) throw new IllegalArgumentException("mode callback exceeds the original numeric clamp");
        for (int i = 0; i < options.size(); i++) {
            if (options.get(i) == null) { publicIndices.add(-1); continue; }
            int index = all.indexOf(options.get(i));
            if (index < 0) throw new IllegalArgumentException("available mode is absent from the actual source");
            publicIndices.add(index);
        }
        Set<Integer> used = new HashSet<>();
        for (Object item : Json.arr(decision, "candidates")) {
            Map<String, Object> action = Json.obj(Json.obj(item), "semantic");
            String kind = Json.str(action, "kind");
            if (!Json.canonical(reference).equals(Json.canonical(action.get("source")))) {
                throw new IllegalArgumentException("mode candidate source differs from the verified callback source");
            }
            int ordinal;
            if ("choose_spell_mode".equals(kind)) {
                Object index = action.get("mode_index");
                if (!(index instanceof Long) || (Long) index < 0 || (Long) index >= all.size()
                        || Json.num(action, "mode_count", -1) != all.size()
                        || Json.num(action, "selected_count", -1) != modes.getSelectedModes().size()
                        || Json.num(action, "minimum", -1) != modes.getMinModes()
                        || Json.num(action, "maximum", -1) != Math.min(modes.getMaxModes(game, source), all.size())) {
                    throw new IllegalArgumentException("mode candidate count or range differs from the actual callback");
                }
                ordinal = options.indexOf(all.get(Math.toIntExact((Long) index)));
                if (ordinal < 0 || options.get(ordinal) == null) {
                    throw new IllegalArgumentException("offered mode is unavailable to the original policy");
                }
            } else if ("finish_selection".equals(kind) && "modes".equals(Json.str(action, "purpose"))) {
                if (Json.num(action, "selected_count", -1) != modes.getSelectedModes().size()) {
                    throw new IllegalArgumentException("mode stop candidate has a different selected count");
                }
                int selected = modes.getSelectedModes().size();
                if (!(modes.getMaxPawPrints() > 0 ? selected > 0
                        : selected >= modes.getMinModes() || modes.isMayChooseNone() && selected == 0)) {
                    throw new IllegalArgumentException("mode stop is offered before the actual callback permits it");
                }
                ordinal = options.indexOf(null);
                if (ordinal < 0) throw new IllegalArgumentException("original mode callback has no stop ordinal");
            } else {
                throw new IllegalArgumentException("mode decision mixes unrelated candidate families");
            }
            if (!used.add(ordinal)) throw new IllegalArgumentException("aliased original mode ordinal");
            actions.put(ordinal, action);
        }
        if (actions.isEmpty()) throw new IllegalArgumentException("mode root has no offered actions");
    }

    /** Called only after ModelReplay verifies the entire current observation. */
    private static UUID visibleSource(World world, Map<String, Object> decision,
                                      Map<String, Object> reference, Game game) {
        if (reference == null) throw new IllegalArgumentException("mode source reference is missing");
        Map<String, Object> observation = Json.obj(decision, "observation");
        String alias = Json.str(reference, "object_id");
        Map<String, Object> visible = new ObsIndex(observation).ref(alias);
        if (visible == null || !Json.canonical(visible).equals(Json.canonical(reference))) {
            throw new IllegalArgumentException("mode source is absent or differs from its visible reference");
        }
        if (!"stack".equals(Json.str(reference, "zone"))) return world.idToUuid.get(alias);
        // Casting creates a new stack alias after the saved hand snapshot.
        // Both the engine observation and WorldBuilder use bottom-to-top order;
        // ArrayDeque's descending iterator gives that order in the replayed game.
        List<Object> entries = Json.arr(observation, "stack");
        if (entries.size() != game.getStack().size()) {
            throw new IllegalArgumentException("mode source stack differs from the verified observation");
        }
        Iterator<StackObject> actual = game.getStack().descendingIterator();
        UUID result = null;
        for (Object item : entries) {
            StackObject object = actual.next();
            if (alias.equals(Json.str(Json.obj(item), "object_id"))) {
                if (result != null) throw new IllegalArgumentException("aliased visible mode source");
                result = object.getId();
            }
        }
        return result;
    }

    int selected(Map<String, Object> semantic) {
        for (Map.Entry<Integer, Map<String, Object>> entry : actions.entrySet()) {
            if (Json.canonical(entry.getValue()).equals(Json.canonical(semantic))) return entry.getKey();
        }
        throw new IllegalArgumentException("recorded mode selection was not bound to the original callback");
    }
}
