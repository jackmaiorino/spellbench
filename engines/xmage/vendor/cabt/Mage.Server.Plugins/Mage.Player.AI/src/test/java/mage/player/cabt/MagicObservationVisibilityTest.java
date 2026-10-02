package mage.player.cabt;

import mage.cards.Card;
import mage.cards.CardsImpl;
import mage.game.Game;
import mage.game.stack.SpellStack;
import mage.players.Player;
import org.junit.jupiter.api.Test;

import java.util.LinkedHashMap;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Task 6: hand visibility is controlled by selecting-player identity — a
 * player sees their own hand as object views, opponents stay count-only.
 */
class MagicObservationVisibilityTest {

    private final MagicObservationSerializer serializer = new MagicObservationSerializer();

    private final UUID aliceId = UUID.randomUUID();
    private final UUID bobId = UUID.randomUUID();
    private final UUID islandId = UUID.randomUUID();
    private final UUID boltId = UUID.randomUUID();

    private LinkedHashMap<UUID, Player> players;
    private Game game;

    private void setUpGame() {
        CardsImpl aliceHand = new CardsImpl();
        aliceHand.add(islandId);
        aliceHand.add(boltId);
        LinkedHashMap<UUID, Card> cards = new LinkedHashMap<UUID, Card>();
        cards.put(islandId, StubGames.card(islandId, "Island", aliceId));
        cards.put(boltId, StubGames.card(boltId, "Lightning Bolt", aliceId));

        players = new LinkedHashMap<UUID, Player>();
        players.put(aliceId, StubGames.player(aliceId, "Alice", 20, aliceHand, null));
        players.put(bobId, StubGames.player(bobId, "Bob", 18, 5));
        game = StubGames.game(players, aliceId, aliceId, null, new SpellStack(), cards);
    }

    @Test
    void ownHandVisibleWhenSelectingPlayer() {
        setUpGame();
        MagicObservation observation = serializer.serialize(
                game, players.get(aliceId), PendingDecision.priority(aliceId));

        MagicPlayerView aliceView = observation.getCurrent().getPlayers().get(0);
        assertThat(aliceView.getHand()).hasSize(2);
        assertThat(aliceView.getHand().get(0).getRef().getName()).isEqualTo("Island");
        assertThat(aliceView.getHand().get(1).getRef().getName()).isEqualTo("Lightning Bolt");
        assertThat(aliceView.getHandCount()).isEqualTo(2);

        // opponent: count only, empty hand list per the DTO contract
        MagicPlayerView bobView = observation.getCurrent().getPlayers().get(1);
        assertThat(bobView.getHandCount()).isEqualTo(5);
        assertThat(bobView.getHand()).isEmpty();
    }

    @Test
    void handVisibilityFollowsTheSelectingPlayer() {
        setUpGame();
        // same game, Bob selecting: now Alice's hand is the hidden one
        MagicObservation observation = serializer.serialize(
                game, players.get(bobId), PendingDecision.priority(bobId));

        MagicPlayerView aliceView = observation.getCurrent().getPlayers().get(0);
        assertThat(aliceView.getHand()).isEmpty();
        assertThat(aliceView.getHandCount()).isEqualTo(2);

        MagicPlayerView bobView = observation.getCurrent().getPlayers().get(1);
        assertThat(bobView.getHand()).hasSize(5);
    }

    @Test
    void revealedHandStaysEmptyUntilRevealTrackingExists() {
        setUpGame();
        MagicObservation observation = serializer.serialize(
                game, players.get(aliceId), PendingDecision.priority(aliceId));

        for (MagicPlayerView view : observation.getCurrent().getPlayers()) {
            assertThat(view.getRevealedHand()).isEmpty();
        }
    }
}
