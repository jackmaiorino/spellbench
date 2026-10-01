package mage.player.cabt;

import mage.cards.Card;
import mage.constants.RangeOfInfluence;
import mage.game.Game;
import mage.game.permanent.Battlefield;
import mage.game.stack.SpellStack;
import mage.players.Player;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Task 14: the bridge player surfaces selectAttackers as a DECLARE_ATTACKERS
 * prompt; the option is a combat declaration — damage stays with the engine.
 */
class CabtBridgePlayerAttackersTest {

    private RecordingBridgeController recording;
    private CabtBridgePlayer player;
    private Game game;
    private UUID bearsId;

    private void setUpCombatGame(List<Selection> scripted) {
        recording = new RecordingBridgeController(
                new ScriptedBridgeController(scripted),
                new MagicObservationSerializer());
        player = new CabtBridgePlayer("CABT", RangeOfInfluence.ALL, recording);
        UUID bobId = UUID.randomUUID();
        bearsId = UUID.randomUUID();
        Battlefield battlefield = new Battlefield();
        battlefield.addPermanent(StubGames.permanent(
                bearsId, "Grizzly Bears", player.getId(), player.getId(), false, 2, 2));
        LinkedHashMap<UUID, Player> players = new LinkedHashMap<UUID, Player>();
        players.put(player.getId(), player);
        players.put(bobId, StubGames.player(bobId, "Bob", 20, 7));
        game = StubGames.game(players, player.getId(), player.getId(),
                battlefield, new SpellStack(), new LinkedHashMap<UUID, Card>());
        game.getCombat().setAttacker(player.getId());
        game.getCombat().setDefenders(game);
    }

    @Test
    void selectedAttackerIsDeclaredThroughTheEngine() {
        setUpCombatGame(Collections.singletonList(Selection.of(0)));

        player.selectAttackers(game, player.getId());

        assertThat(game.getCombat().getAttackers()).contains(bearsId);
        assertThat(recording.getLastObservation().getSelect().getType())
                .isEqualTo("DECLARE_ATTACKERS");
        CabtDecisionTrace trace = player.getTraceRecorder().getLastTrace();
        assertThat(trace.getMethod()).isEqualTo("SELECT_ATTACKERS");
        assertThat(trace.getStage()).isEqualTo(CabtDecisionTrace.Stage.APPLIED);
    }

    @Test
    void emptyAttackSelectionDeclaresNoAttackers() {
        setUpCombatGame(Collections.singletonList(new Selection(new ArrayList<Integer>())));

        player.selectAttackers(game, player.getId());

        assertThat(game.getCombat().getAttackers()).isEmpty();
        // the decision was still surfaced and traced: declining is a choice
        assertThat(player.getTraceRecorder().getLastTrace().getSelection().indices()).isEmpty();
        assertThat(player.getTraceRecorder().getLastTrace().getStage())
                .isEqualTo(CabtDecisionTrace.Stage.APPLIED);
    }
}
