package mage.player.cabt;

import mage.Mana;
import mage.abilities.Abilities;
import mage.abilities.AbilitiesImpl;
import mage.abilities.Ability;
import mage.abilities.costs.mana.ManaCost;
import mage.abilities.costs.mana.ManaCostsImpl;
import mage.abilities.mana.GreenManaAbility;
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
 * Task 13: PAY_MANA prompts are discovered through the inherited player's
 * own mana path — PlayerImpl.getAvailableManaProducers and
 * getUseableManaAbilities — plus the mana pool, with cancel always last.
 */
class CabtManaPromptBuilderTest {

    private final CabtManaPromptBuilder builder = new CabtManaPromptBuilder();

    private CabtBridgePlayer player;
    private Game game;
    private UUID forestId;

    private void setUpForestGame() {
        player = new CabtBridgePlayer("CABT", RangeOfInfluence.ALL,
                new ScriptedBridgeController(Collections.<Selection>emptyList()));
        forestId = UUID.randomUUID();
        Abilities<Ability> abilities = new AbilitiesImpl<Ability>();
        GreenManaAbility greenMana = new GreenManaAbility();
        greenMana.setSourceId(forestId);
        greenMana.setControllerId(player.getId());
        abilities.add(greenMana);
        Battlefield battlefield = new Battlefield();
        battlefield.addPermanent(StubGames.permanent(
                forestId, "Forest", player.getId(), player.getId(), false, 0, 0, abilities));
        LinkedHashMap<UUID, Player> players = new LinkedHashMap<UUID, Player>();
        players.put(player.getId(), player);
        game = StubGames.game(players, player.getId(), player.getId(),
                battlefield, new SpellStack(), new LinkedHashMap<UUID, Card>());
    }

    private static ManaCost unpaidGreen() {
        return new ManaCostsImpl<ManaCost>("{G}");
    }

    @Test
    void manaPromptIncludesBasicLandSource() {
        setUpForestGame();

        PendingDecision decision = builder.build(
                player, game, StubGames.ability(), unpaidGreen(), "{1}{G}");

        assertThat(decision.selectType()).isEqualTo(MagicSelectType.PAY_MANA);
        assertThat(decision.options()).hasSize(2); // Forest + cancel
        MagicOption forest = decision.options().get(0);
        assertThat(forest.type()).isEqualTo(MagicOptionType.PROMPT_MANA_SOURCE);
        assertThat(forest.label()).isEqualTo("Tap Forest for mana");
        assertThat(forest.payload().get("manaOptionKind")).isEqualTo("MANA_ABILITY_SOURCE");
        assertThat(forest.payload().get("objectName")).isEqualTo("Forest");
        assertThat(forest.payload().get("objectId")).isEqualTo(forestId.toString());
        assertThat(forest.payload().get("unpaid")).isEqualTo("{G}");
        assertThat(forest.payload().get("promptText")).isEqualTo("{1}{G}");

        MagicOption cancel = decision.options().get(1);
        assertThat(cancel.type()).isEqualTo(MagicOptionType.PROMPT_CANCEL_PAYMENT);
        assertThat(cancel.payload().get("manaOptionKind")).isEqualTo("CANCEL");
    }

    @Test
    void manaPoolOptionUsesAvailablePoolMana() {
        setUpForestGame();
        player.getManaPool().addMana(Mana.GreenMana(1), game, StubGames.ability());

        PendingDecision decision = builder.build(
                player, game, StubGames.ability(), unpaidGreen(), "{G}");

        MagicOption pool = null;
        for (MagicOption option : decision.options()) {
            if (option.type() == MagicOptionType.PROMPT_MANA_POOL) {
                pool = option;
            }
        }
        assertThat(pool).isNotNull();
        assertThat(pool.payload().get("manaType")).isEqualTo("GREEN");
        assertThat(pool.payload().get("available")).isEqualTo(1);
    }
}
