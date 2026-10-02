package mage.player.cabt;

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
import java.util.List;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Task 13: the bridge player surfaces playMana as a PAY_MANA prompt and pays
 * one step per selection through the engine's own activation path.
 * <p>
 * The spec's full "select CAST_SPELL, then pay" integration needs a
 * CAST_SPELL priority option, which the bridge does not have yet (priority
 * is still pass-only) — so these tests drive the playMana callback exactly
 * as the engine's payment loop does.
 */
class CabtBridgePlayerManaPromptTest {

    private RecordingBridgeController recording;
    private CabtBridgePlayer player;
    private Game game;

    private void setUpForestGame(List<Selection> scripted) {
        recording = new RecordingBridgeController(
                new ScriptedBridgeController(scripted),
                new MagicObservationSerializer());
        player = new CabtBridgePlayer("CABT", RangeOfInfluence.ALL, recording);
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

    @Test
    void payingWithBasicLandContinuesThePaymentLoop() {
        setUpForestGame(Collections.singletonList(Selection.of(0)));

        boolean result = player.playMana(StubGames.ability(),
                new ManaCostsImpl<ManaCost>("{G}"), "{G}", game);

        assertThat(result).isTrue();
        assertThat(player.getManaPool().get(ManaType.GREEN)).isEqualTo(1);

        MagicSelectView select = recording.getLastObservation().getSelect();
        assertThat(select.getType()).isEqualTo("PAY_MANA");
        assertThat(select.getOption().get(0).getType()).isEqualTo("PROMPT_MANA_SOURCE");
        assertThat(select.getOption().get(0).getPayload().get("unpaid")).isEqualTo("{G}");

        CabtDecisionTrace trace = player.getTraceRecorder().getLastTrace();
        assertThat(trace.getMethod()).isEqualTo("PLAY_MANA");
        assertThat(trace.getSelectType()).isEqualTo(MagicSelectType.PAY_MANA);
        assertThat(trace.getStage()).isEqualTo(CabtDecisionTrace.Stage.APPLIED);
        // the trace carries the unpaid cost and the selected mana source
        assertThat(trace.getDecision().options().get(0).payload().get("unpaid")).isEqualTo("{G}");
        assertThat(trace.getSelection().indices()).containsExactly(0);
    }

    @Test
    void cancelSelectionStopsPayment() {
        setUpForestGame(Collections.singletonList(Selection.of(1))); // Forest + cancel

        boolean result = player.playMana(StubGames.ability(),
                new ManaCostsImpl<ManaCost>("{G}"), "{G}", game);

        assertThat(result).isFalse();
        assertThat(player.getManaPool().get(ManaType.GREEN)).isEqualTo(0);
    }
}
