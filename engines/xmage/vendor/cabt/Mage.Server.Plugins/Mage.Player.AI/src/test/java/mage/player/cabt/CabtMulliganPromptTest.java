package mage.player.cabt;

import mage.game.Game;
import mage.players.Player;
import org.junit.jupiter.api.Test;

import java.util.LinkedHashMap;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Task 16: the pregame MULLIGAN prompt has Keep (index 0) and Mulligan
 * (index 1), and the applier returns XMage's boolean convention — true takes
 * the mulligan (as in HumanPlayer's "Mulligan down to N?" dialog).
 */
class CabtMulliganPromptTest {

    private final CabtMulliganPromptBuilder builder = new CabtMulliganPromptBuilder();
    private final CabtMulliganSelectionApplier applier = new CabtMulliganSelectionApplier();

    private final UUID aliceId = UUID.randomUUID();
    private final Player alice = StubGames.player(aliceId, "Alice", 20, 7);

    private Game game() {
        LinkedHashMap<UUID, Player> players = new LinkedHashMap<UUID, Player>();
        players.put(aliceId, alice);
        return StubGames.game(players, aliceId, aliceId);
    }

    @Test
    void mulliganPromptHasKeepAndMulligan() {
        PendingDecision decision = builder.build(alice, game());

        assertThat(decision.selectType()).isEqualTo(MagicSelectType.MULLIGAN);
        assertThat(decision.minCount()).isEqualTo(1);
        assertThat(decision.maxCount()).isEqualTo(1);
        assertThat(decision.options()).hasSize(2);
        assertThat(decision.options().get(0).type()).isEqualTo(MagicOptionType.PROMPT_KEEP);
        assertThat(decision.options().get(0).label()).isEqualTo("Keep");
        assertThat(decision.options().get(1).type()).isEqualTo(MagicOptionType.PROMPT_MULLIGAN);
        assertThat(decision.options().get(1).label()).isEqualTo("Mulligan");
        assertThat(decision.options().get(0).payload().get("handCount")).isEqualTo(7);
        assertThat(decision.options().get(0).payload().get("mulliganDownTo")).isEqualTo(7);
    }

    @Test
    void keepReturnsExpectedBoolean() {
        PendingDecision decision = builder.build(alice, game());

        // keep = no mulligan = false
        assertThat(applier.apply(Selection.of(0), decision)).isFalse();
    }

    @Test
    void mulliganReturnsExpectedBoolean() {
        PendingDecision decision = builder.build(alice, game());

        // true = take the mulligan
        assertThat(applier.apply(Selection.of(1), decision)).isTrue();
    }
}
