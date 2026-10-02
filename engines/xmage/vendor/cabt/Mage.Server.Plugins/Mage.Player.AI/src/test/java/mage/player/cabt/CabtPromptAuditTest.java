package mage.player.cabt;

import mage.constants.Outcome;
import mage.constants.RangeOfInfluence;
import mage.game.Game;
import mage.players.Player;
import mage.target.common.TargetAnyTargetAmount;
import org.junit.jupiter.api.Test;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * Task 23: the prompt audit enforces implementation coverage. Every SURFACED
 * or DELEGATED entry must name an implementation class and a test class that
 * resolve on the classpath, FAIL_CLOSED callbacks must actually throw
 * {@link CabtUnhandledDecisionException} from the bridge, and REFERENCE_ONLY
 * entries must be query/design references, never active Player callbacks.
 * <p>
 * This is the maintainability gate: a newly discovered XMage callback or
 * prompt family can only be added as audit entry + implementation + tests,
 * and a surfaced prompt that loses its coverage fails the suite here.
 */
class CabtPromptAuditTest {

    @Test
    void allSurfacedPromptsHaveTests() {
        assertThat(CabtPromptAudit.byStatus(CabtDecisionSurfaceStatus.SURFACED)).isNotEmpty();
        for (CabtDecisionSurface entry : CabtPromptAudit.byStatus(CabtDecisionSurfaceStatus.SURFACED)) {
            assertThat(entry.getTestClass())
                    .as("test class of surfaced prompt %s", entry.getName())
                    .isNotEmpty();
            assertThat(CabtPromptAudit.classExists(entry.getTestClass()))
                    .as("test class %s of %s exists on the classpath",
                            entry.getTestClass(), entry.getName())
                    .isTrue();
            assertThat(CabtPromptAudit.classExists(entry.getImplementationClass()))
                    .as("implementation class %s of %s exists on the classpath",
                            entry.getImplementationClass(), entry.getName())
                    .isTrue();
        }
        // commit APIs invoked from surfaced prompts are held to the same bar
        for (CabtDecisionSurface entry : CabtPromptAudit.byStatus(CabtDecisionSurfaceStatus.DELEGATED)) {
            assertThat(CabtPromptAudit.classExists(entry.getImplementationClass()))
                    .as("implementation class of delegated surface %s", entry.getName())
                    .isTrue();
            assertThat(CabtPromptAudit.classExists(entry.getTestClass()))
                    .as("test class of delegated surface %s", entry.getName())
                    .isTrue();
        }
    }

    @Test
    void failClosedPromptsThrowCabtUnhandledDecisionException() {
        // every FAIL_CLOSED entry points at a resolvable test
        for (CabtDecisionSurface entry : CabtPromptAudit.byStatus(CabtDecisionSurfaceStatus.FAIL_CLOSED)) {
            assertThat(CabtPromptAudit.classExists(entry.getTestClass()))
                    .as("test class of fail-closed surface %s", entry.getName())
                    .isTrue();
        }

        // and the bridge really does fail closed instead of letting the
        // inherited ComputerPlayer silently decide
        ScriptedBridgeController scripted = new ScriptedBridgeController(
                Collections.<Selection>emptyList());
        CabtBridgePlayer player = new CabtBridgePlayer("CABT", RangeOfInfluence.ALL, scripted);
        LinkedHashMap<UUID, Player> players = new LinkedHashMap<UUID, Player>();
        players.put(player.getId(), player);
        Game game = StubGames.game(players, player.getId(), player.getId());

        assertThatThrownBy(() -> player.chooseTargetAmount(
                Outcome.Damage, new TargetAnyTargetAmount(3), StubGames.ability(), game))
                .isInstanceOf(CabtUnhandledDecisionException.class)
                .hasMessageContaining("chooseTargetAmount");
    }

    @Test
    void referenceOnlyEntriesAreNotCallbacks() {
        assertThat(CabtPromptAudit.byStatus(CabtDecisionSurfaceStatus.REFERENCE_ONLY)).isNotEmpty();
        for (CabtDecisionSurface entry : CabtPromptAudit.byStatus(CabtDecisionSurfaceStatus.REFERENCE_ONLY)) {
            assertThat(entry.getImplementationClass())
                    .as("reference entry %s must not claim an implementation", entry.getName())
                    .isEmpty();
            String name = entry.getName();
            assertThat(name.startsWith("getPlayable")
                    || name.startsWith("getAvailable")
                    || name.startsWith("GameSessionPlayer.")
                    || name.startsWith("Arena"))
                    .as("reference entry %s is a playable/available query, client mirror, "
                            + "or replay note — not an active Player callback", name)
                    .isTrue();
        }
        // and no active Player callback hides among the references
        for (CabtDecisionSurface entry : CabtPromptAudit.playerCallbackEntries()) {
            assertThat(entry.getStatus()).isNotEqualTo(CabtDecisionSurfaceStatus.REFERENCE_ONLY);
        }
    }
}
