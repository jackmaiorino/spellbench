package mage.player.cabt;

import mage.constants.Outcome;
import mage.constants.RangeOfInfluence;
import mage.game.Game;
import mage.players.Player;
import org.junit.jupiter.api.Test;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Task 8: chooseUse surfaces as a YES_NO prompt — option 0 YES, option 1 NO —
 * and the boolean answer follows the selected option.
 */
class CabtYesNoPromptTest {

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
    void chooseUseReturnsTrueForYes() {
        setUpPlayer(Selection.of(0));

        boolean result = player.chooseUse(Outcome.Benefit, "Draw a card?", StubGames.ability(), game);

        assertThat(result).isTrue();
        MagicSelectView select = recording.getLastObservation().getSelect();
        assertThat(select.getType()).isEqualTo("YES_NO");
        assertThat(select.getMinCount()).isEqualTo(1);
        assertThat(select.getMaxCount()).isEqualTo(1);
        assertThat(select.getOption()).hasSize(2);
        assertThat(select.getOption().get(0).getType()).isEqualTo("PROMPT_YES");
        assertThat(select.getOption().get(0).getLabel()).isEqualTo("Yes");
        assertThat(select.getOption().get(1).getType()).isEqualTo("PROMPT_NO");
        assertThat(select.getOption().get(1).getLabel()).isEqualTo("No");
        assertThat(select.getOption().get(0).getPayload().get("message")).isEqualTo("Draw a card?");

        CabtDecisionTrace trace = player.getTraceRecorder().getLastTrace();
        assertThat(trace.getMethod()).isEqualTo("CHOOSE_USE");
        assertThat(trace.getStage()).isEqualTo(CabtDecisionTrace.Stage.APPLIED);
    }

    @Test
    void chooseUseReturnsFalseForNo() {
        setUpPlayer(Selection.of(1));

        boolean result = player.chooseUse(Outcome.Benefit, "Draw a card?", StubGames.ability(), game);

        assertThat(result).isFalse();
        assertThat(player.getTraceRecorder().getLastTrace().getMethod()).isEqualTo("CHOOSE_USE");
    }

    @Test
    void longFormUsesCustomOptionLabels() {
        setUpPlayer(Selection.of(0));

        boolean result = player.chooseUse(Outcome.Neutral, "Choose a side", "Heads or tails",
                "Heads", "Tails", StubGames.ability(), game);

        assertThat(result).isTrue();
        MagicSelectView select = recording.getLastObservation().getSelect();
        assertThat(select.getOption().get(0).getLabel()).isEqualTo("Heads");
        assertThat(select.getOption().get(1).getLabel()).isEqualTo("Tails");
        assertThat(select.getOption().get(0).getPayload().get("secondMessage")).isEqualTo("Heads or tails");
    }
}
