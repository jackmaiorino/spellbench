package mage.player.cabt;

import mage.constants.RangeOfInfluence;
import mage.game.Game;
import mage.players.Player;
import org.junit.jupiter.api.Test;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Task 2: RecordingBridgeController captures an observation of every prompt
 * before delegating the selection, leaving Task 1 priority behavior intact.
 */
class RecordingBridgeControllerTest {

    @Test
    void recordingControllerCapturesObservationBeforeReturningSelection() {
        UUID aliceId = UUID.randomUUID();
        Player alice = StubGames.player(aliceId, "Alice", 20, 7);
        LinkedHashMap<UUID, Player> players = new LinkedHashMap<>();
        players.put(aliceId, alice);
        Game game = StubGames.game(players, aliceId, aliceId);

        final AtomicReference<RecordingBridgeController> recordingRef = new AtomicReference<>();
        final AtomicInteger observationsWhenDelegateRan = new AtomicInteger(-1);
        CabtBridgeController delegate = new CabtBridgeController() {
            @Override
            public Selection requestSelection(Game g, Player p, PendingDecision d) {
                observationsWhenDelegateRan.set(recordingRef.get().getObservations().size());
                return Selection.of(0);
            }
        };
        RecordingBridgeController recording =
                new RecordingBridgeController(delegate, new MagicObservationSerializer());
        recordingRef.set(recording);

        Selection selection = recording.requestSelection(
                game, alice, PendingDecision.priority(aliceId));

        assertThat(selection.indices()).containsExactly(0);
        // observation was captured before the delegate was consulted
        assertThat(observationsWhenDelegateRan.get()).isEqualTo(1);
        assertThat(recording.getLastObservation()).isNotNull();
        assertThat(recording.getObservations()).hasSize(1);
        assertThat(recording.getLastObservation().getSelect().getOption().get(0).getType())
                .isEqualTo("PASS_PRIORITY");
    }

    @Test
    void bridgePlayerPriorityProducesObservationEndToEnd() {
        // the exact wiring Task 2 promises: scripted -> recording -> bridge player
        CabtBridgeController scripted =
                new ScriptedBridgeController(Collections.singletonList(Selection.of(0)));
        RecordingBridgeController recording =
                new RecordingBridgeController(scripted, new MagicObservationSerializer());
        CabtBridgePlayer player =
                new CabtBridgePlayer("CABT", RangeOfInfluence.ALL, recording);

        LinkedHashMap<UUID, Player> players = new LinkedHashMap<>();
        players.put(player.getId(), player);
        Game game = StubGames.game(players, player.getId(), player.getId());

        boolean result = player.priority(game);

        // Task 1 contract unchanged
        assertThat(result).isFalse();
        assertThat(player.isPassed()).isTrue();

        MagicObservation observation = recording.getLastObservation();
        assertThat(observation).isNotNull();
        assertThat(observation.getLogs()).isEmpty();
        assertThat(observation.getSelect().getType()).isEqualTo("PRIORITY");
        assertThat(observation.getSelect().getPlayerIndex()).isEqualTo(0);
        assertThat(observation.getSelect().getPlayerId()).isEqualTo(player.getId().toString());
        assertThat(observation.getSelect().getOption()).hasSize(1);
        assertThat(observation.getSelect().getOption().get(0).getType()).isEqualTo("PASS_PRIORITY");
        assertThat(observation.getCurrent().getPlayers()).hasSize(1);
        assertThat(observation.getCurrent().getPlayers().get(0).getName()).isEqualTo("CABT");
        // the observation was taken before the pass was dispatched
        assertThat(observation.getCurrent().getPlayers().get(0).isPassed()).isFalse();
    }
}
