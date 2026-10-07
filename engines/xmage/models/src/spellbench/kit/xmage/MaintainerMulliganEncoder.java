package spellbench.kit.xmage;

import mage.game.Game;
import mage.players.Player;
import spellbench.kit.core.Json;
import spellbench.kit.core.Sampler;
import spellbench.kit.core.Seeds;

import java.lang.reflect.InvocationTargetException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** Source-backed mulligan features on a permitted pregame world. */
public final class MaintainerMulliganEncoder {
    private MaintainerMulliganEncoder() { }
    public static final String SOURCE_SHA256 = "69e039a69c5d983f5614d6a9c7efc77a7cf9f0ca1df64851d642d0f2ad718497";
    public static final String VARIANT = "original own-hand features and remaining-library multiset; library sorted by card name; no hidden order";

    public static Map<String, Object> encode(Map<String, Object> start, Map<String, Object> decision,
                                             byte[] worldSeed, byte[] idSeed) throws Exception {
        Map<String, Object> obs = Json.obj(Json.copy(decision.get("observation")));
        String viewer = Json.str(obs, "viewer");
        if (viewer == null || !viewer.equals(Json.str(start, "seat"))
                || !viewer.equals(Json.str(decision, "acting_seat"))
                || !"pregame".equals(Json.str(obs, "phase_step"))) {
            throw new IllegalArgumentException("the maintainer's mulligan requires its own acting pregame viewer");
        }
        List<Object> offered = Json.arr(decision, "candidates");
        Set<Object> ids = new HashSet<>(), choices = new HashSet<>();
        if (offered == null || offered.size() != 2) {
            throw new IllegalArgumentException("the maintainer's mulligan features require both offered decisions");
        }
        for (Object item : offered) {
            Map<String, Object> c = Json.obj(item), semantic = Json.obj(c, "semantic");
            Object id = c.get("candidate_id"), keep = semantic.get("keep");
            if (!(id instanceof Long) || (Long) id < 0 || !ids.add(id)
                    || !"mulligan".equals(Json.str(semantic, "kind"))
                    || !(keep instanceof Boolean) || !choices.add(keep)) {
                throw new IllegalArgumentException("the maintainer's mulligan choices are unbound or aliased");
            }
        }
        Map<String, Object> player = null;
        for (Object item : Json.arr(obs, "players")) {
            Map<String, Object> p = Json.obj(item);
            if (viewer.equals(Json.str(p, "seat"))) {
                if (player != null) throw new IllegalArgumentException("duplicate acting mulligan player");
                player = p;
            }
        }
        Object count = player == null ? null : player.get("mulligans_taken");
        if (!(count instanceof Long) || (Long) count < 0 || (Long) count > 7) {
            throw new IllegalArgumentException("mulligan count must be the observed nonnegative integer");
        }
        List<Object> handRecords = Json.arr(player, "hand");
        if (handRecords == null || handRecords.size() < 1 || handRecords.size() > 7
                || !(player.get("hand_count") instanceof Long)
                || (Long) player.get("hand_count") != handRecords.size()) {
            throw new IllegalArgumentException("mulligan hand must be completely visible to its owner");
        }
        for (Object item : offered) {
            Map<String, Object> semantic = Json.obj(Json.obj(item), "semantic");
            if (!count.equals(semantic.get("mulligans_taken"))
                    || !Long.valueOf(handRecords.size()).equals(semantic.get("hand_size"))) {
                throw new IllegalArgumentException("mulligan semantic differs from its observed hand and counter");
            }
        }
        String staged = System.getProperty("spellbench.maintainer.mulliganEncoderSourceSha256");
        if (staged == null || !staged.matches("[a-f0-9]{64}")) {
            throw new IllegalArgumentException("the maintainer's mulligan needs its staged source identity");
        }
        KitContext.reset(); KitRandom.installBoot();
        List<String> names = WorldBuilder.restoreVisibleNames(obs, Json.obj(decision, "x_history"));
        KitRandom random = KitRandom.install(worldSeed, idSeed);
        Sampler.Sample sample = Sampler.sample(start, obs, random.stream("sampler"));
        Sampler.SeatSample own = sample.seats.get(viewer);
        if (own == null || own.deficit != 0 || own.surplus != 0 || !own.faceDown.isEmpty()
                || own.library.size() > 60 || !own.hand.isEmpty()) {
            throw new IllegalArgumentException("own remaining deck cannot be reconstructed exactly");
        }
        WorldBuilder.Spec spec = new WorldBuilder.Spec();
        spec.gameStart = start; spec.observation = obs; spec.sample = sample; spec.random = random;
        spec.mode = WorldBuilder.Mode.PREGAME;
        spec.viewerFactory = seat -> new KitMad(seat, 6); spec.otherFactory = Puppet::new;
        spec.history = Json.obj(decision, "x_history");
        World world = WorldBuilder.build(spec); world.flags.addAll(names);
        for (String flag : world.flags) {
            if (flag.startsWith("unsupported:") || flag.startsWith("horizon:")) {
                throw new IllegalArgumentException("unsupported reconstructed mulligan world: " + flag);
            }
        }
        Class<?> codec = Class.forName("spellbench.models.maintainer.MulliganEncoder");
        if (!SOURCE_SHA256.equals(codec.getField("SOURCE_SHA256").get(null))) {
            throw new IllegalArgumentException("the maintainer's mulligan codec differs from its original source");
        }
        float[] values;
        try {
            values = (float[]) codec.getMethod("features", Player.class, Game.class, int.class)
                    .invoke(codec.getConstructor().newInstance(), world.viewerPlayer(), world.game, ((Long) count).intValue());
        } catch (InvocationTargetException e) {
            if (e.getCause() instanceof RuntimeException) throw (RuntimeException) e.getCause();
            if (e.getCause() instanceof Error) throw (Error) e.getCause();
            throw e;
        }
        if (values.length != 71) throw new IllegalArgumentException("wrong original mulligan feature width");
        List<Object> result = new ArrayList<>();
        for (int i = 0; i < values.length; i++) {
            float v = values[i];
            if (!Float.isFinite(v) || v < 0 || v > 1000000
                    || i != 3 && v != (int) v || i >= 4 && v >= 65536) {
                throw new IllegalArgumentException("invalid original mulligan feature or token");
            }
            if (i == 3) result.add((double) v); else result.add((long) v);
        }
        int hand = world.viewerPlayer().getHand().size();
        return Json.map("schema", "spellbench-maintainer-mulligan-features/v1", "kind", "mulligan", "values", result,
                "decision_sha256", hash(decision), "game_start_sha256", hash(start),
                "original_mulligan_encoder_sha256", SOURCE_SHA256, "mulligan_encoder_source_sha256", staged,
                "mulligans_taken", count, "hand_size", (long) hand, "remaining_library_size", (long) own.library.size(),
                "variant", VARIANT, "world_flags", world.flags,
                "scope", "original evaluation mulligan feature component; other callbacks and full game qualification unfinished");
    }
    static String hash(Map<String, Object> value) throws Exception {
        return Seeds.hex(MessageDigest.getInstance("SHA-256").digest(Json.canonical(value).getBytes(StandardCharsets.UTF_8)));
    }
}
