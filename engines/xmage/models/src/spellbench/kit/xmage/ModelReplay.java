package spellbench.kit.xmage;

import mage.abilities.Ability;
import mage.abilities.ActivatedAbility;
import mage.abilities.common.PassAbility;
import mage.abilities.Mode;
import mage.abilities.Modes;
import mage.abilities.mana.ManaOptions;
import mage.MageObject;
import mage.cards.Card;
import mage.cards.Cards;
import mage.choices.Choice;
import mage.constants.Outcome;
import mage.game.Game;
import mage.players.Player;
import mage.player.ai.encoder.ActionEncoder;
import mage.target.Target;
import mage.target.TargetCard;
import mage.target.TargetAmount;
import mage.target.common.TargetCardInLibrary;
import spellbench.kit.core.Json;
import spellbench.kit.core.ObsCompare;
import spellbench.kit.core.ObsIndex;
import spellbench.kit.core.Sampler;
import spellbench.kit.core.Seeds;
import spellbench.models.exp1.GameAccess;
import spellbench.models.exp1.MCTSNode2;
import spellbench.models.exp1.RemoteModelEvaluator;
import spellbench.models.exp1.SearchPlayer;
import spellbench.models.exp1.PlaySettings;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.text.Normalizer;
import java.util.UUID;
import java.util.function.BooleanSupplier;
import mage.abilities.costs.mana.ManaCost;

/** Reaches original search callbacks by replaying a saved permitted priority. */
final class ModelReplay {
    private ModelReplay() { }
    interface ModeCapture {
        default ManaOptions available(Player viewer, Game game) { return null; }
        default ManaCapture paymentRules() { return null; }
        Mode earlier(World world, Map<String, Object> decision, Modes modes, Ability source,
                     Game game, Map<String, Object> semantic);
        Map<String, Object> encode(World world, Map<String, Object> decision, Modes modes, Ability source,
                                   Game game);
    }
    interface DialogCapture {
        default ManaCapture paymentRules() { return null; }
        ManaOptions available(Player viewer, Game game, boolean fast);
        boolean earlierUse(World world, Map<String, Object> decision, Outcome outcome, String message,
                           Ability source, Game game, Map<String, Object> semantic);
        Map<String, Object> encodeUse(World world, Map<String, Object> decision, Outcome outcome, String message,
                                     Ability source, Game game);
        int earlierX(World world, Map<String, Object> decision, int min, int max, boolean mana,
                     Ability source, Game game, Map<String, Object> semantic);
        Map<String, Object> encodeX(World world, Map<String, Object> decision, int min, int max, boolean mana,
                                   Ability source, Game game);
    }
    interface ManaCapture {
        String sourceSha256();
        List<MageObject> producers(Player viewer, List<MageObject> original, Game game);
        boolean payment(Player viewer, ManaCost unpaid, BooleanSupplier engine);
        boolean activation(Player viewer, ActivatedAbility source, Game game, BooleanSupplier engine);
        Boolean target(Player viewer, Outcome outcome, Target target, Ability source, Game game);
        Boolean color(Player viewer, Outcome outcome, Choice choice, Game game);
    }
    interface TargetPick {
        UUID choose(List<UUID> possible, int selected, int minimum, int maximum,
                    boolean forced, UUID direct, String reason);
    }
    interface TargetCapture extends ModeCapture, DialogCapture {
        @Override ManaCapture paymentRules();
        default boolean generalCardTargets() { return false; }
        boolean select(Player viewer, Outcome outcome, Target target, Ability source, Game game, TargetPick picker);
        UUID earlier(World world, Map<String, Object> decision, Target target, Ability source, Game game,
                     List<UUID> possible, int selected, int minimum, int maximum,
                     boolean forced, UUID direct, String reason, Map<String, Object> semantic);
        Map<String, Object> encode(World world, Map<String, Object> decision, Target target, Ability source, Game game,
                                   List<UUID> possible, int selected, int minimum, int maximum,
                                   boolean forced, UUID direct, String reason);
    }
    interface CardSetPick {
        UUID choose(List<List<UUID>> groups, int selected, int minimum, int maximum,
                    boolean forced, boolean deduplicated);
    }
    interface CardSetCapture extends TargetCapture {
        boolean selectCards(Player viewer, Outcome outcome, Cards cards, TargetCard target, Ability source, Game game, CardSetPick picker);
        UUID earlierCards(World world, Map<String, Object> decision, TargetCard target, Ability source, Game game,
                          List<List<UUID>> groups, int selected, int minimum, int maximum,
                          boolean forced, boolean deduplicated, Map<String, Object> semantic);
        Map<String, Object> encodeCards(World world, Map<String, Object> decision, TargetCard target, Ability source, Game game,
                                        List<List<UUID>> groups, int selected, int minimum, int maximum,
                                        boolean forced, boolean deduplicated);
    }
    interface ParentCardPick {
        void choose(List<UUID> possible, UUID chosen, int selected, int minimum, int maximum, String rule);
    }
    interface ParentCardCapture extends CardSetCapture {
        boolean selectParentCards(Player viewer, Outcome outcome, Cards cards, TargetCard target, Ability source, Game game, ParentCardPick picker);
        void earlierParentCards(World world, Map<String, Object> decision, TargetCard target, Ability source, Game game,
                                List<UUID> possible, UUID chosen, int selected, int minimum, int maximum, String rule, Map<String, Object> semantic);
        Map<String, Object> encodeParentCards(World world, Map<String, Object> decision, TargetCard target, Ability source, Game game,
                                             List<UUID> possible, UUID chosen, int selected, int minimum, int maximum, String rule);
    }
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
        int visits;
        PlaySettings settings;
        int replayed;
        int binaryCallbacks;
        boolean libraryFailToFindExcluded;
        Integer numericMinimum;
        boolean numericRangeRestricted;
        Map<String, Map<String, Object>> namedActions;
        ModelModes modeActions;
        ModeCapture modeCapture;
        DialogCapture dialogCapture;
        ManaCapture manaCapture;
        TargetCapture targetCapture;
        Map<String, Object> encoded;

        void searchAllowed() {
            if (targetCapture != null) throw new IllegalArgumentException("target feature capture reached another callback");
            if (modeCapture != null) throw new IllegalArgumentException("mode feature capture reached another callback");
            if (dialogCapture != null) throw new IllegalArgumentException("dialog feature capture reached another callback");
        }

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
                List<String> diff = ObsCompare.diff(current, projected, 8);
                if (!diff.isEmpty()) throw new IllegalArgumentException("callback replay observation differs: " + diff);
            } catch (RuntimeException e) { throw e; }
            catch (Exception e) { throw new IllegalStateException("callback replay projection failed", e); }
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
        private ManaCapture paymentRules() {
            return live != null && live.manaCapture != null
                    && getId().equals(live.world.player(live.world.viewer)) ? live.manaCapture : null;
        }
        @Override public List<MageObject> getAvailableManaProducers(Game game) {
            List<MageObject> original = super.getAvailableManaProducers(game);
            ManaCapture rules = paymentRules();
            return rules == null ? original : rules.producers(this, original, game);
        }
        @Override public boolean playMana(Ability ability, ManaCost unpaid, String prompt, Game game) {
            ManaCapture rules = paymentRules();
            return rules == null ? super.playMana(ability, unpaid, prompt, game)
                    : rules.payment(this, unpaid, () -> super.playMana(ability, unpaid, prompt, game));
        }
        @Override public boolean chooseTarget(Outcome outcome, Target target, Ability source, Game game) {
            try {
                ManaCapture rules = paymentRules();
                Boolean handled = rules == null ? null : rules.target(this, outcome, target, source, game);
                if (handled != null) return handled;
                Result replay = context(game);
                if (replay == null || replay.targetCapture == null) return super.chooseTarget(outcome, target, source, game);
                if (!getId().equals(replay.world.player(replay.world.viewer)) || target == null
                        || target instanceof TargetAmount || target instanceof TargetCard && !replay.targetCapture.generalCardTargets()) {
                    throw new IllegalArgumentException("original general targets exclude opponent, card-set and divided callbacks");
                }
                return replay.targetCapture.select(this, outcome, target, source, game,
                        (possible, selected, minimum, maximum, forced, direct, reason) -> {
                            Map<String, Object> past = replay.earlierPick(game);
                            if (past != null) {
                                UUID pick = replay.targetCapture.earlier(replay.world, replay.callbackDecision(), target, source,
                                        game, possible, selected, minimum, maximum, forced, direct, reason, past);
                                getPlayerHistory().targetSequence.add(pick == null ? GameAccess.STOP_CHOOSING : pick);
                                replay.replayed++;
                                return pick;
                            }
                            replay.compare(game);
                            replay.player = this;
                            replay.encoded = replay.targetCapture.encode(replay.world, replay.decision, target, source,
                                    game, possible, selected, minimum, maximum, forced, direct, reason);
                            throw new Stop();
                        });
            } catch (RuntimeException e) { if (context(game) != null) throw new Failure(e); throw e; }
        }
        @Override public boolean choose(Outcome outcome, Target target, Ability source, Game game) {
            Result replay = context(game);
            return replay != null && replay.targetCapture != null ? chooseTarget(outcome, target, source, game)
                    : super.choose(outcome, target, source, game);
        }
        @Override public boolean chooseTarget(Outcome outcome, Cards cards, TargetCard target, Ability source, Game game) {
            try {
                Result replay = context(game);
                if (replay == null || !(replay.targetCapture instanceof CardSetCapture)) {
                    return super.chooseTarget(outcome, cards, target, source, game);
                }
                if (!getId().equals(replay.world.player(replay.world.viewer)) || cards == null || target == null) {
                    throw new IllegalArgumentException("provided-card callback exceeds its acting-player scope");
                }
                CardSetCapture capture = (CardSetCapture) replay.targetCapture;
                return capture.selectCards(this, outcome, cards, target, source, game,
                        (groups, selected, minimum, maximum, forced, deduplicated) -> {
                            Map<String, Object> past = replay.earlierPick(game);
                            if (past != null) {
                                UUID pick = capture.earlierCards(replay.world, replay.callbackDecision(), target, source, game,
                                        groups, selected, minimum, maximum, forced, deduplicated, past);
                                replay.replayed++;
                                return pick;
                            }
                            replay.compare(game);
                            replay.player = this;
                            replay.encoded = capture.encodeCards(replay.world, replay.decision, target, source, game,
                                    groups, selected, minimum, maximum, forced, deduplicated);
                            throw new Stop();
                        });
            } catch (RuntimeException e) { if (context(game) != null) throw new Failure(e); throw e; }
        }
        @Override public boolean choose(Outcome outcome, Cards cards, TargetCard target, Ability source, Game game) {
            try {
                Result replay = context(game);
                if (replay != null && replay.targetCapture instanceof ParentCardCapture) {
                    if (!getId().equals(replay.world.player(replay.world.viewer)) || cards == null || target == null) {
                        throw new IllegalArgumentException("parent card callback exceeds its acting-player scope");
                    }
                    ParentCardCapture capture = (ParentCardCapture) replay.targetCapture;
                    return capture.selectParentCards(this, outcome, cards, target, source, game,
                            (possible, chosen, selected, minimum, maximum, rule) -> {
                                Map<String, Object> past = replay.earlierPick(game);
                                if (past != null) {
                                    capture.earlierParentCards(replay.world, replay.callbackDecision(), target, source, game,
                                            possible, chosen, selected, minimum, maximum, rule, past);
                                    replay.replayed++;
                                    return;
                                }
                                replay.compare(game); replay.player = this;
                                replay.encoded = capture.encodeParentCards(replay.world, replay.decision, target, source, game,
                                        possible, chosen, selected, minimum, maximum, rule);
                                throw new Stop();
                            });
                }
                if (replay != null && replay.targetCapture instanceof CardSetCapture) {
                    throw new IllegalArgumentException("inherited choose(Cards) is separate from original neural chooseTarget(Cards)");
                }
                return super.choose(outcome, cards, target, source, game);
            } catch (RuntimeException e) { if (context(game) != null) throw new Failure(e); throw e; }
        }
        @Override public ManaOptions getManaAvailable(Game game) {
            Result replay = live;
            if (replay != null && replay.dialogCapture != null
                    && getId().equals(replay.world.player(replay.world.viewer))) {
                return replay.dialogCapture.available(this, game, false);
            }
            if (replay != null && replay.modeCapture != null
                    && getId().equals(replay.world.player(replay.world.viewer))) {
                ManaOptions available = replay.modeCapture.available(this, game);
                if (available != null) return available;
            }
            return super.getManaAvailable(game);
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
            replay.searchAllowed();
            configure(replay.evaluator, replay.settings);
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
                Object value = replay.dialogCapture == null ? booleanValue(past)
                        : replay.dialogCapture.earlierUse(replay.world, replay.callbackDecision(), outcome, message, source, game, past);
                if (!(value instanceof Boolean)) throw new IllegalArgumentException("recorded dialog is not binary");
                if (replay.dialogCapture == null) getPlayerHistory().useSequence.add((Boolean) value);
                replay.replayed++;
                return (Boolean) value;
            }
            replay.compare(game);
            replay.player = this;
            if (replay.dialogCapture != null) {
                replay.encoded = replay.dialogCapture.encodeUse(replay.world, replay.decision, outcome, message, source, game);
                throw new Stop();
            }
            replay.searchAllowed();
            configure(replay.evaluator, replay.settings);
            replay.chosen = searchAction(game, ActionEncoder.ActionType.CHOOSE_USE, message);
            throw new Stop();
        }
        @Override public boolean choose(Outcome outcome, Choice choice, Game game) {
            try { return replayChoice(outcome, choice, game); }
            catch (RuntimeException e) { if (context(game) != null) throw new Failure(e); throw e; }
        }
        private boolean replayChoice(Outcome outcome, Choice choice, Game game) {
            ManaCapture rules = paymentRules();
            Boolean handled = rules == null ? null : rules.color(this, outcome, choice, game);
            if (handled != null) return handled;
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
            replay.searchAllowed();
            configure(replay.evaluator, replay.settings);
            replay.chosen = searchChoice(game, choice);
            throw new Stop();
        }
        @Override public int announceX(int min, int max, String message, Game game, Ability source, boolean mana) {
            Result replay = context(game);
            if (replay == null || replay.dialogCapture == null) return super.announceX(min, max, message, game, source, mana);
            try {
                if (!getId().equals(replay.world.player(replay.world.viewer))) {
                    throw new IllegalArgumentException("unrecorded opponent X callback");
                }
                Map<String, Object> past = replay.earlierPick(game);
                if (past != null) {
                    int value = replay.dialogCapture.earlierX(replay.world, replay.callbackDecision(), min, max,
                            mana, source, game, past);
                    replay.replayed++;
                    return value;
                }
                replay.compare(game);
                replay.player = this;
                replay.encoded = replay.dialogCapture.encodeX(replay.world, replay.decision, min, max, mana, source, game);
                throw new Stop();
            } catch (RuntimeException e) { throw new Failure(e); }
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
                replay.searchAllowed();
                configure(replay.evaluator, replay.settings);
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
            replay.searchAllowed();
            configure(replay.evaluator, replay.settings);
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
                if (replay.modeCapture != null) {
                    Map<String, Object> past = replay.earlierPick(game);
                    if (past != null) {
                        Mode picked = replay.modeCapture.earlier(replay.world, replay.callbackDecision(),
                                modes, source, game, past);
                        replay.replayed++;
                        return picked;
                    }
                    replay.compare(game);
                    replay.encoded = replay.modeCapture.encode(replay.world, replay.decision, modes, source, game);
                    throw new Stop();
                }
                replay.compare(game, replay.callbackDecision());
                replay.modeActions = new ModelModes(replay.world, replay.callbackDecision(), modes, source, game);
                Mode picked = super.chooseMode(modes, source, game);
                replay.modeActions = null;
                return picked;
            } catch (RuntimeException e) { throw new Failure(e); }
        }
        @Override public void selectAttackers(Game game, UUID player) {
            rejectReplay(game, "attack");
            super.selectAttackers(game, player);
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
    static Result run(Map<String, Object> record, RemoteModelEvaluator evaluator, int visits) {
        return run(record, evaluator, PlaySettings.diagnostic(visits));
    }
    static Result run(Map<String, Object> record, RemoteModelEvaluator evaluator, PlaySettings settings) {
        return run(record, evaluator, settings, null, null, null);
    }
    static Result runMode(Map<String, Object> record, ModeCapture capture) {
        if (capture == null) throw new IllegalArgumentException("mode capture is required");
        return run(record, null, PlaySettings.diagnostic(2), capture, null, null);
    }
    static Result runDialog(Map<String, Object> record, DialogCapture capture) {
        if (capture == null) throw new IllegalArgumentException("dialog capture is required");
        return run(record, null, PlaySettings.diagnostic(2), null, capture, null);
    }
    static Result runTarget(Map<String, Object> record, TargetCapture capture) {
        if (capture == null) throw new IllegalArgumentException("target capture is required");
        return run(record, null, PlaySettings.diagnostic(2), capture, capture, capture);
    }
    private static Result run(Map<String, Object> record, RemoteModelEvaluator evaluator,
                              PlaySettings settings, ModeCapture capture, DialogCapture dialogs, TargetCapture targets) {
        settings.activate();
        Map<String, Object> anchor = Json.obj(record, "anchor");
        Map<String, Object> a = Json.obj(anchor, "decision");
        if (a == null || !"priority".equals(Json.str(Json.obj(a, "context"), "kind"))) {
            throw new IllegalArgumentException("callback search needs a saved priority decision");
        }
        Map<String, Object> action = selectedSemantic(a, Json.obj(anchor, "selection"));
        Result result = new Result();
        result.modeCapture = capture;
        result.dialogCapture = dialogs;
        result.targetCapture = targets;
        result.manaCapture = capture != null ? capture.paymentRules() : dialogs != null ? dialogs.paymentRules() : null;
        result.evaluator = evaluator; result.visits = settings.defaults.searchBudget; result.settings = settings;
        result.decision = Json.obj(record, "decision");
        Map<String, Object> history = Json.obj(record, "replay");
        if (history == null) throw new IllegalArgumentException("callback search needs explicit replay history");
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
        for (String flag : result.world.flags) {
            if (flag.startsWith("unsupported:") || flag.startsWith("horizon:")) {
                throw new IllegalArgumentException("callback anchor is unsupported: " + flag);
            }
        }
        if (capture == null && dialogs == null) result.player.configure(evaluator, settings);
        Game game = result.world.game;
        game.getState().resume();
        Ability ability = "pass".equals(Json.str(action, "kind")) ? new PassAbility()
                : Mapping.findPlayable(result.world, result.player, action, new ObsIndex(observation));
        if (!(ability instanceof ActivatedAbility)) throw new IllegalArgumentException("anchor action is not playable");
        GameAccess.setLastPriority(game, result.player.getId());
        live = result;
        try {
            if (ability instanceof PassAbility) result.player.pass(game);
            else if (!(result.manaCapture == null ? result.player.activateAbility((ActivatedAbility) ability.copy(), game)
                    : result.manaCapture.activation(result.player, (ActivatedAbility) ability.copy(), game,
                            () -> result.player.activateAbility((ActivatedAbility) ability.copy(), game)))) {
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
            if (result.chosen == null && result.encoded == null || result.replayed != result.earlier.size()
                    || !result.passes.isEmpty()) {
                throw new IllegalArgumentException("callback replay did not complete its recorded prefix");
            }
            return result;
        } finally { live = null; }
    }
}
