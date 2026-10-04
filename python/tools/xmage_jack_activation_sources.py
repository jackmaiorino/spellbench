"""Stage original activation plumbing, requiring original strategic/parent callbacks."""
from __future__ import annotations

import hashlib

from xmage_jack_sources import CALLBACK_SHA256, extract, replace_once

ACTIVATION_VARIANT = ("original fresh-ability activation, tap-cost reservations, filtered mana and payment context; "
                      "original cast/play-ability bookmark recovery and stack-dependent passing; "
                      "required original strategic/parent callbacks; persistent player and native games unfinished")


def activation_source(source: str) -> str:
    if hashlib.sha256(source.encode()).hexdigest() != CALLBACK_SHA256:
        raise ValueError("Jack activation player requires the pinned April callback bytes")
    action = extract(source, "    protected void act(Game game, ActivatedAbility ability) {",
                     "    /**\n     * Adds a trace entry to the activation trace buffer")
    action = replace_once(action, "super.activateAbility(freshAbility, game)", "activateOriginalAbility(freshAbility, game)")
    trace = extract(source, "    private void trace(String msg) {", "    /**\n     * Parses mana symbols from a chooseUse prompt")
    fresh = extract(source, "    private ActivatedAbility resolveFreshAbility(", "    private boolean hasRequiredTargets(")
    helpers = extract(source, "    private static boolean inPlayManaContext() {", "    public void setAttachedGameLogger(")
    plumbing = extract(source, "    @Override\n    public boolean playMana(", "    /**\n     * Override cast() to add safety bookmarks")
    plumbing = replace_once(plumbing, "super.playMana(ability, unpaid, promptText, game)",
                            "originalParentPlayMana(ability, unpaid, promptText, game)")
    plumbing = replace_once(plumbing, "super.getAvailableManaProducers(game)", "originalParentManaProducers(game)")
    plumbing = replace_once(plumbing, "Game game = originalGame.createSimulationForPlayableCalc();",
                            "Game game = originalGame.createSimulationForPlayableCalc();\n        requireOriginalManaSimulation(originalGame, game);")
    # The pinned engine has no fast-getter hook. Retain the original body as an explicit method.
    plumbing = replace_once(plumbing, "    @Override\n    protected ManaOptions getManaAvailableFast(Game game)",
                            "    protected ManaOptions getManaAvailableFast(Game game)")
    recovery = extract(source, "    @Override\n    public boolean cast(", "    // Disables engine auto-targeting heuristics")
    recovery = replace_once(recovery, "super.cast(ability, game, noMana, approvingObject)",
                            "castOriginalSpell(ability, game, noMana, approvingObject)")
    recovery = replace_once(recovery, "super.playAbility(ability, game)", "playOriginalAbility(ability, game)")
    mana_target = extract(source, "        // During mana payment, avoid tapping key mana producers",
                          "        // RL-only target selection. No engine fallback.")
    mana_target = mana_target.replace("super.chooseTarget(outcome, target, source, game)", "parent.getAsBoolean()")
    return '''package spellbench.models.jack;

import mage.MageObject;
import mage.Mana;
import mage.ConditionalMana;
import mage.abilities.Ability;
import mage.abilities.Abilities;
import mage.abilities.ActivatedAbility;
import mage.abilities.SpellAbility;
import mage.abilities.mana.ManaAbility;
import mage.abilities.mana.ManaOptions;
import mage.cards.Card;
import mage.cards.Cards;
import mage.choices.Choice;
import mage.constants.Outcome;
import mage.constants.RangeOfInfluence;
import mage.constants.Zone;
import mage.game.Game;
import mage.game.permanent.Permanent;
import mage.player.ai.ComputerPlayer;
import mage.target.Target;
import mage.target.TargetAmount;
import mage.target.TargetCard;
import java.io.Serializable;
import java.util.*;
import java.util.stream.Collectors;

/** Original activation plumbing. Strategic callbacks and parent policy are mandatory. */
public abstract class OriginalActivationPlayer extends ComputerPlayer {
    public static final String SOURCE_SHA256 = "%s";
    public static final String VARIANT = "%s";
    public static final int ORIGINAL_PARENT_SKILL = 10;
    private static final boolean ACTIVATION_DIAG = false;
    private static final boolean USE_ENGINE_CHOICES = true;
    private static final java.util.concurrent.atomic.AtomicInteger RL_ACTIVATION_FAILURES = new java.util.concurrent.atomic.AtomicInteger();
    private static final ThreadLocal<List<String>> activationTrace = ThreadLocal.withInitial(ArrayList::new);
    private static final ThreadLocal<Boolean> traceEnabled = ThreadLocal.withInitial(() -> false);
    private static final ThreadLocal<Integer> playManaDepth = ThreadLocal.withInitial(() -> 0);
    private static final ThreadLocal<String> currentUnpaidManaText = new ThreadLocal<>();
    private Ability currentAbility;
    private UUID abilitySourceToExcludeFromMana;
    private Set<UUID> tapTargetCostReservations = new HashSet<>();
    private boolean lastActivationHadStateLeak;
    protected OriginalActivationPlayer(String name, RangeOfInfluence range) { super(name, range); }
    protected OriginalActivationPlayer(OriginalActivationPlayer player) {
        super(player);
        currentAbility = player.currentAbility;
        // Original copy semantics: current ability is copied; payment reservations and leak state reset.
        abilitySourceToExcludeFromMana = null;
        tapTargetCostReservations = new HashSet<>();
    }
    @Override public abstract OriginalActivationPlayer copy();
    @Override public abstract boolean priority(Game game);
    @Override public abstract boolean chooseTarget(Outcome outcome, Target target, Ability source, Game game);
    @Override public abstract boolean chooseTarget(Outcome outcome, Cards cards, TargetCard target, Ability source, Game game);
    @Override public abstract boolean choose(Outcome outcome, Target target, Ability source, Game game);
    @Override public abstract boolean choose(Outcome outcome, Cards cards, TargetCard target, Ability source, Game game);
    @Override public abstract boolean choose(Outcome outcome, Choice choice, Game game);
    @Override public abstract boolean chooseTargetAmount(Outcome outcome, TargetAmount target, Ability source, Game game);
    @Override public abstract boolean choose(Outcome outcome, Target target, Ability source, Game game, Map<String, Serializable> options);
    @Override public abstract mage.abilities.Mode chooseMode(mage.abilities.Modes modes, Ability source, Game game);
    @Override public abstract int announceX(int min, int max, String message, Game game, Ability source, boolean isManaPay);
    @Override public abstract boolean chooseUse(Outcome outcome, String message, Ability source, Game game);
    @Override public abstract boolean chooseUse(Outcome outcome, String message, String secondMessage, String trueText, String falseText, Ability source, Game game);
    @Override public abstract void selectAttackers(Game game, UUID attackingPlayerId);
    @Override public abstract void selectBlockers(Ability source, Game game, UUID defendingPlayerId);
    @Override public abstract boolean chooseMulligan(Game game);
    protected abstract boolean originalParentPlayMana(Ability ability, mage.abilities.costs.mana.ManaCost unpaid, String promptText, Game game);
    protected abstract List<MageObject> originalParentManaProducers(Game game);
    // The pinned engine ComputerPlayer delegates this primitive directly to PlayerImpl.
    protected List<MageObject> engineParentManaProducers(Game game) { return super.getAvailableManaProducers(game); }
    protected void requireOriginalActivationWorld(Game game) {
        if (game == null || game.getPlayer(getId()) != this)
            throw new IllegalArgumentException("original activation needs its owned player");
    }
    protected void requireOriginalManaSimulation(Game source, Game copied) {
        // A complete player supplies the permitted-copy gate; partial components cannot qualify it.
    }
    public final void applyOriginalPriorityAbility(Game game, ActivatedAbility ability) {
        if (game == null || game.getPlayer(getId()) != this) throw new IllegalArgumentException("original activation needs its owned permitted player");
        requireOriginalActivationWorld(game);
        act(game, ability);
    }
    public final boolean dispatchOriginalPriority(PriorityRules rules, Game game,
            java.util.function.ToIntFunction<List<ActivatedAbility>> chooser) {
        if (rules == null || rules.owner() != this || game == null || game.getPlayer(getId()) != this || chooser == null)
            throw new IllegalArgumentException("priority dispatch needs its persistent owned rules and original chooser");
        requireOriginalActivationWorld(game);
        return rules.dispatch(game, chooser, ability -> act(game, ability), () -> pass(game));
    }
    public final Ability activationAbility() { return currentAbility; }
    protected final boolean inOriginalPlayManaContext() { return inPlayManaContext(); }
    protected final String originalUnpaidManaText() { return currentUnpaidManaText.get(); }
    protected final String originalPreferredManaColor(Choice choice) {
        return preferredManaColorForUnpaid(currentUnpaidManaText.get(), choice.getChoices());
    }
    public final UUID excludedManaSource() { return abilitySourceToExcludeFromMana; }
    public final Set<UUID> reservedTapSources() { return Collections.unmodifiableSet(new HashSet<>(tapTargetCostReservations)); }
    public final boolean activationHadStateLeak() { return lastActivationHadStateLeak; }
    protected boolean activateOriginalAbility(ActivatedAbility ability, Game game) { return super.activateAbility(ability, game); }
    protected boolean castOriginalSpell(SpellAbility ability, Game game, boolean noMana, mage.ApprovingObject approvingObject) {
        return super.cast(ability, game, noMana, approvingObject);
    }
    protected boolean playOriginalAbility(ActivatedAbility ability, Game game) { return super.playAbility(ability, game); }
    @Override public boolean getStrictChooseMode() { return !USE_ENGINE_CHOICES; }
    private static final class Log { void info(String value) { } void error(String value) { } }
    private static final class RLTrainer { static final ThreadLocal<Log> threadLocalLogger = ThreadLocal.withInitial(Log::new); }
    // Training/debug file I/O is excluded. These diagnostics do not change an activation choice.
    private void logActivationFailure(ActivatedAbility ability, Game game) { }
    private void writeActivationFailureToFile(ActivatedAbility ability, Game game, Exception error, List<String> trace) { }
    private void logAbilityTargets(ActivatedAbility ability, Game game) { }
    private void pauseOnActivationFailure() { }
''' % (CALLBACK_SHA256, ACTIVATION_VARIANT) + action + trace + fresh + helpers + plumbing + recovery + '''
    protected final Boolean originalManaTarget(Outcome outcome, Target target, Ability source, Game game,
            java.util.function.BooleanSupplier parent) {
''' + mana_target + "        return null;\n    }\n}\n"
