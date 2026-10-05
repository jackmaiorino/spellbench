package spellbench.kit.xmage;

import mage.abilities.Ability;
import spellbench.models.magezero.v02.encoder.ActionEncoder;
import spellbench.models.magezero.v02.encoder.StateEncoder;
import spellbench.kit.core.Json;
import spellbench.kit.core.ObsIndex;
import spellbench.kit.core.Sampler;
import spellbench.kit.core.Seeds;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

/** The original MageZero v0.2 priority hashes on a permitted sampled world. */
public final class MageZeroEncoder {
    private MageZeroEncoder() { }

    public static Map<String, Object> decision(Map<String, Object> start, Map<String, Object> decision,
                                               byte[] worldSeed, byte[] idSeed) {
        Map<String, Object> context = Json.obj(decision, "context");
        if (context == null || !"priority".equals(Json.str(context, "kind"))) {
            throw new IllegalArgumentException("MageZero currently implements the priority encoder slice only");
        }
        List<Object> candidates = Json.arr(decision, "candidates");
        if (candidates == null || candidates.isEmpty()) {
            throw new IllegalArgumentException("encoded decision has no offered candidates");
        }
        Set<Object> ids = new HashSet<>();
        for (Object candidate : candidates) {
            Object id = Json.obj(candidate).get("candidate_id");
            if (!(id instanceof Long) || (Long) id < 0 || (Long) id > 9007199254740991L || !ids.add(id)) {
                throw new IllegalArgumentException("encoded candidate ids must be unique nonnegative protocol integers");
            }
        }
        Map<String, Object> obs = Json.obj(Json.copy(decision.get("observation")));
        String viewer = Json.str(obs, "viewer");
        if (viewer == null || !viewer.equals(Json.str(start, "seat"))
                || !viewer.equals(Json.str(decision, "acting_seat"))) {
            throw new IllegalArgumentException("MageZero priority slice requires the viewer's own decision");
        }
        KitContext.reset();
        KitRandom.installBoot();
        List<String> nameFlags = WorldBuilder.restoreVisibleNames(obs, Json.obj(decision, "x_history"));
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
        world.flags.addAll(nameFlags);
        for (String flag : world.flags) {
            if (flag.startsWith("unsupported:") || flag.startsWith("horizon:")) {
                throw new IllegalArgumentException("encoded world is unsupported: " + flag);
            }
        }
        UUID agent = world.player(world.viewer);
        StateEncoder encoder = new StateEncoder();
        encoder.setAgent(agent);
        encoder.setOpponent(world.player("p0".equals(world.viewer) ? "p1" : "p0"));
        // Preserve the original hasher and disable its forbidden opponent-hand encoding.
        encoder.perfectInfo = false;
        List<Integer> features = new ArrayList<>(encoder.processState(world.game, agent));
        Collections.sort(features);
        if (features.isEmpty() || features.size() > 16384) {
            throw new IllegalArgumentException("MageZero feature vector exceeds its envelope");
        }
        for (int feature : features) {
            if (feature < 0 || feature >= Integer.MAX_VALUE) {
                throw new IllegalArgumentException("original MageZero feature hash is outside its envelope");
            }
        }
        // Encode before getPlayable, which may update transient player state.
        ActionEncoder actions = new ActionEncoder();
        ObsIndex index = new ObsIndex(obs);
        List<Object> slots = new ArrayList<>();
        for (Object candidate : candidates) {
            Map<String, Object> c = Json.obj(candidate);
            Map<String, Object> semantic = Json.obj(c, "semantic");
            String kind = Json.str(semantic, "kind");
            int slot;
            if ("pass".equals(kind)) {
                slot = 0;
            } else {
                Ability ability = Mapping.findPlayable(world, world.viewerPlayer(), semantic, index);
                if (ability == null) {
                    throw new IllegalArgumentException("offered MageZero priority action cannot be mapped: " + kind);
                }
                slot = actions.getActionIndex(ability, true);
            }
            // Keep Math.abs/hashCode behavior; refuse its MIN_VALUE overflow case.
            if (slot < 0 || slot >= 128) {
                throw new IllegalArgumentException("original MageZero action hash is outside its policy head");
            }
            slots.add(Json.map("candidate_id", c.get("candidate_id"), "policy_slot", (long) slot));
        }
        try {
            return Json.map("schema", "spellbench-magezero-priority-features/v1", "head", "priority",
                    "decision_sha256", Seeds.hex(MessageDigest.getInstance("SHA-256")
                            .digest(Json.canonical(decision).getBytes(StandardCharsets.UTF_8))),
                    "features", features, "policy_slots", slots,
                    "encoding", Json.map("hash_algorithm", "xmage_feature_hash", "hash_version", 1L,
                            "feature_hash_bins", 2147483647L),
                    "world_flags", world.flags, "information", "permitted observation and sampled hidden world",
                    "variant", "opponent-hand encoding disabled; reconstructed priority slice; empty dialog history; activation flag false; no original MCTS search");
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }
}
