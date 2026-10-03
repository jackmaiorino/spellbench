package spellbench.kit.xmage;

import mage.constants.TurnPhase;
import mage.game.Game;
import spellbench.kit.core.Json;
import spellbench.kit.core.ObsIndex;
import spellbench.kit.core.Sampler;
import spellbench.kit.core.Seeds;

import java.lang.reflect.InvocationTargetException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/** Base-state feature port. Candidate encoding and full play are unfinished. */
public final class JackEncoder {
    private JackEncoder() { }
    public static final String VARIANT = "acting-player perspective; named permitted entity references only; "
            + "explicitly known library cards ordered by public alias; pinned read-only embeddings";

    public static Map<String, Object> encode(Map<String, Object> start, Map<String, Object> decision,
                                             byte[] worldSeed, byte[] idSeed) throws Exception {
        Map<String, Object> obs = Json.obj(Json.copy(decision.get("observation")));
        String viewer = Json.str(obs, "viewer");
        if (viewer == null || !viewer.equals(Json.str(decision, "acting_seat"))
                || !"priority".equals(Json.str(Json.obj(decision, "context"), "kind"))) {
            throw new IllegalArgumentException("Jack base encoder currently requires the acting viewer's priority");
        }
        String source = System.getProperty("spellbench.jack.encoderSourceSha256");
        if (source == null || !source.matches("[a-f0-9]{64}")) {
            throw new IllegalArgumentException("Jack encoder needs its staged source identity");
        }
        KitContext.reset();
        KitRandom.installBoot();
        List<String> names = WorldBuilder.restoreVisibleNames(obs, Json.obj(decision, "x_history"));
        KitRandom random = KitRandom.install(worldSeed, idSeed);
        WorldBuilder.Spec spec = new WorldBuilder.Spec();
        spec.gameStart = start;
        spec.observation = obs;
        spec.sample = Sampler.sample(start, obs, random.stream("sampler"));
        spec.random = random;
        spec.mode = WorldBuilder.Mode.PRIORITY;
        spec.viewerFactory = seat -> new KitMad(seat, 6);
        spec.otherFactory = Puppet::new;
        spec.history = Json.obj(decision, "x_history");
        World world = WorldBuilder.build(spec);
        world.flags.addAll(names);
        for (String flag : world.flags) {
            if (flag.startsWith("unsupported:") || flag.startsWith("horizon:")) {
                throw new IllegalArgumentException("Jack encoded world is unsupported: " + flag);
            }
        }
        ObsIndex index = new ObsIndex(obs);
        Map<UUID, String> permitted = new LinkedHashMap<>();
        for (String alias : index.ids()) {
            Map<String, Object> ref = index.ref(alias);
            String name = Json.str(ref, "card_name");
            UUID id = world.idToUuid.get(alias);
            if (name != null && !name.isEmpty() && id != null) permitted.put(id, alias);
        }
        Class<?> encoder = Class.forName("spellbench.models.jack.StateSequenceBuilder");
        Object state;
        try {
            state = encoder.getMethod("buildBaseState", Game.class, TurnPhase.class, int.class, UUID.class, Map.class)
                    .invoke(null, world.game, world.game.getPhase() == null ? null : world.game.getPhase().getType(),
                            256, world.player(viewer), permitted);
        } catch (InvocationTargetException e) {
            if (e.getCause() instanceof RuntimeException) throw (RuntimeException) e.getCause();
            if (e.getCause() instanceof Error) throw (Error) e.getCause();
            throw e;
        }
        float[][] tokens = (float[][]) state.getClass().getField("tokens").get(state);
        int[] masks = (int[]) state.getClass().getField("mask").get(state);
        int[] ids = (int[]) state.getClass().getField("tokenIds").get(state);
        if (tokens.length != 256 || masks.length != 256 || ids.length != 256) {
            throw new IllegalArgumentException("Jack base encoder returned the wrong sequence shape");
        }
        List<Object> sequence = new ArrayList<>(), padding = new ArrayList<>(), tokenIds = new ArrayList<>();
        for (int i = 0; i < tokens.length; i++) {
            if (tokens[i].length != 128 || (masks[i] != 0 && masks[i] != 1) || ids[i] < 0 || ids[i] >= 65536) {
                throw new IllegalArgumentException("Jack base encoder returned an invalid vector or token");
            }
            List<Object> row = new ArrayList<>();
            for (float value : tokens[i]) {
                if (!Float.isFinite(value) || Math.abs(value) > 1000000) {
                    throw new IllegalArgumentException("Jack base encoder returned invalid numeric features");
                }
                row.add((double) value);
            }
            sequence.add(row);
            padding.add(masks[i] == 1);
            tokenIds.add((long) ids[i]);
        }
        return Json.map("schema", "spellbench-jack-base-features/v1", "sequence", sequence,
                "padding", padding, "token_ids", tokenIds,
                "decision_sha256", Seeds.hex(MessageDigest.getInstance("SHA-256")
                        .digest(Json.canonical(decision).getBytes(StandardCharsets.UTF_8))),
                "encoder_source_sha256", source,
                "embedding_cache_sha256", System.getProperty("spellbench.jack.embeddingSha256"),
                "variant", VARIANT, "world_flags", world.flags,
                "scope", "base-state features only; no trained candidate mapping or game qualification");
    }
}
