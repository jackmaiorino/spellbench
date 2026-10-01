package mage.player.cabt;

import mage.cards.Card;
import mage.cards.CardsImpl;
import mage.constants.Outcome;
import mage.game.Game;
import mage.game.permanent.Battlefield;
import mage.game.stack.SpellStack;
import mage.players.Player;
import org.junit.jupiter.api.Test;

import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Task 7: TARGET prompts are built from Target.possibleTargets and the
 * target's own min/max/selected state, with one option per possible target.
 */
class CabtTargetPromptBuilderTest {

    private final CabtTargetPromptBuilder builder = new CabtTargetPromptBuilder();

    private final UUID aliceId = UUID.randomUUID();
    private final UUID bobId = UUID.randomUUID();

    private LinkedHashMap<UUID, Player> players;

    private Game gameWithBattlefield(Battlefield battlefield, LinkedHashMap<UUID, Card> cards) {
        players = new LinkedHashMap<UUID, Player>();
        players.put(aliceId, StubGames.player(aliceId, "Alice", 20, 7));
        players.put(bobId, StubGames.player(bobId, "Bob", 18, 5));
        return StubGames.game(players, aliceId, aliceId, battlefield, new SpellStack(), cards);
    }

    @Test
    void targetPromptUsesPossibleTargets() {
        UUID bears1 = UUID.randomUUID();
        UUID bears2 = UUID.randomUUID();
        Battlefield battlefield = new Battlefield();
        battlefield.addPermanent(StubGames.permanent(bears1, "Grizzly Bears", aliceId, aliceId, false, 2, 2));
        battlefield.addPermanent(StubGames.permanent(bears2, "Runeclaw Bear", bobId, bobId, false, 2, 2));
        Game game = gameWithBattlefield(battlefield, new LinkedHashMap<UUID, Card>());
        StubTarget target = new StubTarget(1, 1, Arrays.asList(bears1, bears2));

        PendingDecision decision = builder.buildTargetPrompt(
                players.get(aliceId), game, Outcome.Damage, target, StubGames.ability());

        assertThat(decision.selectType()).isEqualTo(MagicSelectType.TARGET);
        assertThat(decision.minCount()).isEqualTo(1);
        assertThat(decision.maxCount()).isEqualTo(1);
        assertThat(decision.options()).hasSize(2);
        for (MagicOption option : decision.options()) {
            assertThat(option.type()).isEqualTo(MagicOptionType.PROMPT_OBJECT);
            assertThat(option.payload().get("targetId")).isNotNull();
            assertThat(option.label()).startsWith("Target ");
        }
        // deterministic option order: sorted by target UUID string
        String first = (String) decision.options().get(0).payload().get("targetId");
        String second = (String) decision.options().get(1).payload().get("targetId");
        assertThat(first).isLessThan(second);
    }

    @Test
    void remainingCountsSubtractAlreadyChosenTargets() {
        UUID a = UUID.randomUUID();
        UUID b = UUID.randomUUID();
        UUID c = UUID.randomUUID();
        Battlefield battlefield = new Battlefield();
        for (UUID id : Arrays.asList(a, b, c)) {
            battlefield.addPermanent(StubGames.permanent(id, "Bear", aliceId, aliceId, false, 2, 2));
        }
        Game game = gameWithBattlefield(battlefield, new LinkedHashMap<UUID, Card>());
        StubTarget target = new StubTarget(2, 3, Arrays.asList(a, b, c));
        target.add(a, game);

        PendingDecision decision = builder.buildTargetPrompt(
                players.get(aliceId), game, Outcome.Damage, target, StubGames.ability());

        assertThat(decision.minCount()).isEqualTo(1);
        assertThat(decision.maxCount()).isEqualTo(2);
        assertThat(decision.options()).hasSize(2);
        for (MagicOption option : decision.options()) {
            assertThat(option.payload().get("targetId")).isNotEqualTo(a.toString());
        }
    }

    @Test
    void playerTargetsBecomePlayerOptions() {
        Game game = gameWithBattlefield(null, new LinkedHashMap<UUID, Card>());
        StubTarget target = new StubTarget(1, 1, Collections.singletonList(bobId));

        PendingDecision decision = builder.buildTargetPrompt(
                players.get(aliceId), game, Outcome.Damage, target, StubGames.ability());

        assertThat(decision.options()).hasSize(1);
        assertThat(decision.options().get(0).type()).isEqualTo(MagicOptionType.PROMPT_PLAYER);
        assertThat(decision.options().get(0).label()).isEqualTo("Target Bob");
    }

    @Test
    void targetCardPromptFiltersByCardsAndUsesCardOptions() {
        UUID inSet = UUID.randomUUID();
        UUID notInSet = UUID.randomUUID();
        LinkedHashMap<UUID, Card> cards = new LinkedHashMap<UUID, Card>();
        cards.put(inSet, StubGames.card(inSet, "Doom Blade", aliceId));
        Game game = gameWithBattlefield(null, cards);
        StubTargetCard target = new StubTargetCard(1, 1, Arrays.asList(inSet, notInSet));
        CardsImpl fromCards = new CardsImpl();
        fromCards.add(inSet);

        PendingDecision decision = builder.buildTargetCardPrompt(
                players.get(aliceId), game, Outcome.ReturnToHand, fromCards, target, StubGames.ability());

        assertThat(decision.selectType()).isEqualTo(MagicSelectType.TARGET);
        assertThat(decision.options()).hasSize(1);
        MagicOption option = decision.options().get(0);
        assertThat(option.type()).isEqualTo(MagicOptionType.PROMPT_CARD);
        assertThat(option.payload().get("targetId")).isEqualTo(inSet.toString());
        assertThat(option.payload().get("targetName")).isEqualTo("Doom Blade");
    }
}
