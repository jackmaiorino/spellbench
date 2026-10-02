package mage.player.cabt;

import mage.constants.RangeOfInfluence;
import mage.game.Game;
import mage.players.Player;
import org.junit.jupiter.api.Test;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * Task 10: announceX/getAmount surface as NUMBER prompts with one option per
 * integer in [min, max] — no value outside the engine's bounds can come back.
 */
class CabtNumberPromptTest {

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
    void announceXReturnsSelectedValue() {
        setUpPlayer(Selection.of(2));

        int value = player.announceX(0, 3, "Choose X", game, StubGames.ability(), false);

        assertThat(value).isEqualTo(2);
        MagicSelectView select = recording.getLastObservation().getSelect();
        assertThat(select.getType()).isEqualTo("NUMBER");
        assertThat(select.getOption()).hasSize(4);
        assertThat(select.getOption().get(2).getType()).isEqualTo("PROMPT_NUMBER");
        assertThat(select.getOption().get(2).getLabel()).isEqualTo("2");

        // the trace carries the method, the full prompt (min/max/message in
        // the option payloads), and the selected index
        CabtDecisionTrace trace = player.getTraceRecorder().getLastTrace();
        assertThat(trace.getMethod()).isEqualTo("ANNOUNCE_X");
        assertThat(trace.getStage()).isEqualTo(CabtDecisionTrace.Stage.APPLIED);
        assertThat(trace.getSelection().indices()).containsExactly(2);
        assertThat(trace.getDecision().options().get(2).payload().get("value")).isEqualTo(2);
        assertThat(trace.getDecision().options().get(2).payload().get("min")).isEqualTo(0);
        assertThat(trace.getDecision().options().get(2).payload().get("max")).isEqualTo(3);
        assertThat(trace.getDecision().options().get(2).payload().get("message")).isEqualTo("Choose X");
    }

    @Test
    void getAmountReturnsSelectedValue() {
        setUpPlayer(Selection.of(2));

        int value = player.getAmount(1, 5, "Choose an amount", StubGames.ability(), game);

        // options are 1..5, so index 2 is the value 3
        assertThat(value).isEqualTo(3);
        assertThat(player.getTraceRecorder().getLastTrace().getMethod()).isEqualTo("GET_AMOUNT");
    }

    @Test
    void numberPromptRejectsOutOfRangeSelection() {
        setUpPlayer(Selection.of(7));

        assertThatThrownBy(() -> player.announceX(0, 3, "Choose X", game, StubGames.ability(), false))
                .isInstanceOf(InvalidSelectionException.class)
                .hasMessage("OPTION_INDEX_OUT_OF_RANGE");
        // nothing applied: the trace records the rejected selection as FAILED
        assertThat(player.getTraceRecorder().getLastTrace().getStage())
                .isEqualTo(CabtDecisionTrace.Stage.FAILED);
        assertThat(player.getTraceRecorder().getLastTrace().getError())
                .contains("OPTION_INDEX_OUT_OF_RANGE");
    }

    @Test
    void oversizedRangeFailsClosed() {
        setUpPlayer(Selection.of(0));

        assertThatThrownBy(() -> player.getAmount(
                0, CabtNumberPromptBuilder.MAX_ENUMERATED_NUMBER_OPTIONS + 1, "too big",
                StubGames.ability(), game))
                .isInstanceOf(UnsupportedOperationException.class)
                .hasMessageContaining("failing closed");
    }
}
