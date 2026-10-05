// Vendored from XMage fd40ad5c (MIT, see engines/xmage/NOTICE). Kit changes are marked KIT; the diff is published in kit/diffs/.


package mage.player.ai;

import java.util.concurrent.Callable;
import mage.abilities.Ability;
import mage.game.Game;
import org.apache.log4j.Logger;

/**
 *
 * @author BetaSteward_at_googlemail.com
 */
public class SimulationWorker2 implements Callable {

    private static final Logger logger = Logger.getLogger(SimulationWorker2.class);

    private Game game;
    private SimulatedAction2 previousActions;
    private Ability action;
    private SimulatedPlayer2 player;

    public SimulationWorker2(Game game, SimulatedPlayer2 player, SimulatedAction2 previousActions, Ability action) {
        this.game = game;
        this.player = player;
        this.previousActions = previousActions;
        this.action = action;
    }

    @Override
    public Object call() {
        try {
//            player.simulateAction(game, previousActions, action);
        } catch (Exception ex) {
            logger.error(null, ex);
        }
        return null;
    }

}

