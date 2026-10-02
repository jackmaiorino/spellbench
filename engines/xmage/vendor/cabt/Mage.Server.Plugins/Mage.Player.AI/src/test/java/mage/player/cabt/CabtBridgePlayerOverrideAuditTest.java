package mage.player.cabt;

import mage.MageObject;
import mage.abilities.Ability;
import mage.abilities.Modes;
import mage.abilities.TriggeredAbility;
import mage.abilities.costs.mana.ManaCost;
import mage.cards.Card;
import mage.cards.Cards;
import mage.choices.Choice;
import mage.constants.MultiAmountType;
import mage.constants.Outcome;
import mage.constants.RangeOfInfluence;
import mage.game.Game;
import mage.players.Player;
import mage.target.Target;
import mage.target.TargetAmount;
import mage.target.TargetCard;
import org.junit.jupiter.api.Test;

import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.fail;

/**
 * Concrete override audit over the Player-callback decision surface: the
 * heuristic-leakage gate. For every PLAYER_INTERFACE entry in
 * {@link CabtDecisionSurfaceAudit}:
 * <ul>
 * <li>the audited signature must exist on mage.players.Player (the audit
 * cannot drift from the real interface),</li>
 * <li>SURFACED and FAIL_CLOSED callbacks must be overridden by
 * CabtBridgePlayer itself — inheriting them from ComputerPlayer would let
 * the built-in AI silently decide,</li>
 * <li>FAIL_CLOSED callbacks must actually throw
 * {@link CabtUnhandledDecisionException} when invoked,</li>
 * <li>DELEGATED and REFERENCE_ONLY entries may stay inherited (commit APIs
 * and queries — the decision happens in a surfaced prompt).</li>
 * </ul>
 */
class CabtBridgePlayerOverrideAuditTest {

    /**
     * Audited callbacks that CabtBridgePlayer deliberately does not override:
     * Player.getMultiAmount's implementation delegates to
     * getMultiAmountWithIndividualConstraints, which the bridge overrides —
     * the inherited method routes into the bridge's own prompt.
     */
    private static final Set<String> COVERED_BY_OVERRIDDEN_PRIMITIVE = new HashSet<>(
            Collections.singletonList(
                    "getMultiAmount(Outcome, List<String>, int, int, int, MultiAmountType, Game)"));

    private static final Map<String, Class<?>> TYPE_TOKENS = buildTypeTokens();

    private static Map<String, Class<?>> buildTypeTokens() {
        Map<String, Class<?>> tokens = new HashMap<String, Class<?>>();
        tokens.put("int", int.class);
        tokens.put("boolean", boolean.class);
        tokens.put("String", String.class);
        tokens.put("UUID", UUID.class);
        tokens.put("List", List.class);
        tokens.put("Map", Map.class);
        tokens.put("Game", Game.class);
        tokens.put("Outcome", Outcome.class);
        tokens.put("Target", Target.class);
        tokens.put("TargetAmount", TargetAmount.class);
        tokens.put("TargetCard", TargetCard.class);
        tokens.put("Cards", Cards.class);
        tokens.put("Card", Card.class);
        tokens.put("Ability", Ability.class);
        tokens.put("Choice", Choice.class);
        tokens.put("Modes", Modes.class);
        tokens.put("ManaCost", ManaCost.class);
        tokens.put("MultiAmountType", MultiAmountType.class);
        tokens.put("TriggeredAbility", TriggeredAbility.class);
        tokens.put("MageObject", MageObject.class);
        return tokens;
    }

    @Test
    void auditedPlayerCallbacksMatchTheRealPlayerInterface() {
        for (CabtDecisionSurface entry : CabtPromptAudit.playerCallbackEntries()) {
            MethodSignature signature = MethodSignature.parse(entry.getName());
            assertThat(findMethod(Player.class, signature))
                    .as("audited callback %s exists on mage.players.Player", entry.getName())
                    .isNotNull();
        }
    }

    @Test
    void surfacedAndFailClosedCallbacksAreOverriddenByTheBridge() {
        int checked = 0;
        for (CabtDecisionSurface entry : CabtPromptAudit.playerCallbackEntries()) {
            if (entry.getStatus() != CabtDecisionSurfaceStatus.SURFACED
                    && entry.getStatus() != CabtDecisionSurfaceStatus.FAIL_CLOSED) {
                continue;
            }
            if (COVERED_BY_OVERRIDDEN_PRIMITIVE.contains(entry.getName())) {
                continue;
            }
            MethodSignature signature = MethodSignature.parse(entry.getName());
            assertThat(declaresMethod(CabtBridgePlayer.class, signature))
                    .as("%s callback %s must be overridden by CabtBridgePlayer, "
                                    + "not inherited from ComputerPlayer",
                            entry.getStatus(), entry.getName())
                    .isTrue();
            checked++;
        }
        assertThat(checked).isGreaterThan(15);
    }

    @Test
    void failClosedCallbacksThrowInsteadOfLettingComputerPlayerDecide() {
        CabtBridgePlayer player = new CabtBridgePlayer("CABT", RangeOfInfluence.ALL,
                new ScriptedBridgeController(Collections.<Selection>emptyList()));

        int checked = 0;
        for (CabtDecisionSurface entry : CabtPromptAudit.playerCallbackEntries()) {
            if (entry.getStatus() != CabtDecisionSurfaceStatus.FAIL_CLOSED) {
                continue;
            }
            MethodSignature signature = MethodSignature.parse(entry.getName());
            Method method = findMethod(CabtBridgePlayer.class, signature);
            Object[] args = new Object[signature.parameterTypes.length];
            for (int i = 0; i < args.length; i++) {
                Class<?> type = signature.parameterTypes[i];
                args[i] = type == int.class ? Integer.valueOf(0)
                        : type == boolean.class ? Boolean.FALSE
                        : null;
            }
            try {
                method.invoke(player, args);
                fail("FAIL_CLOSED callback %s did not throw", entry.getName());
            } catch (InvocationTargetException e) {
                assertThat(e.getCause())
                        .as("FAIL_CLOSED callback %s throws CabtUnhandledDecisionException "
                                + "before touching its arguments", entry.getName())
                        .isInstanceOf(CabtUnhandledDecisionException.class);
            } catch (IllegalAccessException e) {
                throw new AssertionError(e);
            }
            checked++;
        }
        assertThat(checked).isGreaterThan(0);
    }

    private static Method findMethod(Class<?> owner, MethodSignature signature) {
        try {
            return owner.getMethod(signature.name, signature.parameterTypes);
        } catch (NoSuchMethodException e) {
            return null;
        }
    }

    private static boolean declaresMethod(Class<?> owner, MethodSignature signature) {
        try {
            owner.getDeclaredMethod(signature.name, signature.parameterTypes);
            return true;
        } catch (NoSuchMethodException e) {
            return false;
        }
    }

    /**
     * Parses an audit surface name like
     * "choose(Outcome, Cards, TargetCard, Ability, Game)" into a method name
     * and erased parameter classes ("List<? extends Card>" erases to List).
     */
    private static final class MethodSignature {

        private final String name;
        private final Class<?>[] parameterTypes;

        private MethodSignature(String name, Class<?>[] parameterTypes) {
            this.name = name;
            this.parameterTypes = parameterTypes;
        }

        static MethodSignature parse(String surfaceName) {
            int open = surfaceName.indexOf('(');
            if (open < 0 || !surfaceName.endsWith(")")) {
                throw new IllegalArgumentException("not a method signature: " + surfaceName);
            }
            String name = surfaceName.substring(0, open);
            String paramList = surfaceName.substring(open + 1, surfaceName.length() - 1).trim();
            if (paramList.isEmpty()) {
                return new MethodSignature(name, new Class<?>[0]);
            }
            List<String> tokens = splitTopLevel(paramList);
            Class<?>[] types = new Class<?>[tokens.size()];
            for (int i = 0; i < tokens.size(); i++) {
                types[i] = resolve(tokens.get(i));
            }
            return new MethodSignature(name, types);
        }

        private static List<String> splitTopLevel(String paramList) {
            List<String> tokens = new ArrayList<String>();
            int depth = 0;
            StringBuilder current = new StringBuilder();
            for (char c : paramList.toCharArray()) {
                if (c == '<') {
                    depth++;
                } else if (c == '>') {
                    depth--;
                }
                if (c == ',' && depth == 0) {
                    tokens.add(current.toString().trim());
                    current.setLength(0);
                } else {
                    current.append(c);
                }
            }
            tokens.add(current.toString().trim());
            return tokens;
        }

        private static Class<?> resolve(String token) {
            String erased = token.contains("<") ? token.substring(0, token.indexOf('<')) : token;
            Class<?> type = TYPE_TOKENS.get(erased.trim());
            if (type == null) {
                throw new IllegalArgumentException(
                        "audit signature uses unknown type token '" + token
                                + "' — add it to TYPE_TOKENS: " + Arrays.toString(TYPE_TOKENS.keySet().toArray()));
            }
            return type;
        }
    }
}
