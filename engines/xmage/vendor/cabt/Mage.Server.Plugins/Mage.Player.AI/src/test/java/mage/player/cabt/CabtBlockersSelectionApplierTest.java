package mage.player.cabt;

import mage.game.combat.CombatGroup;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Task 15: selected blocks are committed through the engine's own
 * Player.declareBlocker(...) into the attacker's combat group.
 */
class CabtBlockersSelectionApplierTest {

    private final CabtBlockersPromptBuilder builder = new CabtBlockersPromptBuilder();
    private final CabtBlockersSelectionApplier applier = new CabtBlockersSelectionApplier();

    @Test
    void selectedBlockerIsDeclared() {
        CabtBlockersPromptBuilderTest fixture = new CabtBlockersPromptBuilderTest();
        fixture.setUpBlockGame();
        PendingDecision decision = builder.build(
                fixture.defender, fixture.game, fixture.defender.getId());

        applier.apply(fixture.defender, fixture.game, Selection.of(0), decision);

        CombatGroup group = fixture.game.getCombat().findGroup(fixture.bearsId);
        assertThat(group).isNotNull();
        assertThat(group.getBlockers()).contains(fixture.giantId);
    }

    @Test
    void emptyBlockSelectionDeclaresNoBlocks() {
        CabtBlockersPromptBuilderTest fixture = new CabtBlockersPromptBuilderTest();
        fixture.setUpBlockGame();
        PendingDecision decision = builder.build(
                fixture.defender, fixture.game, fixture.defender.getId());

        applier.apply(fixture.defender, fixture.game,
                new Selection(new ArrayList<Integer>()), decision);

        CombatGroup group = fixture.game.getCombat().findGroup(fixture.bearsId);
        assertThat(group.getBlockers()).isEmpty();
    }
}
