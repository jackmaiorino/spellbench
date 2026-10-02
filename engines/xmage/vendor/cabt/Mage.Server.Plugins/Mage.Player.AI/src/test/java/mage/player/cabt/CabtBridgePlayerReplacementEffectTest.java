package mage.player.cabt;

import mage.MageObject;
import mage.constants.RangeOfInfluence;
import mage.game.Game;
import mage.players.Player;
import org.junit.jupiter.api.Test;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Task 12: the bridge player answers chooseReplacementEffect with the chosen
 * entry's index in the effectsMap order — the int the engine expects. The
 * bridge does not judge which replacement is strategically better.
 */
class CabtBridgePlayerReplacementEffectTest {

    private RecordingBridgeController recording;
    private CabtBridgePlayer player;
    private Game game;

    private void setUpPlayer(List<Selection> scripted) {
        recording = new RecordingBridgeController(
                new ScriptedBridgeController(scripted),
                new MagicObservationSerializer());
        player = new CabtBridgePlayer("CABT", RangeOfInfluence.ALL, recording);
        LinkedHashMap<UUID, Player> players = new LinkedHashMap<UUID, Player>();
        players.put(player.getId(), player);
        game = StubGames.game(players, player.getId(), player.getId());
    }

    private static LinkedHashMap<String, String> threeEffects() {
        LinkedHashMap<String, String> effects = new LinkedHashMap<String, String>();
        effects.put("effect-a", "If a creature would die, exile it instead");
        effects.put("effect-b", "If you would draw a card, draw two instead");
        effects.put("effect-c", "Prevent all combat damage");
        return effects;
    }

    @Test
    void replacementChoiceReturnsSelectedOriginalIndex() {
        setUpPlayer(Collections.singletonList(Selection.of(2)));

        int result = player.chooseReplacementEffect(threeEffects(),
                new LinkedHashMap<String, MageObject>(), game);

        assertThat(result).isEqualTo(2);
        MagicSelectView select = recording.getLastObservation().getSelect();
        assertThat(select.getType()).isEqualTo("REPLACEMENT_EFFECT");
        assertThat(select.getOption()).hasSize(3);

        CabtDecisionTrace trace = player.getTraceRecorder().getLastTrace();
        assertThat(trace.getMethod()).isEqualTo("CHOOSE_REPLACEMENT_EFFECT");
        assertThat(trace.getStage()).isEqualTo(CabtDecisionTrace.Stage.APPLIED);
    }

    @Test
    void singleReplacementEffectNeedsNoPrompt() {
        setUpPlayer(Collections.<Selection>emptyList());
        LinkedHashMap<String, String> single = new LinkedHashMap<String, String>();
        single.put("only", "If you would draw a card, draw two instead");

        // same shortcut as HumanPlayer: one applicable effect -> index 0
        int result = player.chooseReplacementEffect(single,
                new LinkedHashMap<String, MageObject>(), game);

        assertThat(result).isEqualTo(0);
        assertThat(player.getTraceRecorder().getTraces()).isEmpty();
        assertThat(recording.getObservations()).isEmpty();
    }
}
