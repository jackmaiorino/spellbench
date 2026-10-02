package mage.player.cabt;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * Test fixture: the session-API twin of {@link GreedyPolicyBridgeController}.
 * Maps a {@link CabtGameSession.Event} decision to option indices — keep the
 * opening hand, play a land when offered, cast a spell when offered, pay mana
 * from the first source, never attack or block, otherwise pass; prompts with
 * no rule take the first {@code minCount} options rather than failing, since
 * protocol games run past the scripted smoke-game surface.
 */
final class CabtEventPolicy {

    private CabtEventPolicy() {
    }

    static List<Integer> choose(CabtGameSession.Event event) {
        PendingDecision decision = event.decision();
        switch (decision.selectType()) {
            case TARGET:
                if (allOptionsAre(decision, MagicOptionType.PROMPT_PLAYER)) {
                    Integer self = firstIndexWithPayload(decision, "targetId", event.playerId());
                    return Collections.singletonList(self != null ? self : 0);
                }
                return firstMinCount(decision);
            case PRIORITY:
                Integer land = firstIndexOf(decision, MagicOptionType.PLAY_LAND);
                if (land != null) {
                    return Collections.singletonList(land);
                }
                Integer cast = firstIndexOf(decision, MagicOptionType.CAST_SPELL);
                if (cast != null) {
                    return Collections.singletonList(cast);
                }
                return Collections.singletonList(
                        requireIndexOf(decision, MagicOptionType.PASS_PRIORITY));
            case MULLIGAN:
                return Collections.singletonList(
                        requireIndexOf(decision, MagicOptionType.PROMPT_KEEP));
            case PAY_MANA:
                Integer source = firstIndexOf(decision, MagicOptionType.PROMPT_MANA_SOURCE);
                if (source != null) {
                    return Collections.singletonList(source);
                }
                Integer pool = firstIndexOf(decision, MagicOptionType.PROMPT_MANA_POOL);
                if (pool != null) {
                    return Collections.singletonList(pool);
                }
                return Collections.singletonList(
                        requireIndexOf(decision, MagicOptionType.PROMPT_CANCEL_PAYMENT));
            case DECLARE_ATTACKERS:
            case DECLARE_BLOCKERS:
                return Collections.emptyList();
            default:
                return firstMinCount(decision);
        }
    }

    private static List<Integer> firstMinCount(PendingDecision decision) {
        List<Integer> indices = new ArrayList<Integer>();
        for (int i = 0; i < decision.minCount(); i++) {
            indices.add(i);
        }
        return indices;
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
            if (value != null && value.equals(options.get(i).payload().get(key))) {
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
                    "event policy expected a " + type + " option in " + decision.selectType());
        }
        return index;
    }
}
