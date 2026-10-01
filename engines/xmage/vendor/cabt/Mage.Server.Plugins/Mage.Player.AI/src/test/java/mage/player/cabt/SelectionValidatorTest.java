package mage.player.cabt;

import org.junit.jupiter.api.Test;

import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * CABT-style selection validation: count within min/max, indices in range, no duplicates.
 */
class SelectionValidatorTest {

    private PendingDecision priorityDecision() {
        return PendingDecision.priority(UUID.randomUUID());
    }

    /**
     * A two-option prompt that allows picking both, so the duplicate check
     * (not the count check) is what a [0, 0] selection violates.
     */
    private PendingDecision twoOptionMultiSelectDecision() {
        PendingDecision decision = new PendingDecision(MagicSelectType.PRIORITY, UUID.randomUUID(), 1, 2);
        decision.addOption(MagicOptionFactory.passPriority());
        decision.addOption(MagicOptionFactory.passPriority());
        return decision;
    }

    @Test
    void acceptsSinglePassSelection() {
        assertThatCode(() -> SelectionValidator.validate(priorityDecision(), Selection.of(0)))
                .doesNotThrowAnyException();
    }

    @Test
    void rejectsEmptySelection() {
        assertThatThrownBy(() -> SelectionValidator.validate(priorityDecision(), Selection.of()))
                .isInstanceOf(InvalidSelectionException.class)
                .hasMessage("INVALID_SELECTION_COUNT");
    }

    @Test
    void rejectsTooManySelections() {
        // count is checked before duplicates, so a max-1 prompt reports the count error
        assertThatThrownBy(() -> SelectionValidator.validate(priorityDecision(), Selection.of(0, 0)))
                .isInstanceOf(InvalidSelectionException.class)
                .hasMessage("INVALID_SELECTION_COUNT");
    }

    @Test
    void rejectsDuplicateIndices() {
        assertThatThrownBy(() -> SelectionValidator.validate(twoOptionMultiSelectDecision(), Selection.of(0, 0)))
                .isInstanceOf(InvalidSelectionException.class)
                .hasMessage("DUPLICATE_SELECTION");
    }

    @Test
    void rejectsNegativeIndex() {
        assertThatThrownBy(() -> SelectionValidator.validate(priorityDecision(), Selection.of(-1)))
                .isInstanceOf(InvalidSelectionException.class)
                .hasMessage("OPTION_INDEX_OUT_OF_RANGE");
    }

    @Test
    void rejectsOutOfRangeIndex() {
        assertThatThrownBy(() -> SelectionValidator.validate(priorityDecision(), Selection.of(1)))
                .isInstanceOf(InvalidSelectionException.class)
                .hasMessage("OPTION_INDEX_OUT_OF_RANGE");
    }
}
