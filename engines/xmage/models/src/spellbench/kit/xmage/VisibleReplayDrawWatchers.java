package spellbench.kit.xmage;

import mage.game.events.GameEvent;
import mage.watchers.Watcher;
import mage.watchers.common.CardsDrawnThisTurnWatcher;

/** Restore only draw counters proved by a received public second-draw trigger. */
final class VisibleReplayDrawWatchers {
    private VisibleReplayDrawWatchers() { }

    static void restore(World world, int priorOwnDraws) {
        if (priorOwnDraws == 0) return;
        if (priorOwnDraws != 1 || !world.flags.contains("approximate:watchers_reset")) {
            throw new IllegalArgumentException("public draw watcher replay needs a fresh reconstructed world");
        }
        CardsDrawnThisTurnWatcher total = world.game.getState().getWatcher(CardsDrawnThisTurnWatcher.class);
        Watcher nth;
        try {
            // The pinned engine keeps this watcher package-private. Resolve its
            // fixed class, never an input-supplied class or a live game watcher.
            Class<? extends Watcher> type = Class.forName("mage.abilities.common.DrawNthCardWatcher")
                    .asSubclass(Watcher.class);
            nth = world.game.getState().getWatcher(type);
        } catch (ClassNotFoundException failure) {
            throw new IllegalArgumentException("pinned draw watcher is unavailable", failure);
        }
        if (total == null || nth == null || total.getCardsDrawnThisTurn(world.player(world.viewer)) != 0) {
            throw new IllegalArgumentException("public draw watcher replay lacks fresh matching counters");
        }
        // Update these two counters only. Do not fire an event, draw a card,
        // inject a pending trigger, or seed unrelated watcher state. The next
        // real draw will generate the observed Mystic trigger through XMage.
        world.random.scopeWorld("replay-public-draw-watcher");
        try {
            GameEvent event = GameEvent.getEvent(GameEvent.EventType.DREW_CARD, null, null,
                    world.player(world.viewer));
            total.watch(event, world.game);
            nth.watch(event, world.game);
        } finally {
            world.random.scopeWorld("play");
        }
        world.flags.add("replay:public_second_draw_watcher_conditioning");
    }
}
