"""Wire original priority and Choice callbacks into inherited and neural paths."""
from __future__ import annotations

import hashlib

from xmage_jack_sources import CALLBACK_SHA256, extract, replace_once

PRIORITY_CHOICE_VARIANT = (
    "original priority step dispatch and regular-choice order/application; original "
    "mana-color and alternative-cost delegation; shared original neural session; "
    "copy requires owned permitted-world binding; model-error fallback refuses; "
    "remaining callbacks and native full-player qualification unfinished")


def priority_choice_source(source: str) -> str:
    if hashlib.sha256(source.encode()).hexdigest() != CALLBACK_SHA256:
        raise ValueError("Jack priority/choice player requires the pinned April callback bytes")
    mana = extract(source, "        // Mana color payment: delegate to base AI logic",
                   "        // Detect alternative cost choices")
    mana = mana.replace("inPlayManaContext()", "inOriginalPlayManaContext()")
    mana = replace_once(mana, "preferredManaColorForUnpaid(currentUnpaidManaText.get(), choice.getChoices())",
                        "originalPreferredManaColor(choice)")
    mana = mana.replace("currentUnpaidManaText.get()", "originalUnpaidManaText()")
    mana = replace_once(mana, "super.choose(outcome, choice, game)", "originalParentChoice(outcome, choice, game)")
    regular = extract(source, "        // Handle regular choices (modal spells, etc.) with RL model",
                      "        // Use RL model to score the choices")
    if regular.count("super.choose(outcome, choice, game)") != 2:
        raise ValueError("original regular-choice parent delegation changed")
    regular = regular.replace("super.choose(outcome, choice, game)", "originalParentChoice(outcome, choice, game)")
    pick = extract(source, "                rankedIndices = genericChoose(", "            } finally {\n                choiceExplosionContext.remove();")
    pick = replace_once(pick, "rankedIndices = genericChoose(", "List<Integer> rankedIndices = originalNeural.genericChoose(")
    pick = replace_once(pick, "                        currentAbility", "                        activationAbility()")
    apply = extract(source, "            if (rankedIndices != null && !rankedIndices.isEmpty()) {\n                int chosenIdx",
                    "                if (ACTIVATION_DIAG) {\n                    RLTrainer.threadLocalLogger.get().info(\n                            \"CHOOSE: RL model selected:")
    return '''package spellbench.models.jack;

import mage.abilities.*;
import mage.choices.Choice;
import mage.constants.*;
import mage.game.Game;
import java.util.*;
import java.util.function.Supplier;

/** Actual original priority/choice dispatch. Remaining strategic callbacks are required. */
public abstract class OriginalPriorityChoicePlayer extends OriginalParentDialogsPlayer {
    public static final String SOURCE_SHA256 = "%s";
    public static final String VARIANT = "%s";
    private static final boolean USE_ENGINE_CHOICES = true;
    private Game originalWorld;
    private PriorityRules originalPriority;
    private OriginalNeuralSelection originalNeural;
    private OriginalNeuralSelection.Session originalSession;
    private OriginalNeuralSelection.Admission originalAdmission;
    protected OriginalPriorityChoicePlayer(String name, RangeOfInfluence range) { super(name, range); }
    protected OriginalPriorityChoicePlayer(mage.player.ai.ComputerPlayer bootstrap) { super(bootstrap); }
    protected OriginalPriorityChoicePlayer(OriginalPriorityChoicePlayer player) {
        super(player);
        // Original policy/model sharing, with explicit admission of the copied world.
        originalSession = player.originalSession;
        // Never copy a root world, aliases, cached rules or its player-bound encoder.
    }
    @Override public abstract OriginalPriorityChoicePlayer copy();
    public final void bindOriginalWorld(Game game, Map<UUID, String> aliases,
            OriginalNeuralSelection.Session session, OriginalNeuralSelection.Admission admission) {
        if (originalWorld != null || game == null || game.getPlayer(getId()) != this
                || aliases == null || session == null || admission == null
                || (originalSession != null && originalSession != session))
            throw new IllegalArgumentException("original callback player needs one owned world and its shared session");
        admission.require(game, this);
        PriorityRules rules = new PriorityRules(this, aliases);
        OriginalNeuralSelection neural = new OriginalNeuralSelection(this, rules, session, admission);
        neural.requireWorld(game);
        originalWorld = game; originalPriority = rules; originalNeural = neural; originalSession = session;
        originalAdmission = admission;
    }
    @Override protected final void requireOriginalPermittedWorld(Game game) {
        if (originalWorld == null || game != originalWorld || game.getPlayer(getId()) != this) {
            IllegalArgumentException error = new IllegalArgumentException("original callback player world/copy is not admitted");
            closeOriginalSession(error); throw error;
        }
        originalNeural.requireWorld(game);
    }
    protected final PriorityRules originalPriorityRules() { return originalPriority; }
    protected final OriginalNeuralSelection.Session originalNeuralSession() { return originalSession; }
    protected final OriginalNeuralSelection originalNeuralSelection() { return originalNeural; }
    protected final OriginalNeuralSelection.Admission originalWorldAdmission() { return originalAdmission; }
    @Override protected final void requireOriginalActivationWorld(Game game) { requireOriginalPermittedWorld(game); }
    @Override protected final void act(Game game, ActivatedAbility ability) {
        requireOriginalPermittedWorld(game); super.act(game, ability); requireOriginalPermittedWorld(game);
    }
    @Override public final boolean activateAbility(ActivatedAbility ability, Game game) {
        requireOriginalPermittedWorld(game); boolean result = super.activateAbility(ability, game);
        requireOriginalPermittedWorld(game); return result;
    }
    @Override public final boolean playMana(Ability ability, mage.abilities.costs.mana.ManaCost unpaid, String text, Game game) {
        requireOriginalPermittedWorld(game); boolean result = super.playMana(ability, unpaid, text, game);
        requireOriginalPermittedWorld(game); return result;
    }
    @Override public final mage.abilities.mana.ManaOptions getManaAvailable(Game game) {
        requireOriginalPermittedWorld(game); mage.abilities.mana.ManaOptions result = super.getManaAvailable(game);
        requireOriginalPermittedWorld(game); return result;
    }
    @Override protected final mage.abilities.mana.ManaOptions getManaAvailableFast(Game game) {
        requireOriginalPermittedWorld(game); mage.abilities.mana.ManaOptions result = super.getManaAvailableFast(game);
        requireOriginalPermittedWorld(game); return result;
    }
    @Override public final List<mage.MageObject> getAvailableManaProducers(Game game) {
        requireOriginalPermittedWorld(game); List<mage.MageObject> result = super.getAvailableManaProducers(game);
        requireOriginalPermittedWorld(game); return result;
    }
    @Override public final boolean cast(SpellAbility ability, Game game, boolean noMana, mage.ApprovingObject approving) {
        requireOriginalPermittedWorld(game); boolean result = super.cast(ability, game, noMana, approving);
        requireOriginalPermittedWorld(game); return result;
    }
    @Override protected final boolean playAbility(ActivatedAbility ability, Game game) {
        requireOriginalPermittedWorld(game); boolean result = super.playAbility(ability, game);
        requireOriginalPermittedWorld(game); return result;
    }
    private void closeOriginalSession(Throwable failure) {
        if (originalSession != null) {
            try { originalSession.close(); } catch (RuntimeException | Error closing) { failure.addSuppressed(closing); }
        }
    }
    @Override public final boolean priority(Game game) {
        requireOriginalPermittedWorld(game);
        game.resumeTimer(getTurnControlledBy());
        try {
            boolean result = dispatchOriginalPriority(originalPriority, game, options -> originalNeural.genericChoose(
                    options, 1, 1, StateSequenceBuilder.ActionType.ACTIVATE_ABILITY_OR_SPELL, game, null).get(0));
            requireOriginalPermittedWorld(game); return result;
        } catch (RuntimeException | Error failure) { closeOriginalSession(failure); throw failure; }
        finally { game.pauseTimer(getTurnControlledBy()); }
    }
    private static void trace(String ignored) { }
    protected boolean replayOriginalChoice(Outcome outcome, Choice choice, Game game, Supplier<Boolean> work) {
        return work.get();
    }
    protected boolean ownsOriginalReplayPause(Game game, Throwable failure) { return false; }
    @Override public final boolean choose(Outcome outcome, Choice choice, Game game) {
        requireOriginalPermittedWorld(game);
        try {
            boolean result = replayOriginalChoice(outcome, choice, game, () -> chooseOriginalBody(outcome, choice, game));
            requireOriginalPermittedWorld(game); return result;
        } catch (RuntimeException | Error failure) {
            if (!ownsOriginalReplayPause(game,failure)) closeOriginalSession(failure);
            throw failure;
        }
    }
    private boolean chooseOriginalBody(Outcome outcome, Choice choice, Game game) {
''' % (CALLBACK_SHA256, PRIORITY_CHOICE_VARIANT) + mana + '''
        Boolean alternative = originalPriority.alternativeChoice(outcome, choice, game,
                () -> originalParentChoice(outcome, choice, game));
        if (alternative != null) return alternative;
''' + regular + pick + apply + '''
                return true;
            }
            throw new IllegalArgumentException("original required choice produced no selected slot");
    }
}
'''
