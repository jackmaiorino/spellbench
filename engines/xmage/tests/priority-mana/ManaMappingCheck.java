package spellbench.kit.xmage;

import mage.abilities.AbilitiesImpl;
import mage.abilities.Ability;
import mage.abilities.ActivatedAbility;
import mage.cards.Card;
import mage.constants.AbilityType;
import mage.constants.Zone;
import mage.constants.RangeOfInfluence;
import mage.game.Game;
import mage.players.Player;
import spellbench.kit.core.Json;
import spellbench.kit.core.ObsIndex;

import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Proxy;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/** Isolated semantic/lookup regression checks. No game, card database or model is started. */
public final class ManaMappingCheck {
    private static final class LookupPlayer extends mage.player.ai.ComputerPlayer {
        private final Game expectedGame;
        private final List<ActivatedAbility> collapsed, complete;
        final int[] calls = {0, 0};

        LookupPlayer(Game game, List<ActivatedAbility> collapsed, List<ActivatedAbility> complete) {
            super("mana-lookup", RangeOfInfluence.ALL);
            this.expectedGame = game; this.collapsed = collapsed; this.complete = complete;
        }

        @Override
        public List<ActivatedAbility> getPlayable(Game game, boolean hidden) {
            require(game == expectedGame && hidden, "wrong playable world");
            calls[0]++; return collapsed;
        }

        @Override
        public List<ActivatedAbility> getPlayable(Game game, boolean hidden, Zone zone, boolean hideDuplicates) {
            require(game == expectedGame && hidden && zone == Zone.ALL && !hideDuplicates,
                    "offered mana lookup hid duplicate sources");
            calls[1]++; return complete;
        }
    }
    private static void require(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }

    @SuppressWarnings("unchecked")
    private static <T> T proxy(Class<T> type, InvocationHandler handler) {
        return (T) Proxy.newProxyInstance(type.getClassLoader(), new Class<?>[]{type}, (object, method, args) -> {
            if ("toString".equals(method.getName())) return "test " + type.getSimpleName();
            if ("hashCode".equals(method.getName())) return System.identityHashCode(object);
            if ("equals".equals(method.getName())) return object == args[0];
            return handler.invoke(object, method, args);
        });
    }

    private static ActivatedAbility ability(UUID source, UUID identity, AbilityType type) {
        return proxy(ActivatedAbility.class, (object, method, args) -> {
            switch (method.getName()) {
                case "getSourceId": return source;
                case "getId": case "getOriginalId": return identity;
                case "getAbilityType": return type;
                case "getRule": return "{T}: Add {G}.";
                default: throw new AssertionError("unexpected ability access: " + method.getName());
            }
        });
    }

    private static Card card(List<Ability> abilities) {
        AbilitiesImpl<Ability> collection = new AbilitiesImpl<>();
        collection.addAll(abilities);
        return proxy(Card.class, (object, method, args) -> {
            if ("getAbilities".equals(method.getName())) return collection;
            if ("getSecondCardFace".equals(method.getName())) return null;
            throw new AssertionError("unexpected card access: " + method.getName());
        });
    }

    public static void main(String[] args) {
        UUID first = new UUID(0, 1), second = new UUID(0, 2), nonmanaSource = new UUID(0, 3);
        ActivatedAbility a = ability(first, new UUID(0, 11), AbilityType.ACTIVATED_MANA);
        ActivatedAbility b = ability(second, new UUID(0, 12), AbilityType.ACTIVATED_MANA);
        ActivatedAbility c = ability(nonmanaSource, new UUID(0, 13), AbilityType.ACTIVATED_NONMANA);
        Map<UUID, Card> cards = new LinkedHashMap<>();
        cards.put(first, card(Arrays.asList(a))); cards.put(second, card(Arrays.asList(b)));
        cards.put(nonmanaSource, card(Arrays.asList(c)));
        Game game = proxy(Game.class, (object, method, values) -> {
            if ("getPermanent".equals(method.getName())) return null;
            if ("getCard".equals(method.getName())) return cards.get(values[0]);
            throw new AssertionError("unexpected game access: " + method.getName());
        });
        LookupPlayer player = new LookupPlayer(game, Arrays.asList(a, c), Arrays.asList(a, b, c));
        int[] calls = player.calls;
        World world = new World(game, "p0", 0, null);
        world.bind("first", first); world.bind("second", second); world.bind("nonmana", nonmanaSource);
        List<Object> battlefield = Arrays.asList(
                Json.map("object_id", "first", "card_name", "Forest", "owner_seat", "p0", "controller_seat", "p0", "zone", "battlefield"),
                Json.map("object_id", "second", "card_name", "Forest", "owner_seat", "p0", "controller_seat", "p0", "zone", "battlefield"),
                Json.map("object_id", "nonmana", "card_name", "other", "owner_seat", "p0", "controller_seat", "p0", "zone", "battlefield"));
        ObsIndex index = new ObsIndex(Json.map("players", Arrays.asList(Json.map("hand", Collections.emptyList(),
                "battlefield", battlefield, "graveyard", Collections.emptyList(), "exile", Collections.emptyList(),
                "command", Collections.emptyList())), "stack", Collections.emptyList(), "known", Collections.emptyList()));
        Map<String, Object> desired = Mapping.priorityManaSemantic(world, game, b, index);
        require(Mapping.findPlayable(world, player, desired, index) == b, "second equal-text producer was lost");
        require(calls[0] == 0 && calls[1] == 1, "mana used the collapsed lookup");
        require(Mapping.prioritySemantic(world, game, b, index) == null, "legacy search mapper behavior changed");
        Map<String, Object> ordinary = Mapping.prioritySemantic(world, game, c, index);
        require(Mapping.findPlayable(world, player, ordinary, index) == c && calls[0] == 1,
                "ordinary lookup behavior changed");
        Map<String, Object> changed = new LinkedHashMap<>(desired); changed.put("ability_index", 1L);
        require(Mapping.findPlayable(world, player, changed, index) == null, "wrong Oracle index matched");
        changed = new LinkedHashMap<>(desired); changed.put("mana_choice", "G");
        require(Mapping.findPlayable(world, player, changed, index) == null, "unoffered color payload matched");
        changed = new LinkedHashMap<>(desired); changed.put("source", index.ref("first"));
        require(Mapping.findPlayable(world, player, changed, index) == a, "source binding changed");
        world.uuidToId.remove(second);
        require(Mapping.priorityManaSemantic(world, game, b, index) == null, "unobserved source mapped");
        System.out.println("priority-mana semantic lookup: PASS");
    }
}
