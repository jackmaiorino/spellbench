package mage.player.cabt;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import mage.cards.Sets;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

/**
 * Production-path regression: a fresh {@link CabtProtocolServer} — the exact
 * object a subprocess constructs — must resolve a repository-only name through
 * {@code resolve_card} <b>without this test scanning the card database first</b>.
 * The resolver owns that precondition (its default repository lookup scans on
 * the first query); if it didn't, {@code Boseiju, Who Endures} would fall
 * through to the class-name heuristic (resolved, but {@code CLASS_HEURISTIC}
 * with no printing) instead of the repository ({@code EXACT} with a set code),
 * which is exactly what the strategy/set assertions below catch.
 * <p>
 * Deliberately no {@code CardScanner.scan()} here and no {@code @BeforeAll} —
 * the whole point is to prove the server needs no external priming. The guard
 * uses {@link Sets#getInstance()} (the set registry, which does not build the
 * card database) so the test skips only when there are no set classes on the
 * classpath at all.
 */
class CardResolverProductionScanTest {

    @Test
    void freshServerResolvesRepositoryOnlyNameWithoutAnExternalScan() {
        assumeTrue(!Sets.getInstance().isEmpty(),
                "no XMage set classes on the classpath in this environment");

        CabtProtocolServer server = new CabtProtocolServer();
        JsonObject response = JsonParser.parseString(server.handleLine(
                "{\"command\": \"resolve_card\", \"name\": \"Boseiju, Who Endures\"}"))
                .getAsJsonObject();

        assertThat(response.get("ok").getAsBoolean()).isTrue();
        JsonObject resolution = response.getAsJsonObject("resolution");
        assertThat(resolution.get("resolved").getAsBoolean())
                .as("fresh server resolves a repository-only name")
                .isTrue();
        assertThat(resolution.get("canonicalName").getAsString())
                .isEqualTo("Boseiju, Who Endures");
        // the tell that it came from the repository, not the heuristic fallback
        assertThat(resolution.get("strategy").getAsString()).isEqualTo("EXACT");
        assertThat(resolution.get("setCode").isJsonNull())
                .as("repository resolution carries a printing")
                .isFalse();
    }
}
