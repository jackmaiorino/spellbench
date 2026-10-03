package spellbench.kit.xmage;

import mage.abilities.Ability;
import mage.abilities.Mode;
import mage.abilities.Modes;
import mage.game.Game;
import spellbench.kit.core.Json;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

/** Binds the original numeric mode ordinals to the public engine's mode indices. */
final class ModelModes {
    final List<Mode> options = new ArrayList<>();
    final Map<Integer, Map<String, Object>> actions = new HashMap<>();
    final List<Integer> publicIndices = new ArrayList<>();

    ModelModes(World world, Map<String, Object> decision, Modes modes, Ability source, Game game) {
        if (source == null || !world.player(world.viewer).equals(source.getControllerId())) {
            throw new IllegalArgumentException("mode callback needs the viewer's actual source ability");
        }
        List<Mode> all = new ArrayList<>(modes.values());
        // Exactly ComputerPlayerMCTS.chooseMode: null at ordinal zero, then
        // available unselected modes whose targets can be chosen, in source order.
        options.add(null);
        for (Mode mode : modes.getAvailableModes(source, game)) {
            if (!modes.getSelectedModes().contains(mode.getId())
                    && mode.getTargets().canChoose(source.getControllerId(), source, game)) {
                options.add(mode);
            }
        }
        if (options.size() > 65) throw new IllegalArgumentException("mode callback exceeds the original numeric clamp");
        publicIndices.add(-1);
        for (int i = 1; i < options.size(); i++) {
            int index = all.indexOf(options.get(i));
            if (index < 0) throw new IllegalArgumentException("available mode is absent from the actual source");
            publicIndices.add(index);
        }
        Set<Integer> used = new HashSet<>();
        for (Object item : Json.arr(decision, "candidates")) {
            Map<String, Object> action = Json.obj(Json.obj(item), "semantic");
            String kind = Json.str(action, "kind");
            UUID id = world.idToUuid.get(Json.str(Json.obj(action, "source"), "object_id"));
            if (id == null || !(id.equals(source.getSourceId())
                    || game.getStack().getStackObject(id) != null
                    && source.getSourceId().equals(game.getStack().getStackObject(id).getSourceId()))) {
                throw new IllegalArgumentException("mode candidate belongs to a different source");
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
                if (ordinal <= 0) throw new IllegalArgumentException("offered mode is unavailable to the original policy");
            } else if ("finish_selection".equals(kind) && "modes".equals(Json.str(action, "purpose"))) {
                if (Json.num(action, "selected_count", -1) != modes.getSelectedModes().size()) {
                    throw new IllegalArgumentException("mode stop candidate has a different selected count");
                }
                int selected = modes.getSelectedModes().size();
                if (!(modes.getMaxPawPrints() > 0 ? selected > 0
                        : selected >= modes.getMinModes() || modes.isMayChooseNone() && selected == 0)) {
                    throw new IllegalArgumentException("mode stop is offered before the actual callback permits it");
                }
                ordinal = 0;
            } else {
                throw new IllegalArgumentException("mode decision mixes unrelated candidate families");
            }
            if (!used.add(ordinal)) throw new IllegalArgumentException("aliased original mode ordinal");
            actions.put(ordinal, action);
        }
        if (actions.isEmpty()) throw new IllegalArgumentException("mode root has no offered actions");
    }

    int selected(Map<String, Object> semantic) {
        for (Map.Entry<Integer, Map<String, Object>> entry : actions.entrySet()) {
            if (Json.canonical(entry.getValue()).equals(Json.canonical(semantic))) return entry.getKey();
        }
        throw new IllegalArgumentException("recorded mode selection was not bound to the original callback");
    }
}
