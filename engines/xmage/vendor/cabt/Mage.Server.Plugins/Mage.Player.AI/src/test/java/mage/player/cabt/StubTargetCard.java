package mage.player.cabt;

import mage.abilities.Ability;
import mage.constants.Zone;
import mage.filter.FilterCard;
import mage.game.Game;
import mage.target.TargetCard;

import java.util.Collection;
import java.util.LinkedHashSet;
import java.util.Set;
import java.util.UUID;

/**
 * Test fixture: a TargetCard with a fixed set of possible cards, exercising
 * the real TargetCard selection state without a full game to search zones in.
 */
class StubTargetCard extends TargetCard {

    private final Set<UUID> possible;

    StubTargetCard(int minTargets, int maxTargets, Collection<UUID> possible) {
        super(minTargets, maxTargets, Zone.GRAVEYARD, new FilterCard());
        this.possible = new LinkedHashSet<UUID>(possible);
    }

    private StubTargetCard(StubTargetCard other) {
        super(other);
        this.possible = other.possible;
    }

    @Override
    public Set<UUID> possibleTargets(UUID sourceControllerId, Ability source, Game game) {
        Set<UUID> result = new LinkedHashSet<UUID>(possible);
        result.removeAll(getTargets());
        return result;
    }

    @Override
    public Set<UUID> possibleTargets(UUID sourceControllerId, Ability source, Game game, Set<UUID> cards) {
        Set<UUID> result = possibleTargets(sourceControllerId, source, game);
        result.retainAll(cards);
        return result;
    }

    @Override
    public StubTargetCard copy() {
        return new StubTargetCard(this);
    }
}
