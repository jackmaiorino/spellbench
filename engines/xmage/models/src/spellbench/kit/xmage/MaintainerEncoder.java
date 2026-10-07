package spellbench.kit.xmage;

import mage.constants.TurnPhase;
import mage.abilities.Ability;
import mage.abilities.common.PassAbility;
import mage.game.Game;
import mage.players.Player;
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
import java.util.HashSet;
import java.util.Set;

/** Permitted base-state and original priority features. Full play is unfinished. */
public final class MaintainerEncoder {
    private MaintainerEncoder() { }
    public static final String VARIANT = "acting-player perspective; named permitted entity references only; "
            + "explicitly known library cards ordered by public alias; pinned read-only embeddings";

    public static Map<String, Object> encode(Map<String, Object> start, Map<String, Object> decision,
                                             byte[] worldSeed, byte[] idSeed) throws Exception {
        Map<String, Object> obs = Json.obj(Json.copy(decision.get("observation")));
        String viewer = Json.str(obs, "viewer");
        if (viewer == null || !viewer.equals(Json.str(decision, "acting_seat"))
                || !"priority".equals(Json.str(Json.obj(decision, "context"), "kind"))) {
            throw new IllegalArgumentException("the maintainer's base encoder currently requires the acting viewer's priority");
        }
        for (Object value : Json.arr(decision, "candidates")) {
            if ("activate_mana_ability".equals(Json.obj(Json.obj(value), "semantic").get("kind"))) {
                Object rawProfile = start.get("engine_profile");
                Object kinds = rawProfile instanceof Map ? Json.obj(rawProfile).get("decision_kinds") : null;
                if (!(kinds instanceof List) || !((List<?>) kinds).contains("activate_mana_ability")) {
                    throw new IllegalArgumentException("the maintainer's priority mana requires the declared opt-in engine profile");
                }
            }
        }
        String source = System.getProperty("spellbench.maintainer.encoderSourceSha256");
        String candidatesSource = System.getProperty("spellbench.maintainer.candidateSourceSha256");
        if (source == null || !source.matches("[a-f0-9]{64}") || candidatesSource == null
                || !candidatesSource.matches("[a-f0-9]{64}")) {
            throw new IllegalArgumentException("the maintainer's encoder needs both staged source identities");
        }
        List<Object> offered = Json.arr(decision, "candidates");
        if (offered == null || offered.isEmpty() || offered.size() > 64) {
            throw new IllegalArgumentException("the maintainer's priority requires 1 to 64 offered choices; no silent truncation");
        }
        Set<Object> offeredIds = new HashSet<>();
        for (Object value : offered) {
            Object id = Json.obj(value).get("candidate_id");
            if (!(id instanceof Long) || (Long) id < 0 || !offeredIds.add(id)) {
                throw new IllegalArgumentException("offered candidate IDs must be unique nonnegative integers");
            }
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
                throw new IllegalArgumentException("the maintainer's encoded world is unsupported: " + flag);
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
        Class<?> encoder = Class.forName("spellbench.models.maintainer.StateSequenceBuilder");
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
            throw new IllegalArgumentException("the maintainer's base encoder returned the wrong sequence shape");
        }
        List<Object> sequence = new ArrayList<>(), padding = new ArrayList<>(), tokenIds = new ArrayList<>();
        for (int i = 0; i < tokens.length; i++) {
            if (tokens[i].length != 128 || (masks[i] != 0 && masks[i] != 1) || ids[i] < 0 || ids[i] >= 65536) {
                throw new IllegalArgumentException("the maintainer's base encoder returned an invalid vector or token");
            }
            List<Object> row = new ArrayList<>();
            for (float value : tokens[i]) {
                if (!Float.isFinite(value) || Math.abs(value) > 1000000) {
                    throw new IllegalArgumentException("the maintainer's base encoder returned invalid numeric features");
                }
                row.add((double) value);
            }
            sequence.add(row);
            padding.add(masks[i] == 1);
            tokenIds.add((long) ids[i]);
        }
        Class<?> codec = Class.forName("spellbench.models.maintainer.CandidateEncoder");
        String originalCallback = (String) codec.getField("SOURCE_SHA256").get(null);
        if (!"b45257a66fc3914506fca4dd83461b6c8853d129b3e1f38b2d3aeba6137bd0c6".equals(originalCallback)) {
            throw new IllegalArgumentException("the maintainer's priority codec is not the pinned April source");
        }
        Object candidateEncoder = codec.getConstructor(Player.class).newInstance(world.viewerPlayer());
        List<Object> candidateFeatures = new ArrayList<>(), candidateIds = new ArrayList<>();
        List<Object> candidateMask = new ArrayList<>(), refs = new ArrayList<>();
        for (int i = 0; i < 64; i++) {
            float[] features = new float[48];
            int actionId = 0;
            if (i < offered.size()) {
                Map<String, Object> candidate = Json.obj(offered.get(i));
                Map<String, Object> semantic = Json.obj(candidate, "semantic");
                String kind = Json.str(semantic, "kind");
                Ability ability;
                if ("pass".equals(kind)) {
                    ability = new PassAbility();
                } else if ("play_land".equals(kind) || "cast_spell".equals(kind)
                        || "activate_ability".equals(kind) || "special_action".equals(kind)
                        || "activate_mana_ability".equals(kind)) {
                    ability = Mapping.findPlayable(world, world.viewerPlayer(), semantic, index);
                    if (ability == null || !permitted.containsKey(ability.getSourceId())) {
                        throw new IllegalArgumentException("offered maintainer priority action lacks a named permitted source");
                    }
                } else {
                    throw new IllegalArgumentException("unsupported maintainer priority semantic: " + kind);
                }
                try {
                    actionId = (Integer) codec.getMethod("priorityId", Game.class, Ability.class)
                            .invoke(candidateEncoder, world.game, ability);
                    features = (float[]) codec.getMethod("priorityFeatures", Game.class, Ability.class, state.getClass())
                            .invoke(candidateEncoder, world.game, ability, state);
                } catch (InvocationTargetException e) {
                    if (e.getCause() instanceof RuntimeException) throw (RuntimeException) e.getCause();
                    if (e.getCause() instanceof Error) throw (Error) e.getCause();
                    throw e;
                }
                if (features.length != 48 || actionId <= 0 || actionId >= 65536) {
                    throw new IllegalArgumentException("the maintainer's priority codec returned an invalid feature shape or ID");
                }
                refs.add(Json.map("candidate_id", candidate.get("candidate_id"), "index", (long) i));
            }
            List<Object> values = new ArrayList<>();
            for (float value : features) {
                if (!Float.isFinite(value) || Math.abs(value) > 1000000) {
                    throw new IllegalArgumentException("the maintainer's priority codec returned invalid numeric features");
                }
                values.add((double) value);
            }
            candidateFeatures.add(values);
            candidateIds.add((long) actionId);
            candidateMask.add(i < offered.size());
        }
        return Json.map("schema", "spellbench-maintainer-priority-features/v1", "kind", "candidates", "head", "action",
                "sequence", sequence,
                "padding", padding, "token_ids", tokenIds,
                "candidate_features", candidateFeatures, "candidate_ids", candidateIds,
                "candidate_mask", candidateMask, "candidate_refs", refs,
                "decision_sha256", Seeds.hex(MessageDigest.getInstance("SHA-256")
                        .digest(Json.canonical(decision).getBytes(StandardCharsets.UTF_8))),
                "encoder_source_sha256", source,
                "candidate_source_sha256", candidatesSource, "original_callback_sha256", originalCallback,
                "embedding_cache_sha256", System.getProperty("spellbench.maintainer.embeddingSha256"),
                "variant", VARIANT, "world_flags", world.flags,
                "scope", "original priority IDs and features, fixed 64-candidate padding; no other callbacks or game qualification");
    }
}
