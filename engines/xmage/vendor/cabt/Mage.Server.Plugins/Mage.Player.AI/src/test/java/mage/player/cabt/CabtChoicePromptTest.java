package mage.player.cabt;

import mage.choices.Choice;
import mage.choices.ChoiceImpl;
import mage.constants.Outcome;
import mage.constants.RangeOfInfluence;
import mage.game.Game;
import mage.players.Player;
import org.junit.jupiter.api.Test;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Task 8: choose(Outcome, Choice, Game) surfaces as a CHOICE prompt built
 * from the Choice object's own values, and the selection is applied through
 * setChoice/setChoiceByKey.
 */
class CabtChoicePromptTest {

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

    private static Choice colorChoice() {
        ChoiceImpl choice = new ChoiceImpl(true);
        choice.setMessage("Choose a color");
        choice.setChoices(new LinkedHashSet<String>(
                java.util.Arrays.asList("Red", "Green", "Blue")));
        return choice;
    }

    @Test
    void choicePromptUsesChoiceObjectValues() {
        setUpPlayer(Selection.of(1));
        Choice choice = colorChoice();

        boolean result = player.choose(Outcome.Neutral, choice, game);

        assertThat(result).isTrue();
        MagicSelectView select = recording.getLastObservation().getSelect();
        assertThat(select.getType()).isEqualTo("CHOICE");
        assertThat(select.getOption()).hasSize(3);
        for (MagicOptionView option : select.getOption()) {
            assertThat(option.getType()).isEqualTo("PROMPT_CHOICE");
            assertThat(option.getPayload().get("choiceValue")).isIn("Red", "Green", "Blue");
        }
        assertThat(player.getTraceRecorder().getLastTrace().getMethod()).isEqualTo("CHOOSE_CHOICE");
    }

    @Test
    void choiceSelectionUpdatesChoice() {
        setUpPlayer(Selection.of(2));
        Choice choice = colorChoice();

        boolean result = player.choose(Outcome.Neutral, choice, game);

        assertThat(result).isTrue();
        assertThat(choice.isChosen()).isTrue();
        MagicOptionView selected = recording.getLastObservation().getSelect().getOption().get(2);
        assertThat(choice.getChoice()).isEqualTo(selected.getPayload().get("choiceValue"));
    }

    @Test
    void keyChoiceSelectionSetsChoiceByKey() {
        setUpPlayer(Selection.of(0));
        ChoiceImpl choice = new ChoiceImpl(true);
        choice.setMessage("Choose a creature type");
        LinkedHashMap<String, String> keyChoices = new LinkedHashMap<String, String>();
        keyChoices.put("bear", "Bear (2/2)");
        keyChoices.put("wolf", "Wolf (3/1)");
        choice.setKeyChoices(keyChoices);

        boolean result = player.choose(Outcome.Neutral, choice, game);

        assertThat(result).isTrue();
        assertThat(choice.isChosen()).isTrue();
        MagicOptionView selected = recording.getLastObservation().getSelect().getOption().get(0);
        assertThat(choice.getChoiceKey()).isEqualTo(selected.getPayload().get("choiceKey"));
        assertThat(selected.getPayload().get("choiceKey")).isEqualTo("bear");
        assertThat(selected.getPayload().get("choiceValue")).isEqualTo("Bear (2/2)");
    }
}
