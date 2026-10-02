package mage.player.cabt;

import mage.abilities.ActivatedAbility;
import mage.abilities.PlayLandAbility;
import mage.abilities.SpellAbility;
import mage.abilities.costs.mana.ManaCost;
import mage.abilities.costs.mana.ManaCostsImpl;
import mage.abilities.mana.GreenManaAbility;
import mage.cards.Card;
import mage.constants.AbilityType;
import mage.constants.RangeOfInfluence;
import mage.game.Game;
import mage.players.Player;
import org.junit.jupiter.api.Test;

import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * The PRIORITY prompt is built from the engine's playable-ability list:
 * PASS_PRIORITY stays at index 0, and every ability maps to a typed option
 * (PLAY_LAND / CAST_SPELL / ACTIVATE_ABILITY / SPECIAL_ACTION) whose payload
 * carries the identifiers and whose playableIndex points back at the live
 * ability held by the prompt.
 */
class CabtPriorityPromptBuilderTest {

    private final CabtPriorityPromptBuilder builder = new CabtPriorityPromptBuilder();

    private CabtBridgePlayer player;
    private Game game;
    private UUID forestId;
    private UUID bearsId;

    private void setUpNamedCards() {
        player = new CabtBridgePlayer("CABT", RangeOfInfluence.ALL,
                new ScriptedBridgeController(Collections.<Selection>emptyList()));
        forestId = UUID.randomUUID();
        bearsId = UUID.randomUUID();
        LinkedHashMap<UUID, Card> cards = new LinkedHashMap<UUID, Card>();
        cards.put(forestId, StubGames.card(forestId, "Forest", player.getId()));
        cards.put(bearsId, StubGames.card(bearsId, "Grizzly Bears", player.getId()));
        LinkedHashMap<UUID, Player> players = new LinkedHashMap<UUID, Player>();
        players.put(player.getId(), player);
        game = StubGames.game(players, player.getId(), player.getId(),
                null, new mage.game.stack.SpellStack(), cards);
    }

    @Test
    void noPlayablesYieldsPassOnlyPrompt() {
        setUpNamedCards();

        CabtPriorityPrompt prompt = builder.build(
                player, game, Collections.<ActivatedAbility>emptyList());

        assertThat(prompt.getDecision().selectType()).isEqualTo(MagicSelectType.PRIORITY);
        assertThat(prompt.getDecision().options()).hasSize(1);
        assertThat(prompt.getDecision().options().get(0).type())
                .isEqualTo(MagicOptionType.PASS_PRIORITY);
        assertThat(prompt.playables()).isEmpty();
    }

    @Test
    void playableAbilitiesBecomeTypedOptionsBehindPass() {
        setUpNamedCards();
        PlayLandAbility land = new PlayLandAbility("Forest");
        land.setSourceId(forestId);
        SpellAbility cast = new SpellAbility(new ManaCostsImpl<ManaCost>("{1}{G}"), "Grizzly Bears");
        cast.setSourceId(bearsId);
        GreenManaAbility mana = new GreenManaAbility();
        mana.setSourceId(forestId);
        List<ActivatedAbility> playables = Arrays.<ActivatedAbility>asList(land, cast, mana);

        CabtPriorityPrompt prompt = builder.build(player, game, playables);

        List<MagicOption> options = prompt.getDecision().options();
        assertThat(options).hasSize(4);
        assertThat(options.get(0).type()).isEqualTo(MagicOptionType.PASS_PRIORITY);

        MagicOption landOption = options.get(1);
        assertThat(landOption.type()).isEqualTo(MagicOptionType.PLAY_LAND);
        assertThat(landOption.label()).isEqualTo("Play Forest");
        assertThat(landOption.payload().get("playableIndex")).isEqualTo(0);
        assertThat(landOption.payload().get("abilityType")).isEqualTo("PLAY_LAND");
        assertThat(landOption.payload().get("sourceId")).isEqualTo(forestId.toString());
        assertThat(landOption.payload().get("sourceName")).isEqualTo("Forest");

        MagicOption castOption = options.get(2);
        assertThat(castOption.type()).isEqualTo(MagicOptionType.CAST_SPELL);
        assertThat(castOption.label()).isEqualTo("Cast Grizzly Bears");
        assertThat(castOption.payload().get("playableIndex")).isEqualTo(1);
        assertThat(castOption.payload().get("manaCost")).isEqualTo("{1}{G}");

        MagicOption manaOption = options.get(3);
        assertThat(manaOption.type()).isEqualTo(MagicOptionType.ACTIVATE_ABILITY);
        assertThat(manaOption.payload().get("playableIndex")).isEqualTo(2);
        assertThat(manaOption.payload().get("abilityType")).isEqualTo("ACTIVATED_MANA");

        // the prompt keeps the live abilities for dispatch, aligned by playableIndex
        assertThat(prompt.playableAt(0)).isSameAs(land);
        assertThat(prompt.playableAt(1)).isSameAs(cast);
        assertThat(prompt.playableAt(2)).isSameAs(mana);
    }

    @Test
    void abilityTypeWithoutPriorityMappingFailsClosed() {
        setUpNamedCards();
        ActivatedAbility rogue = rogueAbility(AbilityType.TRIGGERED_NONMANA, "not a playable");

        assertThatThrownBy(() -> builder.build(
                player, game, Collections.singletonList(rogue)))
                .isInstanceOf(CabtUnhandledDecisionException.class)
                .hasMessageContaining("TRIGGERED_NONMANA");
    }

    private static ActivatedAbility rogueAbility(final AbilityType type, final String rule) {
        InvocationHandler handler = new InvocationHandler() {
            @Override
            public Object invoke(Object proxy, Method method, Object[] args) {
                String name = method.getName();
                if (name.equals("getAbilityType")) {
                    return type;
                }
                if (name.equals("getRule")) {
                    return rule;
                }
                if (name.equals("getId")) {
                    return UUID.randomUUID();
                }
                Class<?> returnType = method.getReturnType();
                if (returnType == boolean.class) {
                    return false;
                }
                if (returnType.isPrimitive() && returnType != void.class) {
                    return 0;
                }
                return null;
            }
        };
        return (ActivatedAbility) Proxy.newProxyInstance(
                ActivatedAbility.class.getClassLoader(),
                new Class<?>[]{ActivatedAbility.class}, handler);
    }
}
