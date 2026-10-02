package mage.player.cabt;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import mage.game.Game;
import mage.players.Player;
import org.junit.jupiter.api.Test;

import java.io.BufferedWriter;
import java.io.IOException;
import java.io.StringWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Task 22: the dataset writer emits one JSON line per transition with
 * schemaVersion and run metadata, and records carry only generic transition
 * fields — no outcome labels.
 */
class CabtDatasetWriterTest {

    private final CabtDatasetMetadata metadata =
            new CabtDatasetMetadata("1.4.60-test", "deck-forest-bears", "deck-island-drakes");

    private MagicObservation observation() {
        UUID playerId = UUID.randomUUID();
        Player player = StubGames.player(playerId, "Alice", 20, 7);
        LinkedHashMap<UUID, Player> players = new LinkedHashMap<UUID, Player>();
        players.put(playerId, player);
        Game game = StubGames.game(players, playerId, playerId);
        return new MagicObservationSerializer()
                .serialize(game, player, PendingDecision.priority(playerId));
    }

    @Test
    void writesOneJsonLinePerTransition() throws IOException {
        MagicObservation before = observation();
        MagicObservation after = observation();
        StringWriter sink = new StringWriter();
        // buffered on purpose: proves test mode flushes each record through
        CabtDatasetWriter writer = new CabtDatasetWriter(new BufferedWriter(sink), metadata, true);

        writer.write(new CabtDatasetRecord("game-1", 0, "PRIORITY",
                before, before.getSelect(), Collections.singletonList(0), after, false, null));
        writer.write(new CabtDatasetRecord("game-1", 1, "PRIORITY",
                after, after.getSelect(), Collections.singletonList(0), null, true, 1.0));

        String[] lines = sink.toString().split("\n");
        assertThat(lines).hasSize(2);
        for (String line : lines) {
            JsonObject parsed = JsonParser.parseString(line).getAsJsonObject();
            assertThat(parsed.get("schemaVersion").getAsInt()).isEqualTo(CabtDatasetWriter.SCHEMA_VERSION);
            assertThat(parsed.get("gameId").getAsString()).isEqualTo("game-1");
            assertThat(parsed.has("observation")).isTrue();
            assertThat(parsed.has("select")).isTrue();
            assertThat(parsed.has("selectedIndices")).isTrue();
            assertThat(parsed.has("nextObservation")).isTrue();
            assertThat(parsed.has("terminal")).isTrue();
            assertThat(parsed.has("reward")).isTrue();
            JsonObject meta = parsed.getAsJsonObject("metadata");
            assertThat(meta.get("xmageVersion").getAsString()).isEqualTo("1.4.60-test");
            assertThat(meta.get("deck0Id").getAsString()).isEqualTo("deck-forest-bears");
            assertThat(meta.get("deck1Id").getAsString()).isEqualTo("deck-island-drakes");
        }
        JsonObject first = JsonParser.parseString(lines[0]).getAsJsonObject();
        assertThat(first.get("terminal").getAsBoolean()).isFalse();
        assertThat(first.get("reward").isJsonNull()).isTrue();
        JsonObject last = JsonParser.parseString(lines[1]).getAsJsonObject();
        assertThat(last.get("terminal").getAsBoolean()).isTrue();
        assertThat(last.get("nextObservation").isJsonNull()).isTrue();

        // regenerate the cross-language fixture consumed by the Python tests
        Path fixtureDir = Paths.get("target", "cabt-fixtures");
        Files.createDirectories(fixtureDir);
        Files.write(fixtureDir.resolve("dataset_sample.jsonl"),
                sink.toString().getBytes(StandardCharsets.UTF_8));
    }

    @Test
    void datasetRecordContainsNoOutcomeLabels() {
        MagicObservation before = observation();
        StringWriter sink = new StringWriter();
        CabtDatasetWriter writer = new CabtDatasetWriter(sink, metadata, true);
        writer.write(new CabtDatasetRecord("game-1", 0, "PRIORITY",
                before, before.getSelect(), Collections.singletonList(0), before, false, null));

        Set<String> keys = new HashSet<String>();
        collectKeys(JsonParser.parseString(sink.toString().trim()), keys);

        assertThat(keys).isNotEmpty();
        assertThat(keys).doesNotContainAnyElementsOf(Arrays.asList(
                "countered", "destroyed", "fizzled", "succeeded", "removalSucceeded"));
    }

    private static void collectKeys(JsonElement element, Set<String> keys) {
        if (element.isJsonObject()) {
            for (Map.Entry<String, JsonElement> entry : element.getAsJsonObject().entrySet()) {
                keys.add(entry.getKey());
                collectKeys(entry.getValue(), keys);
            }
        } else if (element.isJsonArray()) {
            for (JsonElement child : element.getAsJsonArray()) {
                collectKeys(child, keys);
            }
        }
    }
}
