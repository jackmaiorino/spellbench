package mage.player.cabt;

import mage.cards.Card;
import mage.cards.decks.Deck;
import mage.constants.RangeOfInfluence;
import org.junit.jupiter.api.Test;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import static org.assertj.core.api.Assertions.assertThat;

class CabtInitialLibraryOrderTest {
    @Test
    void nativeSetupRetainsDeclaredCardOrderBeforeTheEngineShuffle() {
        for (int repetition = 0; repetition < 8; repetition++) {
            CabtLiveDuel game = new CabtLiveDuel();
            CabtBridgePlayer player = new CabtBridgePlayer("P0", RangeOfInfluence.ALL,
                    (ignoredGame, ignoredPlayer, decision) -> {
                        throw new AssertionError("Setup must not request a move");
                    });
            Deck deck = new Deck();
            CabtDeckFactory factory = new CabtDeckFactory();
            List<UUID> expected = new ArrayList<UUID>();
            for (String name : new String[]{"Forest", "Grizzly Bears", "Forest", "Grizzly Bears"}) {
                Card card = factory.createCard(name);
                card.setOwnerId(player.getId());
                deck.getCards().add(card);
                expected.add(card.getId());
            }
            game.loadCards(deck.getCards(), player.getId());
            game.addPlayer(player, deck);
            assertThat(player.getLibrary().getCardList()).containsExactlyElementsOf(expected);
            assertThat(player.getLibrary().size()).isEqualTo(4);
        }
    }
}
