package mage.player.cabt;

import mage.MageInt;
import mage.abilities.Abilities;
import mage.abilities.AbilitiesImpl;
import mage.abilities.Ability;
import mage.abilities.TriggeredAbility;
import mage.cards.Card;
import mage.cards.CardsImpl;
import mage.constants.CardType;
import mage.constants.MultiplayerAttackOption;
import mage.constants.PhaseStep;
import mage.constants.RangeOfInfluence;
import mage.constants.TurnPhase;
import mage.game.Game;
import mage.game.GameState;
import mage.game.Graveyard;
import mage.game.combat.Combat;
import mage.game.permanent.Battlefield;
import mage.game.permanent.Permanent;
import mage.game.stack.SpellStack;
import mage.game.stack.StackObject;
import mage.players.Player;
import mage.players.PlayerList;
import mage.util.SubTypes;

import java.util.LinkedHashSet;
import java.util.Set;

import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;

/**
 * Test fixtures: reflection-proxy stubs over the Game, Player, Permanent,
 * Card, StackObject, and Ability interfaces, answering just enough state for
 * observation serialization and target prompts. Battlefield, SpellStack, and
 * Graveyard are the real engine classes filled with proxy objects; no real
 * engine loop runs.
 */
final class StubGames {

    private StubGames() {
    }

    /**
     * A game at turn 3, precombat main, empty stack, no battlefield, not ended.
     * Player order and lookup come from the given map (insertion order).
     */
    static Game game(final LinkedHashMap<UUID, Player> players,
                     final UUID activePlayerId, final UUID priorityPlayerId) {
        return game(players, activePlayerId, priorityPlayerId,
                null, new SpellStack(), Collections.<UUID, Card>emptyMap());
    }

    /**
     * Same fixed turn position, with real Battlefield/SpellStack contents and
     * a card lookup map backing getCard/getObject. getObject also resolves
     * battlefield permanents, mirroring GameImpl.getObject.
     */
    static Game game(final LinkedHashMap<UUID, Player> players,
                     final UUID activePlayerId, final UUID priorityPlayerId,
                     final Battlefield battlefield, final SpellStack stack,
                     final Map<UUID, Card> cards) {
        // a real (empty) state: mode/zone lookups answer null values instead
        // of the proxy NPE-ing on getState()
        final GameState state = new GameState();
        // a real combat so declareAttacker/declareBlocker exercise the
        // engine's own combat bookkeeping
        final Combat combat = new Combat();
        InvocationHandler handler = new InvocationHandler() {
            @Override
            public Object invoke(Object proxy, Method method, Object[] args) {
                String name = method.getName();
                if (name.equals("getState")) {
                    return state;
                }
                if (name.equals("getContinuousEffects")) {
                    return state.getContinuousEffects();
                }
                if (name.equals("getCombat")) {
                    return combat;
                }
                if (name.equals("getRangeOfInfluence")) {
                    return RangeOfInfluence.ALL;
                }
                if (name.equals("getAttackOption")) {
                    return MultiplayerAttackOption.MULTIPLE;
                }
                if (name.equals("getOpponents")) {
                    Set<UUID> opponents = new LinkedHashSet<UUID>(players.keySet());
                    opponents.remove(args[0]);
                    return opponents;
                }
                if (name.equals("getPermanent")) {
                    return battlefield == null ? null : battlefield.getPermanent((UUID) args[0]);
                }
                if (name.equals("mulliganDownTo")) {
                    return 7;
                }
                if (name.equals("getPlayerList")) {
                    PlayerList list = new PlayerList();
                    for (UUID playerId : players.keySet()) {
                        // CircularList.add(E) inserts at the current position
                        // (reversing order); the indexed add appends
                        list.add(list.size(), playerId);
                    }
                    return list;
                }
                if (name.equals("getPlayer")) {
                    return players.get(args[0]);
                }
                if (name.equals("getTurnNum")) {
                    return 3;
                }
                if (name.equals("getActivePlayerId")) {
                    return activePlayerId;
                }
                if (name.equals("getPriorityPlayerId")) {
                    return priorityPlayerId;
                }
                if (name.equals("getTurnPhaseType")) {
                    return TurnPhase.PRECOMBAT_MAIN;
                }
                if (name.equals("getTurnStepType")) {
                    return PhaseStep.PRECOMBAT_MAIN;
                }
                if (name.equals("getBattlefield")) {
                    return battlefield;
                }
                if (name.equals("getStack")) {
                    return stack;
                }
                if (name.equals("getCard")) {
                    return cards.get(args[0]);
                }
                if (name.equals("getObject") && args != null && args.length == 1
                        && args[0] instanceof UUID) {
                    Card card = cards.get(args[0]);
                    if (card != null) {
                        return card;
                    }
                    return battlefield == null ? null : battlefield.getPermanent((UUID) args[0]);
                }
                return typeDefault(method);
            }
        };
        return (Game) Proxy.newProxyInstance(
                Game.class.getClassLoader(), new Class<?>[]{Game.class}, handler);
    }

    /**
     * A player stub exposing only what MagicPlayerView needs. The hand holds
     * {@code handCount} placeholder card ids; library and graveyard are null
     * to exercise the serializer's null-safety.
     */
    static Player player(final UUID id, final String name, final int life, final int handCount) {
        CardsImpl hand = new CardsImpl();
        for (int i = 0; i < handCount; i++) {
            hand.add(UUID.randomUUID());
        }
        return player(id, name, life, hand, null);
    }

    /**
     * Player stub with an explicit hand and graveyard (either may be null).
     */
    static Player player(final UUID id, final String name, final int life,
                         final CardsImpl hand, final Graveyard graveyard) {
        InvocationHandler handler = new InvocationHandler() {
            @Override
            public Object invoke(Object proxy, Method method, Object[] args) {
                String methodName = method.getName();
                if (methodName.equals("getId")) {
                    return id;
                }
                if (methodName.equals("getName")) {
                    return name;
                }
                if (methodName.equals("getLife")) {
                    return life;
                }
                if (methodName.equals("getHand")) {
                    return hand;
                }
                if (methodName.equals("getGraveyard")) {
                    return graveyard;
                }
                if (methodName.equals("isInGame")) {
                    return true;
                }
                if (methodName.equals("getMaxAttackedBy")) {
                    return Integer.MAX_VALUE;
                }
                if (methodName.equals("hasOpponent")) {
                    return true;
                }
                return typeDefault(method);
            }
        };
        return (Player) Proxy.newProxyInstance(
                Player.class.getClassLoader(), new Class<?>[]{Player.class}, handler);
    }

    /**
     * An untapped, phased-in creature permanent with the given stats.
     */
    static Permanent permanent(final UUID id, final String name,
                               final UUID controllerId, final UUID ownerId,
                               final boolean tapped, final int power, final int toughness) {
        return permanent(id, name, controllerId, ownerId, tapped, power, toughness,
                new AbilitiesImpl<Ability>());
    }

    /**
     * A creature permanent carrying real abilities (e.g. a mana ability).
     * Answers yes to combat/activation legality checks (canAttack, canBlock,
     * canTap, canUseActivatedAbilities) so real engine paths can run on it.
     */
    static Permanent permanent(final UUID id, final String name,
                               final UUID controllerId, final UUID ownerId,
                               final boolean tapped, final int power, final int toughness,
                               final Abilities<Ability> abilities) {
        InvocationHandler handler = new InvocationHandler() {
            @Override
            public Object invoke(Object proxy, Method method, Object[] args) {
                String methodName = method.getName();
                if (methodName.equals("getId")) {
                    return id;
                }
                if (methodName.equals("getName")) {
                    return name;
                }
                if (methodName.equals("getControllerId")) {
                    return controllerId;
                }
                if (methodName.equals("getOwnerId")) {
                    return ownerId;
                }
                if (methodName.equals("isTapped")) {
                    return tapped;
                }
                if (methodName.equals("isPhasedIn")) {
                    return true;
                }
                if (methodName.equals("getAbilities")) {
                    return abilities;
                }
                if (methodName.equals("canAttack")
                        || methodName.equals("canBlock")
                        || methodName.equals("canTap")
                        || methodName.equals("tap")
                        || methodName.equals("canUseActivatedAbilities")
                        || methodName.equals("isCreature")) {
                    return true;
                }
                if (methodName.equals("isControlledBy")) {
                    return controllerId != null && controllerId.equals(args[0]);
                }
                if (methodName.equals("getBandedCards")) {
                    // combat's banding bookkeeping iterates this
                    return Collections.emptyList();
                }
                if (methodName.equals("getPower")) {
                    return new MageInt(power);
                }
                if (methodName.equals("getToughness")) {
                    return new MageInt(toughness);
                }
                if (methodName.equals("getCardType")) {
                    return Arrays.asList(CardType.CREATURE);
                }
                if (methodName.equals("getSubtype")) {
                    return new SubTypes();
                }
                return typeDefault(method);
            }
        };
        return (Permanent) Proxy.newProxyInstance(
                Permanent.class.getClassLoader(), new Class<?>[]{Permanent.class}, handler);
    }

    /**
     * A named card owned by the given player.
     */
    static Card card(final UUID id, final String name, final UUID ownerId) {
        InvocationHandler handler = new InvocationHandler() {
            @Override
            public Object invoke(Object proxy, Method method, Object[] args) {
                String methodName = method.getName();
                if (methodName.equals("getId")) {
                    return id;
                }
                if (methodName.equals("getName")) {
                    return name;
                }
                if (methodName.equals("getOwnerId")) {
                    return ownerId;
                }
                if (methodName.equals("getCardType")) {
                    return Arrays.asList(CardType.INSTANT);
                }
                if (methodName.equals("getSubtype")) {
                    return new SubTypes();
                }
                return typeDefault(method);
            }
        };
        return (Card) Proxy.newProxyInstance(
                Card.class.getClassLoader(), new Class<?>[]{Card.class}, handler);
    }

    /**
     * A stack object (spell/ability on the stack) without a stack ability.
     */
    static StackObject stackObject(final UUID id, final String name,
                                   final UUID controllerId, final UUID sourceId) {
        InvocationHandler handler = new InvocationHandler() {
            @Override
            public Object invoke(Object proxy, Method method, Object[] args) {
                String methodName = method.getName();
                if (methodName.equals("getId")) {
                    return id;
                }
                if (methodName.equals("getName")) {
                    return name;
                }
                if (methodName.equals("getControllerId")) {
                    return controllerId;
                }
                if (methodName.equals("getSourceId")) {
                    return sourceId;
                }
                return typeDefault(method);
            }
        };
        return (StackObject) Proxy.newProxyInstance(
                StackObject.class.getClassLoader(), new Class<?>[]{StackObject.class}, handler);
    }

    /**
     * A waiting triggered ability with fixed ids and rule text. getRule
     * answers the same rule for every overload.
     */
    static TriggeredAbility triggeredAbility(final UUID id, final UUID originalId,
                                             final UUID sourceId, final String rule) {
        InvocationHandler handler = new InvocationHandler() {
            @Override
            public Object invoke(Object proxy, Method method, Object[] args) {
                String methodName = method.getName();
                if (methodName.equals("getId")) {
                    return id;
                }
                if (methodName.equals("getOriginalId")) {
                    return originalId;
                }
                if (methodName.equals("getSourceId")) {
                    return sourceId;
                }
                if (methodName.equals("getRule")) {
                    return rule;
                }
                return typeDefault(method);
            }
        };
        return (TriggeredAbility) Proxy.newProxyInstance(
                TriggeredAbility.class.getClassLoader(),
                new Class<?>[]{TriggeredAbility.class}, handler);
    }

    /**
     * A minimal source ability for target prompts; every call answers a
     * type-correct default.
     */
    static Ability ability() {
        InvocationHandler handler = new InvocationHandler() {
            @Override
            public Object invoke(Object proxy, Method method, Object[] args) {
                return typeDefault(method);
            }
        };
        return (Ability) Proxy.newProxyInstance(
                Ability.class.getClassLoader(), new Class<?>[]{Ability.class}, handler);
    }

    private static Object typeDefault(Method method) {
        Class<?> returnType = method.getReturnType();
        if (returnType == boolean.class) {
            return false;
        }
        if (returnType.isPrimitive() && returnType != void.class) {
            return 0;
        }
        return null;
    }
}
