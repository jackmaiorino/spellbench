package spellbench.kit.xmage;

import mage.player.ai.ComputerPlayer;
import mage.players.Player;
import spellbench.kit.core.Json;

import java.lang.reflect.InvocationTargetException;
import java.util.Map;

/**
 * Reconstruct with setup players, then install the actual private callback player.
 * The returned player still requires permitted-world admission and a model session.
 * No heuristic setup player is used to answer the observed decision.
 */
public final class JackPlayerBootstrap {
    private JackPlayerBootstrap() { }

    public static World build(WorldBuilder.Spec input) {
        if (input == null || input.observation == null || input.viewerFactory != null || input.otherFactory != null)
            throw new IllegalArgumentException("Jack reconstruction owns both setup player factories");
        String viewer = Json.str(input.observation, "viewer");
        if (!WorldBuilder.SEATS.contains(viewer))
            throw new IllegalArgumentException("Jack reconstruction requires an observed viewer");
        int mulligans = observedMulligans(input.observation, viewer);
        // Preserve the caller's spec for deterministic replay or another sampled world.
        WorldBuilder.Spec spec = new WorldBuilder.Spec();
        spec.gameStart = input.gameStart; spec.observation = input.observation;
        spec.sample = input.sample; spec.random = input.random; spec.mode = input.mode;
        spec.index = input.index; spec.combatDamageStep = input.combatDamageStep; spec.history = input.history;
        spec.viewerFactory = seat -> new KitMad(seat, 10);
        spec.otherFactory = Puppet::new;
        World world = WorldBuilder.build(spec);
        replaceViewer(world, mulligans);
        return world;
    }

    static int observedMulligans(Map<String, Object> observation, String viewer) {
        Integer count = null;
        for (Object item : Json.arr(observation, "players")) {
            Map<String, Object> player = Json.obj(item);
            if (!viewer.equals(Json.str(player, "seat"))) continue;
            Object value = player.get("mulligans_taken");
            if (count != null || !(value instanceof Long || value instanceof Integer)
                    || ((Number) value).longValue() < 0 || ((Number) value).longValue() > 7)
                throw new IllegalArgumentException("one observed London mulligan count required");
            count = ((Number) value).intValue();
        }
        if (count == null) throw new IllegalArgumentException("observed viewer mulligan count required");
        return count;
    }

    // Package-private: callers must enter through permitted-input reconstruction.
    static void replaceViewer(World world, int mulligans) {
        if (world == null || world.game == null || world.game.isSimulation() || mulligans < 0 || mulligans > 7)
            throw new IllegalArgumentException("initialized reconstruction root required");
        Player old = world.viewerPlayer();
        if (old == null || old.getClass() != KitMad.class || !((KitMad) old).setup
                || world.game.getState().getPlayers().get(old.getId()) != old
                || world.game.getPlayers().get(old.getId()) != old)
            throw new IllegalArgumentException("owned setup viewer required before replacement");
        final Player player;
        try {
            player = (Player) Class.forName("spellbench.models.jack.OriginalCallbackPlayer")
                    .getConstructor(ComputerPlayer.class, int.class).newInstance(old, mulligans);
        } catch (InvocationTargetException failure) {
            Throwable cause = failure.getCause();
            if (cause instanceof RuntimeException) throw (RuntimeException) cause;
            if (cause instanceof Error) throw (Error) cause;
            throw new IllegalArgumentException("original bootstrap construction failed", cause);
        } catch (ReflectiveOperationException failure) {
            throw new IllegalArgumentException("staged original callback player unavailable", failure);
        }
        if (player == old || !old.getId().equals(player.getId()) || !old.getName().equals(player.getName()))
            throw new IllegalArgumentException("original bootstrap changed player identity");
        world.game.getState().getPlayers().put(old.getId(), player);
        if (world.viewerPlayer() != player || world.game.getPlayers().get(old.getId()) != player)
            throw new IllegalStateException("original viewer replacement was not installed");
    }
}
