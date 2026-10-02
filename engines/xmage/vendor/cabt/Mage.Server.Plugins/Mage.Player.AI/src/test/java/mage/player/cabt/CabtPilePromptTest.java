package mage.player.cabt;

import mage.cards.Card;
import mage.constants.Outcome;
import mage.constants.RangeOfInfluence;
import mage.game.Game;
import mage.players.Player;
import org.junit.jupiter.api.Test;

import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Task 8: choosePile surfaces as a PILE prompt with exactly two options
 * carrying the piles' cards. Selecting pile 1 returns true — the same
 * boolean convention as HumanPlayer.choosePile (its response boolean is
 * true for pile 1).
 */
class CabtPilePromptTest {

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

    private static List<Card> pile(String... names) {
        Card[] cards = new Card[names.length];
        for (int i = 0; i < names.length; i++) {
            cards[i] = StubGames.card(UUID.randomUUID(), names[i], null);
        }
        return Arrays.asList(cards);
    }

    @Test
    void pilePromptHasTwoOptions() {
        setUpPlayer(Selection.of(0));
        List<Card> pile1 = pile("Island", "Forest");
        List<Card> pile2 = pile("Lightning Bolt");

        boolean result = player.choosePile(Outcome.Neutral, "Choose a pile", pile1, pile2, game);

        // pile 1 selected -> true
        assertThat(result).isTrue();
        MagicSelectView select = recording.getLastObservation().getSelect();
        assertThat(select.getType()).isEqualTo("PILE");
        assertThat(select.getOption()).hasSize(2);
        assertThat(select.getOption().get(0).getType()).isEqualTo("PROMPT_PILE");
        assertThat(select.getOption().get(0).getPayload().get("pileIndex")).isEqualTo(1);
        assertThat(select.getOption().get(1).getPayload().get("pileIndex")).isEqualTo(2);

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> cards1 =
                (List<Map<String, Object>>) select.getOption().get(0).getPayload().get("cards");
        assertThat(cards1).hasSize(2);
        assertThat(cards1.get(0).get("name")).isEqualTo("Island");
        assertThat(cards1.get(0).get("objectId")).isNotNull();

        assertThat(player.getTraceRecorder().getLastTrace().getMethod()).isEqualTo("CHOOSE_PILE");
    }

    @Test
    void selectingPileTwoReturnsFalse() {
        setUpPlayer(Selection.of(1));

        boolean result = player.choosePile(Outcome.Neutral, "Choose a pile",
                pile("Island"), pile("Lightning Bolt"), game);

        assertThat(result).isFalse();
    }
}
