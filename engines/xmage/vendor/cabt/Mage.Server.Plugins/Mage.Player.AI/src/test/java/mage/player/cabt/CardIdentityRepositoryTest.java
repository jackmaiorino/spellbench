package mage.player.cabt;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import mage.cards.repository.CardRepository;
import mage.cards.repository.CardScanner;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

/**
 * Repository-backed regression tests for the card identity layer, run against
 * XMage's real scanned card database. Covers the resolver directly and the
 * {@code resolve_card} / {@code validate_deck} / {@code repository_card_data}
 * protocol commands (all of which work without an active game), and
 * regenerates the cross-language fixtures the Python tests parse.
 * <p>
 * Scanning the card database requires the XMage set classes on the runtime
 * classpath; when they are absent (a bare Python-only or partial checkout) the
 * database stays empty and every test here is skipped via an assumption,
 * exactly like the Python live tests skip without a built bridge.
 */
class CardIdentityRepositoryTest {

    /** A realistic decklist spanning the resolver's regression cases. */
    private static final String[] REALISTIC_DECK_NAMES = {
        "Forest",                 // basic land, simple name
        "Lightning Bolt",         // simple spell
        "Llanowar Elves",         // simple creature
        "Boseiju, Who Endures",   // punctuation (comma) in the printed name
        "Fire // Ice",            // split card (two-name form)
    };

    private static boolean databaseAvailable;

    @BeforeAll
    static void scanCardDatabase() {
        CardScanner.scan();
        databaseAvailable = CardRepository.instance.findCard("Forest") != null;
    }

    private void requireDatabase() {
        assumeTrue(databaseAvailable, "XMage card database is not scanned in this environment");
    }

    private static CabtProtocolServer server() {
        return new CabtProtocolServer();
    }

    private static JsonObject handle(CabtProtocolServer server, String line) {
        return JsonParser.parseString(server.handleLine(line)).getAsJsonObject();
    }

    // --- resolver, directly ---

    @Test
    void resolvesEveryEntryOfARealisticDecklist() {
        requireDatabase();
        CardResolver resolver = new CardResolver();

        for (String name : REALISTIC_DECK_NAMES) {
            CardResolution resolution = resolver.resolve(name);
            assertThat(resolution.isResolved())
                    .as("resolves \"" + name + "\"")
                    .isTrue();
            assertThat(resolution.canonicalName()).isNotNull();
            assertThat(resolution.setCode())
                    .as("repository resolution carries a printing for \"" + name + "\"")
                    .isNotNull();
            assertThat(resolution.strategy())
                    .isIn(CardResolution.Strategy.EXACT, CardResolution.Strategy.NORMALIZED);
        }
        // canonical names round-trip exactly for these
        assertThat(resolver.resolve("Boseiju, Who Endures").canonicalName())
                .isEqualTo("Boseiju, Who Endures");
        assertThat(resolver.resolve("Fire // Ice").canonicalName()).isEqualTo("Fire // Ice");
    }

    @Test
    void splitCardResolvesToItsFullNameFromASingleHalf() {
        requireDatabase();
        CardResolver resolver = new CardResolver();

        // "Fire" alone is a split half; the class-name heuristic can't reach
        // the combined card, but the repository resolves it to the full name.
        CardResolution resolution = resolver.resolve("Fire");

        assertThat(resolution.isResolved()).isTrue();
        assertThat(resolution.strategy()).isEqualTo(CardResolution.Strategy.EXACT);
        assertThat(resolution.canonicalName()).isEqualTo("Fire // Ice");
        assertThat(resolution.setCode()).isNotNull();
    }

    @Test
    void punctuationResolvesAfterNormalization() {
        requireDatabase();
        assumeTrue(CardRepository.instance.findCard("Urza's Mine") != null,
                "Urza's Mine not present in this database");
        CardResolver resolver = new CardResolver();

        // a curly apostrophe (as decklist exporters emit) only matches once
        // normalized to the ASCII spelling the repository stores
        CardResolution resolution = resolver.resolve("Urza’s Mine");

        assertThat(resolution.isResolved()).isTrue();
        assertThat(resolution.strategy()).isEqualTo(CardResolution.Strategy.NORMALIZED);
        assertThat(resolution.canonicalName()).isEqualTo("Urza's Mine");
    }

    @Test
    void unknownCardFailsClosed() {
        requireDatabase();
        CardResolver resolver = new CardResolver();

        CardResolution resolution = resolver.resolve("No Such Card Ever Printed");

        assertThat(resolution.isResolved()).isFalse();
        assertThat(resolution.failureCode()).isEqualTo("UNKNOWN_CARD");
    }

    // --- protocol commands, no active game ---

    @Test
    void resolveCardCommandReturnsDiagnostics() {
        requireDatabase();
        JsonObject response = handle(server(),
                "{\"command\": \"resolve_card\", \"name\": \"Boseiju, Who Endures\"}");

        assertThat(response.get("ok").getAsBoolean()).isTrue();
        JsonObject resolution = response.getAsJsonObject("resolution");
        assertThat(resolution.get("resolved").getAsBoolean()).isTrue();
        assertThat(resolution.get("canonicalName").getAsString()).isEqualTo("Boseiju, Who Endures");
        assertThat(resolution.get("strategy").getAsString()).isEqualTo("EXACT");
    }

    @Test
    void validateDeckCommandNeedsNoGameAndWritesFixture() throws IOException {
        requireDatabase();
        JsonObject response = handle(server(),
                "{\"command\": \"validate_deck\", \"deck\": " + deckJson(REALISTIC_DECK_NAMES) + "}");

        assertThat(response.get("ok").getAsBoolean()).isTrue();
        assertThat(response.get("valid").getAsBoolean()).isTrue();
        assertThat(response.getAsJsonArray("resolutions")).hasSize(REALISTIC_DECK_NAMES.length);
        assertThat(response.getAsJsonArray("failures")).isEmpty();

        writeFixture("validate_deck_response.json", response.toString());
    }

    @Test
    void validateDeckReportsFailuresWithoutRejectingTheWholeRequest() {
        requireDatabase();
        JsonObject response = handle(server(),
                "{\"command\": \"validate_deck\", \"deck\": ["
                        + "{\"name\": \"Forest\", \"count\": 4}, "
                        + "{\"name\": \"No Such Card Ever Printed\", \"count\": 2}]}");

        assertThat(response.get("ok").getAsBoolean()).isTrue();
        assertThat(response.get("valid").getAsBoolean()).isFalse();
        JsonArray failures = response.getAsJsonArray("failures");
        assertThat(failures).hasSize(1);
        JsonObject failure = failures.get(0).getAsJsonObject();
        assertThat(failure.get("resolved").getAsBoolean()).isFalse();
        assertThat(failure.get("error").getAsString()).isEqualTo("UNKNOWN_CARD");
        assertThat(failure.get("requestedName").getAsString())
                .isEqualTo("No Such Card Ever Printed");
    }

    @Test
    void repositoryCardDataExportsWithoutAGameAndWritesFixture() throws IOException {
        requireDatabase();
        JsonObject response = handle(server(),
                "{\"command\": \"repository_card_data\", \"names\": "
                        + "[\"Forest\", \"Lightning Bolt\", \"Boseiju, Who Endures\"]}");

        assertThat(response.get("ok").getAsBoolean()).isTrue();
        JsonArray cards = response.getAsJsonArray("cards");
        assertThat(cards).hasSize(3);
        assertThat(cards.toString()).contains("Forest", "Lightning Bolt", "Boseiju, Who Endures");
        assertThat(response.getAsJsonArray("resolutions")).hasSize(3);

        writeFixture("repository_card_data_response.json", response.toString());
    }

    @Test
    void repositoryCardDataFailsClosedOnAnUnknownName() {
        requireDatabase();
        JsonObject response = handle(server(),
                "{\"command\": \"repository_card_data\", \"names\": "
                        + "[\"Forest\", \"No Such Card Ever Printed\"]}");

        assertThat(response.get("ok").getAsBoolean()).isFalse();
        assertThat(response.get("error").getAsString()).isEqualTo("UNKNOWN_CARD");
        assertThat(response.getAsJsonArray("failures")).hasSize(1);
        assertThat(response.has("cards")).isFalse();
    }

    @Test
    void gameStartUsesRepositoryResolvedCards() {
        requireDatabase();
        CabtProtocolServer server = server();
        // a deck whose non-basic card carries a comma the naive class-name
        // transform mangles: it must come from repository resolution
        JsonObject started = handle(server, "{\"command\": \"game_start\", \"decks\": ["
                + "[{\"name\": \"Forest\", \"count\": 36}, "
                + "{\"name\": \"Boseiju, Who Endures\", \"count\": 24}], "
                + "[{\"name\": \"Forest\", \"count\": 60}]], "
                + "\"options\": {\"seed\": 20260705, \"maxTurns\": 2}}");

        assertThat(started.get("ok").getAsBoolean())
                .as("game_start response: " + started)
                .isTrue();
        assertThat(handle(server, "{\"command\": \"game_finish\"}").get("ok").getAsBoolean())
                .isTrue();
    }

    @Test
    void gameStartFailsClosedWithStructuredFailuresForUnknownCards() {
        requireDatabase();
        JsonObject response = handle(server(), "{\"command\": \"game_start\", \"decks\": ["
                + "[{\"name\": \"No Such Card Ever Printed\", \"count\": 60}], "
                + "[{\"name\": \"Forest\", \"count\": 60}]]}");

        assertThat(response.get("ok").getAsBoolean()).isFalse();
        assertThat(response.get("error").getAsString()).isEqualTo("UNKNOWN_CARD");
        assertThat(response.get("message").getAsString()).contains("No Such Card Ever Printed");
        JsonArray failures = response.getAsJsonArray("failures");
        assertThat(failures).isNotEmpty();
        assertThat(failures.get(0).getAsJsonObject().get("deckIndex").getAsInt()).isEqualTo(0);
    }

    // --- helpers ---

    private static String deckJson(String[] names) {
        StringBuilder json = new StringBuilder("[");
        for (int i = 0; i < names.length; i++) {
            if (i > 0) {
                json.append(", ");
            }
            json.append("{\"name\": \"").append(names[i]).append("\", \"count\": 1}");
        }
        return json.append("]").toString();
    }

    private static void writeFixture(String fileName, String content) throws IOException {
        Path fixtureDir = Paths.get("target", "cabt-fixtures");
        Files.createDirectories(fixtureDir);
        Files.write(fixtureDir.resolve(fileName), content.getBytes(StandardCharsets.UTF_8));
    }
}
