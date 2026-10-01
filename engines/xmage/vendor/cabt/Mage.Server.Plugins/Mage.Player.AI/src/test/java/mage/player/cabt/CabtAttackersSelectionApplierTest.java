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
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Task 14: selected attacks are committed through the engine's own
 * Player.declareAttacker(...) into game.getCombat().
 */
class CabtAttackersSelectionApplierTest {

    private final CabtAttackersPromptBuilder builder = new CabtAttackersPromptBuilder();
    private final CabtAttackersSelectionApplier applier = new CabtAttackersSelectionApplier();

    private CabtBridgePlayer player;
    private Game game;
    private UUID bearsId;
    private UUID bobId;

    private void setUpCombatGame() {
        player = new CabtBridgePlayer("CABT", RangeOfInfluence.ALL,
                new ScriptedBridgeController(Collections.<Selection>emptyList()));
        bobId = UUID.randomUUID();
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
    void selectedAttackerIsDeclared() {
        setUpCombatGame();
        PendingDecision decision = builder.build(player, game, player.getId());

        applier.apply(player, game, Selection.of(0), decision);

        assertThat(game.getCombat().getAttackers()).contains(bearsId);
    }

    @Test
    void emptyAttackSelectionDeclaresNoAttackers() {
        setUpCombatGame();
        PendingDecision decision = builder.build(player, game, player.getId());

        applier.apply(player, game, new Selection(new ArrayList<Integer>()), decision);

        assertThat(game.getCombat().getAttackers()).isEmpty();
    }
}
