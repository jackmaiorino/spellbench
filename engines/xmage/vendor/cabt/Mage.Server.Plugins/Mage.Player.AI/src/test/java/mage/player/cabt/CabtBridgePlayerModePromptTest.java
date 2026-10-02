package mage.player.cabt;

import mage.abilities.Mode;
import mage.abilities.Modes;
import mage.constants.RangeOfInfluence;
import mage.game.Game;
import mage.players.Player;
import org.junit.jupiter.api.Test;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Task 9: the bridge player surfaces chooseMode as a MODE prompt and returns
 * the selected Mode to the engine — the same callback Modes.choose(...) makes
 * while a modal spell is being cast. (Running an actual modal cast requires
 * the full engine loop, which this module's tests do not boot; the callback
 * boundary is exercised directly, as in the target prompt tests.)
 */
class CabtBridgePlayerModePromptTest {

    private RecordingBridgeController recording;
    private CabtBridgePlayer player;
    private Game game;

    private void setUpPlayer(java.util.List<Selection> scripted) {
        recording = new RecordingBridgeController(
                new ScriptedBridgeController(scripted),
                new MagicObservationSerializer());
        player = new CabtBridgePlayer("CABT", RangeOfInfluence.ALL, recording);
        LinkedHashMap<UUID, Player> players = new LinkedHashMap<UUID, Player>();
        players.put(player.getId(), player);
        game = StubGames.game(players, player.getId(), player.getId());
    }

    @Test
    void modalSpellPromptsForMode() {
        setUpPlayer(Collections.singletonList(Selection.of(0)));
        Modes modes = CabtModePromptBuilderTest.twoModes();

        Mode mode = player.chooseMode(modes, StubGames.ability(), game);

        // the engine's Modes.choose(...) receives a mode and casting continues
        assertThat(mode).isNotNull();
        MagicSelectView select = recording.getLastObservation().getSelect();
        assertThat(select.getType()).isEqualTo("MODE");
        assertThat(mode.getId().toString())
                .isEqualTo(select.getOption().get(0).getPayload().get("modeId"));

        CabtDecisionTrace trace = player.getTraceRecorder().getLastTrace();
        assertThat(trace.getMethod()).isEqualTo("CHOOSE_MODE");
        assertThat(trace.getStage()).isEqualTo(CabtDecisionTrace.Stage.APPLIED);
    }

    @Test
    void singleModeSkipsThePromptLikeHumanPlayer() {
        setUpPlayer(Collections.<Selection>emptyList());
        Modes modes = new Modes(); // one default mode only

        Mode mode = player.chooseMode(modes, StubGames.ability(), game);

        assertThat(mode).isSameAs(modes.getMode());
        assertThat(player.getTraceRecorder().getTraces()).isEmpty();
        assertThat(recording.getObservations()).isEmpty();
    }
}
