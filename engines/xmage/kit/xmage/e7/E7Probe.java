package mage.player.ai.upstream;

import mage.abilities.Ability;
import mage.cards.Cards;
import mage.constants.Outcome;
import mage.constants.PhaseStep;
import mage.constants.RangeOfInfluence;
import mage.game.Game;
import mage.target.Target;

import java.io.Serializable;
import java.util.Map;

/**
 * E7 reference (design Section 9.1 E7): upstream {@code ComputerPlayer7} at the XMage pin, compiled from the pristine
 * sources into this package with the same X-P4 candidate as the kit, and nothing else changed. Its priority decision
 * is {@code ComputerPlayer7.priorityPlay}'s: pass outside the thinking steps, else the first action of the best chain.
 * Built only by kit/scripts/upstream.sh, never on an entry's classpath.
 */
public class E7Probe extends ComputerPlayer7 {

    private static final long serialVersionUID = 1L;
    public transient boolean setup = true;

    public E7Probe(String name, int skill) {
        super(name, RangeOfInfluence.ALL, skill);
    }

    protected E7Probe(final E7Probe p) {
        super(p);
        this.setup = p.setup;
    }

    @Override
    public E7Probe copy() {
        return new E7Probe(this);
    }

    @Override
    public boolean chooseMulligan(Game game) {
        return setup ? false : super.chooseMulligan(game);
    }

    @Override
    public boolean chooseUse(Outcome outcome, String message, String secondMessage, String trueText, String falseText,
                             Ability source, Game game) {
        return setup ? false : super.chooseUse(outcome, message, secondMessage, trueText, falseText, source, game);
    }

    @Override
    public boolean choose(Outcome outcome, Target target, Ability source, Game game, Map<String, Serializable> options) {
        return setup ? false : super.choose(outcome, target, source, game, options);
    }

    /** The first action of the best chain, or null for a pass. */
    public Ability decide(Game game) {
        setup = false;
        game.getState().setPriorityPlayerId(playerId);
        game.firePriorityEvent(playerId);
        PhaseStep s = game.getTurnStepType();
        if (!(s == PhaseStep.PRECOMBAT_MAIN || s == PhaseStep.DECLARE_ATTACKERS || s == PhaseStep.DECLARE_BLOCKERS
                || s == PhaseStep.POSTCOMBAT_MAIN)) {
            return null;
        }
        calculateActions(game);
        return actions.peek();
    }
}
