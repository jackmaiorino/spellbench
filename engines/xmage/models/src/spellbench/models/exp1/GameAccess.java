package spellbench.models.exp1;

import mage.MageObject;
import mage.constants.PhaseStep;
import mage.game.Game;
import mage.game.GameImpl;
import mage.game.GameState;
import mage.game.permanent.Permanent;
import mage.game.stack.StackObject;
import mage.players.Player;
import spellbench.models.Exp1Compat;

import java.lang.reflect.Field;
import java.util.IdentityHashMap;
import java.util.Map;
import java.util.UUID;

/** Fork core helpers, scoped to this process's permitted reconstructed games. */
public final class GameAccess {
    private GameAccess() { }
    public static final UUID STOP_CHOOSING = new UUID(0, "stop choosing flag".hashCode());
    private static final Map<Game, Game> anchors = new IdentityHashMap<>();

    public static void reset() { anchors.clear(); }
    public static Player opponent(Game game, UUID player) { return Exp1Compat.opponent(game, player); }
    public static PlayerScript history(Player player) {
        return player instanceof ComputerPlayer ? ((ComputerPlayer) player).getPlayerHistory() : new PlayerScript();
    }
    public static void setLastPriority(Game game, UUID player) {
        for (Player p : game.getPlayers().values()) history(p).clear();
        if (!game.isSimulation()) anchors.put(game, game.copy());
    }
    public static Game lastPriority(Game game) {
        Game anchor = anchors.get(game);
        return anchor == null ? game : anchor;
    }
    public static boolean checkPoint(Game game, UUID player) {
        if (manualTap(game.getPlayer(player)) || manualTap(opponent(game, player))) return true;
        PhaseStep step = game.getTurnStepType();
        return (game.getTurnNum() == 1 && step == PhaseStep.UPKEEP) || step == PhaseStep.BEGIN_COMBAT
                || step == PhaseStep.DECLARE_ATTACKERS || step == PhaseStep.DECLARE_BLOCKERS;
    }
    public static boolean manualTap(Player player) {
        return player instanceof ComputerPlayer && ((ComputerPlayer) player).isManualTappingAI();
    }
    public static String entityName(Game game, UUID id, UUID viewer) { return Exp1Compat.entityName(game, id, viewer); }
    public static String entityValue(Game game, UUID id, UUID viewer) {
        String name = entityName(game, id, viewer);
        MageObject object = game.getObject(id);
        if (object instanceof StackObject) object = game.getObject(((StackObject) object).getSourceId());
        return name + (object instanceof Permanent ? Exp1Compat.permanentValue((Permanent) object, game, viewer) : "");
    }
    public static void setState(Game game, GameState state) {
        // Same event-free state injection as WorldBuilder. No live game is reachable.
        try {
            Field field = GameImpl.class.getDeclaredField("state");
            field.setAccessible(true);
            field.set(game, state);
        } catch (ReflectiveOperationException e) { throw new IllegalStateException("search state restore failed", e); }
    }
    public static void setMctsSimulation(Game game, boolean enabled) {
        // The reviewed engine has the simulation flag. The fork's separate
        // flag also changes a combat retry shortcut; full combat qualification
        // must account for that engine difference.
        if (!enabled || !game.isSimulation()) throw new IllegalArgumentException("search requires a simulation game");
    }
}
