package mage.player.cabt;

import mage.MageObject;
import mage.players.Player;
import org.junit.jupiter.api.Test;

import java.util.LinkedHashMap;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Task 12: REPLACEMENT_EFFECT prompts preserve the effectsMap iteration
 * order (the index XMage expects back) and carry object context from the
 * objectsMap when available.
 */
class CabtReplacementEffectPromptTest {

    private final CabtReplacementEffectPromptBuilder builder = new CabtReplacementEffectPromptBuilder();
    private final CabtReplacementEffectSelectionApplier applier = new CabtReplacementEffectSelectionApplier();

    private final UUID aliceId = UUID.randomUUID();
    private final Player alice = StubGames.player(aliceId, "Alice", 20, 7);

    private static LinkedHashMap<String, String> threeEffects() {
        LinkedHashMap<String, String> effects = new LinkedHashMap<String, String>();
        effects.put("effect-a", "If a creature would die, exile it instead");
        effects.put("effect-b", "If you would draw a card, draw two instead");
        effects.put("effect-c", "Prevent all combat damage");
        return effects;
    }

    @Test
    void replacementPromptPreservesEffectOrder() {
        PendingDecision decision = builder.build(alice, threeEffects(),
                new LinkedHashMap<String, MageObject>());

        assertThat(decision.selectType()).isEqualTo(MagicSelectType.REPLACEMENT_EFFECT);
        assertThat(decision.options()).hasSize(3);
        for (int i = 0; i < 3; i++) {
            MagicOption option = decision.options().get(i);
            assertThat(option.type()).isEqualTo(MagicOptionType.PROMPT_REPLACEMENT_EFFECT);
            assertThat(option.payload().get("originalIndex")).isEqualTo(i);
            assertThat(option.label()).startsWith("Choose replacement effect: ");
        }
        assertThat(decision.options().get(0).payload().get("effectKey")).isEqualTo("effect-a");
        assertThat(decision.options().get(1).payload().get("effectKey")).isEqualTo("effect-b");
        assertThat(decision.options().get(2).payload().get("effectKey")).isEqualTo("effect-c");
    }

    @Test
    void replacementSelectionReturnsOriginalIndex() {
        PendingDecision decision = builder.build(alice, threeEffects(),
                new LinkedHashMap<String, MageObject>());

        int result = applier.apply(Selection.of(2), decision);

        assertThat(result).isEqualTo(2);
    }

    @Test
    void replacementOptionIncludesObjectContext() {
        UUID sourceId = UUID.randomUUID();
        LinkedHashMap<String, MageObject> objects = new LinkedHashMap<String, MageObject>();
        objects.put("effect-b", StubGames.card(sourceId, "Thought Reflection", aliceId));

        PendingDecision decision = builder.build(alice, threeEffects(), objects);

        MagicOption withObject = decision.options().get(1);
        assertThat(withObject.payload().get("objectId")).isEqualTo(sourceId.toString());
        assertThat(withObject.payload().get("objectName")).isEqualTo("Thought Reflection");
        // entries without an object stay null-safe
        assertThat(decision.options().get(0).payload().get("objectId")).isNull();
        assertThat(decision.options().get(0).payload().get("objectName")).isNull();
    }
}
