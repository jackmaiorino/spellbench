package mage.player.cabt;

import mage.cards.Card;
import mage.constants.Zone;
import mage.game.Game;
import mage.game.permanent.Permanent;
import mage.game.stack.StackObject;
import mage.players.Player;
import org.junit.jupiter.api.Test;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Task 6: object views carry stable references (engine UUIDs) plus the
 * public state of the object, with null-safe fallbacks.
 */
class MagicObjectViewFactoryTest {

    private final UUID aliceId = UUID.randomUUID();

    private Game emptyGame() {
        return StubGames.game(new LinkedHashMap<UUID, Player>(), aliceId, aliceId);
    }

    @Test
    void permanentViewCarriesBoardState() {
        UUID bearsId = UUID.randomUUID();
        Permanent bears = StubGames.permanent(bearsId, "Grizzly Bears", aliceId, aliceId, true, 2, 2);

        MagicPermanentView view = MagicObjectViewFactory.permanentView(emptyGame(), bears);

        assertThat(view.getRef().getObjectId()).isEqualTo(bearsId.toString());
        assertThat(view.getRef().getName()).isEqualTo("Grizzly Bears");
        // no game state in the stub: zone falls back to the calling context
        assertThat(view.getRef().getZone()).isEqualTo("BATTLEFIELD");
        assertThat(view.getControllerId()).isEqualTo(aliceId.toString());
        assertThat(view.getOwnerId()).isEqualTo(aliceId.toString());
        assertThat(view.isTapped()).isTrue();
        assertThat(view.isFaceDown()).isFalse();
        assertThat(view.getPower()).isEqualTo(2);
        assertThat(view.getToughness()).isEqualTo(2);
        assertThat(view.getCounters()).isEmpty();
        assertThat(view.getCardTypes()).containsExactly("CREATURE");
    }

    @Test
    void stackObjectViewCarriesSourceAndName() {
        UUID spellId = UUID.randomUUID();
        UUID sourceId = UUID.randomUUID();
        StackObject bolt = StubGames.stackObject(spellId, "Lightning Bolt", aliceId, sourceId);

        MagicStackObjectView view = MagicObjectViewFactory.stackObjectView(emptyGame(), bolt);

        assertThat(view.getRef().getObjectId()).isEqualTo(spellId.toString());
        assertThat(view.getRef().getZone()).isEqualTo("STACK");
        assertThat(view.getRef().getSourceId()).isEqualTo(sourceId.toString());
        assertThat(view.getName()).isEqualTo("Lightning Bolt");
        assertThat(view.getSourceId()).isEqualTo(sourceId.toString());
        assertThat(view.getControllerId()).isEqualTo(aliceId.toString());
        // stub has no stack ability: target list stays empty, not null
        assertThat(view.getTargetIds()).isEmpty();
    }

    @Test
    void objectViewCarriesCardIdentity() {
        UUID cardId = UUID.randomUUID();
        Card card = StubGames.card(cardId, "Doom Blade", aliceId);

        MagicObjectView view = MagicObjectViewFactory.objectView(emptyGame(), card, Zone.GRAVEYARD);

        assertThat(view.getRef().getObjectId()).isEqualTo(cardId.toString());
        assertThat(view.getRef().getName()).isEqualTo("Doom Blade");
        assertThat(view.getRef().getZone()).isEqualTo("GRAVEYARD");
        assertThat(view.getRef().getOwnerId()).isEqualTo(aliceId.toString());
        assertThat(view.getCardTypes()).containsExactly("INSTANT");
    }

    @Test
    void zoneViewNamesItsZone() {
        MagicZoneView view = MagicObjectViewFactory.zoneView(
                Zone.EXILED, Collections.<MagicObjectView>emptyList());

        assertThat(view.getZone()).isEqualTo("EXILED");
        assertThat(view.getObjects()).isEmpty();
    }
}
