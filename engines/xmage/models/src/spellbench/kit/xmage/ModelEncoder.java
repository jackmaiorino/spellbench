package spellbench.kit.xmage;

import mage.abilities.Ability;
import mage.player.ai.encoder.ActionEncoder;
import mage.player.ai.encoder.StateEncoder;
import spellbench.kit.core.Json;
import spellbench.kit.core.ObsIndex;
import spellbench.kit.core.Sampler;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * Exp1's exact feature hasher and action vocabulary on a reconstructed world.
 * This class has no reference to the live engine and accepts only permitted
 * game_start and observation data. It is the priority slice of a fair variant;
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
        UUID viewer = world.player(world.viewer);
        StateEncoder encoder = new StateEncoder();
        encoder.setAgent(viewer);
        encoder.setOpponent(world.player("p0".equals(world.viewer) ? "p1" : "p0"));
        encoder.perfectInfo = false;
        List<Integer> features = new ArrayList<>(encoder.processState(world.game, viewer));
        Collections.sort(features);
        ActionEncoder actions = new ActionEncoder();
        ObsIndex index = new ObsIndex(obs);
        List<Object> slots = new ArrayList<>();
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
        return Json.map("schema", "spellbench-draftzero-priority-features/v1", "features", features,
                "encoding", Json.map("hash_algorithm", "xmage_feature_hash", "hash_version", 1L,
                        "feature_hash_bins", 2000000L), "priority_slots", slots,
                "world_flags", world.flags, "information", "permitted observation and sampled hidden world",
                "variant", "opponent-hand encoding disabled; reconstructed world; no original MCTS search");
    }
}
