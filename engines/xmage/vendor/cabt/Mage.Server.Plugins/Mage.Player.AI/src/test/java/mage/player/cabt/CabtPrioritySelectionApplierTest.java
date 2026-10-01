package mage.player.cabt;

import mage.abilities.ActivatedAbility;
import mage.abilities.PlayLandAbility;
import mage.constants.RangeOfInfluence;
import mage.game.Game;
import mage.players.Player;
import org.junit.jupiter.api.Test;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * PASS_PRIORITY passes and reports PASSED; a playable option must carry the
 * playableIndex that links it back to the live ability, and the engine's
 * activateAbility answer is reported (APPLIED/REJECTED), never assumed. The
 * successful dispatch path (activateAbility actually performing the action)
 * is covered by the real-engine smoke tests — stub games cannot host it
 * honestly, but they do host the engine's own rejection path (playLand on a
 * card the game cannot resolve returns false).
 */
class CabtPrioritySelectionApplierTest {

    private final CabtPriorityPromptBuilder builder = new CabtPriorityPromptBuilder();
    private final CabtPrioritySelectionApplier applier = new CabtPrioritySelectionApplier();

    private CabtBridgePlayer player;
    private Game game;

    private void setUp() {
        player = new CabtBridgePlayer("CABT", RangeOfInfluence.ALL,
                new ScriptedBridgeController(Collections.<Selection>emptyList()));
        LinkedHashMap<UUID, Player> players = new LinkedHashMap<UUID, Player>();
        players.put(player.getId(), player);
        game = StubGames.game(players, player.getId(), player.getId());
    }

    @Test
    void passOptionPassesAndReportsNoAction() {
        setUp();
        CabtPriorityPrompt prompt = builder.build(
                player, game, Collections.<ActivatedAbility>emptyList());

        CabtPrioritySelectionApplier.Result result =
                applier.apply(player, game, Selection.of(0), prompt);

        assertThat(result).isEqualTo(CabtPrioritySelectionApplier.Result.PASSED);
        assertThat(player.isPassed()).isTrue();
    }

    @Test
    void engineDecliningActivationReportsRejectedNotApplied() {
        setUp();
        // a real PlayLandAbility whose source card the stub game cannot
        // resolve: PlayerImpl.playLand answers false — the engine's own
        // rejection path, not a bridge error
        PlayLandAbility playLand = new PlayLandAbility("Forest");
        playLand.setSourceId(UUID.randomUUID());
        CabtPriorityPrompt prompt = builder.build(
                player, game, Collections.<ActivatedAbility>singletonList(playLand));

        CabtPrioritySelectionApplier.Result result =
                applier.apply(player, game, Selection.of(1), prompt);

        assertThat(result).isEqualTo(CabtPrioritySelectionApplier.Result.REJECTED);
        assertThat(player.isPassed()).isFalse();
    }

    @Test
    void playableOptionWithoutIndexPayloadFailsLoudly() {
        setUp();
        PendingDecision decision = PendingDecision.priority(player.getId());
        decision.addOption(new MagicOption(MagicOptionType.PLAY_LAND, "Play Forest",
                Collections.<String, Object>emptyMap()));
        CabtPriorityPrompt prompt = new CabtPriorityPrompt(
                decision, Collections.<ActivatedAbility>emptyList());

        assertThatThrownBy(() -> applier.apply(player, game, Selection.of(1), prompt))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("playableIndex");
        assertThat(player.isPassed()).isFalse();
    }

    @Test
    void staleIndexOutsidePromptFailsLoudly() {
        setUp();
        PendingDecision decision = PendingDecision.priority(player.getId());
        LinkedHashMap<String, Object> payload = new LinkedHashMap<String, Object>();
        payload.put("playableIndex", 0);
        decision.addOption(new MagicOption(MagicOptionType.PLAY_LAND, "Play Forest", payload));
        CabtPriorityPrompt prompt = new CabtPriorityPrompt(
                decision, Collections.<ActivatedAbility>emptyList());

        assertThatThrownBy(() -> applier.apply(player, game, Selection.of(1), prompt))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("playableIndex 0 outside");
    }
}
