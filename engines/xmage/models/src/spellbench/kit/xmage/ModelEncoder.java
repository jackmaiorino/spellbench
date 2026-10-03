package spellbench.kit.xmage;

import mage.abilities.Ability;
import mage.player.ai.encoder.ActionEncoder;
import mage.player.ai.encoder.StateEncoder;
import spellbench.models.Exp1Compat;
import spellbench.kit.core.Json;
import spellbench.kit.core.ObsIndex;
import spellbench.kit.core.Sampler;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.HashSet;
import java.util.Set;
import java.util.UUID;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import spellbench.kit.core.Seeds;

/**
 * Exp1's exact feature hasher and action vocabulary on a reconstructed world.
 * This class has no reference to the live engine and accepts only permitted
 * game_start and observation data. It is a decision slice of a fair variant;
 * it does not implement a complete match policy or the original MCTS search.
 */
public final class ModelEncoder {
    private ModelEncoder() { }

    public static Map<String, Object> priority(Map<String, Object> start, Map<String, Object> decision,
                                               byte[] worldSeed, byte[] idSeed) {
        Map<String, Object> context = Json.obj(decision, "context");
        if (context == null || !"priority".equals(Json.str(context, "kind"))) {
            throw new IllegalArgumentException("only the priority encoder slice is implemented");
        }
        Reconstructed view = reconstruct(start, decision, worldSeed, idSeed, WorldBuilder.Mode.PRIORITY);
        World world = view.world;
        List<Object> slots = new ArrayList<>();
        // Preserve the original slice's order: encode before getPlayable can
        // evaluate abilities and update transient player state.
        Map<String, Object> result = encoded(world, "spellbench-draftzero-priority-features/v1", "priority_slots", slots);
        ActionEncoder actions = new ActionEncoder();
        ObsIndex index = new ObsIndex(view.observation);
        for (Object candidate : Json.arr(decision, "candidates")) {
            Map<String, Object> c = Json.obj(candidate);
            Map<String, Object> a = Json.obj(c, "semantic");
            String kind = Json.str(a, "kind");
            int slot;
            if ("pass".equals(kind)) {
                slot = 0;
            } else {
                Ability ability = Mapping.findPlayable(world, world.viewerPlayer(), a, index);
                if (ability == null) {
                    throw new IllegalArgumentException("offered priority action cannot be mapped: " + kind);
                }
                slot = actions.getActionIndex(ability, true);
            }
            slots.add(Json.map("candidate_id", c.get("candidate_id"), "policy_slot", (long) slot));
        }
        return result;
    }

    /** Only callbacks with a trained Exp1 policy head are accepted here. */
    public static Map<String, Object> decision(Map<String, Object> start, Map<String, Object> decision,
                                               byte[] worldSeed, byte[] idSeed) {
        List<Object> candidates = Json.arr(decision, "candidates");
        if (candidates == null || candidates.isEmpty()) {
            throw new IllegalArgumentException("encoded decision has no offered candidates");
        }
        Set<Object> ids = new HashSet<>();
        for (Object candidate : candidates) {
            Map<String, Object> c = Json.obj(candidate);
            Object id = c.get("candidate_id");
            if (!(id instanceof Long) || (Long) id < 0 || !ids.add(id)) {
                throw new IllegalArgumentException("encoded candidate ids must be unique nonnegative integers");
            }
        }
        Map<String, Object> context = Json.obj(decision, "context");
        if (context != null && "priority".equals(Json.str(context, "kind"))) {
            Map<String, Object> result = priority(start, decision, worldSeed, idSeed);
            result.put("head", "priority");
            result.put("policy_slots", result.get("priority_slots"));
            bind(result, decision);
            return result;
        }
        String head = null;
        for (Object candidate : candidates) {
            String kind = Json.str(Json.obj(Json.obj(candidate), "semantic"), "kind");
            String next;
            switch (kind == null ? "" : kind) {
                case "choose_target": case "choose_cost_target": case "select_object":
                case "finish_target_selection": case "finish_selection":
                    next = "target";
                    break;
                case "choose_boolean": case "optional_cost": case "optional_cast":
                    next = "binary";
                    break;
                default:
                    throw new IllegalArgumentException("Exp1 has no trained policy head for callback: " + kind);
            }
            if (head != null && !head.equals(next)) {
                throw new IllegalArgumentException("encoded decision mixes policy callback families");
            }
            head = next;
        }
        World world = reconstruct(start, decision, worldSeed, idSeed, WorldBuilder.Mode.SNAPSHOT).world;
        ActionEncoder actions = new ActionEncoder();
        List<Object> slots = new ArrayList<>();
        for (Object candidate : candidates) {
            Map<String, Object> c = Json.obj(candidate);
            Map<String, Object> sem = Json.obj(c, "semantic");
            String kind = Json.str(sem, "kind");
            int slot;
            if ("target".equals(head)) {
                if ("finish_target_selection".equals(kind) || "finish_selection".equals(kind)) {
                    slot = actions.getTargetIndex("Stop Choosing");
                } else {
                    UUID id = Dialogs.uuidOf(world, sem);
                    String name = id == null ? "null" : Exp1Compat.entityName(world.game, id, world.player(world.viewer));
                    if ("null".equals(name)) {
                        throw new IllegalArgumentException("offered target is absent from the permitted world");
                    }
                    slot = actions.getTargetIndex(name);
                }
            } else {
                String field = "optional_cost".equals(kind) ? "pay" : "optional_cast".equals(kind) ? "cast_it" : "value";
                Object value = sem.get(field);
                if (!(value instanceof Boolean)) {
                    throw new IllegalArgumentException("offered binary decision lacks its boolean value");
                }
                slot = (Boolean) value ? 1 : 0;
            }
            slots.add(Json.map("candidate_id", c.get("candidate_id"), "policy_slot", (long) slot));
        }
        Map<String, Object> result = encoded(world, "spellbench-draftzero-decision-features/v1", "policy_slots", slots);
        result.put("head", head);
        bind(result, decision);
        result.put("variant", "opponent-hand encoding disabled; reconstructed snapshot; empty micro-decision history; activation flag false; no original MCTS search");
        return result;
    }

    private static void bind(Map<String, Object> result, Map<String, Object> decision) {
        try {
            result.put("decision_sha256", Seeds.hex(MessageDigest.getInstance("SHA-256")
                    .digest(Json.canonical(decision).getBytes(StandardCharsets.UTF_8))));
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }

    private static final class Reconstructed {
        final World world;
        final Map<String, Object> observation;
        Reconstructed(World world, Map<String, Object> observation) {
            this.world = world;
            this.observation = observation;
        }
    }

    private static Reconstructed reconstruct(Map<String, Object> start, Map<String, Object> decision,
                                             byte[] worldSeed, byte[] idSeed, WorldBuilder.Mode mode) {
        if (!ActionEncoder.vocabLoaded() || ActionEncoder.ACTION_DIM != 1024) {
            throw new IllegalArgumentException("Exp1 requires the pinned FDN 1024-slot action vocabulary");
        }
        Map<String, Object> obs = Json.obj(Json.copy(decision.get("observation")));
        KitContext.reset();
        KitRandom.installBoot();
        List<String> nameFlags = WorldBuilder.restoreVisibleNames(obs, Json.obj(decision, "x_history"));
        KitRandom random = KitRandom.install(worldSeed, idSeed);
        WorldBuilder.Spec spec = new WorldBuilder.Spec();
        spec.gameStart = start;
        spec.observation = obs;
        spec.sample = Sampler.sample(start, obs, random.stream("sampler"));
        spec.random = random;
        spec.mode = mode;
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
        return new Reconstructed(world, obs);
    }

    private static Map<String, Object> encoded(World world, String schema, String slotField, List<Object> slots) {
        UUID viewer = world.player(world.viewer);
        StateEncoder encoder = new StateEncoder();
        encoder.setAgent(viewer);
        encoder.setOpponent(world.player("p0".equals(world.viewer) ? "p1" : "p0"));
        encoder.perfectInfo = false;
        List<Integer> features = new ArrayList<>(encoder.processState(world.game, viewer));
        Collections.sort(features);
        return Json.map("schema", schema, "features", features,
                "encoding", Json.map("hash_algorithm", "xmage_feature_hash", "hash_version", 1L,
                        "feature_hash_bins", 2000000L), slotField, slots,
                "world_flags", world.flags, "information", "permitted observation and sampled hidden world",
                "variant", "opponent-hand encoding disabled; reconstructed world; no original MCTS search");
    }
}
