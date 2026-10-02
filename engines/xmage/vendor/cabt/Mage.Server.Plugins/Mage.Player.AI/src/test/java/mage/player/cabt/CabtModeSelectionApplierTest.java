package mage.player.cabt;

import mage.abilities.Mode;
import mage.abilities.Modes;
import mage.game.Game;
import mage.players.Player;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Task 9: a validated selection resolves back to the exact XMage Mode object;
 * the engine's Modes.choose(...) marks it selected afterwards.
 */
class CabtModeSelectionApplierTest {

    private final CabtModePromptBuilder builder = new CabtModePromptBuilder();
    private final CabtModeSelectionApplier applier = new CabtModeSelectionApplier();

    @Test
    void modeSelectionReturnsSelectedMode() {
        UUID aliceId = UUID.randomUUID();
        Player alice = StubGames.player(aliceId, "Alice", 20, 7);
        LinkedHashMap<UUID, Player> players = new LinkedHashMap<UUID, Player>();
        players.put(aliceId, alice);
        Game game = StubGames.game(players, aliceId, aliceId);
        Modes modes = CabtModePromptBuilderTest.twoModes();
        PendingDecision decision = builder.build(alice, game, modes, StubGames.ability());

        Mode mode = applier.apply(modes, StubGames.ability(), game, Selection.of(1), decision);

        assertThat(mode).isNotNull();
        assertThat(mode.getId().toString())
                .isEqualTo(decision.options().get(1).payload().get("modeId"));
    }

    @Test
    void emptySelectionReturnsNoMode() {
        UUID aliceId = UUID.randomUUID();
        Player alice = StubGames.player(aliceId, "Alice", 20, 7);
        LinkedHashMap<UUID, Player> players = new LinkedHashMap<UUID, Player>();
        players.put(aliceId, alice);
        Game game = StubGames.game(players, aliceId, aliceId);
        Modes modes = CabtModePromptBuilderTest.twoModes();
        PendingDecision decision = builder.build(alice, game, modes, StubGames.ability());

        Mode mode = applier.apply(modes, StubGames.ability(), game,
                new Selection(new ArrayList<Integer>()), decision);

        assertThat(mode).isNull();
    }
}
