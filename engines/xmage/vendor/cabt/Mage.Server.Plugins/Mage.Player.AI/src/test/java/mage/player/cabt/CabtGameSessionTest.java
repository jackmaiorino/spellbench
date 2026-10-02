package mage.player.cabt;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * End-to-end session test on the real engine: a full protocol-style loop —
 * start → events → validated selections → game over — without any process
 * boundary. The same greedy policy as the smoke game answers each surfaced
 * event, but through the session's pull-based API instead of a controller
 * callback.
 */
@Timeout(120)
class CabtGameSessionTest {

    private CabtGameSession session;

    @AfterEach
    void tearDown() {
        if (session != null) {
            session.finish();
        }
    }

    private static List<CabtDeckFactory.Entry> forestBearsDeck() {
        return Arrays.asList(
                new CabtDeckFactory.Entry("Forest", 24),
                new CabtDeckFactory.Entry("Grizzly Bears", 36));
    }

    private static CabtGameSession.Config config() {
        return new CabtGameSession.Config()
                .playerNames("Alice", "Bob")
                .seed(20260704L)
                .maxTurns(4)
                .decisionTimeoutSeconds(60);
    }

    @Test
    void sessionRunsARealGameToTheTurnLimit() {
        session = new CabtGameSession(forestBearsDeck(), forestBearsDeck(), config());
        CabtGameSession.Event event = session.start();

        List<String> seenSelectTypes = new ArrayList<String>();
        int guard = 0;
        while (event.kind() == CabtGameSession.Event.Kind.DECISION) {
            assertThat(guard++).as("decision count stays bounded").isLessThan(2000);
            seenSelectTypes.add(event.decision().selectType().name());
            event = session.select(CabtEventPolicy.choose(event));
        }

        assertThat(event.kind()).isEqualTo(CabtGameSession.Event.Kind.GAME_OVER);
        assertThat(event.finalState()).isNotNull();
        assertThat(session.isFinished()).isTrue();
        // the real pregame and priority surfaces all appeared
        assertThat(seenSelectTypes).contains("PRIORITY", "MULLIGAN");
        // the policy played lands through real priority prompts
        assertThat(event.finalState().getBattlefield()).isNotEmpty();
    }

    @Test
    void invalidSelectionLeavesThePendingDecisionAnswerable() {
        session = new CabtGameSession(forestBearsDeck(), forestBearsDeck(), config());
        CabtGameSession.Event first = session.start();
        assertThat(first.kind()).isEqualTo(CabtGameSession.Event.Kind.DECISION);
        int optionCount = first.decision().options().size();

        assertThatThrownBy(() -> session.select(Collections.singletonList(optionCount + 5)))
                .isInstanceOf(InvalidSelectionException.class)
                .hasMessage("OPTION_INDEX_OUT_OF_RANGE");
        // the decision is still pending and still the same one
        assertThat(session.currentEvent()).isSameAs(first);

        // a valid retry advances the game
        CabtGameSession.Event next = session.select(CabtEventPolicy.choose(first));
        assertThat(next).isNotSameAs(first);
    }

    @Test
    void selectAfterTimeoutDoesNotReuseStaleDecision() {
        // Use a very short timeout so the engine can exceed it at least once
        // during pre-game setup (mulligan → first priority). If the engine
        // happens to be fast enough to never time out, the test still proves
        // the success-path invariant: after select(), currentEvent is the new
        // event, not the stale answered one.
        CabtGameSession shortSession = new CabtGameSession(forestBearsDeck(),
                forestBearsDeck(),
                new CabtGameSession.Config()
                        .playerNames("Alice", "Bob")
                        .seed(20260704L)
                        .maxTurns(4)
                        .decisionTimeoutSeconds(1));
        CabtGameSession.Event first = shortSession.start();
        assertThat(first.kind()).isEqualTo(CabtGameSession.Event.Kind.DECISION);

        try {
            shortSession.select(CabtEventPolicy.choose(first));
            // no timeout: the next event arrived, the old decision is gone
            assertThat(shortSession.currentEvent()).isNotSameAs(first);
        } catch (IllegalStateException e) {
            // timeout occurred: the session must be closed and the stale
            // decision must not be answerable
            assertThat(e.getMessage()).contains("ENGINE_TIMEOUT");
            assertThat(shortSession.currentEvent())
                    .as("currentEvent must be null after timeout")
                    .isNull();
            assertThatThrownBy(() -> shortSession.select(CabtEventPolicy.choose(first)))
                    .isInstanceOf(IllegalStateException.class)
                    .hasMessageContaining("NO_PENDING_DECISION");
        } finally {
            shortSession.finish();
        }
    }

    @Test
    void unknownCardNameFailsDeckConstructionLoudly() {
        List<CabtDeckFactory.Entry> badDeck = Collections.singletonList(
                new CabtDeckFactory.Entry("No Such Card Ever Printed", 60));
        assertThatThrownBy(() -> new CabtGameSession(badDeck, forestBearsDeck(), config()))
                .isInstanceOf(CabtDeckFactory.UnknownCardException.class)
                .hasMessageContaining("No Such Card Ever Printed");
    }
}
