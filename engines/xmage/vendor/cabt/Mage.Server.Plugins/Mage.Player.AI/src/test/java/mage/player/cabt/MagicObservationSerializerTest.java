package mage.player.cabt;

import mage.game.Game;
import mage.players.Player;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.lang.reflect.Modifier;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Task 2: the pass-only priority prompt produces a CABT-style observation —
 * logs + current (public counts only) + select (indexed options).
 */
class MagicObservationSerializerTest {

    private final MagicObservationSerializer serializer = new MagicObservationSerializer();

    private final UUID aliceId = UUID.randomUUID();
    private final UUID bobId = UUID.randomUUID();
    private final Player alice = StubGames.player(aliceId, "Alice", 20, 7);
    private final Player bob = StubGames.player(bobId, "Bob", 18, 5);

    private Game twoPlayerGame() {
        LinkedHashMap<UUID, Player> players = new LinkedHashMap<>();
        players.put(aliceId, alice);
        players.put(bobId, bob);
        return StubGames.game(players, aliceId, aliceId);
    }

    @Test
    void serializesPassOnlyPrioritySelect() {
        MagicObservation observation = serializer.serialize(
                twoPlayerGame(), alice, PendingDecision.priority(aliceId));

        MagicSelectView select = observation.getSelect();
        assertThat(select.getType()).isEqualTo("PRIORITY");
        assertThat(select.getPlayerIndex()).isEqualTo(0);
        assertThat(select.getPlayerId()).isEqualTo(aliceId.toString());
        assertThat(select.getMinCount()).isEqualTo(1);
        assertThat(select.getMaxCount()).isEqualTo(1);
        assertThat(select.getOption()).hasSize(1);
        MagicOptionView option = select.getOption().get(0);
        assertThat(option.getIndex()).isEqualTo(0);
        assertThat(option.getType()).isEqualTo("PASS_PRIORITY");
        assertThat(option.getLabel()).isEqualTo("Pass priority");
        assertThat(option.getPayload()).isEmpty();

        assertThat(observation.getLogs()).isEmpty();
    }

    @Test
    void selectUsesStablePlayerOrderForIndex() {
        MagicObservation observation = serializer.serialize(
                twoPlayerGame(), bob, PendingDecision.priority(bobId));

        assertThat(observation.getSelect().getPlayerIndex()).isEqualTo(1);
        assertThat(observation.getSelect().getPlayerId()).isEqualTo(bobId.toString());
    }

    @Test
    void serializesMinimalCurrentState() {
        MagicObservation observation = serializer.serialize(
                twoPlayerGame(), alice, PendingDecision.priority(aliceId));

        MagicCurrent current = observation.getCurrent();
        assertThat(current.getTurnNumber()).isEqualTo(3);
        assertThat(current.getActivePlayerId()).isEqualTo(aliceId.toString());
        assertThat(current.getPriorityPlayerId()).isEqualTo(aliceId.toString());
        assertThat(current.getPhase()).isEqualTo("PRECOMBAT_MAIN");
        assertThat(current.getStep()).isEqualTo("PRECOMBAT_MAIN");
        assertThat(current.getStackSize()).isEqualTo(0);
        assertThat(current.getBattlefieldSize()).isEqualTo(0);
        assertThat(current.isGameEnded()).isFalse();
        assertThat(current.getWinner()).isNull();

        assertThat(current.getPlayers()).hasSize(2);
        MagicPlayerView first = current.getPlayers().get(0);
        assertThat(first.getPlayerIndex()).isEqualTo(0);
        assertThat(first.getPlayerId()).isEqualTo(aliceId.toString());
        assertThat(first.getName()).isEqualTo("Alice");
        assertThat(first.getLife()).isEqualTo(20);
        assertThat(first.getHandCount()).isEqualTo(7);
        // library and graveyard are null in the stub: counts fall back to 0
        assertThat(first.getLibraryCount()).isEqualTo(0);
        assertThat(first.getGraveyardCount()).isEqualTo(0);
        assertThat(first.isPassed()).isFalse();
        assertThat(first.isInGame()).isTrue();

        MagicPlayerView second = current.getPlayers().get(1);
        assertThat(second.getPlayerIndex()).isEqualTo(1);
        assertThat(second.getName()).isEqualTo("Bob");
        assertThat(second.getLife()).isEqualTo(18);
        assertThat(second.getHandCount()).isEqualTo(5);
    }

    @Test
    void doesNotExposeHandContents() {
        // structural guarantee: scalar fields stay counts/flags only, and the
        // only collection-typed fields are the four known object-view lists —
        // whose visibility rules MagicObservationVisibilityTest enforces
        List<String> scalarFields = new ArrayList<>();
        List<String> listFields = new ArrayList<>();
        for (Field field : MagicPlayerView.class.getDeclaredFields()) {
            if (Modifier.isStatic(field.getModifiers())) {
                continue;
            }
            if (field.getType() == List.class) {
                listFields.add(field.getName());
                continue;
            }
            scalarFields.add(field.getName());
            assertThat(field.getType())
                    .as("field %s must be a primitive or String", field.getName())
                    .isIn(int.class, boolean.class, String.class);
        }
        assertThat(scalarFields).containsExactlyInAnyOrder(
                "playerIndex", "playerId", "name", "life",
                "handCount", "libraryCount", "graveyardCount", "passed", "inGame");
        assertThat(listFields).containsExactlyInAnyOrder(
                "graveyard", "exile", "revealedHand", "hand");
    }
}
