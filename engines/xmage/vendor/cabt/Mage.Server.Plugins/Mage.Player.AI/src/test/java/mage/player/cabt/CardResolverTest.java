package mage.player.cabt;

import mage.cards.Card;
import mage.cards.CardSetInfo;
import mage.cards.g.GrizzlyBears;
import mage.cards.repository.CardInfo;
import mage.constants.Rarity;
import org.junit.jupiter.api.Test;

import java.util.HashMap;
import java.util.Map;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * Branch-level tests for {@link CardResolver} driven by a fake repository, so
 * they run in milliseconds without a scanned card database: repository-first
 * precedence, normalization-then-retry, the class-name heuristic fallback, and
 * fail-closed behavior on unknown names. The repository's real
 * behavior against actual card data is covered by
 * {@link CardIdentityRepositoryTest}.
 */
class CardResolverTest {

    /** A repository that only knows the exact names put into it. */
    private static final class FakeRepository implements CardResolver.RepositoryLookup {
        private final Map<String, CardInfo> byName = new HashMap<String, CardInfo>();

        FakeRepository with(String name, CardInfo info) {
            byName.put(name, info);
            return this;
        }

        @Override
        public CardInfo find(String name) {
            return byName.get(name);
        }
    }

    private static CardInfo grizzlyInfo() {
        return new CardInfo(new GrizzlyBears(UUID.randomUUID(),
                new CardSetInfo("Grizzly Bears", "TST", "1", Rarity.COMMON)));
    }

    private static CardResolver resolver(CardResolver.RepositoryLookup repository,
                                         boolean allowHeuristicFallback) {
        return new CardResolver(repository, new CabtDeckFactory(), allowHeuristicFallback);
    }

    @Test
    void exactRepositoryMatchWinsAndBuildsAnOwnedCard() {
        CardResolver resolver = resolver(
                new FakeRepository().with("Grizzly Bears", grizzlyInfo()), true);

        CardResolution resolution = resolver.resolve("Grizzly Bears");

        assertThat(resolution.isResolved()).isTrue();
        assertThat(resolution.strategy()).isEqualTo(CardResolution.Strategy.EXACT);
        assertThat(resolution.requestedName()).isEqualTo("Grizzly Bears");
        assertThat(resolution.normalizedName()).isEqualTo("Grizzly Bears");
        assertThat(resolution.canonicalName()).isEqualTo("Grizzly Bears");
        assertThat(resolution.setCode()).isEqualTo("TST");
        assertThat(resolution.failureCode()).isNull();

        UUID owner = UUID.randomUUID();
        Card card = resolution.createCard(owner);
        assertThat(card.getName()).isEqualTo("Grizzly Bears");
        assertThat(card.getOwnerId()).isEqualTo(owner);
    }

    @Test
    void normalizationIsRetriedWhenTheRawNameMisses() {
        // repository only knows the collapsed spelling
        CardResolver resolver = resolver(
                new FakeRepository().with("Grizzly Bears", grizzlyInfo()), true);

        CardResolution resolution = resolver.resolve("  Grizzly   Bears ");

        assertThat(resolution.isResolved()).isTrue();
        assertThat(resolution.strategy()).isEqualTo(CardResolution.Strategy.NORMALIZED);
        assertThat(resolution.normalizedName()).isEqualTo("Grizzly Bears");
        assertThat(resolution.canonicalName()).isEqualTo("Grizzly Bears");
    }

    @Test
    void repositoryIsPreferredOverTheHeuristicEvenWhenBothCouldResolve() {
        // "Grizzly Bears" is buildable by the heuristic too, but the repository
        // hit must win (carrying set/number the heuristic can't provide)
        CardResolver resolver = resolver(
                new FakeRepository().with("Grizzly Bears", grizzlyInfo()), true);

        CardResolution resolution = resolver.resolve("Grizzly Bears");

        assertThat(resolution.strategy()).isNotEqualTo(CardResolution.Strategy.CLASS_HEURISTIC);
        assertThat(resolution.setCode()).isNotNull();
    }

    @Test
    void fallsBackToTheClassNameHeuristicWhenTheRepositoryHasNothing() {
        CardResolver resolver = resolver(new FakeRepository(), true);

        CardResolution resolution = resolver.resolve("Grizzly Bears");

        assertThat(resolution.isResolved()).isTrue();
        assertThat(resolution.strategy()).isEqualTo(CardResolution.Strategy.CLASS_HEURISTIC);
        assertThat(resolution.canonicalName()).isEqualTo("Grizzly Bears");
        // the heuristic can't know the printing
        assertThat(resolution.setCode()).isNull();
        assertThat(resolution.createCard(UUID.randomUUID()).getName()).isEqualTo("Grizzly Bears");
    }

    @Test
    void unknownNameFailsClosedWithDiagnostics() {
        CardResolver resolver = resolver(new FakeRepository(), true);

        final CardResolution resolution = resolver.resolve("No Such Card Ever Printed");

        assertThat(resolution.isResolved()).isFalse();
        assertThat(resolution.strategy()).isNull();
        assertThat(resolution.canonicalName()).isNull();
        assertThat(resolution.failureCode()).isEqualTo("UNKNOWN_CARD");
        assertThat(resolution.failureReason()).contains("No Such Card Ever Printed");
        assertThatThrownBy(() -> resolution.createCard(UUID.randomUUID()))
                .isInstanceOf(CabtDeckFactory.UnknownCardException.class);
    }

    @Test
    void heuristicFallbackCanBeDisabledSoOnlyTheRepositoryResolves() {
        CardResolver resolver = resolver(new FakeRepository(), false);

        assertThat(resolver.resolve("Grizzly Bears").isResolved()).isFalse();
    }
}
