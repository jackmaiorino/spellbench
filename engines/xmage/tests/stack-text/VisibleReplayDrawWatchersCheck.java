package spellbench.kit.xmage;

import mage.abilities.common.DrawNthCardTriggeredAbility;
import mage.abilities.effects.common.InfoEffect;
import mage.game.Game;
import mage.game.events.GameEvent;
import mage.constants.WatcherScope;
import mage.watchers.Watcher;
import mage.watchers.common.CardsDrawnThisTurnWatcher;

import java.util.UUID;

/** Exercise the pinned engine's actual second-draw trigger without any live or hidden game input. */
public final class VisibleReplayDrawWatchersCheck {
    private static final class OtherWatcher extends Watcher {
        int calls;
        OtherWatcher() { super(WatcherScope.GAME); }
        @Override public void watch(GameEvent event, Game game) { calls++; }
    }

    private static void require(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    public static void main(String[] args) {
        KitRandom random = KitRandom.install(new byte[32], new byte[32]);
        KitDuel game = new KitDuel();
        World world = new World(game, "p0", 0, random);
        UUID own = new UUID(0, 1), other = new UUID(0, 2);
        world.seatPlayer.put("p0", own); world.seatPlayer.put("p1", other);
        world.flags.add("approximate:watchers_reset");
        CardsDrawnThisTurnWatcher total = new CardsDrawnThisTurnWatcher();
        DrawNthCardTriggeredAbility ability = new DrawNthCardTriggeredAbility(new InfoEffect("observed trigger"));
        ability.setControllerId(own);
        Watcher nth = ability.getWatchers().get(0);
        OtherWatcher unrelated = new OtherWatcher();
        game.getState().addWatcher(total); game.getState().addWatcher(nth); game.getState().addWatcher(unrelated);
        // GameState may already install a default watcher under the same key.
        // Test the installed instances used by the actual ability, not a spare.
        total = game.getState().getWatcher(CardsDrawnThisTurnWatcher.class);
        nth = game.getState().getWatcher(nth.getKey());
        VisibleReplayDrawWatchers.restore(world, 0);
        require(total.getCardsDrawnThisTurn(own) == 0, "unknown past draw count changed");
        VisibleReplayDrawWatchers.restore(world, 1);
        require(total.getCardsDrawnThisTurn(own) == 1 && total.getCardsDrawnThisTurn(other) == 0,
                "public history seeded a wrong player or count");
        require(unrelated.calls == 0, "unrelated watcher was seeded");
        require("world:play".equals(random.idScope()), "replay changed the engine ID stream");
        GameEvent next = GameEvent.getEvent(GameEvent.EventType.DREW_CARD, null, null, own);
        total.watch(next, game); nth.watch(next, game);
        require(ability.checkTrigger(next, game), "actual pinned second-draw ability did not trigger");
        require(total.getCardsDrawnThisTurn(own) == 2, "actual draw did not advance the restored count");
        try {
            VisibleReplayDrawWatchers.restore(world, 1);
            throw new AssertionError("nonfresh watcher state accepted");
        } catch (IllegalArgumentException expected) {
            require(total.getCardsDrawnThisTurn(own) == 2, "refusal mutated a watcher");
        }
        System.out.println("public second-draw watcher replay: PASS");
    }
}
