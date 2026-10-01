package mage.player.cabt;

import mage.Mana;
import mage.abilities.Abilities;
import mage.abilities.AbilitiesImpl;
import mage.abilities.Ability;
import mage.abilities.costs.mana.ManaCost;
import mage.abilities.costs.mana.ManaCostsImpl;
import mage.abilities.mana.GreenManaAbility;
import mage.cards.Card;
import mage.constants.ManaType;
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
 * Task 13: PAY_MANA selections are applied through XMage's own payment paths
 * — PlayerImpl.playManaAbility for a source, ManaPool.unlockManaType for
 * floating mana — so one selection is one real payment step.
 */
class CabtManaSelectionApplierTest {

    private final CabtManaPromptBuilder builder = new CabtManaPromptBuilder();
    private final CabtManaSelectionApplier applier = new CabtManaSelectionApplier();

    private CabtBridgePlayer player;
    private Game game;

    private void setUpForestGame() {
        player = new CabtBridgePlayer("CABT", RangeOfInfluence.ALL,
                new ScriptedBridgeController(Collections.<Selection>emptyList()));
        UUID forestId = UUID.randomUUID();
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

    private PendingDecision decision() {
        return builder.build(player, game, StubGames.ability(),
                new ManaCostsImpl<ManaCost>("{G}"), "{G}");
    }

    @Test
    void selectingManaSourcePaysOneStep() {
        setUpForestGame();
        assertThat(player.getManaPool().get(ManaType.GREEN)).isEqualTo(0);

        boolean result = applier.apply(player, game, Selection.of(0), decision());

        // the Forest's mana ability was activated through the engine: one
        // green mana is now in the pool for the payment loop to consume
        assertThat(result).isTrue();
        assertThat(player.getManaPool().get(ManaType.GREEN)).isEqualTo(1);
    }

    @Test
    void cancelStopsThePaymentLoop() {
        setUpForestGame();
        PendingDecision decision = decision();
        int cancelIndex = decision.options().size() - 1;

        boolean result = applier.apply(player, game, Selection.of(cancelIndex), decision);

        assertThat(result).isFalse();
        assertThat(player.getManaPool().get(ManaType.GREEN)).isEqualTo(0);
    }

    @Test
    void poolManaSelectionUnlocksThroughManaPool() {
        setUpForestGame();
        player.getManaPool().addMana(Mana.GreenMana(1), game, StubGames.ability());
        PendingDecision decision = decision();
        int poolIndex = -1;
        for (int i = 0; i < decision.options().size(); i++) {
            if (decision.options().get(i).type() == MagicOptionType.PROMPT_MANA_POOL) {
                poolIndex = i;
            }
        }
        assertThat(poolIndex).isNotNegative();

        boolean result = applier.apply(player, game, Selection.of(poolIndex), decision);

        assertThat(result).isTrue();
    }
}
