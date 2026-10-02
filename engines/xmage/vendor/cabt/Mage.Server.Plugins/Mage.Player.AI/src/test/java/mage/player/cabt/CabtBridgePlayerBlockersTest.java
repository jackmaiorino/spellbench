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
 * Task 15: the bridge player surfaces selectBlockers as a DECLARE_BLOCKERS
 * prompt and commits blocks through declareBlocker; combat damage and lethal
 * handling stay with the engine.
 */
class CabtBridgePlayerBlockersTest {

    private RecordingBridgeController recording;
    private CabtBridgePlayer defender;
    private Game game;
    private UUID bearsId;
    private UUID giantId;

    private void setUpBlockGame(List<Selection> scripted) {
        recording = new RecordingBridgeController(
                new ScriptedBridgeController(scripted),
                new MagicObservationSerializer());
        defender = new CabtBridgePlayer("CABT", RangeOfInfluence.ALL, recording);
        UUID bobId = UUID.randomUUID();
        bearsId = UUID.randomUUID();
        giantId = UUID.randomUUID();
        Battlefield battlefield = new Battlefield();
        battlefield.addPermanent(StubGames.permanent(
                bearsId, "Grizzly Bears", bobId, bobId, false, 2, 2));
        battlefield.addPermanent(StubGames.permanent(
                giantId, "Hill Giant", defender.getId(), defender.getId(), false, 3, 3));
        LinkedHashMap<UUID, Player> players = new LinkedHashMap<UUID, Player>();
        players.put(defender.getId(), defender);
        players.put(bobId, StubGames.player(bobId, "Bob", 20, 7));
        game = StubGames.game(players, bobId, bobId,
                battlefield, new SpellStack(), new LinkedHashMap<UUID, Card>());
        game.getCombat().setAttacker(bobId);
        game.getCombat().setDefenders(game);
        game.getCombat().declareAttacker(bearsId, defender.getId(), bobId, game);
    }

    @Test
    void selectedBlockerIsDeclaredThroughTheEngine() {
        setUpBlockGame(Collections.singletonList(Selection.of(0)));

        defender.selectBlockers(StubGames.ability(), game, defender.getId());

        assertThat(game.getCombat().findGroup(bearsId).getBlockers()).contains(giantId);
        assertThat(recording.getLastObservation().getSelect().getType())
                .isEqualTo("DECLARE_BLOCKERS");
        CabtDecisionTrace trace = defender.getTraceRecorder().getLastTrace();
        assertThat(trace.getMethod()).isEqualTo("SELECT_BLOCKERS");
        assertThat(trace.getStage()).isEqualTo(CabtDecisionTrace.Stage.APPLIED);
    }

    @Test
    void emptyBlockSelectionDeclaresNoBlocks() {
        setUpBlockGame(Collections.singletonList(new Selection(new ArrayList<Integer>())));

        defender.selectBlockers(StubGames.ability(), game, defender.getId());

        assertThat(game.getCombat().findGroup(bearsId).getBlockers()).isEmpty();
    }
}
