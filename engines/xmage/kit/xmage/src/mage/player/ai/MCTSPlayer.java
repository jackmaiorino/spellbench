// Vendored from XMage fd40ad5c (MIT, see engines/xmage/NOTICE). Kit changes are marked KIT; the diff is published in kit/diffs/.
package mage.player.ai;

import mage.abilities.Ability;
import mage.abilities.ActivatedAbility;
import mage.abilities.SpellAbility;
import mage.abilities.common.PassAbility;
import mage.abilities.costs.mana.GenericManaCost;
import mage.game.Game;
import mage.game.permanent.Permanent;
import org.apache.log4j.Logger;

import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

/**
 * AI: server side bot with monte carlo logic (experimental, the latest version)
 * <p>
 * Simple implementation for random play, outdate and do not support,
 * see <a href="https://github.com/magefree/mage/issues/7075">more details here</a>
 *
 * @author BetaSteward_at_googlemail.com
 */
public class MCTSPlayer extends KitPayPlayer { // KIT: deterministic producer order

    private static final Logger logger = Logger.getLogger(MCTSPlayer.class);

    private NextAction nextAction;

    public enum NextAction {
        PRIORITY, SELECT_ATTACKERS, SELECT_BLOCKERS
    }

    public MCTSPlayer(UUID id) {
        super(id);
    }

    public MCTSPlayer(final MCTSPlayer player) {
        super(player);
        this.nextAction = player.nextAction;
    }

    @Override
    public MCTSPlayer copy() {
        return new MCTSPlayer(this);
    }

    protected List<ActivatedAbility> getPlayableAbilities(Game game) {
        List<ActivatedAbility> playables = getPlayable(game, true);
        playables.add(new PassAbility());
        return playables;
    }

    public List<Ability> getPlayableOptions(Game game) {
        List<Ability> all = new ArrayList<>();
        List<ActivatedAbility> playables = getPlayableAbilities(game);
        for (ActivatedAbility ability : playables) {
            // KIT: option-generation budget in expansion (addendum change 2)
            if (KitBudgets.estimateOptions(ability, playerId, game) > spellbench.kit.xmage.KitContext.optionBudget) {
                spellbench.kit.xmage.KitContext.count("cap:options_skipped");
                continue;
            }
            List<Ability> options = game.getPlayer(playerId).getPlayableOptions(ability, game);
            if (options.size() > spellbench.kit.xmage.KitContext.optionBudget) {
                options = new ArrayList<>(options.subList(0, spellbench.kit.xmage.KitContext.optionBudget));
                spellbench.kit.xmage.KitContext.count("cap:options_truncated");
            }
            if (options.isEmpty()) {
                if (!ability.getManaCosts().getVariableCosts().isEmpty()) {
                    simulateVariableCosts(ability, all, game);
                } else {
                    all.add(ability);
                }
            } else {
                for (Ability option : options) {
                    if (!ability.getManaCosts().getVariableCosts().isEmpty()) {
                        simulateVariableCosts(option, all, game);
                    } else {
                        all.add(option);
                    }
                }
            }
        }
        return all;
    }

    protected void simulateVariableCosts(Ability ability, List<Ability> options, Game game) {
        int numAvailable = getAvailableManaProducers(game).size() - ability.getManaCosts().manaValue();
        int start = 0;
        if (!(ability instanceof SpellAbility)) {
            //only use x=0 on spell abilities
            if (numAvailable == 0)
                return;
            else
                start = 1;
        }
        for (int i = start; i < numAvailable; i++) {
            Ability newAbility = ability.copy();
            newAbility.addManaCostsToPay(new GenericManaCost(i));
            options.add(newAbility);
        }
    }

    public List<List<UUID>> getAttacks(Game game) {
        List<List<UUID>> engagements = new ArrayList<>();
        List<Permanent> attackersList = super.getAvailableAttackers(game);
        //use binary digits to calculate powerset of attackers
        int powerElements = (int) Math.pow(2, attackersList.size());
        StringBuilder binary = new StringBuilder();
        for (int i = powerElements - 1; i >= 0; i--) {
            if (engagements.size() >= spellbench.kit.xmage.KitContext.combatOptionBudget) { // KIT: combat option budget
                spellbench.kit.xmage.KitContext.count("cap:combat_options");
                break;
            }
            binary.setLength(0);
            binary.append(Integer.toBinaryString(i));
            while (binary.length() < attackersList.size()) {
                binary.insert(0, '0');
            }
            List<UUID> engagement = new ArrayList<>();
            for (int j = 0; j < attackersList.size(); j++) {
                if (binary.charAt(j) == '1') {
                    engagement.add(attackersList.get(j).getId());
                }
            }
            engagements.add(engagement);
        }
        return engagements;
    }

    public List<List<List<UUID>>> getBlocks(Game game) {
        List<List<List<UUID>>> engagements = new ArrayList<>();
        int numGroups = game.getCombat().getGroups().size();
        if (numGroups == 0) {
            return engagements;
        }

        //add a node with no blockers
        List<List<UUID>> engagement = new ArrayList<>();
        for (int i = 0; i < numGroups; i++) {
            engagement.add(new ArrayList<UUID>());
        }
        engagements.add(engagement);

        List<Permanent> blockers = getAvailableBlockers(game);
        addBlocker(game, engagement, blockers, engagements);

        return engagements;
    }

    private List<List<UUID>> copyEngagement(List<List<UUID>> engagement) {
        List<List<UUID>> newEngagement = new ArrayList<>();
        for (List<UUID> group : engagement) {
            newEngagement.add(new ArrayList<>(group));
        }
        return newEngagement;
    }

    protected void addBlocker(Game game, List<List<UUID>> engagement, List<Permanent> blockers, List<List<List<UUID>>> engagements) {
        if (blockers.isEmpty())
            return;
        if (engagements.size() >= spellbench.kit.xmage.KitContext.combatOptionBudget) { // KIT: combat option budget
            spellbench.kit.xmage.KitContext.count("cap:combat_options");
            return;
        }
        int numGroups = game.getCombat().getGroups().size();
        //try to block each attacker with each potential blocker
        Permanent blocker = blockers.get(0);
//        if (logger.isDebugEnabled())
//            logger.debug("simulating -- block:" + blocker);
        List<Permanent> remaining = remove(blockers, blocker);
        for (int i = 0; i < numGroups; i++) {
            if (game.getCombat().getGroups().get(i).canBlock(blocker, game)) {
                List<List<UUID>> newEngagement = copyEngagement(engagement);
                newEngagement.get(i).add(blocker.getId());
                if (engagements.size() >= spellbench.kit.xmage.KitContext.combatOptionBudget) { // KIT
                    spellbench.kit.xmage.KitContext.count("cap:combat_options");
                    return;
                }
                engagements.add(newEngagement);
//                    logger.debug("simulating -- found redundant block combination");
                addBlocker(game, newEngagement, remaining, engagements);  // and recurse minus the used blocker
            }
        }
        addBlocker(game, engagement, remaining, engagements);
    }

    public NextAction getNextAction() {
        return nextAction;
    }

    public void setNextAction(NextAction action) {
        this.nextAction = action;
    }

    @Override
    public boolean priority(Game game) {
        game.pause();
        nextAction = NextAction.PRIORITY;
        return false;
    }

    // KIT: looks and reveals fire no event; the branch's knowledge is notified (addendum change 1)
    @Override
    public void revealCards(Ability source, String titleSuffix, mage.cards.Cards cards, Game game, boolean postToLog) {
        super.revealCards(source, titleSuffix, cards, game, postToLog);
        spellbench.kit.xmage.KnowledgeWatcher.looked(game, playerId, cards, true);
    }

    @Override
    public void lookAtCards(Ability source, String titleSuffix, mage.cards.Cards cards, Game game) {
        super.lookAtCards(source, titleSuffix, cards, game);
        spellbench.kit.xmage.KnowledgeWatcher.looked(game, playerId, cards, false);
    }

    @Override
    public boolean chooseTarget(mage.constants.Outcome outcome, mage.cards.Cards cards, mage.target.TargetCard target, Ability source, Game game) {
        spellbench.kit.xmage.KitContext.dialog(); // KIT: dialog count (H3 non-stack detection)
        // a choice among library cards shows them to the chooser (scry, surveil, look at the top)
        spellbench.kit.xmage.KnowledgeWatcher.looked(game, playerId, cards, false);
        return super.chooseTarget(outcome, cards, target, source, game);
    }

    // KIT: every dialog is counted, so an action that leaves no stack object and asked one is detected at the root
    @Override
    public boolean chooseUse(mage.constants.Outcome outcome, String message, String secondMessage, String trueText,
                             String falseText, Ability source, Game game) {
        spellbench.kit.xmage.KitContext.dialog();
        return super.chooseUse(outcome, message, secondMessage, trueText, falseText, source, game);
    }

    @Override
    public boolean choose(mage.constants.Outcome outcome, mage.choices.Choice choice, Game game) {
        spellbench.kit.xmage.KitContext.dialog();
        boolean r = super.choose(outcome, choice, game);
        if (choice instanceof mage.choices.ChoiceColor) {
            spellbench.kit.xmage.KitContext.color(choice.getChoice()); // KIT: a color the plan can carry
        }
        return r;
    }

    @Override
    public boolean choose(mage.constants.Outcome outcome, mage.target.Target target, Ability source, Game game,
                          java.util.Map<String, java.io.Serializable> options) {
        spellbench.kit.xmage.KitContext.dialog();
        return super.choose(outcome, target, source, game, options);
    }

    @Override
    public boolean choose(mage.constants.Outcome outcome, mage.cards.Cards cards, mage.target.TargetCard target,
                          Ability source, Game game) {
        spellbench.kit.xmage.KitContext.dialog();
        return super.choose(outcome, cards, target, source, game);
    }

    @Override
    public boolean chooseTarget(mage.constants.Outcome outcome, mage.target.Target target, Ability source, Game game) {
        spellbench.kit.xmage.KitContext.dialog();
        return super.chooseTarget(outcome, target, source, game);
    }

    @Override
    public int getAmount(int min, int max, String message, Ability source, Game game) {
        spellbench.kit.xmage.KitContext.dialog();
        return super.getAmount(min, max, message, source, game);
    }

    @Override
    public void selectAttackers(Game game, UUID attackingPlayerId) {
        game.pause();
        nextAction = NextAction.SELECT_ATTACKERS;
    }

    @Override
    public void selectBlockers(Ability source, Game game, UUID defendingPlayerId) {
        game.pause();
        nextAction = NextAction.SELECT_BLOCKERS;
    }
}
