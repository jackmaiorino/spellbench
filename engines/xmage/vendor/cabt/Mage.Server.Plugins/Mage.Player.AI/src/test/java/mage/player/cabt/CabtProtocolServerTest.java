package mage.player.cabt;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;

import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Protocol boundary test: drives {@link CabtProtocolServer#handleLine} with
 * raw request lines — exactly what a Python client sends over stdin — and
 * asserts on raw response lines. A real engine game runs underneath; the
 * JSON-level greedy policy mirrors {@link CabtEventPolicy} to prove the whole
 * loop works from serialized observations alone (no Java-side objects), the
 * way an external agent must.
 */
@Timeout(120)
class CabtProtocolServerTest {

    private final CabtProtocolServer server = new CabtProtocolServer();

    @AfterEach
    void tearDown() {
        server.handleLine("{\"command\": \"game_finish\"}");
    }

    private static final String GAME_START = "{\"command\": \"game_start\", \"decks\": ["
            + deckJson() + ", " + deckJson() + "], \"options\": {"
            + "\"playerNames\": [\"Alice\", \"Bob\"], \"seed\": 20260704, \"maxTurns\": 4}}";

    private static String deckJson() {
        return "[{\"name\": \"Forest\", \"count\": 24}, {\"name\": \"Grizzly Bears\", \"count\": 36}]";
    }

    private JsonObject handle(String line) {
        return JsonParser.parseString(server.handleLine(line)).getAsJsonObject();
    }

    // --- transport-level behavior ---

    @Test
    void pingAndCapabilitiesAnswerWithoutAGame() {
        JsonObject pong = handle("{\"command\": \"ping\", \"id\": 7}");
        assertThat(pong.get("ok").getAsBoolean()).isTrue();
        assertThat(pong.get("pong").getAsBoolean()).isTrue();
        assertThat(pong.get("id").getAsInt()).isEqualTo(7);

        JsonObject capabilities = handle("{\"command\": \"capabilities\"}");
        assertThat(capabilities.get("ok").getAsBoolean()).isTrue();
        assertThat(capabilities.get("protocolVersion").getAsInt())
                .isEqualTo(CabtProtocolServer.PROTOCOL_VERSION);
        assertThat(capabilities.get("commands").getAsJsonArray().toString())
                .contains("game_start", "game_select", "game_finish", "all_card_data");
        assertThat(capabilities.get("cardDataScope").getAsString())
                .isEqualTo("ACTIVE_GAME_DECK_POOL");
    }

    @Test
    void malformedAndUnknownRequestsFailClosed() {
        assertThat(handle("this is not json").get("error").getAsString())
                .isEqualTo("MALFORMED_REQUEST");
        assertThat(handle("[1, 2]").get("error").getAsString())
                .isEqualTo("MALFORMED_REQUEST");
        assertThat(handle("{\"no\": \"command\"}").get("error").getAsString())
                .isEqualTo("MALFORMED_REQUEST");
        assertThat(handle("{\"command\": \"battle_cheat\"}").get("error").getAsString())
                .isEqualTo("UNKNOWN_COMMAND");
        assertThat(handle("{\"command\": \"game_select\", \"select\": [0]}")
                .get("error").getAsString()).isEqualTo("NO_ACTIVE_GAME");
        assertThat(handle("{\"command\": \"all_card_data\"}").get("error").getAsString())
                .isEqualTo("NO_ACTIVE_GAME");
    }

    @Test
    void malformedDeckEntryTypesReturnMalformedRequestNotInternal() {
        String validDeck = deckJson();
        String[] malformedGameStarts = {
            // count is a string instead of an integer
            "{\"command\": \"game_start\", \"decks\": ["
                + "[{\"name\": \"Forest\", \"count\": \"abc\"}], " + validDeck + "]}",
            // name is null
            "{\"command\": \"game_start\", \"decks\": ["
                + "[{\"name\": null, \"count\": 1}], " + validDeck + "]}",
            // count is 0
            "{\"command\": \"game_start\", \"decks\": ["
                + "[{\"name\": \"Forest\", \"count\": 0}], " + validDeck + "]}",
            // count is negative
            "{\"command\": \"game_start\", \"decks\": ["
                + "[{\"name\": \"Forest\", \"count\": -1}], " + validDeck + "]}",
            // deck entry is not an object
            "{\"command\": \"game_start\", \"decks\": ["
                + "[\"Forest\"], " + validDeck + "]}",
            // name is missing
            "{\"command\": \"game_start\", \"decks\": ["
                + "[{\"count\": 5}], " + validDeck + "]}",
        };
        for (String request : malformedGameStarts) {
            JsonObject response = handle(request);
            assertThat(response.get("ok").getAsBoolean()).isFalse();
            assertThat(response.get("error").getAsString())
                    .as("expected MALFORMED_REQUEST for: " + request)
                    .isEqualTo("MALFORMED_REQUEST");
        }
    }

    @Test
    void malformedConfigOptionsReturnMalformedRequestNotInternal() {
        String validDecks = "[" + deckJson() + ", " + deckJson() + "]";
        String[] malformedOptions = {
            // maxTurns is a string
            "{\"command\": \"game_start\", \"decks\": " + validDecks
                + ", \"options\": {\"maxTurns\": \"abc\"}}",
            // seed is a string
            "{\"command\": \"game_start\", \"decks\": " + validDecks
                + ", \"options\": {\"seed\": \"abc\"}}",
            // maxTurns is 0
            "{\"command\": \"game_start\", \"decks\": " + validDecks
                + ", \"options\": {\"maxTurns\": 0}}",
            // maxTurns is negative
            "{\"command\": \"game_start\", \"decks\": " + validDecks
                + ", \"options\": {\"maxTurns\": -1}}",
            // decisionTimeoutSeconds is 0
            "{\"command\": \"game_start\", \"decks\": " + validDecks
                + ", \"options\": {\"decisionTimeoutSeconds\": 0}}",
            // decisionTimeoutSeconds is negative
            "{\"command\": \"game_start\", \"decks\": " + validDecks
                + ", \"options\": {\"decisionTimeoutSeconds\": -5}}",
            // decisionTimeoutSeconds is a string
            "{\"command\": \"game_start\", \"decks\": " + validDecks
                + ", \"options\": {\"decisionTimeoutSeconds\": \"abc\"}}",
        };
        for (String request : malformedOptions) {
            JsonObject response = handle(request);
            assertThat(response.get("ok").getAsBoolean()).isFalse();
            assertThat(response.get("error").getAsString())
                    .as("expected MALFORMED_REQUEST for: " + request)
                    .isEqualTo("MALFORMED_REQUEST");
            // session must not have been created
            assertThat(server.handleLine("{\"command\": \"game_finish\"}")
                    .contains("\"ok\":true")).isTrue();
        }
    }

    @Test
    void unknownCardNamesFailGameStartLoudly() {
        JsonObject response = handle("{\"command\": \"game_start\", \"decks\": ["
                + "[{\"name\": \"No Such Card Ever Printed\", \"count\": 60}], "
                + deckJson() + "]}");
        assertThat(response.get("ok").getAsBoolean()).isFalse();
        assertThat(response.get("error").getAsString()).isEqualTo("UNKNOWN_CARD");
        assertThat(response.get("message").getAsString())
                .contains("No Such Card Ever Printed");
    }

    // --- a real game over the protocol ---

    @Test
    void protocolDrivesARealGameFromStartToFinish() {
        JsonObject response = handle(GAME_START);
        assertThat(response.get("ok").getAsBoolean()).isTrue();

        List<String> selectTypes = new ArrayList<String>();
        boolean sawOwnHand = false;
        int guard = 0;
        while (!response.get("finished").getAsBoolean()) {
            assertThat(guard++).as("decision count stays bounded").isLessThan(2000);
            JsonObject observation = response.get("observation").getAsJsonObject();
            JsonObject select = observation.get("select").getAsJsonObject();
            selectTypes.add(select.get("type").getAsString());

            // hidden-information boundary: only the selecting player's hand
            // is dealt out; every other hand stays counts-only
            int selectingIndex = select.get("playerIndex").getAsInt();
            JsonArray players = observation.get("current").getAsJsonObject()
                    .get("players").getAsJsonArray();
            for (int i = 0; i < players.size(); i++) {
                JsonObject player = players.get(i).getAsJsonObject();
                int handCount = player.get("handCount").getAsInt();
                int handShown = player.get("hand").getAsJsonArray().size();
                if (i == selectingIndex) {
                    sawOwnHand |= handShown > 0 && handShown == handCount;
                } else {
                    assertThat(handShown)
                            .as("opponent hand must not leak (handCount=" + handCount + ")")
                            .isZero();
                }
            }

            response = handle("{\"command\": \"game_select\", \"select\": "
                    + chooseFromJson(select) + "}");
            assertThat(response.get("ok").getAsBoolean())
                    .as("select response: " + response)
                    .isTrue();
        }

        assertThat(selectTypes).contains("PRIORITY", "MULLIGAN");
        assertThat(sawOwnHand).as("the selecting player sees its own hand").isTrue();
        JsonObject result = response.get("result").getAsJsonObject();
        assertThat(result.get("finalState").isJsonObject()).isTrue();

        // after the game ended a fresh game_start must be accepted again
        JsonObject restarted = handle(GAME_START);
        assertThat(restarted.get("ok").getAsBoolean()).isTrue();
    }

    @Test
    void invalidSelectionsReturnStructuredErrorsAndTheGameSurvives() {
        JsonObject first = handle(GAME_START);
        assertThat(first.get("ok").getAsBoolean()).isTrue();
        JsonObject select = first.get("observation").getAsJsonObject()
                .get("select").getAsJsonObject();
        int optionCount = select.get("option").getAsJsonArray().size();

        JsonObject outOfRange = handle(
                "{\"command\": \"game_select\", \"select\": [" + (optionCount + 5) + "]}");
        assertThat(outOfRange.get("ok").getAsBoolean()).isFalse();
        assertThat(outOfRange.get("error").getAsString()).isEqualTo("OPTION_INDEX_OUT_OF_RANGE");

        JsonObject duplicate = handle("{\"command\": \"game_select\", \"select\": [0, 0]}");
        assertThat(duplicate.get("ok").getAsBoolean()).isFalse();
        assertThat(duplicate.get("error").getAsString()).isIn(
                "DUPLICATE_SELECTION", "INVALID_SELECTION_COUNT");

        JsonObject malformed = handle("{\"command\": \"game_select\", \"select\": [0.5]}");
        assertThat(malformed.get("error").getAsString()).isEqualTo("MALFORMED_REQUEST");

        JsonObject secondStart = handle(GAME_START);
        assertThat(secondStart.get("ok").getAsBoolean()).isFalse();
        assertThat(secondStart.get("error").getAsString()).isEqualTo("GAME_ALREADY_ACTIVE");

        // the pending decision survived every rejected request
        JsonObject retried = handle("{\"command\": \"game_select\", \"select\": "
                + chooseFromJson(select) + "}");
        assertThat(retried.get("ok").getAsBoolean()).isTrue();
    }

    @Test
    void protocolProvesZoneTransitionsForPlayLandAndCastSpell() {
        JsonObject response = handle(GAME_START);
        assertThat(response.get("ok").getAsBoolean()).isTrue();

        boolean verifiedPlayLand = false;
        boolean verifiedCastSpell = false;
        int guard = 0;
        // Track a cast-spell sourceId across observations until it reaches the
        // battlefield (it may sit on the stack first, then resolve).
        String pendingCastSpellSourceId = null;

        while (!response.get("finished").getAsBoolean()) {
            assertThat(guard++).as("decision count stays bounded").isLessThan(2000);
            JsonObject observation = response.get("observation").getAsJsonObject();
            JsonObject select = observation.get("select").getAsJsonObject();
            String selectingPlayerId = select.get("playerId").getAsString();

            // Resolve a tracked cast-spell sourceId against the current state.
            // Check the battlefield for a permanent whose ref.objectId matches;
            // the spell may transit through the stack first.
            if (pendingCastSpellSourceId != null) {
                JsonArray battlefield = observation.get("current").getAsJsonObject()
                        .get("battlefield").getAsJsonArray();
                for (JsonElement bfElement : battlefield) {
                    JsonObject ref = bfElement.getAsJsonObject().get("ref").getAsJsonObject();
                    if (pendingCastSpellSourceId.equals(ref.get("objectId").getAsString())) {
                        verifiedCastSpell = true;
                        pendingCastSpellSourceId = null;
                        break;
                    }
                }
            }

            // Determine the greedy choice and capture transition data
            String selectType = select.get("type").getAsString();
            JsonArray options = select.get("option").getAsJsonArray();
            int chosenIndex = -1;
            String chosenType = null;
            String chosenSourceId = null;

            if (selectType.equals("PRIORITY")) {
                for (String want : new String[]{"PLAY_LAND", "CAST_SPELL", "PASS_PRIORITY"}) {
                    for (int i = 0; i < options.size(); i++) {
                        JsonObject option = options.get(i).getAsJsonObject();
                        if (want.equals(option.get("type").getAsString())) {
                            chosenIndex = i;
                            chosenType = want;
                            JsonObject payload = option.has("payload")
                                    && option.get("payload").isJsonObject()
                                    ? option.get("payload").getAsJsonObject() : null;
                            if (payload != null && payload.has("sourceId")
                                    && !payload.get("sourceId").isJsonNull()) {
                                chosenSourceId = payload.get("sourceId").getAsString();
                            }
                            break;
                        }
                    }
                    if (chosenIndex >= 0) {
                        break;
                    }
                }
            } else if (selectType.equals("MULLIGAN")) {
                for (int i = 0; i < options.size(); i++) {
                    if ("PROMPT_KEEP".equals(
                            options.get(i).getAsJsonObject().get("type").getAsString())) {
                        chosenIndex = i;
                        break;
                    }
                }
            } else if (selectType.equals("PAY_MANA")) {
                for (String want : new String[]{"PROMPT_MANA_SOURCE",
                        "PROMPT_MANA_POOL", "PROMPT_CANCEL_PAYMENT"}) {
                    for (int i = 0; i < options.size(); i++) {
                        if (want.equals(
                                options.get(i).getAsJsonObject().get("type").getAsString())) {
                            chosenIndex = i;
                            break;
                        }
                    }
                    if (chosenIndex >= 0) {
                        break;
                    }
                }
            } else if (selectType.equals("DECLARE_ATTACKERS")
                    || selectType.equals("DECLARE_BLOCKERS")) {
                chosenIndex = -1; // pass
            } else {
                int minCount = select.get("minCount").getAsInt();
                chosenIndex = minCount > 0 ? 0 : -1;
            }

            // Send the selection
            String selectJson = chosenIndex >= 0 ? "[" + chosenIndex + "]" : "[]";
            response = handle("{\"command\": \"game_select\", \"select\": " + selectJson + "}");
            assertThat(response.get("ok").getAsBoolean())
                    .as("select response: " + response)
                    .isTrue();

            // --- PLAY_LAND transition invariant ---
            // After selecting PLAY_LAND, the sourceId must have left the hand
            // and appeared on the battlefield under the same controller.
            if ("PLAY_LAND".equals(chosenType) && chosenSourceId != null
                    && response.has("observation")) {
                JsonObject nextObs = response.get("observation").getAsJsonObject();
                JsonArray nextPlayers = nextObs.get("current").getAsJsonObject()
                        .get("players").getAsJsonArray();

                // The original selecting player's hand: only visible if they
                // are also the next selecting player; otherwise it's empty
                // (hidden) and we check the battlefield only.
                for (int pi = 0; pi < nextPlayers.size(); pi++) {
                    JsonObject p = nextPlayers.get(pi).getAsJsonObject();
                    if (selectingPlayerId.equals(p.get("playerId").getAsString())) {
                        JsonArray hand = p.get("hand").getAsJsonArray();
                        for (JsonElement e : hand) {
                            assertThat(e.getAsJsonObject().get("ref").getAsJsonObject()
                                    .get("objectId").getAsString())
                                    .as("played land card must leave hand")
                                    .isNotEqualTo(chosenSourceId);
                        }
                        break;
                    }
                }

                // Battlefield: the sourceId must have arrived as a permanent
                JsonArray battlefield = nextObs.get("current").getAsJsonObject()
                        .get("battlefield").getAsJsonArray();
                boolean foundOnBattlefield = false;
                for (JsonElement e : battlefield) {
                    JsonObject ref = e.getAsJsonObject().get("ref").getAsJsonObject();
                    if (chosenSourceId.equals(ref.get("objectId").getAsString())) {
                        foundOnBattlefield = true;
                        assertThat(e.getAsJsonObject().get("controllerId").getAsString())
                                .as("land on battlefield under same controller")
                                .isEqualTo(selectingPlayerId);
                        break;
                    }
                }
                assertThat(foundOnBattlefield)
                        .as("PLAY_LAND sourceId must appear on battlefield after selection")
                        .isTrue();
                verifiedPlayLand = true;
            }

            // --- CAST_SPELL transition: start tracking ---
            if ("CAST_SPELL".equals(chosenType) && chosenSourceId != null) {
                pendingCastSpellSourceId = chosenSourceId;
            }
        }

        assertThat(verifiedPlayLand)
                .as("at least one PLAY_LAND zone transition was verified across serialization")
                .isTrue();
        // If a cast was tracked and the game ended without it reaching the
        // battlefield, fail; if no cast happened (all-pass), skip.
        if (pendingCastSpellSourceId != null) {
            assertThat(verifiedCastSpell)
                    .as("CAST_SPELL sourceId must reach battlefield before game end")
                    .isTrue();
        }
    }

    @Test
    void cardDataAndVisualizationAreServedDuringAGame() {
        assertThat(handle(GAME_START).get("ok").getAsBoolean()).isTrue();

        JsonObject cardData = handle("{\"command\": \"all_card_data\"}");
        assertThat(cardData.get("ok").getAsBoolean()).isTrue();
        String cards = cardData.get("cards").getAsJsonArray().toString();
        assertThat(cards).contains("Forest", "Grizzly Bears");
        // deck pool is deduplicated by name: 60 physical cards, 2 entries
        assertThat(cardData.get("cards").getAsJsonArray().size()).isEqualTo(2);

        JsonObject visualization = handle("{\"command\": \"visualize_data\"}");
        assertThat(visualization.get("ok").getAsBoolean()).isTrue();
        assertThat(visualization.get("text").getAsString()).contains("turn", "life=");
        assertThat(visualization.get("state").isJsonObject()).isTrue();

        assertThat(handle("{\"command\": \"game_finish\"}").get("ok").getAsBoolean()).isTrue();
        assertThat(handle("{\"command\": \"visualize_data\"}").get("error").getAsString())
                .isEqualTo("NO_ACTIVE_GAME");
    }

    /**
     * JSON-level twin of {@link CabtEventPolicy}: same greedy rules, but read
     * from the serialized select block only.
     */
    private static String chooseFromJson(JsonObject select) {
        String type = select.get("type").getAsString();
        JsonArray options = select.get("option").getAsJsonArray();
        if (type.equals("DECLARE_ATTACKERS") || type.equals("DECLARE_BLOCKERS")) {
            return "[]";
        }
        String[] preferred;
        switch (type) {
            case "PRIORITY":
                preferred = new String[]{"PLAY_LAND", "CAST_SPELL", "PASS_PRIORITY"};
                break;
            case "MULLIGAN":
                preferred = new String[]{"PROMPT_KEEP"};
                break;
            case "PAY_MANA":
                preferred = new String[]{"PROMPT_MANA_SOURCE", "PROMPT_MANA_POOL",
                        "PROMPT_CANCEL_PAYMENT"};
                break;
            default:
                preferred = new String[0];
                break;
        }
        for (String want : preferred) {
            for (int i = 0; i < options.size(); i++) {
                if (options.get(i).getAsJsonObject().get("type").getAsString().equals(want)) {
                    return "[" + i + "]";
                }
            }
        }
        // no rule: take the first minCount options
        int minCount = select.get("minCount").getAsInt();
        StringBuilder indices = new StringBuilder("[");
        for (int i = 0; i < minCount; i++) {
            indices.append(i == 0 ? "" : ", ").append(i);
        }
        return indices.append("]").toString();
    }
}
