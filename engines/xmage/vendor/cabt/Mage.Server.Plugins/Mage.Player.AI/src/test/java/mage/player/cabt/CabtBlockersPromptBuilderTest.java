package mage.player.cabt;

import mage.cards.Card;
import mage.constants.RangeOfInfluence;
import mage.game.Game;
import mage.game.permanent.Battlefield;
import mage.game.stack.SpellStack;
import mage.players.Player;
import org.junit.jupiter.api.Test;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Task 15: DECLARE_BLOCKERS prompts pair each available blocker with each
 * attacker it can legally block, using the same CombatGroup.canBlock check
 * declareBlocker applies.
 */
class CabtBlockersPromptBuilderTest {

    private final CabtBlockersPromptBuilder builder = new CabtBlockersPromptBuilder();

    CabtBridgePlayer defender;
    Game game;
    UUID bearsId;
    UUID giantId;
    UUID bobId;

    void setUpBlockGame() {
        defender = new CabtBridgePlayer("CABT", RangeOfInfluence.ALL,
                new ScriptedBridgeController(Collections.<Selection>emptyList()));
        bobId = UUID.randomUUID();
        bearsId = UUID.randomUUID();
        giantId = UUID.randomUUID();
        Battlefield battlefield = new Battlefield();
        // Bob's attacker and the bridge player's blocker
        battlefield.addPermanent(StubGames.permanent(
                bearsId, "Grizzly Bears", bobId, bobId, false, 2, 2));
        battlefield.addPermanent(StubGames.permanent(
                giantId, "Hill Giant", defender.getId(), defender.getId(), false, 3, 3));
        LinkedHashMap<UUID, Player> players = new LinkedHashMap<UUID, Player>();
        players.put(defender.getId(), defender);
        players.put(bobId, StubGames.player(bobId, "Bob", 20, 7));
        game = StubGames.game(players, bobId, bobId,
                battlefield, new SpellStack(), new LinkedHashMap<UUID, Card>());
        // the engine has already declared Bob's attack on the bridge player
        game.getCombat().setAttacker(bobId);
        game.getCombat().setDefenders(game);
        game.getCombat().declareAttacker(bearsId, defender.getId(), bobId, game);
    }

    @Test
    void blockPromptIncludesLegalBlockerAttackerPairs() {
        setUpBlockGame();

        PendingDecision decision = builder.build(defender, game, defender.getId());

        assertThat(decision.selectType()).isEqualTo(MagicSelectType.DECLARE_BLOCKERS);
        assertThat(decision.minCount()).isEqualTo(0);
        assertThat(decision.maxCount()).isEqualTo(1);
        assertThat(decision.options()).hasSize(1);
        MagicOption option = decision.options().get(0);
        assertThat(option.type()).isEqualTo(MagicOptionType.PROMPT_BLOCKER);
        assertThat(option.label()).isEqualTo("Block Grizzly Bears with Hill Giant");
        assertThat(option.payload().get("blockerId")).isEqualTo(giantId.toString());
        assertThat(option.payload().get("blockerName")).isEqualTo("Hill Giant");
        assertThat(option.payload().get("attackerId")).isEqualTo(bearsId.toString());
        assertThat(option.payload().get("attackerName")).isEqualTo("Grizzly Bears");
        assertThat(option.payload().get("defendingPlayerId"))
                .isEqualTo(defender.getId().toString());
    }
}
