package mage.player.cabt;

import org.junit.jupiter.api.Test;

import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * Traces are replay-grade records: sequentially numbered per recorder, tied
 * to the deciding player, resolving selections to the actual options picked,
 * and carrying an error state when a selection failed validation.
 */
class CabtDecisionTraceRecorderTest {

    private final CabtDecisionTraceRecorder recorder = new CabtDecisionTraceRecorder();

    private static PendingDecision decision(UUID playerId) {
        return PendingDecision.priority(playerId);
    }

    @Test
    void tracesAreSequentiallyNumberedAndCarryThePlayer() {
        UUID playerId = UUID.randomUUID();

        CabtDecisionTrace first = recorder.recordPending("PRIORITY", decision(playerId));
        CabtDecisionTrace second = recorder.recordPending("CHOOSE_TARGET", decision(playerId));

        assertThat(first.getSequenceNumber()).isEqualTo(0);
        assertThat(second.getSequenceNumber()).isEqualTo(1);
        assertThat(first.getPlayerId()).isEqualTo(playerId);
        assertThat(first.getSelectType()).isEqualTo(MagicSelectType.PRIORITY);
    }

    @Test
    void selectedOptionsResolveTheAnsweredIndices() {
        UUID playerId = UUID.randomUUID();
        PendingDecision decision = decision(playerId);
        CabtDecisionTrace trace = recorder.recordPending("PRIORITY", decision);

        assertThat(trace.getSelectedOptions()).isEmpty();

        recorder.recordSelected(trace.getTraceId(), Selection.of(0));

        assertThat(trace.getSelectedOptions()).hasSize(1);
        assertThat(trace.getSelectedOptions().get(0).type())
                .isEqualTo(MagicOptionType.PASS_PRIORITY);

        recorder.recordApplied(trace.getTraceId());
        assertThat(trace.getStage()).isEqualTo(CabtDecisionTrace.Stage.APPLIED);
        assertThat(trace.getError()).isNull();
    }

    @Test
    void failedSelectionMovesTraceToFailedWithTheError() {
        CabtDecisionTrace trace = recorder.recordPending("PRIORITY", decision(UUID.randomUUID()));

        recorder.recordFailed(trace.getTraceId(),
                new InvalidSelectionException("OPTION_INDEX_OUT_OF_RANGE"));

        assertThat(trace.getStage()).isEqualTo(CabtDecisionTrace.Stage.FAILED);
        assertThat(trace.getError())
                .isEqualTo("InvalidSelectionException: OPTION_INDEX_OUT_OF_RANGE");
        // a failed trace cannot be applied afterwards
        assertThatThrownBy(() -> recorder.recordApplied(trace.getTraceId()))
                .isInstanceOf(IllegalStateException.class);
    }

    @Test
    void engineRejectionMovesSelectedTraceToRejected() {
        CabtDecisionTrace trace = recorder.recordPending("PRIORITY", decision(UUID.randomUUID()));
        recorder.recordSelected(trace, Selection.of(0));

        recorder.recordRejected(trace);

        assertThat(trace.getStage()).isEqualTo(CabtDecisionTrace.Stage.REJECTED);
        // the selection stays readable — the trace says what was attempted
        assertThat(trace.getSelectedOptions()).hasSize(1);
        assertThat(trace.getError()).isNull();
        // a rejected trace is final: no applied/failed afterwards
        assertThatThrownBy(() -> recorder.recordApplied(trace))
                .isInstanceOf(IllegalStateException.class);
        assertThatThrownBy(() -> recorder.recordFailed(trace, new RuntimeException("x")))
                .isInstanceOf(IllegalStateException.class);
    }

    @Test
    void rejectionRequiresASelectedTrace() {
        CabtDecisionTrace trace = recorder.recordPending("PRIORITY", decision(UUID.randomUUID()));

        // PENDING → REJECTED is not a legal transition: rejection is the
        // engine's answer to a dispatched selection
        assertThatThrownBy(() -> recorder.recordRejected(trace))
                .isInstanceOf(IllegalStateException.class);
    }

    @Test
    void invalidBridgeSelectionLeavesFailedTraceOnThePlayer() {
        CabtBridgePlayer player = new CabtBridgePlayer("CABT",
                mage.constants.RangeOfInfluence.ALL,
                new ScriptedBridgeController(
                        java.util.Collections.singletonList(Selection.of(7))));
        java.util.LinkedHashMap<UUID, mage.players.Player> players =
                new java.util.LinkedHashMap<UUID, mage.players.Player>();
        players.put(player.getId(), player);

        assertThatThrownBy(() -> player.chooseMulligan(
                StubGames.game(players, player.getId(), player.getId())))
                .isInstanceOf(InvalidSelectionException.class);

        CabtDecisionTrace trace = player.getTraceRecorder().getLastTrace();
        assertThat(trace.getStage()).isEqualTo(CabtDecisionTrace.Stage.FAILED);
        assertThat(trace.getError()).contains("OPTION_INDEX_OUT_OF_RANGE");
    }
}
