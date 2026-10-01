package mage.player.cabt;

import mage.abilities.Ability;
import mage.filter.Filter;
import mage.filter.FilterCard;
import mage.game.Game;
import mage.target.TargetImpl;

import java.util.Collection;
import java.util.LinkedHashSet;
import java.util.Set;
import java.util.UUID;

/**
 * Test fixture: a Target with a fixed set of possible targets, exercising
 * the real TargetImpl selection state (targets map, min/max, isChosen).
 */
class StubTarget extends TargetImpl {

    private final Set<UUID> possible;

    StubTarget(int minTargets, int maxTargets, Collection<UUID> possible) {
        setMinNumberOfTargets(minTargets);
        setMaxNumberOfTargets(maxTargets);
        this.possible = new LinkedHashSet<UUID>(possible);
    }

    private StubTarget(StubTarget other) {
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
    public boolean canTarget(UUID id, Ability source, Game game) {
        return possible.contains(id);
    }

    @Override
    public boolean canTarget(UUID playerId, UUID id, Ability source, Game game) {
        return possible.contains(id);
    }

    @Override
    public boolean canChoose(UUID sourceControllerId, Ability source, Game game) {
        return !possibleTargets(sourceControllerId, source, game).isEmpty();
    }

    @Override
    public Filter getFilter() {
        return new FilterCard();
    }

    @Override
    public String getTargetedName(Game game) {
        return "stub target";
    }

    @Override
    public StubTarget copy() {
        return new StubTarget(this);
    }
}
