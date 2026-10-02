package mage.player.cabt;

import mage.game.Game;
import mage.players.Player;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * Test fixture: an in-process agent for real-engine smoke games. Greedy,
 * deterministic policy over option types — keep the opening hand, play a land
 * when offered, cast a spell when offered, pay mana from the first source,
 * never attack or block, otherwise pass. Any prompt the policy has no rule
 * for fails the game loudly instead of guessing.
 */
final class GreedyPolicyBridgeController implements CabtBridgeController {

    private final List<PendingDecision> decisions = new ArrayList<>();
    private final List<Selection> selections = new ArrayList<>();

    @Override
    public Selection requestSelection(Game game, Player player, PendingDecision decision) {
        Selection selection = decide(player, decision);
        decisions.add(decision);
        selections.add(selection);
        return selection;
    }

    List<PendingDecision> getDecisions() {
        return Collections.unmodifiableList(decisions);
    }

    List<Selection> getSelections() {
        return Collections.unmodifiableList(selections);
    }

    private Selection decide(Player player, PendingDecision decision) {
        switch (decision.selectType()) {
            case TARGET:
                // the only TARGET prompt this policy answers is the game-init
                // "choose the starting player" (every option is a player):
                // pick yourself so the smoke game's turn order is fixed. Any
                // other TARGET prompt falls through to the loud default so a
                // new surface can't be silently mis-answered.
                if (allOptionsAre(decision, MagicOptionType.PROMPT_PLAYER)) {
                    Integer self = firstIndexWithPayload(decision, "targetId", player.getId().toString());
                    return Selection.of(self != null ? self : 0);
                }
                throw new IllegalStateException(
                        "smoke-game policy only answers player-choice TARGET prompts "
                                + "(starting player), got: " + decision.options());
            case PRIORITY:
                Integer land = firstIndexOf(decision, MagicOptionType.PLAY_LAND);
                if (land != null) {
                    return Selection.of(land);
                }
                Integer cast = firstIndexOf(decision, MagicOptionType.CAST_SPELL);
                if (cast != null) {
                    return Selection.of(cast);
                }
                return Selection.of(requireIndexOf(decision, MagicOptionType.PASS_PRIORITY));
            case MULLIGAN:
                return Selection.of(requireIndexOf(decision, MagicOptionType.PROMPT_KEEP));
            case PAY_MANA:
                Integer source = firstIndexOf(decision, MagicOptionType.PROMPT_MANA_SOURCE);
                if (source != null) {
                    return Selection.of(source);
                }
                Integer pool = firstIndexOf(decision, MagicOptionType.PROMPT_MANA_POOL);
                if (pool != null) {
                    return Selection.of(pool);
                }
                return Selection.of(requireIndexOf(decision, MagicOptionType.PROMPT_CANCEL_PAYMENT));
            case DECLARE_ATTACKERS:
            case DECLARE_BLOCKERS:
                return new Selection(Collections.<Integer>emptyList());
            default:
                throw new IllegalStateException(
                        "smoke-game policy has no rule for prompt " + decision.selectType());
        }
    }

    private static boolean allOptionsAre(PendingDecision decision, MagicOptionType type) {
        for (MagicOption option : decision.options()) {
            if (option.type() != type) {
                return false;
            }
        }
        return !decision.options().isEmpty();
    }

    private static Integer firstIndexWithPayload(PendingDecision decision, String key, String value) {
        List<MagicOption> options = decision.options();
        for (int i = 0; i < options.size(); i++) {
            if (value.equals(options.get(i).payload().get(key))) {
                return i;
            }
        }
        return null;
    }

    private static Integer firstIndexOf(PendingDecision decision, MagicOptionType type) {
        List<MagicOption> options = decision.options();
        for (int i = 0; i < options.size(); i++) {
            if (options.get(i).type() == type) {
                return i;
            }
        }
        return null;
    }

    private static int requireIndexOf(PendingDecision decision, MagicOptionType type) {
        Integer index = firstIndexOf(decision, type);
        if (index == null) {
            throw new IllegalStateException(
                    "smoke-game policy expected a " + type + " option in " + decision.selectType());
        }
        return index;
    }
}
