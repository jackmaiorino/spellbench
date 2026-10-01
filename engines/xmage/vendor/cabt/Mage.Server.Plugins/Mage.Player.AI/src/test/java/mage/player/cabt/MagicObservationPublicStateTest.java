package mage.player.cabt;

import mage.cards.Card;
import mage.game.Game;
import mage.game.Graveyard;
import mage.game.permanent.Battlefield;
import mage.game.stack.SpellStack;
import mage.players.Player;
import org.junit.jupiter.api.Test;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Task 6: shared public zones — battlefield, stack, graveyard — serialize as
 * object views with stable engine ids. Battlefield and SpellStack are the
 * real engine classes; their contents are stubs because casting a real spell
 * needs the full engine loop, which this module's tests do not run.
 */
class MagicObservationPublicStateTest {

    private final MagicObservationSerializer serializer = new MagicObservationSerializer();

    private final UUID aliceId = UUID.randomUUID();
    private final UUID bobId = UUID.randomUUID();

    @Test
    void serializesBattlefieldPermanent() {
        UUID islandId = UUID.randomUUID();
        Battlefield battlefield = new Battlefield();
        battlefield.addPermanent(StubGames.permanent(
                islandId, "Island", aliceId, aliceId, false, 0, 0));

        Game game = game(battlefield, new SpellStack(), new LinkedHashMap<UUID, Card>());
        MagicObservation observation = serializer.serialize(
                game, alice(), PendingDecision.priority(aliceId));

        MagicCurrent current = observation.getCurrent();
        assertThat(current.getBattlefield()).hasSize(1);
        assertThat(current.getBattlefieldSize()).isEqualTo(1);
        MagicPermanentView island = current.getBattlefield().get(0);
        assertThat(island.getRef().getObjectId()).isEqualTo(islandId.toString());
        assertThat(island.getRef().getName()).isEqualTo("Island");
        assertThat(island.getControllerId()).isEqualTo(aliceId.toString());
        assertThat(island.isTapped()).isFalse();
    }

    @Test
    void serializesStackObject() {
        UUID spellId = UUID.randomUUID();
        UUID sourceId = UUID.randomUUID();
        SpellStack stack = new SpellStack();
        stack.push(StubGames.stackObject(spellId, "Lightning Bolt", aliceId, sourceId));

        Game game = game(null, stack, new LinkedHashMap<UUID, Card>());
        MagicObservation observation = serializer.serialize(
                game, alice(), PendingDecision.priority(aliceId));

        MagicCurrent current = observation.getCurrent();
        assertThat(current.getStack().size()).isGreaterThanOrEqualTo(1);
        assertThat(current.getStackSize()).isEqualTo(current.getStack().size());
        MagicStackObjectView spell = current.getStack().get(0);
        assertThat(spell.getName()).isEqualTo("Lightning Bolt");
        assertThat(spell.getSourceId()).isEqualTo(sourceId.toString());
        assertThat(spell.getRef().getObjectId()).isEqualTo(spellId.toString());
    }

    @Test
    void graveyardIsPublic() {
        UUID deadCardId = UUID.randomUUID();
        Graveyard graveyard = new Graveyard();
        graveyard.add(deadCardId);
        LinkedHashMap<UUID, Card> cards = new LinkedHashMap<UUID, Card>();
        cards.put(deadCardId, StubGames.card(deadCardId, "Doom Blade", aliceId));

        LinkedHashMap<UUID, Player> players = new LinkedHashMap<UUID, Player>();
        players.put(aliceId, StubGames.player(aliceId, "Alice", 20, null, graveyard));
        players.put(bobId, StubGames.player(bobId, "Bob", 18, 5));
        Game game = StubGames.game(players, aliceId, aliceId, null, new SpellStack(), cards);

        MagicObservation observation = serializer.serialize(
                game, players.get(bobId), PendingDecision.priority(bobId));

        // the opponent's graveyard is fully visible: it is a public zone
        MagicPlayerView aliceView = observation.getCurrent().getPlayers().get(0);
        assertThat(aliceView.getGraveyard()).hasSize(1);
        assertThat(aliceView.getGraveyard().get(0).getRef().getName()).isEqualTo("Doom Blade");
        assertThat(aliceView.getGraveyard().get(0).getRef().getObjectId())
                .isEqualTo(deadCardId.toString());
        assertThat(aliceView.getGraveyardCount()).isEqualTo(1);
    }

    private Player alice() {
        return StubGames.player(aliceId, "Alice", 20, 7);
    }

    private Game game(Battlefield battlefield, SpellStack stack, Map<UUID, Card> cards) {
        LinkedHashMap<UUID, Player> players = new LinkedHashMap<UUID, Player>();
        players.put(aliceId, alice());
        players.put(bobId, StubGames.player(bobId, "Bob", 18, 5));
        return StubGames.game(players, aliceId, aliceId, battlefield, stack, cards);
    }
}
