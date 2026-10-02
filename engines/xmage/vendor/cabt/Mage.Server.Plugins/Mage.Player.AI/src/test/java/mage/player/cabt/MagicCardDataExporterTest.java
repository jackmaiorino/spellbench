package mage.player.cabt;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import mage.cards.Card;
import mage.cards.CardSetInfo;
import mage.cards.g.GrizzlyBears;
import mage.cards.l.LlanowarElves;
import mage.constants.Rarity;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Arrays;
import java.util.List;
import java.util.UUID;
import java.util.function.Supplier;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Task 21: static card metadata export (the all_card_data() equivalent).
 * Static card data is reference data — legal choices still come from live
 * XMage state through the prompt callbacks, not from this metadata.
 */
class MagicCardDataExporterTest {

    private final MagicCardDataExporter exporter = new MagicCardDataExporter();

    private static Card grizzlyBears() {
        return new GrizzlyBears(UUID.randomUUID(),
                new CardSetInfo("Grizzly Bears", "TST", "1", Rarity.COMMON));
    }

    private static Card llanowarElves() {
        return new LlanowarElves(UUID.randomUUID(),
                new CardSetInfo("Llanowar Elves", "TST", "2", Rarity.COMMON));
    }

    @Test
    void exportsBasicCreatureData() {
        MagicCardData data = exporter.export(grizzlyBears());

        assertThat(data.getName()).isEqualTo("Grizzly Bears");
        assertThat(data.getManaCost()).isEqualTo("{1}{G}");
        assertThat(data.getManaValue()).isEqualTo(2);
        assertThat(data.getCardTypes()).containsExactly("Creature");
        assertThat(data.getSubtypes()).containsExactly("Bear");
        assertThat(data.getSupertypes()).isEmpty();
        assertThat(data.getPower()).isEqualTo("2");
        assertThat(data.getToughness()).isEqualTo("2");
        assertThat(data.getColors()).containsExactly("G");
        assertThat(data.getColorIdentity()).containsExactly("G");
        assertThat(data.getLoyalty()).isNull();
        assertThat(data.getDefense()).isNull();
        assertThat(data.getCardId()).isNotEmpty();
    }

    @Test
    void exportsAbilityText() {
        MagicCardData data = exporter.export(llanowarElves());

        // Llanowar Elves carries an activated mana ability: {T}: Add {G}.
        assertThat(data.getAbilities()).isNotEmpty();
        boolean manaAbilityExported = false;
        for (MagicAbilityData ability : data.getAbilities()) {
            if (ability.getRule().contains("Add {G}")) {
                manaAbilityExported = true;
                assertThat(ability.getAbilityType()).isEqualTo("ACTIVATED_MANA");
                assertThat(ability.getZone()).isEqualTo("BATTLEFIELD");
            }
        }
        assertThat(manaAbilityExported)
                .as("activated mana ability rule text is exported")
                .isTrue();
        assertThat(data.getRulesText()).contains("Add {G}");
    }

    @Test
    void protocolCommandReturnsOkAndCards() throws IOException {
        MagicCardDataProtocolCommand command = new MagicCardDataProtocolCommand(
                exporter,
                new Supplier<List<Card>>() {
                    @Override
                    public List<Card> get() {
                        return Arrays.asList(grizzlyBears(), llanowarElves());
                    }
                });

        String response = command.handle("{\"command\": \"all_card_data\"}");

        JsonObject parsed = JsonParser.parseString(response).getAsJsonObject();
        assertThat(parsed.get("ok").getAsBoolean()).isTrue();
        JsonArray cards = parsed.getAsJsonArray("cards");
        assertThat(cards).hasSize(2);
        JsonObject bears = cards.get(0).getAsJsonObject();
        assertThat(bears.get("name").getAsString()).isEqualTo("Grizzly Bears");
        assertThat(bears.get("manaCost").getAsString()).isEqualTo("{1}{G}");
        assertThat(bears.getAsJsonArray("types").get(0).getAsString()).isEqualTo("Creature");
        assertThat(bears.getAsJsonArray("subtypes").get(0).getAsString()).isEqualTo("Bear");

        // regenerate the cross-language fixture consumed by the Python tests
        Path fixtureDir = Paths.get("target", "cabt-fixtures");
        Files.createDirectories(fixtureDir);
        Files.write(fixtureDir.resolve("card_data_response.json"),
                response.getBytes(StandardCharsets.UTF_8));
    }

    @Test
    void protocolCommandFailsClosedOnUnknownCommand() {
        MagicCardDataProtocolCommand command = new MagicCardDataProtocolCommand(
                exporter,
                new Supplier<List<Card>>() {
                    @Override
                    public List<Card> get() {
                        return Arrays.asList(grizzlyBears());
                    }
                });

        JsonObject unknown = JsonParser
                .parseString(command.handle("{\"command\": \"do_something_else\"}"))
                .getAsJsonObject();
        assertThat(unknown.get("ok").getAsBoolean()).isFalse();
        assertThat(unknown.get("error").getAsString()).contains("unknown command");

        JsonObject malformed = JsonParser
                .parseString(command.handle("not json"))
                .getAsJsonObject();
        assertThat(malformed.get("ok").getAsBoolean()).isFalse();
    }
}
