package mage.player.spellbench.x1;

import java.lang.reflect.Method;
import java.util.Map;
import java.util.UUID;

/**
 * Reaches {@code mage.player.spellbench.rng.GameRandom} by reflection, so the X1 harness compiles and runs on a
 * stock build (no X-P1 to X-P3, no router) as the negative control.
 */
final class RouterBridge {

    private static final String ROUTER = "mage.player.spellbench.rng.GameRandom";

    private RouterBridge() {
    }

    static boolean available() {
        try {
            Class.forName("mage.util.RandomUtil$Source");
            Class.forName(ROUTER);
            return true;
        } catch (ClassNotFoundException e) {
            return false;
        }
    }

    static Object installBoot() {
        return call(null, "installBoot", new Class<?>[0]);
    }

    static Object install(byte[] gameSecret) {
        return call(null, "install", new Class<?>[]{byte[].class}, (Object) gameSecret);
    }

    static void assignSeat(Object router, UUID playerId, String seat) {
        call(router, "assignSeat", new Class<?>[]{UUID.class, String.class}, playerId, seat);
    }

    @SuppressWarnings("unchecked")
    static Map<String, Long> usage(Object router) {
        return (Map<String, Long>) call(router, "usage", new Class<?>[0]);
    }

    private static Object call(Object target, String name, Class<?>[] types, Object... args) {
        try {
            Method m = Class.forName(ROUTER).getMethod(name, types);
            return m.invoke(target, args);
        } catch (ReflectiveOperationException e) {
            throw new IllegalStateException("router call " + name + " failed", e);
        }
    }
}
