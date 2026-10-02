package mage.player.cabt;

import mage.abilities.Mode;
import mage.abilities.Modes;
import mage.abilities.effects.common.DrawCardSourceControllerEffect;
import mage.abilities.effects.common.GainLifeEffect;
import mage.game.Game;
import mage.players.Player;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

class CabtModePromptBuilderTest {
    private final CabtModePromptBuilder builder = new CabtModePromptBuilder();
    private final UUID aliceId = UUID.randomUUID();
    private Player alice;
    private Game game;

    private void setUpGame() {
        alice = StubGames.player(aliceId, "Alice", 20, 7);
        LinkedHashMap<UUID, Player> players = new LinkedHashMap<UUID, Player>();
        players.put(aliceId, alice);
        game = StubGames.game(players, aliceId, aliceId);
    }

    static Modes twoModes() {
        Modes modes = new Modes();
        modes.getMode().getEffects().add(new DrawCardSourceControllerEffect(1));
        modes.addMode(new Mode(new GainLifeEffect(3)));
        modes.clearSelectedModes();
        return modes;
    }

    @Test
    void modePromptIncludesAvailableModes() {
        setUpGame();
        Modes modes = twoModes();
        PendingDecision decision = builder.build(alice, game, modes, StubGames.ability());
        assertThat(decision.selectType()).isEqualTo(MagicSelectType.MODE);
        assertThat(decision.minCount()).isEqualTo(1);
        assertThat(decision.maxCount()).isEqualTo(1);
        assertThat(decision.options()).hasSize(2);
        List<String> modeIds = new ArrayList<String>();
        for (MagicOption option : decision.options()) {
            assertThat(option.type()).isEqualTo(MagicOptionType.PROMPT_MODE);
            assertThat(option.label()).startsWith("Choose mode: ");
            modeIds.add((String) option.payload().get("modeId"));
        }
        for (Mode mode : modes.values()) {
            assertThat(modeIds).contains(mode.getId().toString());
        }
        assertThat(((String) decision.options().get(0).payload().get("modeText")).toLowerCase()).contains("draw a card");
        assertThat(((String) decision.options().get(1).payload().get("modeText")).toLowerCase()).contains("gain 3 life");
    }

    @Test
    void alreadySelectedModesAreExcludedWhenAnotherChoiceIsAllowed() {
        setUpGame();
        Modes modes = twoModes();
        modes.setMaxModes(2);
        UUID firstModeId = modes.values().iterator().next().getId();
        modes.addSelectedMode(firstModeId);
        PendingDecision decision = builder.build(alice, game, modes, StubGames.ability());
        assertThat(decision.options()).hasSize(1);
        assertThat(decision.options().get(0).payload().get("modeId")).isNotEqualTo(firstModeId.toString());
    }

    @Test
    void engineReturnsNoMoreModesAfterItsSelectionLimit() {
        setUpGame();
        Modes modes = twoModes();
        modes.addSelectedMode(modes.values().iterator().next().getId());
        assertThat(modes.getMaxModes(game, StubGames.ability())).isEqualTo(1);
        assertThat(modes.getAvailableModes(StubGames.ability(), game)).isEmpty();
        assertThat(builder.build(alice, game, modes, StubGames.ability()).options()).isEmpty();
    }
}
