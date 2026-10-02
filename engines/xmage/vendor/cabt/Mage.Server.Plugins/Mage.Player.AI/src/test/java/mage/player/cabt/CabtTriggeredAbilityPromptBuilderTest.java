package mage.player.cabt;

import mage.abilities.TriggeredAbility;
import mage.cards.Card;
import mage.game.Game;
import mage.game.stack.SpellStack;
import mage.players.Player;
import org.junit.jupiter.api.Test;

import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Task 11: TRIGGER_ORDER prompts carry one option per waiting triggered
 * ability, in the input list's order, with rule text and source context.
 */
class CabtTriggeredAbilityPromptBuilderTest {

    private final CabtTriggeredAbilityPromptBuilder builder = new CabtTriggeredAbilityPromptBuilder();
    private final CabtTriggeredAbilitySelectionApplier applier = new CabtTriggeredAbilitySelectionApplier();

    private final UUID aliceId = UUID.randomUUID();
    private final UUID bearsId = UUID.randomUUID();
    private final UUID wolfId = UUID.randomUUID();

    private Player alice;
    private Game game;
    private List<TriggeredAbility> triggers;

    private void setUpTwoTriggers() {
        alice = StubGames.player(aliceId, "Alice", 20, 7);
        LinkedHashMap<UUID, Player> players = new LinkedHashMap<UUID, Player>();
        players.put(aliceId, alice);
        LinkedHashMap<UUID, Card> cards = new LinkedHashMap<UUID, Card>();
        cards.put(bearsId, StubGames.card(bearsId, "Grizzly Bears", aliceId));
        cards.put(wolfId, StubGames.card(wolfId, "Young Wolf", aliceId));
        game = StubGames.game(players, aliceId, aliceId, null, new SpellStack(), cards);
        triggers = Arrays.asList(
                StubGames.triggeredAbility(UUID.randomUUID(), UUID.randomUUID(), bearsId,
                        "Whenever Grizzly Bears attacks, draw a card."),
                StubGames.triggeredAbility(UUID.randomUUID(), UUID.randomUUID(), wolfId,
                        "When Young Wolf dies, return it with a +1/+1 counter."));
    }

    @Test
    void triggerPromptIncludesEachAbility() {
        setUpTwoTriggers();

        PendingDecision decision = builder.build(alice, game, triggers);

        assertThat(decision.selectType()).isEqualTo(MagicSelectType.TRIGGER_ORDER);
        assertThat(decision.minCount()).isEqualTo(1);
        assertThat(decision.maxCount()).isEqualTo(1);
        assertThat(decision.options()).hasSize(2);
        for (int i = 0; i < 2; i++) {
            MagicOption option = decision.options().get(i);
            assertThat(option.type()).isEqualTo(MagicOptionType.PROMPT_TRIGGERED_ABILITY);
            assertThat(option.label()).startsWith("Put trigger on stack: ");
            assertThat(option.payload().get("abilityId"))
                    .isEqualTo(triggers.get(i).getId().toString());
            assertThat(option.payload().get("sourceId"))
                    .isEqualTo(triggers.get(i).getSourceId().toString());
            assertThat(option.payload().get("rule")).isNotNull();
        }
        assertThat(decision.options().get(0).payload().get("sourceName")).isEqualTo("Grizzly Bears");
        assertThat(decision.options().get(1).payload().get("rule").toString()).contains("Young Wolf");
    }

    @Test
    void triggerSelectionReturnsSelectedAbility() {
        setUpTwoTriggers();
        PendingDecision decision = builder.build(alice, game, triggers);

        TriggeredAbility selected = applier.apply(triggers, Selection.of(1), decision);

        assertThat(selected).isSameAs(triggers.get(1));
    }
}
