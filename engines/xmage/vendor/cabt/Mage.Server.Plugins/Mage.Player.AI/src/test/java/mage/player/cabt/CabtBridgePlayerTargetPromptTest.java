package mage.player.cabt;

import mage.cards.Card;
import mage.constants.Outcome;
import mage.constants.RangeOfInfluence;
import mage.game.Game;
import mage.game.permanent.Battlefield;
import mage.game.stack.SpellStack;
import mage.players.Player;
import org.junit.jupiter.api.Test;

import java.io.Serializable;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Task 7: the bridge player surfaces XMage's chooseTarget callback as a
 * TARGET prompt, applies the scripted answer through Target.addTarget, and
 * traces PENDING → SELECTED → APPLIED.
 * <p>
 * This exercises the spec's integration shape at the Player-callback
 * boundary — the same call XMage's cast flow makes when a targeted spell
 * needs its target — with real TargetImpl/Battlefield state. Running an
 * actual cast requires the full engine loop, which this module's tests do
 * not boot.
 */
class CabtBridgePlayerTargetPromptTest {

    @Test
    void targetedSpellPromptsForTarget() {
        ScriptedBridgeController scripted = new ScriptedBridgeController(
                Collections.singletonList(Selection.of(0)));
        RecordingBridgeController recording = new RecordingBridgeController(
                scripted, new MagicObservationSerializer());
        CabtBridgePlayer player = new CabtBridgePlayer("CABT", RangeOfInfluence.ALL, recording);

        UUID bearsId = UUID.randomUUID();
        Battlefield battlefield = new Battlefield();
        battlefield.addPermanent(StubGames.permanent(
                bearsId, "Grizzly Bears", player.getId(), player.getId(), false, 2, 2));
        Game game = gameWith(player, battlefield);
        StubTarget target = new StubTarget(1, 1, Collections.singletonList(bearsId));

        // XMage calls this exact callback while casting a targeted spell
        boolean result = player.chooseTarget(Outcome.Damage, target, StubGames.ability(), game);

        // spell casting can continue: the target is chosen
        assertThat(result).isTrue();
        assertThat(target.getTargets()).containsExactly(bearsId);

        // the prompt was surfaced and observed as a TARGET select
        MagicObservation observation = recording.getLastObservation();
        assertThat(observation).isNotNull();
        assertThat(observation.getSelect().getType()).isEqualTo("TARGET");
        assertThat(observation.getSelect().getOption()).hasSize(1);
        MagicOptionView option = observation.getSelect().getOption().get(0);
        assertThat(option.getType()).isEqualTo("PROMPT_OBJECT");
        assertThat(option.getLabel()).isEqualTo("Target Grizzly Bears");
        assertThat(option.getPayload().get("targetId")).isEqualTo(bearsId.toString());

        // the decision is traced through its full lifecycle
        assertThat(player.getTraceRecorder().getTraces()).hasSize(1);
        CabtDecisionTrace trace = player.getTraceRecorder().getLastTrace();
        assertThat(trace.getSelectType()).isEqualTo(MagicSelectType.TARGET);
        assertThat(trace.getStage()).isEqualTo(CabtDecisionTrace.Stage.APPLIED);
        assertThat(trace.getSelection().indices()).containsExactly(0);
    }

    @Test
    void optionalTargetAcceptsEmptySelectionAndRecordsTrace() {
        ScriptedBridgeController scripted = new ScriptedBridgeController(
                Collections.singletonList(new Selection(new ArrayList<Integer>())));
        RecordingBridgeController recording = new RecordingBridgeController(
                scripted, new MagicObservationSerializer());
        CabtBridgePlayer player = new CabtBridgePlayer("CABT", RangeOfInfluence.ALL, recording);

        UUID bearsId = UUID.randomUUID();
        Battlefield battlefield = new Battlefield();
        battlefield.addPermanent(StubGames.permanent(
                bearsId, "Grizzly Bears", player.getId(), player.getId(), false, 2, 2));
        Game game = gameWith(player, battlefield);
        StubTarget target = new StubTarget(0, 1, Collections.singletonList(bearsId));

        boolean result = player.choose(Outcome.Damage, target, StubGames.ability(), game);

        assertThat(result).isFalse();
        assertThat(target.getTargets()).isEmpty();
        CabtDecisionTrace trace = player.getTraceRecorder().getLastTrace();
        assertThat(trace).isNotNull();
        // SELECTED was recorded (the empty selection) before APPLY finished
        assertThat(trace.getSelection()).isNotNull();
        assertThat(trace.getSelection().indices()).isEmpty();
        assertThat(trace.getStage()).isEqualTo(CabtDecisionTrace.Stage.APPLIED);
    }

    @Test
    void mapOverloadDelegatesToSurfacedTargetPrompt() {
        ScriptedBridgeController scripted = new ScriptedBridgeController(
                Collections.singletonList(Selection.of(0)));
        RecordingBridgeController recording = new RecordingBridgeController(
                scripted, new MagicObservationSerializer());
        CabtBridgePlayer player = new CabtBridgePlayer("CABT", RangeOfInfluence.ALL, recording);

        UUID bearsId = UUID.randomUUID();
        Battlefield battlefield = new Battlefield();
        battlefield.addPermanent(StubGames.permanent(
                bearsId, "Grizzly Bears", player.getId(), player.getId(), false, 2, 2));
        Game game = gameWith(player, battlefield);
        StubTarget target = new StubTarget(1, 1, Collections.singletonList(bearsId));

        // the options map carries UI hints only; the decision space is the
        // same TARGET prompt as the four-argument choose
        boolean result = player.choose(Outcome.Damage, target, StubGames.ability(), game,
                new HashMap<String, Serializable>());

        assertThat(result).isTrue();
        assertThat(target.getTargets()).containsExactly(bearsId);
        assertThat(recording.getLastObservation().getSelect().getType()).isEqualTo("TARGET");
    }

    @Test
    void applierFailureRecordsFailedTraceNotSelected() {
        ScriptedBridgeController scripted = new ScriptedBridgeController(
                Collections.singletonList(Selection.of(0)));
        CabtBridgePlayer player = new CabtBridgePlayer("CABT", RangeOfInfluence.ALL, scripted);

        UUID bearsId = UUID.randomUUID();
        Battlefield battlefield = new Battlefield();
        battlefield.addPermanent(StubGames.permanent(
                bearsId, "Grizzly Bears", player.getId(), player.getId(), false, 2, 2));
        Game game = gameWith(player, battlefield);
        // the selection is valid, but the engine-side apply blows up — the
        // trace must end FAILED (with the error), not strand at SELECTED
        StubTarget target = new StubTarget(1, 1, Collections.singletonList(bearsId)) {
            @Override
            public void addTarget(UUID id, mage.abilities.Ability source, Game aGame) {
                throw new IllegalStateException("apply phase exploded");
            }
        };

        org.assertj.core.api.Assertions.assertThatThrownBy(
                () -> player.chooseTarget(Outcome.Damage, target, StubGames.ability(), game))
                .isInstanceOf(IllegalStateException.class)
                .hasMessage("apply phase exploded");

        CabtDecisionTrace trace = player.getTraceRecorder().getLastTrace();
        assertThat(trace.getStage()).isEqualTo(CabtDecisionTrace.Stage.FAILED);
        assertThat(trace.getSelection().indices()).containsExactly(0);
        assertThat(trace.getError()).contains("apply phase exploded");
    }

    @Test
    void noPossibleTargetsMeansNoPromptAndNoTrace() {
        ScriptedBridgeController scripted = new ScriptedBridgeController(
                Collections.<Selection>emptyList());
        RecordingBridgeController recording = new RecordingBridgeController(
                scripted, new MagicObservationSerializer());
        CabtBridgePlayer player = new CabtBridgePlayer("CABT", RangeOfInfluence.ALL, recording);
        Game game = gameWith(player, null);
        StubTarget target = new StubTarget(1, 1, Collections.<UUID>emptyList());

        boolean result = player.chooseTarget(Outcome.Damage, target, StubGames.ability(), game);

        assertThat(result).isFalse();
        assertThat(player.getTraceRecorder().getTraces()).isEmpty();
        assertThat(recording.getObservations()).isEmpty();
    }

    private static Game gameWith(CabtBridgePlayer player, Battlefield battlefield) {
        LinkedHashMap<UUID, Player> players = new LinkedHashMap<UUID, Player>();
        players.put(player.getId(), player);
        return StubGames.game(players, player.getId(), player.getId(),
                battlefield, new SpellStack(), new LinkedHashMap<UUID, Card>());
    }
}
