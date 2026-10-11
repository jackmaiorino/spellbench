package spellbench.kit.xmage;

import mage.abilities.Ability;
import mage.cards.Cards;
import mage.game.Game;
import mage.target.Target;
import mage.target.TargetCard;
import spellbench.kit.core.Json;
import spellbench.kit.core.ObsIndex;
import spellbench.models.exp1.GameAccess;
import spellbench.models.exp1.MCTSNode;
import spellbench.models.exp1.MCTSNode2;
import spellbench.models.exp1.SearchPlayer;
import java.util.*;

/** A complete original operation, retained across the wire partition/order group. */
final class ModelArrangement {
    final World world;
    final Map<String, Object> initial;
    final String purpose, away;
    final List<UUID> cards;
    final List<String> aliases = new ArrayList<>();
    final List<Object> roots = new ArrayList<>(), script = new ArrayList<>();
    String stage = "partition";
    int depth, scriptIndex;
    boolean replaying;
    Set<UUID> selectedAway;
    Map<String, Object> retained;

    ModelArrangement(World w, Map<String, Object> decision, String actualPurpose,
                     Target target, Cards offered, Ability source, Game game) {
        world = w; initial = decision;
        Map<String, Object> context = Json.obj(decision, "context");
        purpose = Json.str(context, "purpose"); away = "surveil".equals(purpose) ? "graveyard" : "bottom";
        if (!("surveil".equals(purpose) || "scry".equals(purpose)) || !purpose.equals(actualPurpose)
                || !"choice".equals(Json.str(context, "kind")) || !(target instanceof TargetCard)
                || target.getMinNumberOfTargets() != 0 || offered == null || offered.isEmpty() || offered.size() > 64
                || target.getMaxNumberOfTargets() != offered.size() || !target.getTargets().isEmpty()
                || game.getPlayer(world.player(world.viewer)).getUserData().askMoveToGraveOrder()
                || source == null || !world.player(world.viewer).equals(source.getControllerId())) {
            throw new IllegalArgumentException("arrangement needs its actual original scry/surveil target callback");
        }
        List<UUID> library = game.getPlayer(world.player(world.viewer)).getLibrary().getCardList();
        if (library.size() < offered.size()) throw new IllegalArgumentException("arrangement exceeds actual library");
        cards = new ArrayList<>(library.subList(0, offered.size()));
        if (!new HashSet<>(cards).equals(new HashSet<>(offered)) || !target.isChosen(game)) {
            throw new IllegalArgumentException("arrangement target differs from actual top cards and optional STOP");
        }
        Map<String, Object> reference = Json.obj(context, "source");
        UUID sourceId = ModelModes.visibleSource(world, decision, reference, game);
        if (sourceId == null || !(sourceId.equals(source.getSourceId())
                || game.getStack().getStackObject(sourceId) != null
                && source.getSourceId().equals(game.getStack().getStackObject(sourceId).getSourceId()))) {
            throw new IllegalArgumentException("arrangement source differs");
        }
        ObsIndex index = new ObsIndex(Json.obj(decision, "observation"));
        for (int pos = 0; pos < cards.size(); pos++) {
            String alias = world.uuidToId.get(cards.get(pos)); Map<String, Object> known = index.record(alias);
            if (alias == null || known == null || !"looked_at".equals(Json.str(known, "how"))
                    || !world.viewer.equals(Json.str(known, "owner_seat")) || !"library".equals(Json.str(known, "zone"))
                    || Json.num(known, "position_from_top", -1) != pos) {
                throw new IllegalArgumentException("arrangement lacks exact visible top-card positions");
            }
            aliases.add(alias);
        }
        validateWire(decision, 0, null);
    }
    private Object alias(UUID id) {
        if (GameAccess.STOP_CHOOSING.equals(id)) return null;
        int pos = cards.indexOf(id);
        if (pos < 0) throw new IllegalArgumentException("original arrangement chose an unobserved card");
        return aliases.get(pos);
    }
    private UUID original(Object alias) {
        if (alias == null) return GameAccess.STOP_CHOOSING;
        int pos = aliases.indexOf(alias);
        if (pos < 0) throw new IllegalArgumentException("recorded arrangement target was not visible");
        return cards.get(pos);
    }
    Map<String, Object> frame(Target target, Cards offered, Ability source, Game game, SearchPlayer player) {
        List<String> possible = new ArrayList<>();
        for (UUID id : target.possibleTargets(target.getAffectedAbilityControllerId(player.getId()), source, game, offered)) {
            if (!target.contains(id)) possible.add((String) alias(id));
        }
        Collections.sort(possible);
        return Json.map("stage", stage, "possible", possible,
                "minimum", (long) target.getMinNumberOfTargets(), "maximum", (long) target.getMaxNumberOfTargets());
    }
    void record(Map<String, Object> frame, List<UUID> history, int before) {
        List<Object> choices = new ArrayList<>();
        for (UUID id : history.subList(before, history.size())) choices.add(alias(id));
        frame.put("choices", choices); script.add(frame);
    }
    boolean replayChoice(Target target, Cards offered, Ability source, Game game, SearchPlayer player) {
        if (scriptIndex >= script.size()) throw new IllegalArgumentException("unrecorded arrangement callback");
        Map<String, Object> entry = Json.obj(script.get(scriptIndex++));
        Map<String, Object> expected = frame(target, offered, source, game, player);
        for (String key : expected.keySet()) if (!Json.canonical(expected.get(key)).equals(Json.canonical(entry.get(key)))) {
            throw new IllegalArgumentException("arrangement original callback stage/range changed");
        }
        List<Object> choices = Json.arr(entry, "choices"); int cursor = 0;
        UUID controller = target.getAffectedAbilityControllerId(player.getId());
        // Original ComputerPlayerMCTS.makeChoice stopping, direct-return,
        // target mutation and history rules, without fresh neural inference.
        while (true) {
            if (offered != null && offered.isEmpty() || target.isChoiceCompleted(controller, source, game, offered)) {
                if (cursor != choices.size()) throw new IllegalArgumentException("trailing arrangement target history");
                return cursor > 0 && target.isChosen(game) && !target.getTargets().isEmpty();
            }
            Set<UUID> possible = new HashSet<>(target.possibleTargets(controller, source, game, offered));
            possible.removeAll(target.getTargets());
            if (possible.isEmpty()) {
                if (cursor != choices.size()) throw new IllegalArgumentException("trailing arrangement target history");
                return cursor > 0 && target.isChosen(game) && !target.getTargets().isEmpty();
            }
            if (cursor >= choices.size()) throw new IllegalArgumentException("missing arrangement target history");
            UUID pick = original(choices.get(cursor++));
            int options = possible.size() + (target.isChosen(game) ? 1 : 0);
            if (options == 1) {
                if (!possible.contains(pick) || cursor != choices.size()) throw new IllegalArgumentException("changed forced arrangement target");
                target.addTarget(pick, source, game); player.getPlayerHistory().targetSequence.add(pick); return true;
            }
            if (GameAccess.STOP_CHOOSING.equals(pick)) {
                if (!target.isChosen(game) || cursor != choices.size()) throw new IllegalArgumentException("premature or trailing arrangement STOP");
                player.getPlayerHistory().targetSequence.add(pick);
                return target.isChosen(game) && !target.getTargets().isEmpty();
            }
            if (!possible.contains(pick)) throw new IllegalArgumentException("recorded arrangement target became illegal");
            player.getPlayerHistory().targetSequence.add(pick); target.addTarget(pick, source, game);
        }
    }
    void root(SearchPlayer player, MCTSNode2 chosen, long before, ModelReplay.Result replay) {
        MCTSNode2 tree = player.tree(); long calls = ModelSearchMain.neuralCalls() - before;
        if (chosen == null || tree == null || tree.getVisits() < 1
                || !replay.settings.published && tree.getVisits() < replay.visits || calls <= 0) {
            throw new IllegalStateException("original arrangement root did not complete neural work");
        }
        List<Object> children = new ArrayList<>(); Set<MCTSNode> retained = new HashSet<>(tree.getChildren());
        for (MCTSNode child : player.initialRootChildren()) {
            boolean pruned = !retained.contains(child), masked = !pruned && player.selectionMasked(child);
            children.add(Json.map("action", alias(child.getTargetAction()), "visits", pruned ? 0L : (long) child.getVisits(),
                    "value", pruned || masked ? null : child.getMeanScore(), "pruned", pruned,
                    "selection_masked", masked, "discarded_visits", masked ? (long) player.discardedSelectionVisits(child) : 0L));
        }
        roots.add(Json.map("index", (long) roots.size(), "type", "CHOOSE_TARGET", "stage", stage,
                "selected", alias(chosen.getTargetAction()), "root_visits", (long) tree.getVisits(),
                "requested_minimum", replay.settings.published ? 0L : (long) replay.visits,
                "search_budget", replay.settings.budget(), "neural_calls", calls, "children", children));
    }
    Map<String, Object> finish(Game game) {
        if (selectedAway == null) throw new IllegalArgumentException("arrangement partition did not complete");
        if (replaying && scriptIndex != script.size()) throw new IllegalArgumentException("arrangement script was not consumed");
        List<UUID> library = game.getPlayer(world.player(world.viewer)).getLibrary().getCardList();
        List<Object> top = new ArrayList<>(), moved = new ArrayList<>();
        for (UUID id : library) if (cards.contains(id) && !selectedAway.contains(id)) top.add(alias(id));
        Iterable<UUID> awayZone = "surveil".equals(purpose) ? game.getPlayer(world.player(world.viewer)).getGraveyard() : library;
        for (UUID id : awayZone) if (selectedAway.contains(id)) moved.add(alias(id));
        if (top.size() + moved.size() != cards.size() || moved.size() != selectedAway.size()) {
            throw new IllegalArgumentException("original arrangement did not place every visible card");
        }
        Map<String, Object> destinations = new LinkedHashMap<>();
        for (String id : aliases) destinations.put(id, moved.contains(id) ? away : "top");
        List<Object> order = new ArrayList<>(top); order.addAll(moved);
        Map<String, Object> plan = Json.map("arrangement", purpose, "cards", aliases,
                "destinations", destinations, "order", order, "target_script", script);
        if (replaying && !Json.canonical(plan).equals(Json.canonical(retained))) {
            throw new IllegalArgumentException("original arrangement replay changed its complete plan");
        }
        return plan;
    }
    void earlier(ModelReplay.Result replay, Game game) {
        retained = Json.obj(initial, "x_arrangement_plan");
        if (retained == null || !purpose.equals(Json.str(retained, "arrangement"))
                || !Json.canonical(aliases).equals(Json.canonical(retained.get("cards")))) {
            throw new IllegalArgumentException("completed arrangement lacks original internal history");
        }
        script.addAll(Json.arr(retained, "target_script")); replaying = true;
        int count = 2 * cards.size() - 1;
        if (replay.replayed + count > replay.earlier.size()) throw new IllegalArgumentException("incomplete earlier arrangement group");
        for (int i = 0; i < count; i++) {
            Map<String, Object> entry = Json.obj(replay.earlier.get(replay.replayed + i));
            Map<String, Object> decision = Json.obj(entry, "decision"); replay.compare(game, decision);
            Map<String, Object> selected = ModelReplay.selectedSemantic(decision, Json.obj(entry, "selection"));
            if (!Json.canonical(selected).equals(Json.canonical(validateWire(decision, i, retained)))) {
                throw new IllegalArgumentException("earlier wire arrangement differs from its original plan");
            }
        }
        replay.replayed += count;
    }
    private Map<String, Object> validateWire(Map<String, Object> decision, int step, Map<String, Object> plan) {
        Map<String, Object> group = Json.obj(decision, "group"), firstGroup = Json.obj(initial, "group");
        Map<String, Object> context = Json.obj(decision, "context"), firstContext = Json.obj(initial, "context");
        if (Json.num(group, "substep_index", -1) != step || Json.num(group, "substep_count", -1) != 2L * cards.size() - 1
                || !Json.canonical(group.get("group_id")).equals(Json.canonical(firstGroup.get("group_id")))
                || Json.num(decision, "seat_step", -1) != Json.num(initial, "seat_step", -1) + step
                || !world.viewer.equals(Json.str(decision, "acting_seat")) || !Boolean.FALSE.equals(context.get("rewind"))
                || !Json.canonical(context.get("source")).equals(Json.canonical(firstContext.get("source")))
                || !Json.canonical(Json.obj(decision, "observation")).equals(Json.canonical(Json.obj(initial, "observation")))) {
            throw new IllegalArgumentException("arrangement group skipped a step or changed observation");
        }
        Map<String, Object> source = Json.obj(Json.obj(initial, "context"), "source");
        ObsIndex index = new ObsIndex(Json.obj(initial, "observation"));
        Map<String, Object> wanted = null; Set<String> offered = new HashSet<>(), allowed = new HashSet<>();
        Set<Long> ids = new HashSet<>();
        if (step < cards.size()) { allowed.add("top"); allowed.add(away); }
        else {
            if (plan == null) throw new IllegalArgumentException("arrangement order lacks its retained plan");
            int position = step - cards.size(); List<Object> order = Json.arr(plan, "order");
            Map<String, Object> destinations = Json.obj(plan, "destinations");
            String destination = Json.str(destinations, (String) order.get(position));
            for (int i = position; i < order.size(); i++) {
                String id = (String) order.get(i);
                if (destination.equals(Json.str(destinations, id))) allowed.add(id);
            }
        }
        for (Object item : Json.arr(decision, "candidates")) {
            Map<String, Object> candidate = Json.obj(item), action = Json.obj(candidate, "semantic");
            long id = Json.num(candidate, "candidate_id", -1);
            if (id < 0 || id > 9007199254740991L || !ids.add(id)) throw new IllegalArgumentException("aliased arrangement candidate id");
            if (!Json.canonical(source).equals(Json.canonical(action.get("source")))) throw new IllegalArgumentException("arrangement source changed");
            String key;
            if (step < cards.size()) {
                key = Json.str(action, "destination");
                if (!"arrange_card".equals(Json.str(action, "kind")) || !purpose.equals(Json.str(action, "purpose"))
                        || Json.num(action, "card_count", -1) != cards.size() || Json.num(action, "card_index", -1) != step
                        || !("top".equals(key) || away.equals(key))
                        || !Json.canonical(index.ref(aliases.get(step))).equals(Json.canonical(action.get("card")))) {
                    throw new IllegalArgumentException("arrangement partition menu changed");
                }
                if (plan != null && key.equals(Json.str(Json.obj(plan, "destinations"), aliases.get(step)))) wanted = action;
            } else {
                int position = step - cards.size(); Map<String, Object> ref = Json.obj(Json.obj(action, "item"), "object");
                key = Json.str(ref, "object_id");
                if (!"order_pick".equals(Json.str(action, "kind")) || !"arrangement".equals(Json.str(action, "purpose"))
                        || Json.num(action, "position", -1) != position || Json.num(action, "count", -1) != cards.size()
                        || !allowed.contains(key) || !Json.canonical(index.ref(key)).equals(Json.canonical(ref))) {
                    throw new IllegalArgumentException("arrangement order menu changed");
                }
                if (plan != null && key.equals(Json.arr(plan, "order").get(position))) wanted = action;
            }
            if (!offered.add(key)) throw new IllegalArgumentException("aliased arrangement candidate");
        }
        if (!offered.equals(allowed)
                || plan != null && wanted == null) throw new IllegalArgumentException("original arrangement plan is unoffered");
        return wanted;
    }
}
