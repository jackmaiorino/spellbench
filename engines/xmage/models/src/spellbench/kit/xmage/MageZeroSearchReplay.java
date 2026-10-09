package spellbench.kit.xmage;

import mage.abilities.Ability;
import mage.abilities.ActivatedAbility;
import mage.abilities.common.PassAbility;
import mage.abilities.Mode;
import mage.abilities.Modes;
import mage.MageObject;
import mage.cards.Card;
import mage.cards.Cards;
import mage.choices.Choice;
import mage.constants.Outcome;
import mage.game.Game;
import spellbench.models.magezero.v02.encoder.ActionEncoder;
import mage.target.Target;
import mage.target.TargetAmount;
import mage.target.common.TargetCardInLibrary;
import spellbench.kit.core.Json;
import spellbench.kit.core.ObsCompare;
import spellbench.kit.core.ObsIndex;
import spellbench.kit.core.Sampler;
import spellbench.kit.core.Seeds;
import spellbench.models.magezero.v02.search.GameAccess;
import spellbench.models.magezero.v02.search.MCTSNode2;
import spellbench.models.magezero.v02.search.RemoteModelEvaluator;
import spellbench.models.magezero.v02.search.SearchPlayer;
import spellbench.models.magezero.v02.search.MCTSDefaults;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.text.Normalizer;
import java.util.UUID;

/** Replays the reviewed public callback path for the original MageZero tree.
 * Settings remain explicit; every received observation is compared before inference.
 * This keeps the public replay logic of ModelReplay with separate 128-slot types.
 */
final class MageZeroSearchReplay {
    private MageZeroSearchReplay() { }
    // The private pipe handles one request at a time. Game state restoration
    // may replace Player objects, so the replay context belongs to the game.
    private static Result live;
    private static Result context(Game game) {
        return live != null && game == live.world.game && !game.isSimulation() ? live : null;
    }
    static final class Stop extends Error {
        private static final long serialVersionUID = 1L;
        Stop() { super("model callback reached", null, false, false); }
    }
    static final class Failure extends Error {
        private static final long serialVersionUID = 1L;
        final RuntimeException failure;
        Failure(RuntimeException failure) { super("callback replay refused", failure, false, false); this.failure = failure; }
    }
    static final class Result {
        World world;
        ReplayPlayer player;
        MCTSNode2 chosen;
        Map<String, Object> decision;
        List<Object> earlier;
        ArrayDeque<String> passes = new ArrayDeque<>();
        RemoteModelEvaluator evaluator;
        MCTSDefaults settings;
        boolean diagnostic;
        int replayed;
        int binaryCallbacks;
        boolean libraryFailToFindExcluded;
        Integer numericMinimum;
        boolean numericRangeRestricted;
        Map<String, Map<String, Object>> namedActions;
        ModelModes modeActions;
        /**
         * Opt-in (the graph frontend): characteristic gaps the anchor world already had. Key: the anchor object's id
         * and field; value: the observed and the projected value at the anchor, canonical.
         */
        boolean tolerateGaps;
        /** Opt-in (the graph frontend): which of several identical permanents is tapped (a mana payment) may differ. */
        boolean fungibleTapped;
        final Map<String, String[]> anchorGaps = new java.util.HashMap<>();
        /** Opt-in (the graph frontend): this many earlier entries are this seat's recorded attack declarations. */
        int attackDeclarations;

        void compare(Game game) {
            compare(game, decision);
            if (!passes.isEmpty()) throw new IllegalArgumentException("callback reached before recorded priority passes");
        }
        void compare(Game game, Map<String, Object> received) {
            Map<String, Object> current = Json.obj(received, "observation");
            if (!world.viewer.equals(Json.str(current, "viewer"))
                    || !world.viewer.equals(Json.str(received, "acting_seat"))) {
                throw new IllegalArgumentException("replay callback belongs to another seat");
            }
            try {
                Map<String, Object> projected = RoundTrip.project(world, RoundTrip.flagsFrom(received),
                        Json.str(current, "priority_seat"), Json.arr(current, "known"));
                List<String> diff = new ArrayList<>();
                boolean tolerated = false;
                List<String> tapped = new ArrayList<>();
                for (String d : ObsCompare.diff(current, projected, 1000)) {
                    if (knownGap(current, projected, d)) tolerated = true;
                    else if (fungibleTapped && d.matches("^/players/\\d+/battlefield/\\d+/permanent/tapped \\((true vs false|false vs true)\\)$")) tapped.add(d);
                    else diff.add(d);
                }
                if (!tapped.isEmpty()) {
                    if (diff.isEmpty() && tappedPermutation(current, projected)) {
                        if (!world.flags.contains("approximate:fungible_tapped_permanents")) world.flags.add("approximate:fungible_tapped_permanents");
                    } else {
                        diff.addAll(tapped);
                    }
                }
                if (!diff.isEmpty()) {
                    throw new IllegalArgumentException("callback replay observation differs: " + diff.subList(0, Math.min(8, diff.size())));
                }
                if (tolerated && !world.flags.contains("approximate:unexplained_characteristics_callback")) {
                    world.flags.add("approximate:unexplained_characteristics_callback");
                }
            } catch (RuntimeException e) { throw e; }
            catch (Exception e) { throw new IllegalStateException("callback replay projection failed", e); }
        }
        /**
         * A power, toughness or keyword difference this object already had at the anchor (WorldBuilder cannot rebuild an
         * until-end-of-turn effect: approximate:unexplained_characteristics), with both the received and the replayed
         * value unchanged since the anchor. Any other difference, or a changed value on either side, is refused.
         */
        private boolean knownGap(Map<String, Object> current, Map<String, Object> projected, String difference) {
            if (!tolerateGaps) return false;
            String[] at = gapAt(difference);
            if (at == null) return false;
            Map<String, Object> seen = objectAt(current, at), replayed = objectAt(projected, at);
            if (seen == null || replayed == null) return false;
            String[] gap = anchorGaps.get(Json.str(seen, "object_id") + "/" + at[2]);
            return gap != null && gap[0].equals(characteristic(seen, at[2])) && gap[1].equals(characteristic(replayed, at[2]));
        }
        /**
         * Every battlefield's permanents, grouped by everything but their id and tapped state, have the same number
         * tapped in the observation and in the replayed world: the two differ only in which identical copy is tapped.
         */
        private static boolean tappedPermutation(Map<String, Object> current, Map<String, Object> projected) {
            List<Object> seen = Json.arr(current, "players"), replayed = Json.arr(projected, "players");
            if (seen == null || replayed == null || seen.size() != replayed.size()) return false;
            for (int p = 0; p < seen.size(); p++) {
                Map<String, Integer> counts = new java.util.HashMap<>();
                List<Object> a = Json.arr(Json.obj(seen.get(p)), "battlefield"), b = Json.arr(Json.obj(replayed.get(p)), "battlefield");
                if (a == null || b == null || a.size() != b.size()) return false;
                for (int i = 0; i < a.size(); i++) {
                    String sa = untapped(Json.obj(a.get(i))), sb = untapped(Json.obj(b.get(i)));
                    if (!sa.equals(sb)) return false;
                    if (Boolean.TRUE.equals(Json.obj(Json.obj(a.get(i)), "permanent").get("tapped"))) counts.merge(sa, 1, Integer::sum);
                    if (Boolean.TRUE.equals(Json.obj(Json.obj(b.get(i)), "permanent").get("tapped"))) counts.merge(sa, -1, Integer::sum);
                }
                for (int count : counts.values()) if (count != 0) return false;
            }
            return true;
        }
        private static String untapped(Map<String, Object> object) {
            Map<String, Object> copy = Json.obj(Json.copy(object));
            copy.remove("object_id");
            Map<String, Object> permanent = Json.obj(copy, "permanent");
            if (permanent != null) permanent.remove("tapped");
            return Json.canonical(copy);
        }
        /** Record the anchor world's own characteristic gaps (object id and field: observed and projected values). */
        void recordGaps(Map<String, Object> observation, Map<String, Object> projected) {
            for (String d : ObsCompare.diff(observation, projected, 1000)) {
                String[] at = gapAt(d);
                if (at == null) continue;
                Map<String, Object> seen = objectAt(observation, at), replayed = objectAt(projected, at);
                if (seen != null && replayed != null && Json.str(seen, "object_id") != null) {
                    anchorGaps.put(Json.str(seen, "object_id") + "/" + at[2],
                            new String[]{characteristic(seen, at[2]), characteristic(replayed, at[2])});
                }
            }
        }
        private static String[] gapAt(String difference) {
            java.util.regex.Matcher m = java.util.regex.Pattern
                    .compile("^/players/(\\d+)/battlefield/(\\d+)/characteristics/(power|toughness|keywords)(?:/\\d+)? \\(")
                    .matcher(difference);
            return m.find() ? new String[]{m.group(1), m.group(2), m.group(3)} : null;
        }
        private static Map<String, Object> objectAt(Map<String, Object> observation, String[] at) {
            List<Object> players = Json.arr(observation, "players");
            int player = Integer.parseInt(at[0]), index = Integer.parseInt(at[1]);
            if (players == null || player >= players.size()) return null;
            List<Object> battlefield = Json.arr(Json.obj(players.get(player)), "battlefield");
            return battlefield == null || index >= battlefield.size() ? null : Json.obj(battlefield.get(index));
        }
        private static String characteristic(Map<String, Object> object, String field) {
            Map<String, Object> ch = Json.obj(object, "characteristics");
            return ch == null ? "absent" : Json.canonical(ch.get(field));
        }
        void priority(String seat, SearchPlayer p, Game game) {
            if (passes.isEmpty() || !seat.equals(passes.removeFirst())) {
                throw new IllegalArgumentException("unrecorded or reordered priority during callback replay");
            }
            p.pass(game);
        }
        Map<String, Object> earlierPick(Game game) {
            if (replayed >= earlier.size()) return null;
            Map<String, Object> entry = Json.obj(earlier.get(replayed));
            Map<String, Object> past = Json.obj(entry, "decision");
            Map<String, Object> selected = Json.obj(entry, "selection");
            compare(game, past);
            return selectedSemantic(past, selected);
        }
        Map<String, Object> callbackDecision() {
            return replayed < earlier.size() ? Json.obj(Json.obj(earlier.get(replayed)), "decision") : decision;
        }
    }
    static final class ReplayPlayer extends SearchPlayer {
        private static final long serialVersionUID = 1L;
        final String seat;
        ReplayPlayer(String seat) { super(seat); this.seat = seat; }
        private ReplayPlayer(ReplayPlayer p) { super(p); seat = p.seat; }
        @Override public ReplayPlayer copy() { return new ReplayPlayer(this); }
        private void configureSearch(Result replay) {
            if (replay.diagnostic) configureDiagnostic(replay.evaluator, replay.settings.searchBudget);
            else configure(replay.evaluator, replay.settings);
        }
        @Override public boolean priority(Game game) {
            Result replay = context(game);
            if (replay == null) { pass(game); return false; }
            try { replay.priority(seat, this, game); }
            catch (RuntimeException e) { throw new Failure(e); }
            return false;
        }
        @Override protected boolean makeChoice(Outcome outcome, Target target, Ability source, Game game, Cards cards) {
            try { return replayTarget(outcome, target, source, game, cards); }
            catch (RuntimeException e) { if (context(game) != null) throw new Failure(e); throw e; }
        }
        private boolean replayTarget(Outcome outcome, Target target, Ability source, Game game, Cards cards) {
            Result replay = context(game);
            if (replay == null) return super.makeChoice(outcome, target, source, game, cards);
            if (!getId().equals(replay.world.player(replay.world.viewer)) || target instanceof TargetAmount) {
                throw new IllegalArgumentException("unrecorded opponent or divided-target callback");
            }
            UUID controller = target.getAffectedAbilityControllerId(getId());
            if (target.isChoiceCompleted(controller, source, game, cards)) return false;
            Map<String, Object> past = replay.earlierPick(game);
            if (past != null) {
                String kind = Json.str(past, "kind");
                UUID pick = Dialogs.uuidOf(replay.world, past);
                boolean stop = "finish_target_selection".equals(kind) || "finish_selection".equals(kind);
                if (stop) {
                    if (!target.isChosen(game)) throw new IllegalArgumentException("recorded target finish is premature");
                    getPlayerHistory().targetSequence.add(GameAccess.STOP_CHOOSING);
                    replay.replayed++;
                    return true;
                }
                if (pick == null || !target.possibleTargets(controller, source, game, cards).contains(pick)
                        || target.contains(pick)) throw new IllegalArgumentException("recorded target is not legal here");
                if (target.isNotTarget()) target.add(pick, game); else target.addTarget(pick, source, game);
                getPlayerHistory().targetSequence.add(pick);
                replay.replayed++;
                return makeChoice(outcome, target, source, game, cards);
            }
            replay.compare(game);
            replay.libraryFailToFindExcluded = target instanceof TargetCardInLibrary && !target.isChosen(game)
                    && "search".equals(Json.str(Json.obj(replay.decision, "context"), "purpose"));
            String text = (source == null ? "null" : source.getRule()) + ":Choose a target:" + target.getTargetName();
            replay.player = this;
            configureSearch(replay);
            replay.chosen = searchAction(game, ActionEncoder.ActionType.CHOOSE_TARGET, text);
            throw new Stop();
        }
        @Override public boolean chooseUse(Outcome outcome, String message, String second, String yes, String no,
                                           Ability source, Game game) {
            try { return replayUse(outcome, message, second, yes, no, source, game); }
            catch (RuntimeException e) { if (context(game) != null) throw new Failure(e); throw e; }
        }
        private boolean replayUse(Outcome outcome, String message, String second, String yes, String no,
                                   Ability source, Game game) {
            if (live != null) live.binaryCallbacks++;
            Result replay = context(game);
            if (replay == null) return super.chooseUse(outcome, message, second, yes, no, source, game);
            if (!getId().equals(replay.world.player(replay.world.viewer))) {
                throw new IllegalArgumentException("unrecorded opponent binary callback");
            }
            Map<String, Object> past = replay.earlierPick(game);
            if (past != null) {
                Object value = booleanValue(past);
                if (!(value instanceof Boolean)) throw new IllegalArgumentException("recorded dialog is not binary");
                getPlayerHistory().useSequence.add((Boolean) value);
                replay.replayed++;
                return (Boolean) value;
            }
            replay.compare(game);
            replay.player = this;
            configureSearch(replay);
            replay.chosen = searchAction(game, ActionEncoder.ActionType.CHOOSE_USE, message);
            throw new Stop();
        }
        @Override public boolean choose(Outcome outcome, Choice choice, Game game) {
            try { return replayChoice(outcome, choice, game); }
            catch (RuntimeException e) { if (context(game) != null) throw new Failure(e); throw e; }
        }
        private boolean replayChoice(Outcome outcome, Choice choice, Game game) {
            Result replay = context(game);
            if (replay == null) return super.choose(outcome, choice, game);
            if (!getId().equals(replay.world.player(replay.world.viewer))) {
                throw new IllegalArgumentException("unrecorded opponent named callback");
            }
            if ("Choose creature type".equals(choice.getMessage()) || "Choose a creature type".equals(choice.getMessage())) {
                throw new IllegalArgumentException("original creature-type heuristic needs a separate forced-choice bridge");
            }
            Map<String, Map<String, Object>> actions = bindChoices(choice, replay.callbackDecision());
            Map<String, Object> past = replay.earlierPick(game);
            if (past != null) {
                String key = null;
                for (Map.Entry<String, Map<String, Object>> entry : actions.entrySet()) {
                    if (Json.canonical(entry.getValue()).equals(Json.canonical(past))) key = entry.getKey();
                }
                if (key == null) throw new IllegalArgumentException("recorded named choice is not legal here");
                if (!choice.getKeyChoices().isEmpty()) choice.setChoiceByKey(key); else choice.setChoice(key);
                getPlayerHistory().choiceSequence.add(key);
                replay.replayed++;
                return true;
            }
            replay.compare(game);
            replay.player = this;
            replay.namedActions = actions;
            configureSearch(replay);
            replay.chosen = searchChoice(game, choice);
            throw new Stop();
        }
        @Override protected int makeChoiceAmount(int min, int max, Game game, Ability source, boolean mana) {
            try { return replayAmount(min, max, game, source, mana); }
            catch (RuntimeException e) { if (context(game) != null) throw new Failure(e); throw e; }
        }
        private int replayAmount(int min, int max, Game game, Ability source, boolean mana) {
            Result replay = context(game);
            if (replay == null) return super.makeChoiceAmount(min, max, game, source, mana);
            if (!getId().equals(replay.world.player(replay.world.viewer))) {
                throw new IllegalArgumentException("unrecorded opponent numeric callback");
            }
            if (replay.modeActions != null) {
                ModelModes bound = replay.modeActions;
                if (min != 0 || max != bound.options.size() - 1) {
                    throw new IllegalArgumentException("original mode ordinal range changed");
                }
                Map<String, Object> past = replay.earlierPick(game);
                if (past != null) {
                    int ordinal = bound.selected(past);
                    if (min < max) getPlayerHistory().numSequence.add(ordinal);
                    replay.replayed++;
                    return ordinal;
                }
                replay.compare(game);
                replay.player = this;
                configureSearch(replay);
                replay.chosen = searchAmount(game, min, max, source);
                throw new Stop();
            }
            Map<String, Object> callbackDecision = replay.callbackDecision();
            List<Object> candidates = Json.arr(callbackDecision, "candidates");
            if (candidates.isEmpty()) throw new IllegalArgumentException("numeric root has no offered range");
            int offeredMax = Math.toIntExact(Json.num(Json.obj(Json.obj(candidates.get(0)), "semantic"), "maximum", Long.MIN_VALUE));
            if (offeredMax > max) throw new IllegalArgumentException("numeric offered range exceeds the actual callback");
            bindNumbers(callbackDecision, min, offeredMax);
            if (min < offeredMax) GameAccess.numberBounds(getId(), source, min, offeredMax, getPlayerHistory().numSequence.size());
            if (offeredMax != max) replay.world.flags.add("approximate:numeric_root_uses_offered_range");
            Map<String, Object> past = replay.earlierPick(game);
            if (past != null) {
                int value = Math.toIntExact((Long) past.get("value"));
                if (min < offeredMax) getPlayerHistory().numSequence.add(value - min);
                replay.replayed++;
                return value;
            }
            replay.compare(game);
            replay.player = this;
            replay.numericMinimum = min;
            replay.numericRangeRestricted = offeredMax != max;
            configureSearch(replay);
            replay.chosen = searchAmount(game, min, offeredMax, source);
            throw new Stop();
        }
        @Override public Mode chooseMode(Modes modes, Ability source, Game game) {
            Result replay = context(game);
            if (replay == null) return super.chooseMode(modes, source, game);
            try {
                if (!getId().equals(replay.world.player(replay.world.viewer))) {
                    throw new IllegalArgumentException("unrecorded opponent mode callback");
                }
                replay.compare(game, replay.callbackDecision());
                replay.modeActions = new ModelModes(replay.world, replay.callbackDecision(), modes, source, game,
                        modes.getMinModes() <= modes.getSelectedModes().size());
                Mode picked = super.chooseMode(modes, source, game);
                replay.modeActions = null;
                return picked;
            } catch (RuntimeException e) { throw new Failure(e); }
        }
        @Override public void selectAttackers(Game game, UUID player) {
            Result replay = context(game);
            if (replay == null || replay.attackDeclarations == 0) {
                rejectReplay(game, "attack");
                super.selectAttackers(game, player);
                return;
            }
            try { replayAttacks(replay, game, player); }
            catch (RuntimeException e) { throw new Failure(e); }
        }
        /**
         * The recorded declaration group, declared as MageZero v0.2's selectAttackersOneAtATime would: available
         * attackers in id order, one answer each, kept in the use history the search root later replays. Only the
         * group's first substep shows the state before any declaration, so it alone is compared here; the callback
         * that follows is compared in full.
         */
        private void replayAttacks(Result replay, Game game, UUID attackingPlayer) {
            if (!getId().equals(replay.world.player(replay.world.viewer)) || !getId().equals(attackingPlayer)
                    || replay.replayed != 0 || replay.attackDeclarations > replay.earlier.size()) {
                throw new IllegalArgumentException("recorded attack declarations do not open the callback replay");
            }
            Map<UUID, UUID> picks = new java.util.HashMap<>();
            for (int i = 0; i < replay.attackDeclarations; i++) {
                Map<String, Object> entry = Json.obj(replay.earlier.get(i));
                Map<String, Object> past = Json.obj(entry, "decision");
                Map<String, Object> semantic = selectedSemantic(past, Json.obj(entry, "selection"));
                if (!"declare_attack".equals(Json.str(semantic, "kind"))) {
                    throw new IllegalArgumentException("recorded attack group holds another decision");
                }
                if (i == 0) replay.compare(game, past);
                UUID attacker = replay.world.idToUuid.get(Json.str(Json.obj(semantic, "attacker"), "object_id"));
                Map<String, Object> defender = Json.obj(semantic, "defender");
                UUID target = defender == null ? null : defender.get("player") instanceof String
                        ? replay.world.player(Json.str(defender, "player"))
                        : replay.world.idToUuid.get(Json.str(defender, "object_id"));
                if (attacker == null || picks.containsKey(attacker) || defender != null && target == null) {
                    throw new IllegalArgumentException("recorded attack declaration is not bound to the world");
                }
                picks.put(attacker, target);
                replay.replayed++;
            }
            game.fireEvent(new mage.game.events.GameEvent(mage.game.events.GameEvent.EventType.DECLARE_ATTACKERS_STEP_PRE,
                    null, null, attackingPlayer));
            if (game.replaceEvent(mage.game.events.GameEvent.getEvent(mage.game.events.GameEvent.EventType.DECLARING_ATTACKERS,
                    attackingPlayer, attackingPlayer))) {
                throw new IllegalArgumentException("recorded attack declarations were replaced");
            }
            List<mage.game.permanent.Permanent> available = getAvailableAttackers(game);
            available.sort(java.util.Comparator.comparing(mage.game.permanent.Permanent::getId));
            java.util.Set<UUID> ids = new java.util.HashSet<>();
            for (mage.game.permanent.Permanent creature : available) ids.add(creature.getId());
            if (!ids.equals(picks.keySet())) {
                throw new IllegalArgumentException("recorded attack group does not answer exactly the available attackers");
            }
            for (mage.game.permanent.Permanent creature : available) {
                UUID target = picks.get(creature.getId());
                boolean attack = target != null;
                getPlayerHistory().useSequence.add(attack);
                if (attack) {
                    declareAttacker(creature.getId(), target, game, false);
                    if (!game.getCombat().getAttackers().contains(creature.getId())) {
                        throw new IllegalArgumentException("recorded attacker could not attack here");
                    }
                }
            }
            game.getPlayers().resetPassed();
        }
        @Override public void selectBlockers(Ability source, Game game, UUID player) {
            rejectReplay(game, "block");
            super.selectBlockers(source, game, player);
        }
        @Override public boolean chooseTargetAmount(Outcome outcome, TargetAmount target, Ability source, Game game) {
            rejectReplay(game, "divided-target");
            return super.chooseTargetAmount(outcome, target, source, game);
        }
        @Override public boolean chooseMulligan(Game game) {
            rejectReplay(game, "mulligan");
            return super.chooseMulligan(game);
        }
        @Override public boolean choosePile(Outcome outcome, String message, List<? extends Card> first,
                                             List<? extends Card> second, Game game) {
            rejectReplay(game, "pile");
            return super.choosePile(outcome, message, first, second, game);
        }
        @Override public int chooseReplacementEffect(Map<String, String> effects, Map<String, MageObject> objects, Game game) {
            rejectReplay(game, "replacement-effect");
            return super.chooseReplacementEffect(effects, objects, game);
        }
        private void rejectReplay(Game game, String callback) {
            if (context(game) != null) {
                throw new Failure(new IllegalArgumentException("unrecorded " + callback + " callback"));
            }
        }
    }
    private static void bindNumbers(Map<String, Object> decision, int min, int max) {
        if (min > max || (long) max - min > 64) {
            throw new IllegalArgumentException("numeric callback exceeds the original search envelope");
        }
        List<Object> candidates = Json.arr(decision, "candidates");
        if (candidates.size() != (long) max - min + 1) throw new IllegalArgumentException("numeric candidate count differs");
        java.util.Set<Long> values = new java.util.HashSet<>();
        for (Object candidate : candidates) {
            Map<String, Object> semantic = Json.obj(Json.obj(candidate), "semantic");
            Object value = semantic.get("value");
            if (!"choose_number".equals(Json.str(semantic, "kind")) || !(value instanceof Long)
                    || Json.num(semantic, "minimum", Long.MIN_VALUE) != min
                    || Json.num(semantic, "maximum", Long.MIN_VALUE) != max
                    || (Long) value < min || (Long) value > max || !values.add((Long) value)) {
                throw new IllegalArgumentException("numeric candidate is unbound or aliased");
            }
        }
    }
    private static Map<String, Map<String, Object>> bindChoices(Choice choice, Map<String, Object> decision) {
        Map<String, String> options = new LinkedHashMap<>(choice.getKeyChoices());
        if (options.isEmpty()) for (String option : choice.getChoices()) options.put(option, option);
        List<Object> candidates = Json.arr(decision, "candidates");
        if (options.size() < 2 || options.size() != candidates.size()) {
            throw new IllegalArgumentException("named callback options differ from the offered root");
        }
        Map<String, Map<String, Object>> result = new LinkedHashMap<>();
        java.util.Set<String> used = new java.util.HashSet<>();
        for (Map.Entry<String, String> option : options.entrySet()) {
            Map<String, Object> matched = null;
            for (Object candidate : candidates) {
                Map<String, Object> semantic = Json.obj(Json.obj(candidate), "semantic");
                String kind = Json.str(semantic, "kind"), raw = option.getValue();
                boolean same = "choose_option".equals(kind) ? raw.equals(Json.str(semantic, "option_label"))
                        : "choose_color".equals(kind) ? raw.toLowerCase(Locale.ROOT).equals(Json.str(semantic, "color"))
                        : "choose_name".equals(kind) && nameValue(Json.str(semantic, "purpose"), raw).equals(Json.str(semantic, "value"));
                if (same) {
                    if (matched != null) throw new IllegalArgumentException("aliased named callback label");
                    matched = semantic;
                }
            }
            if (matched == null || !used.add(Json.canonical(matched))) {
                throw new IllegalArgumentException("named callback option is unbound or aliased");
            }
            result.put(option.getKey(), matched);
        }
        return result;
    }
    private static String nameValue(String purpose, String raw) {
        if ("card_name".equals(purpose)) return Normalizer.normalize(raw, Normalizer.Form.NFC);
        return Normalizer.normalize(raw, Normalizer.Form.NFD).replaceAll("\\p{M}", "")
                .toLowerCase(Locale.ROOT).replace("'", "").replace("\u2019", "").replace(' ', '_').replace('-', '_');
    }
    static Object booleanValue(Map<String, Object> semantic) {
        String kind = Json.str(semantic, "kind");
        if ("choose_boolean".equals(kind)) return semantic.get("value");
        if ("optional_cost".equals(kind)) return semantic.get("pay");
        if ("optional_cast".equals(kind)) return semantic.get("cast_it");
        return null;
    }
    static Map<String, Object> selectedSemantic(Map<String, Object> decision, Map<String, Object> selection) {
        if (decision == null || selection == null || !(selection.get("candidate_id") instanceof Long)) {
            throw new IllegalArgumentException("replay needs a bound offered selection");
        }
        Map<String, Object> result = null;
        for (Object item : Json.arr(decision, "candidates")) {
            Map<String, Object> c = Json.obj(item);
            if (selection.get("candidate_id").equals(c.get("candidate_id"))
                    && Json.canonical(c.get("semantic")).equals(Json.canonical(selection.get("semantic_echo")))) {
                if (result != null) throw new IllegalArgumentException("aliased replay selection");
                result = Json.obj(c, "semantic");
            }
        }
        if (result == null) throw new IllegalArgumentException("replay selection was not offered");
        return result;
    }
    static Result run(Map<String, Object> record, RemoteModelEvaluator evaluator,
                      MCTSDefaults settings, boolean diagnostic) {
        Map<String, Object> anchor = Json.obj(record, "anchor");
        Map<String, Object> a = Json.obj(anchor, "decision");
        if (a == null || !"priority".equals(Json.str(Json.obj(a, "context"), "kind"))) {
            throw new IllegalArgumentException("callback search needs a saved priority decision");
        }
        Map<String, Object> action = selectedSemantic(a, Json.obj(anchor, "selection"));
        Result result = new Result();
        result.evaluator = evaluator; result.settings = settings; result.diagnostic = diagnostic;
        result.decision = Json.obj(record, "decision");
        Map<String, Object> history = Json.obj(record, "replay");
        if (history == null) throw new IllegalArgumentException("callback search needs explicit replay history");
        Object gaps = history.get("characteristic_gaps");
        if (gaps != null && !Boolean.TRUE.equals(gaps)) throw new IllegalArgumentException("invalid characteristic gap opt-in");
        result.tolerateGaps = Boolean.TRUE.equals(gaps);
        Object fungible = history.get("fungible_tapped");
        if (fungible != null && !Boolean.TRUE.equals(fungible)) throw new IllegalArgumentException("invalid fungible tapped opt-in");
        result.fungibleTapped = Boolean.TRUE.equals(fungible);
        Object attacks = history.get("attack_declarations");
        if (attacks != null) {
            if (!(attacks instanceof Long) || (Long) attacks < 1) throw new IllegalArgumentException("invalid attack declaration count");
            result.attackDeclarations = ((Long) attacks).intValue();
        }
        result.earlier = new ArrayList<>(Json.arr(history, "earlier"));
        for (Object seat : Json.arr(history, "priority_passes")) {
            if (!(seat instanceof String) || !("p0".equals(seat) || "p1".equals(seat))) {
                throw new IllegalArgumentException("invalid recorded priority seat");
            }
            result.passes.add((String) seat);
        }
        Map<String, Object> observation = Json.obj(Json.copy(a.get("observation")));
        if (!Json.str(observation, "viewer").equals(Json.str(Json.obj(result.decision, "observation"), "viewer"))) {
            throw new IllegalArgumentException("replay anchor belongs to another seat");
        }
        // The current callback may legitimately show library cards that were
        // hidden at the anchor. Condition the sampled world on these permitted
        // facts, without supplying actual unobserved order or opponent cards.
        List<Object> known = new ArrayList<>(Json.arr(observation, "known"));
        String viewer = Json.str(observation, "viewer");
        List<Object> shown = new ArrayList<>(Json.arr(Json.obj(result.decision, "observation"), "known"));
        for (Object entry : result.earlier) {
            shown.addAll(Json.arr(Json.obj(Json.obj(Json.obj(entry), "decision"), "observation"), "known"));
        }
        for (Object entry : shown) {
            Map<String, Object> card = Json.obj(entry);
            if (viewer.equals(Json.str(card, "owner_seat")) && "library".equals(Json.str(card, "zone"))) {
                String how = Json.str(card, "how");
                if (!("searching".equals(how) || "looked_at".equals(how) || "revealed".equals(how))) {
                    throw new IllegalArgumentException("library replay fact has no permitted visibility");
                }
                boolean present = false;
                for (Object old : known) {
                    if (card.get("object_id") != null && card.get("object_id").equals(Json.obj(old).get("object_id"))) present = true;
                }
                if (!present) known.add(Json.copy(card));
            }
        }
        observation.put("known", known);
        KitContext.reset(); GameAccess.reset(); KitRandom.installBoot();
        List<String> flags = WorldBuilder.restoreVisibleNames(observation, Json.obj(a, "x_history"));
        KitRandom random = KitRandom.install(Seeds.unhex(Json.str(record, "world_seed")), Seeds.unhex(Json.str(record, "id_seed")));
        WorldBuilder.Spec spec = new WorldBuilder.Spec();
        spec.gameStart = Json.obj(record, "game_start"); spec.observation = observation; spec.random = random;
        spec.sample = Sampler.sample(spec.gameStart, observation, random.stream("sampler"));
        spec.mode = WorldBuilder.Mode.PRIORITY; spec.history = Json.obj(a, "x_history");
        ReplayPlayer[] other = new ReplayPlayer[1];
        spec.viewerFactory = seat -> result.player = new ReplayPlayer(seat);
        spec.otherFactory = seat -> other[0] = new ReplayPlayer(seat);
        result.world = WorldBuilder.build(spec);
        result.world.flags.addAll(flags);
        if (result.tolerateGaps && result.world.flags.contains("approximate:unexplained_characteristics")) {
            try {
                result.recordGaps(observation, RoundTrip.project(result.world, RoundTrip.flagsFrom(a),
                        Json.str(observation, "priority_seat"), Json.arr(observation, "known")));
            } catch (RuntimeException e) { throw e; }
            catch (Exception e) { throw new IllegalStateException("callback anchor projection failed", e); }
        }
        for (String flag : result.world.flags) {
            if (flag.startsWith("unsupported:") || flag.startsWith("horizon:")) {
                throw new IllegalArgumentException("callback anchor is unsupported: " + flag);
            }
        }
        result.player.configureSearch(result);
        Game game = result.world.game;
        game.getState().resume();
        Ability ability = "pass".equals(Json.str(action, "kind")) ? new PassAbility()
                : Mapping.findPlayable(result.world, result.player, action, new ObsIndex(observation));
        if (!(ability instanceof ActivatedAbility)) throw new IllegalArgumentException("anchor action is not playable");
        GameAccess.setLastPriority(game, result.player.getId());
        live = result;
        try {
            if (ability instanceof PassAbility) result.player.pass(game);
            else if (!result.player.activateAbility((ActivatedAbility) ability.copy(), game)) {
                throw new IllegalArgumentException("recorded anchor action failed");
            }
            // resumePlay must continue the injected priority part rather than
            // treating its already-running step as completed after activation.
            game.pause();
            game.resume();
            throw new IllegalArgumentException("replay ended without the requested callback; remaining public passes="
                    + result.passes.size() + "; binary callbacks=" + result.binaryCallbacks
                    + "; phase=" + game.getTurnStepType() + "; turn=" + game.getTurnNum()
                    + "; stack=" + game.getStack().size() + "; game over=" + game.checkIfGameIsOver()
                    + "; viewer battlefield=" + game.getBattlefield().getAllActivePermanents(result.player.getId()).size());
        } catch (Failure failure) {
            throw failure.failure;
        } catch (Stop stop) {
            if (result.chosen == null || result.replayed != result.earlier.size()) {
                throw new IllegalArgumentException("callback replay did not complete its recorded prefix");
            }
            return result;
        } finally { live = null; }
    }
}
