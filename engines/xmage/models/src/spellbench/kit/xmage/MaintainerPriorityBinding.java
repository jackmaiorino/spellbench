package spellbench.kit.xmage;

import mage.abilities.Ability;
import mage.abilities.ActivatedAbility;
import mage.abilities.common.PassAbility;
import mage.constants.AbilityType;
import mage.player.spellbench.decide.KitBridge;
import spellbench.kit.core.Json;
import spellbench.kit.core.ObsIndex;
import spellbench.kit.core.Seeds;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.lang.reflect.InvocationTargetException;
import java.util.*;

/** Bind the original validated priority prefix to exact offered public choices. */
public final class MaintainerPriorityBinding {
    public static final String VARIANT = "original validated priority order and first 64 slots; exact permitted public binding; "
            + "pass-only shortcut; original copied callbacks, activation and full games unfinished";
    private MaintainerPriorityBinding() { }
    static String hash(Object value) {
        try { return Seeds.hex(MessageDigest.getInstance("SHA-256").digest(Json.canonical(value).getBytes(StandardCharsets.UTF_8))); }
        catch (Exception e) { throw new IllegalStateException(e); }
    }
    public static final class Plan {
        public final List<ActivatedAbility> abilities;
        private final List<Object> refs;
        private final String decisionHash;
        private Plan(List<ActivatedAbility> abilities, List<Object> refs, Map<String, Object> decision) {
            this.abilities = Collections.unmodifiableList(new ArrayList<>(abilities));
            this.refs = new ArrayList<>(refs); this.decisionHash = hash(decision);
        }
        public List<Object> references() { return Json.arr(Json.copy(refs)); }
        public Map<String, Object> select(int index, Map<String, Object> decision) {
            if (index < 0 || index >= abilities.size() || !decisionHash.equals(hash(decision)))
                throw new IllegalArgumentException("priority slot is illegal or its decision is stale");
            Map<String, Object> ref = Json.obj(refs.get(index));
            return Json.map("candidate_id", ref.get("candidate_id"), "semantic_echo", Json.copy(ref.get("semantic")));
        }
    }
    public static Plan bind(Map<String, Object> start, Map<String, Object> decision, World world,
                            List<ActivatedAbility> original) {
        Map<String, Object> obs = Json.obj(decision, "observation");
        if (world == null || !world.viewer.equals(Json.str(start, "seat")) || !world.viewer.equals(Json.str(obs, "viewer"))
                || !world.viewer.equals(Json.str(decision, "acting_seat"))
                || !"priority".equals(Json.str(Json.obj(decision, "context"), "kind")))
            throw new IllegalArgumentException("original priority binding requires the acting permitted viewer");
        for (String flag : world.flags) if (flag.startsWith("unsupported:") || flag.startsWith("horizon:"))
            throw new IllegalArgumentException("priority binding has an unsupported world: " + flag);
        if (original == null || original.isEmpty() || !(original.get(0) instanceof PassAbility))
            throw new IllegalArgumentException("original priority prefix must begin with PassAbility");
        List<Object> offered = Json.arr(decision, "candidates");
        if (offered == null || offered.isEmpty() || offered.size() > 4096)
            throw new IllegalArgumentException("original priority binding requires the offered action list");
        Map<String, Map<String, Object>> bySemantic = new HashMap<>(); Set<Long> ids = new HashSet<>();
        for (Object value : offered) {
            Map<String, Object> candidate = Json.obj(value), semantic = Json.obj(candidate, "semantic");
            Object cid = candidate.get("candidate_id");
            if (!(cid instanceof Long) || (Long) cid < 0 || (Long) cid > 9007199254740991L || !ids.add((Long) cid))
                throw new IllegalArgumentException("offered priority IDs are invalid or aliased");
            if (semantic == null || bySemantic.put(Json.canonical(semantic), candidate) != null)
                throw new IllegalArgumentException("offered priority semantics are ambiguous");
            if ("activate_mana_ability".equals(semantic.get("kind"))) {
                Object raw = start.get("engine_profile");
                Object kinds = raw instanceof Map ? Json.obj(raw).get("decision_kinds") : null;
                if (!(kinds instanceof List) || !((List<?>) kinds).contains("activate_mana_ability"))
                    throw new IllegalArgumentException("priority mana requires the declared opt-in profile");
            }
        }
        ObsIndex index = new ObsIndex(obs); List<Object> refs = new ArrayList<>();
        List<ActivatedAbility> selected = new ArrayList<>(); Set<Long> bound = new HashSet<>();
        for (int slot = 0; slot < Math.min(64, original.size()); slot++) {
            ActivatedAbility ability = original.get(slot);
            if (ability == null) throw new IllegalArgumentException("original priority contains a null ability");
            Map<String, Object> semantic;
            if (ability instanceof PassAbility) semantic = Json.map("kind", "pass");
            else {
                Map<String, Object> source = index.ref(world.uuidToId.get(ability.getSourceId()));
                if (source == null || Json.str(source, "card_name") == null || Json.str(source, "card_name").isEmpty())
                    throw new IllegalArgumentException("original priority source is not named in the permitted observation");
                if (ability.getAbilityType() == AbilityType.ACTIVATED_NONMANA && KitBridge.abilityIndex(world.game, ability) < 0)
                    throw new IllegalArgumentException("unmatched original priority Oracle ability index");
                semantic = ability.getAbilityType() == AbilityType.ACTIVATED_MANA
                        ? Mapping.priorityManaSemantic(world, world.game, ability, index)
                        : Mapping.prioritySemantic(world, world.game, ability, index);
            }
            Map<String, Object> candidate = semantic == null ? null : bySemantic.get(Json.canonical(semantic));
            if (candidate == null || !bound.add((Long) candidate.get("candidate_id")))
                throw new IllegalArgumentException("original priority slot has no unique exact offered action");
            selected.add(ability);
            refs.add(Json.map("index", (long) slot, "candidate_id", candidate.get("candidate_id"), "semantic", Json.copy(semantic)));
        }
        return new Plan(selected, refs, decision);
    }
    static Map<UUID, String> namedAliases(World world, Map<String, Object> decision) {
        ObsIndex index = new ObsIndex(Json.obj(decision, "observation")); Map<UUID, String> aliases = new LinkedHashMap<>();
        for (String alias : index.ids()) {
            Map<String, Object> ref = index.ref(alias); UUID id = world.idToUuid.get(alias);
            if (id != null && Json.str(ref, "card_name") != null && !Json.str(ref, "card_name").isEmpty()) aliases.put(id, alias);
        }
        return aliases;
    }
    /** Encode a prefix provided by the original rules' chooser hook. Never regenerate or reorder its options. */
    public static Map<String, Object> encode(Map<String, Object> start, Map<String, Object> decision, World world,
                                              List<ActivatedAbility> original, Object state, Map<String, Object> sources) throws Exception {
        String[] pins = {"embedding_cache_sha256", "encoder_source_sha256", "candidate_source_sha256", "priority_rules_source_sha256"};
        if (sources == null || !sources.keySet().equals(new HashSet<>(Arrays.asList(pins))))
            throw new IllegalArgumentException("original priority encoding needs exact staged source identities");
        for (String key : pins) if (!(sources.get(key) instanceof String) || !((String) sources.get(key)).matches("[a-f0-9]{64}"))
            throw new IllegalArgumentException("original priority encoding needs staged source identities");
        Plan plan = bind(start, decision, world, original);
        Map<String, Object> frame = Json.map("schema", "spellbench-maintainer-original-priority/v1", "variant", VARIANT,
                "decision_sha256", hash(decision), "game_start_sha256", hash(start), "candidate_count", (long) plan.abilities.size(),
                "candidate_refs", plan.references(), "world_flags", new ArrayList<>(world.flags), "sources", Json.copy(sources),
                "original_callback_sha256", "b45257a66fc3914506fca4dd83461b6c8853d129b3e1f38b2d3aeba6137bd0c6",
                "full_priority_player_qualified", false);
        if (plan.abilities.size() == 1) { frame.put("features", null); return frame; }
        if (state == null || !state.getClass().getName().equals("spellbench.models.maintainer.StateSequenceBuilder$SequenceOutput"))
            throw new IllegalArgumentException("original priority requires its actual permitted cached base state");
        float[][] tokens = (float[][]) state.getClass().getField("tokens").get(state);
        int[] mask = (int[]) state.getClass().getField("mask").get(state), tokenIds = (int[]) state.getClass().getField("tokenIds").get(state);
        if (tokens.length != 256 || mask.length != 256 || tokenIds.length != 256)
            throw new IllegalArgumentException("original priority base-state shape differs");
        List<Object> sequence = new ArrayList<>(), padding = new ArrayList<>(), ids = new ArrayList<>();
        for (int i = 0; i < 256; i++) {
            if ((mask[i] != 0 && mask[i] != 1) || tokenIds[i] < 0 || tokenIds[i] >= 65536)
                throw new IllegalArgumentException("original priority state mask or token differs");
            sequence.add(numbers(tokens[i], 128)); padding.add(mask[i] == 1); ids.add((long) tokenIds[i]);
        }
        Class<?> codec = Class.forName("spellbench.models.maintainer.CandidateEncoder");
        if (!frame.get("original_callback_sha256").equals(codec.getField("SOURCE_SHA256").get(null)))
            throw new IllegalArgumentException("original priority codec source differs");
        Object encoder = codec.getConstructor(mage.players.Player.class).newInstance(world.viewerPlayer());
        List<Object> features = new ArrayList<>(), actionIds = new ArrayList<>(), legal = new ArrayList<>();
        for (int i = 0; i < 64; i++) {
            float[] values = new float[48]; int actionId = 0;
            if (i < plan.abilities.size()) {
                Ability ability = plan.abilities.get(i);
                try {
                    actionId = (Integer) codec.getMethod("priorityId", mage.game.Game.class, Ability.class).invoke(encoder, world.game, ability);
                    values = (float[]) codec.getMethod("priorityFeatures", mage.game.Game.class, Ability.class, state.getClass())
                            .invoke(encoder, world.game, ability, state);
                } catch (InvocationTargetException e) {
                    if (e.getCause() instanceof RuntimeException) throw (RuntimeException) e.getCause();
                    if (e.getCause() instanceof Error) throw (Error) e.getCause();
                    throw e;
                }
                if (actionId <= 0 || actionId >= 65536) throw new IllegalArgumentException("original priority action ID differs");
            }
            features.add(numbers(values, 48)); actionIds.add((long) actionId); legal.add(i < plan.abilities.size());
        }
        frame.put("features", Json.map("kind", "candidates", "head", "action", "sequence", sequence, "padding", padding,
                "token_ids", ids, "candidate_features", features, "candidate_ids", actionIds, "candidate_mask", legal));
        return frame;
    }
    private static List<Object> numbers(float[] values, int width) {
        if (values.length != width) throw new IllegalArgumentException("original priority vector width differs");
        List<Object> result = new ArrayList<>();
        for (float value : values) {
            if (!Float.isFinite(value) || Math.abs(value) > 1000000) throw new IllegalArgumentException("original priority has invalid numeric features");
            result.add((double) value);
        }
        return result;
    }
}
