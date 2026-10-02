package mage.player.cabt;

import mage.constants.MultiplayerAttackOption;
import mage.constants.PhaseStep;
import mage.constants.RangeOfInfluence;
import mage.game.GameImpl;
import mage.game.match.MatchType;
import mage.game.mulligan.MulliganType;
import mage.game.turn.TurnMod;

import java.util.UUID;

/**
 * Test fixture: a real two-player duel on the actual engine loop — a minimal
 * mirror of Mage.Game.TwoPlayerDuel (that plugin is not on this module's
 * classpath). Nothing is stubbed: GameImpl runs turns, priority, the stack,
 * combat, and state-based actions exactly as the server does.
 */
final class CabtSmokeDuel extends GameImpl {

    CabtSmokeDuel() {
        super(MultiplayerAttackOption.LEFT, RangeOfInfluence.ALL,
                MulliganType.GAME_DEFAULT.getMulligan(0), 0, 20, 7);
    }

    private CabtSmokeDuel(final CabtSmokeDuel game) {
        super(game);
    }

    @Override
    public MatchType getGameType() {
        return new CabtSmokeDuelType();
    }

    @Override
    public int getNumPlayers() {
        return 2;
    }

    @Override
    protected void init(UUID choosingPlayerId) {
        super.init(choosingPlayerId);
        // same first-turn draw skip as TwoPlayerDuel
        state.getTurnMods().add(new TurnMod(startingPlayerId).withSkipStep(PhaseStep.DRAW));
    }

    @Override
    public CabtSmokeDuel copy() {
        return new CabtSmokeDuel(this);
    }

    static final class CabtSmokeDuelType extends MatchType {

        CabtSmokeDuelType() {
            this.name = "CABT Smoke Duel";
            this.maxPlayers = 2;
            this.minPlayers = 2;
            this.numTeams = 0;
            this.useAttackOption = false;
            this.useRange = false;
            this.sideboardingAllowed = false;
        }

        private CabtSmokeDuelType(final CabtSmokeDuelType matchType) {
            super(matchType);
        }

        @Override
        public CabtSmokeDuelType copy() {
            return new CabtSmokeDuelType(this);
        }
    }
}
