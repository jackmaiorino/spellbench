package mage.player.cabt;

import mage.constants.RangeOfInfluence;
import mage.game.Game;
import org.junit.jupiter.api.Test;

import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.util.Collections;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * Copy semantics and the simulation guard. XMage's bookmark/rollback restores
 * player copies into the live game, so a copy must keep the live bridge and
 * the live trace history (sharing is required, not an accident). The flip
 * side — a simulation or playable-calc game reaching a live bridge prompt —
 * fails closed instead of consuming an agent decision.
 */
class CabtBridgePlayerCopyAndSimulationTest {

    private static Game gameFlagged(final boolean simulation, final boolean checkPlayable) {
        InvocationHandler handler = new InvocationHandler() {
            @Override
            public Object invoke(Object proxy, Method method, Object[] args) {
                if (method.getName().equals("isSimulation")) {
                    return simulation;
                }
                if (method.getName().equals("inCheckPlayableState")) {
                    return checkPlayable;
                }
                Class<?> returnType = method.getReturnType();
                if (returnType == boolean.class) {
                    return false;
                }
                if (returnType.isPrimitive() && returnType != void.class) {
                    return 0;
                }
                return null;
            }
        };
        return (Game) Proxy.newProxyInstance(
                Game.class.getClassLoader(), new Class<?>[]{Game.class}, handler);
    }

    @Test
    void copySharesLiveBridgeAndTraceHistoryForRollback() {
        CabtBridgePlayer player = new CabtBridgePlayer("CABT", RangeOfInfluence.ALL,
                new ScriptedBridgeController(Collections.singletonList(Selection.of(0))));

        CabtBridgePlayer copy = player.copy();

        // a restored copy must keep writing into the same decision history
        assertThat(copy.getTraceRecorder()).isSameAs(player.getTraceRecorder());
        // and stays a bridge player, never a plain ComputerPlayer
        assertThat(copy).isInstanceOf(CabtBridgePlayer.class);
    }

    @Test
    void simulationGamePromptFailsClosed() {
        CabtBridgePlayer player = new CabtBridgePlayer("CABT", RangeOfInfluence.ALL,
                new ScriptedBridgeController(Collections.singletonList(Selection.of(0))));

        assertThatThrownBy(() -> player.chooseMulligan(gameFlagged(true, false)))
                .isInstanceOf(CabtUnhandledDecisionException.class)
                .hasMessageContaining("simulation");
        // nothing was traced and no scripted selection was consumed
        assertThat(player.getTraceRecorder().getTraces()).isEmpty();
    }

    @Test
    void priorityFailsClosedBeforeEnumeratingPlayables() {
        CabtBridgePlayer player = new CabtBridgePlayer("CABT", RangeOfInfluence.ALL,
                new ScriptedBridgeController(Collections.singletonList(Selection.of(0))));

        // the guard sits at the top of priority(), before getPlayable — a
        // simulation game must not even reach playable enumeration
        assertThatThrownBy(() -> player.priority(gameFlagged(true, false)))
                .isInstanceOf(CabtUnhandledDecisionException.class)
                .hasMessageContaining("simulation");
        assertThat(player.getTraceRecorder().getTraces()).isEmpty();

        assertThatThrownBy(() -> player.priority(gameFlagged(false, true)))
                .isInstanceOf(CabtUnhandledDecisionException.class)
                .hasMessageContaining("playable-check");
        assertThat(player.getTraceRecorder().getTraces()).isEmpty();
    }

    @Test
    void playableCheckGamePromptFailsClosed() {
        CabtBridgePlayer player = new CabtBridgePlayer("CABT", RangeOfInfluence.ALL,
                new ScriptedBridgeController(Collections.singletonList(Selection.of(0))));

        assertThatThrownBy(() -> player.chooseMulligan(gameFlagged(false, true)))
                .isInstanceOf(CabtUnhandledDecisionException.class)
                .hasMessageContaining("playable-check");
    }
}
