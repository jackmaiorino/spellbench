package mage.player.cabt;

import mage.abilities.TriggeredAbility;
import mage.cards.Card;
import mage.constants.RangeOfInfluence;
import mage.game.Game;
import mage.game.stack.SpellStack;
import mage.players.Player;
import org.junit.jupiter.api.Test;

import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Task 11: the bridge player answers the trigger-ordering callback that
 * GameImpl.checkTriggered() makes when the player controls multiple waiting
 * triggers — the bridge only orders; the engine keeps finding the triggers.
 * (As with the other prompt families, the callback boundary is exercised
 * directly; running the real trigger pipeline needs the full engine loop.)
 */
class CabtBridgePlayerTriggeredAbilityTest {

    private RecordingBridgeController recording;
    private CabtBridgePlayer player;
    private Game game;

    private void setUpPlayer(List<Selection> scripted, LinkedHashMap<UUID, Card> cards) {
        recording = new RecordingBridgeController(
                new ScriptedBridgeController(scripted),
                new MagicObservationSerializer());
        player = new CabtBridgePlayer("CABT", RangeOfInfluence.ALL, recording);
        LinkedHashMap<UUID, Player> players = new LinkedHashMap<UUID, Player>();
        players.put(player.getId(), player);
        game = StubGames.game(players, player.getId(), player.getId(),
                null, new SpellStack(), cards);
    }

    @Test
    void multipleTriggersIntegration() {
        UUID bearsId = UUID.randomUUID();
        LinkedHashMap<UUID, Card> cards = new LinkedHashMap<UUID, Card>();
        cards.put(bearsId, StubGames.card(bearsId, "Grizzly Bears", null));
        setUpPlayer(Collections.singletonList(Selection.of(1)), cards);
        // two simultaneous triggers controlled by the bridge player
        List<TriggeredAbility> triggers = Arrays.asList(
                StubGames.triggeredAbility(UUID.randomUUID(), UUID.randomUUID(), bearsId,
                        "Whenever Grizzly Bears attacks, draw a card."),
                StubGames.triggeredAbility(UUID.randomUUID(), UUID.randomUUID(), bearsId,
                        "Whenever Grizzly Bears attacks, you gain 1 life."));

        TriggeredAbility selected = player.chooseTriggeredAbility(triggers, game);

        assertThat(selected).isSameAs(triggers.get(1));
        MagicSelectView select = recording.getLastObservation().getSelect();
        assertThat(select.getType()).isEqualTo("TRIGGER_ORDER");
        assertThat(select.getOption()).hasSize(2);

        CabtDecisionTrace trace = player.getTraceRecorder().getLastTrace();
        assertThat(trace.getMethod()).isEqualTo("CHOOSE_TRIGGERED_ABILITY");
        assertThat(trace.getStage()).isEqualTo(CabtDecisionTrace.Stage.APPLIED);
        assertThat(trace.getSelection().indices()).containsExactly(1);
    }

    @Test
    void singleTriggerNeedsNoOrderingPrompt() {
        setUpPlayer(Collections.<Selection>emptyList(), new LinkedHashMap<UUID, Card>());
        TriggeredAbility only = StubGames.triggeredAbility(
                UUID.randomUUID(), UUID.randomUUID(), UUID.randomUUID(), "a trigger");

        TriggeredAbility selected = player.chooseTriggeredAbility(
                Collections.singletonList(only), game);

        assertThat(selected).isSameAs(only);
        assertThat(player.getTraceRecorder().getTraces()).isEmpty();
        assertThat(recording.getObservations()).isEmpty();
    }
}
