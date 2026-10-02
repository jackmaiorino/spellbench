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
 * Task 14: DECLARE_ATTACKERS prompts pair each available attacker with each
 * legal defender registered on the engine's combat. Attacking is optional:
 * minCount 0.
 */
class CabtAttackersPromptBuilderTest {

    private final CabtAttackersPromptBuilder builder = new CabtAttackersPromptBuilder();

    private CabtBridgePlayer player;
    private Player bob;
    private Game game;
    private UUID bearsId;
    private UUID bobId;

    void setUpCombatGame() {
        player = new CabtBridgePlayer("CABT", RangeOfInfluence.ALL,
                new ScriptedBridgeController(Collections.<Selection>emptyList()));
        bobId = UUID.randomUUID();
        bob = StubGames.player(bobId, "Bob", 20, 7);
        bearsId = UUID.randomUUID();
        Battlefield battlefield = new Battlefield();
        battlefield.addPermanent(StubGames.permanent(
                bearsId, "Grizzly Bears", player.getId(), player.getId(), false, 2, 2));
        LinkedHashMap<UUID, Player> players = new LinkedHashMap<UUID, Player>();
        players.put(player.getId(), player);
        players.put(bobId, bob);
        game = StubGames.game(players, player.getId(), player.getId(),
                battlefield, new SpellStack(), new LinkedHashMap<UUID, Card>());
        // the engine registers combat defenders before selectAttackers runs
        game.getCombat().setAttacker(player.getId());
        game.getCombat().setDefenders(game);
    }

    @Test
    void attackPromptIncludesLegalAttackerDefenderPairs() {
        setUpCombatGame();

        PendingDecision decision = builder.build(player, game, player.getId());

        assertThat(decision.selectType()).isEqualTo(MagicSelectType.DECLARE_ATTACKERS);
        assertThat(decision.minCount()).isEqualTo(0);
        assertThat(decision.maxCount()).isEqualTo(1);
        assertThat(decision.options()).hasSize(1);
        MagicOption option = decision.options().get(0);
        assertThat(option.type()).isEqualTo(MagicOptionType.PROMPT_ATTACKER);
        assertThat(option.label()).isEqualTo("Attack Bob with Grizzly Bears");
        assertThat(option.payload().get("attackerId")).isEqualTo(bearsId.toString());
        assertThat(option.payload().get("attackerName")).isEqualTo("Grizzly Bears");
        assertThat(option.payload().get("defenderId")).isEqualTo(bobId.toString());
        assertThat(option.payload().get("defenderName")).isEqualTo("Bob");
        assertThat(option.payload().get("defenderType")).isEqualTo("PLAYER");
    }
}
