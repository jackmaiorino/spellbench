package mage.player.cabt;

import mage.cards.Card;
import mage.cards.CardsImpl;
import mage.constants.Outcome;
import mage.game.Game;
import mage.game.permanent.Battlefield;
import mage.game.stack.SpellStack;
import mage.players.Player;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;

/**
 * Task 7: validated selections are committed to the engine through
 * Target.addTarget / TargetCard.add — the same APIs XMage's own players use.
 */
class CabtTargetSelectionApplierTest {

    private final CabtTargetPromptBuilder builder = new CabtTargetPromptBuilder();
    private final CabtTargetSelectionApplier applier = new CabtTargetSelectionApplier();

    private final UUID aliceId = UUID.randomUUID();
    private final UUID bobId = UUID.randomUUID();

    private LinkedHashMap<UUID, Player> players;

    private Game game(Battlefield battlefield, LinkedHashMap<UUID, Card> cards) {
        players = new LinkedHashMap<UUID, Player>();
        players.put(aliceId, StubGames.player(aliceId, "Alice", 20, 7));
        players.put(bobId, StubGames.player(bobId, "Bob", 18, 5));
        return StubGames.game(players, aliceId, aliceId, battlefield, new SpellStack(), cards);
    }

    @Test
    void targetSelectionAddsTarget() {
        UUID bearsId = UUID.randomUUID();
        Battlefield battlefield = new Battlefield();
        battlefield.addPermanent(StubGames.permanent(bearsId, "Grizzly Bears", bobId, bobId, false, 2, 2));
        Game game = game(battlefield, new LinkedHashMap<UUID, Card>());
        StubTarget target = new StubTarget(1, 1, Collections.singletonList(bearsId));
        PendingDecision decision = builder.buildTargetPrompt(
                players.get(aliceId), game, Outcome.Damage, target, StubGames.ability());

        boolean result = applier.applyToTarget(
                target, StubGames.ability(), game, Selection.of(0), decision);

        assertThat(target.getTargets()).containsExactly(bearsId);
        assertThat(result).isTrue();
    }

    @Test
    void targetPromptSupportsOptionalEmptySelection() {
        UUID bearsId = UUID.randomUUID();
        Battlefield battlefield = new Battlefield();
        battlefield.addPermanent(StubGames.permanent(bearsId, "Grizzly Bears", bobId, bobId, false, 2, 2));
        Game game = game(battlefield, new LinkedHashMap<UUID, Card>());
        StubTarget target = new StubTarget(0, 1, Collections.singletonList(bearsId));
        PendingDecision decision = builder.buildTargetPrompt(
                players.get(aliceId), game, Outcome.Damage, target, StubGames.ability());
        Selection empty = new Selection(new ArrayList<Integer>());

        // min 0: an empty selection is a legal answer
        assertThatCode(() -> SelectionValidator.validate(decision, empty))
                .doesNotThrowAnyException();

        boolean result = applier.applyToTarget(
                target, StubGames.ability(), game, empty, decision);

        assertThat(result).isFalse();
        assertThat(target.getTargets()).isEmpty();
    }

    @Test
    void cardSelectionUsesTargetCardAdd() {
        UUID cardId = UUID.randomUUID();
        LinkedHashMap<UUID, Card> cards = new LinkedHashMap<UUID, Card>();
        cards.put(cardId, StubGames.card(cardId, "Doom Blade", aliceId));
        Game game = game(null, cards);
        StubTargetCard target = new StubTargetCard(1, 1, Arrays.asList(cardId));
        CardsImpl fromCards = new CardsImpl();
        fromCards.add(cardId);
        PendingDecision decision = builder.buildTargetCardPrompt(
                players.get(aliceId), game, Outcome.ReturnToHand, fromCards, target, StubGames.ability());

        boolean result = applier.applyToTargetCard(target, game, Selection.of(0), decision);

        assertThat(target.getTargets()).containsExactly(cardId);
        assertThat(result).isTrue();
    }
}
