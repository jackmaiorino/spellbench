package mage.player.cabt;

import mage.constants.RangeOfInfluence;
import mage.game.Game;
import mage.players.Player;
import org.junit.jupiter.api.Test;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Task 16: the bridge player surfaces chooseMulligan as a MULLIGAN prompt.
 * Bottoming after a mulligan stays with the engine's own follow-up callbacks.
 */
class CabtBridgePlayerMulliganTest {

    private RecordingBridgeController recording;
    private CabtBridgePlayer player;
    private Game game;

    private void setUpPlayer(Selection scripted) {
        recording = new RecordingBridgeController(
                new ScriptedBridgeController(Collections.singletonList(scripted)),
                new MagicObservationSerializer());
        player = new CabtBridgePlayer("CABT", RangeOfInfluence.ALL, recording);
        LinkedHashMap<UUID, Player> players = new LinkedHashMap<UUID, Player>();
        players.put(player.getId(), player);
        game = StubGames.game(players, player.getId(), player.getId());
    }

    @Test
    void keepingTheHandReturnsFalse() {
        setUpPlayer(Selection.of(0));

        boolean result = player.chooseMulligan(game);

        assertThat(result).isFalse();
        assertThat(recording.getLastObservation().getSelect().getType()).isEqualTo("MULLIGAN");
        CabtDecisionTrace trace = player.getTraceRecorder().getLastTrace();
        assertThat(trace.getMethod()).isEqualTo("CHOOSE_MULLIGAN");
        assertThat(trace.getStage()).isEqualTo(CabtDecisionTrace.Stage.APPLIED);
        assertThat(trace.getSelection().indices()).containsExactly(0);
    }

    @Test
    void takingTheMulliganReturnsTrue() {
        setUpPlayer(Selection.of(1));

        boolean result = player.chooseMulligan(game);

        assertThat(result).isTrue();
        assertThat(player.getTraceRecorder().getLastTrace().getSelection().indices())
                .containsExactly(1);
    }
}
