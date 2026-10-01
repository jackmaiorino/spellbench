package mage.player.cabt;

import mage.constants.MultiAmountType;
import mage.constants.Outcome;
import mage.constants.RangeOfInfluence;
import mage.game.Game;
import mage.players.Player;
import mage.util.MultiAmountMessage;
import org.junit.jupiter.api.Test;

import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Task 10: multi-amount prompts enumerate every valid assignment for small
 * totals and return the selected assignment exactly.
 */
class CabtMultiAmountPromptTest {

    private RecordingBridgeController recording;
    private CabtBridgePlayer player;
    private Game game;

    private void setUpPlayer(Selection scripted) {
        recording = new RecordingBridgeController(
                new ScriptedBridgeController(Collections.singletonList(scripted)),
                new MagicObservationSerializer());
        player = new CabtBridgePlayer("CABT", RangeOfInfluence.ALL, recording);
        LinkedHashMap<UUID, Player> players = new LinkedHashMap<UUID, Player>();
        players.put(player.getId(), player);
        game = StubGames.game(players, player.getId(), player.getId());
    }

    private static List<MultiAmountMessage> twoBuckets() {
        return Arrays.asList(
                new MultiAmountMessage("first target", 0, 2),
                new MultiAmountMessage("second target", 0, 2));
    }

    @Test
    void builderEnumeratesValidAssignments() {
        setUpPlayer(Selection.of(0));

        PendingDecision decision = new CabtMultiAmountPromptBuilder()
                .build(player, twoBuckets(), 2, 2);

        // total exactly 2 over two 0..2 buckets: [0,2], [1,1], [2,0]
        assertThat(decision.selectType()).isEqualTo(MagicSelectType.MULTI_AMOUNT);
        assertThat(decision.options()).hasSize(3);
        assertThat(decision.options().get(0).label()).isEqualTo("[0, 2]");
        assertThat(decision.options().get(1).label()).isEqualTo("[1, 1]");
        assertThat(decision.options().get(2).label()).isEqualTo("[2, 0]");
        assertThat(decision.options().get(1).payload().get("assignment"))
                .isEqualTo(Arrays.asList(1, 1));
    }

    @Test
    void multiAmountReturnsSelectedAssignment() {
        setUpPlayer(Selection.of(1));

        List<Integer> assignment = player.getMultiAmountWithIndividualConstraints(
                Outcome.Benefit, twoBuckets(), 2, 2, MultiAmountType.DAMAGE, game);

        assertThat(assignment).containsExactly(1, 1);
        MagicSelectView select = recording.getLastObservation().getSelect();
        assertThat(select.getType()).isEqualTo("MULTI_AMOUNT");
        assertThat(select.getOption()).hasSize(3);
        assertThat(select.getOption().get(1).getType()).isEqualTo("PROMPT_AMOUNT_ASSIGNMENT");

        CabtDecisionTrace trace = player.getTraceRecorder().getLastTrace();
        assertThat(trace.getMethod()).isEqualTo("GET_MULTI_AMOUNT");
        assertThat(trace.getStage()).isEqualTo(CabtDecisionTrace.Stage.APPLIED);
    }

    @Test
    void perBucketConstraintsAreHonored() {
        setUpPlayer(Selection.of(0));

        // second bucket capped at 1: [2,0] and [1,1] remain, [0,2] is illegal
        List<MultiAmountMessage> buckets = Arrays.asList(
                new MultiAmountMessage("first", 0, 2),
                new MultiAmountMessage("second", 0, 1));
        PendingDecision decision = new CabtMultiAmountPromptBuilder()
                .build(player, buckets, 2, 2);

        assertThat(decision.options()).hasSize(2);
        assertThat(decision.options().get(0).label()).isEqualTo("[1, 1]");
        assertThat(decision.options().get(1).label()).isEqualTo("[2, 0]");
    }
}
