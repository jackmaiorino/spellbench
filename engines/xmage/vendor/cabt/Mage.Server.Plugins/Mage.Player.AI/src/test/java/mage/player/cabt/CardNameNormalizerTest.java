package mage.player.cabt;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * The name normalizer folds cosmetic differences (typographic punctuation,
 * whitespace, Arena's triple-slash split separator) to the ASCII spelling
 * XMage stores, without ever changing letters — so it can never turn one real
 * card name into a different one.
 */
class CardNameNormalizerTest {

    @Test
    void leavesAPlainNameUnchanged() {
        assertThat(CardNameNormalizer.normalize("Lightning Bolt")).isEqualTo("Lightning Bolt");
        assertThat(CardNameNormalizer.normalize("Boseiju, Who Endures"))
                .isEqualTo("Boseiju, Who Endures");
    }

    @Test
    void foldsApostropheAndQuoteVariants() {
        assertThat(CardNameNormalizer.normalize("Urza’s Mine")).isEqualTo("Urza's Mine");
        assertThat(CardNameNormalizer.normalize("Urza‘s Mine")).isEqualTo("Urza's Mine");
        assertThat(CardNameNormalizer.normalize("Gaeaʼs Cradle")).isEqualTo("Gaea's Cradle");
        assertThat(CardNameNormalizer.normalize("“Name”")).isEqualTo("\"Name\"");
    }

    @Test
    void foldsDashVariantsToHyphen() {
        assertThat(CardNameNormalizer.normalize("Wear–Tear")).isEqualTo("Wear-Tear");
        assertThat(CardNameNormalizer.normalize("Wear—Tear")).isEqualTo("Wear-Tear");
        assertThat(CardNameNormalizer.normalize("Ratchet−Bomb")).isEqualTo("Ratchet-Bomb");
    }

    @Test
    void collapsesWhitespaceAndTrims() {
        assertThat(CardNameNormalizer.normalize("  Grizzly   Bears  "))
                .isEqualTo("Grizzly Bears");
        assertThat(CardNameNormalizer.normalize("Grizzly Bears")).isEqualTo("Grizzly Bears");
        assertThat(CardNameNormalizer.normalize("Fire\tIce")).isEqualTo("Fire Ice");
    }

    @Test
    void foldsArenaTripleSlashToXmageSeparator() {
        assertThat(CardNameNormalizer.normalize("Fire /// Ice")).isEqualTo("Fire // Ice");
        assertThat(CardNameNormalizer.normalize("Fire // Ice")).isEqualTo("Fire // Ice");
    }

    @Test
    void treatsNullAndBlankAsEmpty() {
        assertThat(CardNameNormalizer.normalize(null)).isEmpty();
        assertThat(CardNameNormalizer.normalize("   ")).isEmpty();
    }
}
