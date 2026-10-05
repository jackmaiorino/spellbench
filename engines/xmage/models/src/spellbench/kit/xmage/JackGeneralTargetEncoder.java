package spellbench.kit.xmage;

import mage.abilities.Ability;
import mage.abilities.Mode;
import mage.abilities.Modes;
import mage.abilities.mana.ManaOptions;
import mage.constants.Outcome;
import mage.game.Game;
import mage.players.Player;
import mage.target.Target;
import spellbench.kit.core.Json;

import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

/** Original general target loop for spell targets, costs and object choices. */
class JackGeneralTargetEncoder implements ModelReplay.TargetCapture {
    static final String VARIANT = JackTargetEncoder.RULE_VARIANT.replace(
            "acting-player named-source spell targets only; cost, provided-card and divided-target callbacks unqualified",
            "acting-player named-source spell, cost and general object selections; provided-card, divided-target and opponent callbacks unqualified")
            + "; " + JackManaReplay.VARIANT;
    private final JackTargetEncoder original;

    JackGeneralTargetEncoder(Map<String, Object> start, ModelReplay.ManaCapture payments) {
        original = new JackTargetEncoder(start, payments);
    }
    @Override public boolean generalCardTargets() { return true; }
    @Override public ModelReplay.ManaCapture paymentRules() { return original.paymentRules(); }
    @Override public ManaOptions available(Player player, Game game) { return original.available(player, game); }
    @Override public ManaOptions available(Player player, Game game, boolean fast) { return original.available(player, game, fast); }
    @Override public Mode earlier(World world, Map<String, Object> decision, Modes modes, Ability source, Game game, Map<String, Object> semantic) {
        return original.earlier(world, decision, modes, source, game, semantic);
    }
    @Override public boolean earlierUse(World world, Map<String, Object> decision, Outcome outcome, String message, Ability source, Game game, Map<String, Object> semantic) {
        return original.earlierUse(world, decision, outcome, message, source, game, semantic);
    }
    @Override public int earlierX(World world, Map<String, Object> decision, int min, int max, boolean mana, Ability source, Game game, Map<String, Object> semantic) {
        return original.earlierX(world, decision, min, max, mana, source, game, semantic);
    }
    @Override public Map<String, Object> encode(World world, Map<String, Object> decision, Modes modes, Ability source, Game game) {
        return original.encode(world, decision, modes, source, game);
    }
    @Override public Map<String, Object> encodeUse(World world, Map<String, Object> decision, Outcome outcome, String message, Ability source, Game game) {
        return original.encodeUse(world, decision, outcome, message, source, game);
    }
    @Override public Map<String, Object> encodeX(World world, Map<String, Object> decision, int min, int max, boolean mana, Ability source, Game game) {
        return original.encodeX(world, decision, min, max, mana, source, game);
    }
    @Override public boolean select(Player player, Outcome outcome, Target target, Ability source, Game game, ModelReplay.TargetPick picker) {
        return original.select(player, outcome, target, source, game, picker);
    }

    private static Set<String> fields(String... names) { return new HashSet<>(Arrays.asList(names)); }
    private static final Set<String> TARGET = fields("kind", "source", "slot", "target", "selected_count", "minimum", "maximum");
    private static final Set<String> TARGET_FINISH = fields("kind", "source", "slot", "selected_count");
    private static final Set<String> COST = fields("kind", "source", "cost_kind", "candidate", "selected_count", "minimum", "maximum");
    private static final Set<String> OBJECT = fields("kind", "source", "purpose", "choice", "selected_count", "minimum", "maximum");
    private static final Set<String> OBJECT_FINISH = fields("kind", "source", "purpose", "selected_count");

    static Map<String, Object> normalizeSemantic(Map<String, Object> received, long slot) {
        Map<String, Object> result = Json.obj(Json.copy(received));
        String kind = Json.str(result, "kind"); Set<String> expected;
        switch (kind == null ? "" : kind) {
            case "choose_target": expected = TARGET; break;
            case "finish_target_selection": expected = TARGET_FINISH; break;
            case "choose_cost_target": expected = COST; break;
            case "select_object": expected = OBJECT; break;
            case "finish_selection": expected = OBJECT_FINISH; break;
            default: throw new IllegalArgumentException("unrelated general target action");
        }
        if (!result.keySet().equals(expected)) throw new IllegalArgumentException("general target fields differ from the wire action");
        if (COST == expected) {
            label(result, "cost_kind");
            result.put("target", Json.map("object", result.remove("candidate"))); result.remove("cost_kind");
            result.put("kind", "choose_target"); result.put("slot", slot);
        } else if (OBJECT == expected) {
            label(result, "purpose");
            result.put("target", result.remove("choice")); result.remove("purpose");
            result.put("kind", "choose_target"); result.put("slot", slot);
        } else if (OBJECT_FINISH == expected) {
            label(result, "purpose"); result.remove("purpose");
            result.put("kind", "finish_target_selection"); result.put("slot", slot);
        }
        return result;
    }
    private static void label(Map<String, Object> semantic, String key) {
        Object value = semantic.get(key);
        if (!(value instanceof String) || ((String) value).isEmpty() || ((String) value).length() > 128) {
            throw new IllegalArgumentException("general target action needs a bounded " + key);
        }
    }
    static Map<String, Object> normalizeDecision(Map<String, Object> decision, long slot) {
        Map<String, Object> result = Json.obj(Json.copy(decision));
        String family = null, label = null;
        for (Object item : Json.arr(result, "candidates")) {
            Map<String, Object> candidate = Json.obj(item), semantic = Json.obj(candidate, "semantic");
            String kind = Json.str(semantic, "kind");
            String current = "finish_target_selection".equals(kind) ? "choose_target"
                    : "finish_selection".equals(kind) ? "select_object" : kind;
            String currentLabel = "select_object".equals(current) ? Json.str(semantic, "purpose")
                    : "choose_cost_target".equals(current) ? Json.str(semantic, "cost_kind") : "";
            if (family != null && (!family.equals(current) || !java.util.Objects.equals(label, currentLabel))) {
                throw new IllegalArgumentException("general target actions mix callback families or purposes");
            }
            family = current; label = currentLabel;
            candidate.put("semantic", normalizeSemantic(semantic, slot));
        }
        return result;
    }
    /** Bind one pick inside the actual original loop, preserving its direct returns and slot cap. */
    @SuppressWarnings("unchecked")
    static Map<Object,Map<String,Object>> replayChoices(World world,Map<String,Object> decision,
                                                       Object[] arguments,Game game) throws Exception {
        if(arguments.length!=9 || !(arguments[0] instanceof Target) || !(arguments[1] instanceof Ability)
                || !(arguments[2] instanceof List) || !(arguments[3] instanceof Integer)
                || !(arguments[4] instanceof Integer) || !(arguments[5] instanceof Integer)
                || !(arguments[6] instanceof Boolean) || arguments[7]!=null && !(arguments[7] instanceof UUID))
            throw new IllegalArgumentException("original target callback lacks its actual loop state");
        Target target=(Target)arguments[0];Ability source=(Ability)arguments[1];
        List<UUID> possible=(List<UUID>)arguments[2];boolean forced=(Boolean)arguments[6];UUID direct=(UUID)arguments[7];
        Map<String,Object> normalized=normalizeDecision(decision,JackTargetEncoder.slot(source,target));
        JackTargetEncoder.Binding binding=new JackTargetEncoder.Binding(world,normalized,target,source,game,
                possible,(Integer)arguments[3],(Integer)arguments[4],(Integer)arguments[5]);
        Map<Long,Map<String,Object>> wire=new LinkedHashMap<>();
        for(Object item:Json.arr(decision,"candidates")) {
            Map<String,Object> candidate=Json.obj(item);Long id=(Long)candidate.get("candidate_id");
            wire.put(id,Json.map("candidate_id",id,"semantic_echo",Json.copy(candidate.get("semantic"))));
        }
        Map<Object,Map<String,Object>> result=new LinkedHashMap<>();
        for(int i=0;i<possible.size();i++) {
            UUID id=possible.get(i);
            if(forced ? java.util.Objects.equals(id,direct) : i<64) result.put(id,wire.get(binding.ids.get(id)));
        }
        if(result.isEmpty()) throw new IllegalArgumentException("original target has no bound direct return or policy slot");
        return result;
    }
    @Override public UUID earlier(World world, Map<String, Object> decision, Target target, Ability source, Game game,
                                  List<UUID> possible, int selected, int min, int max, boolean forced, UUID direct,
                                  String reason, Map<String, Object> semantic) {
        long slot = JackTargetEncoder.slot(source, target);
        return original.earlier(world, normalizeDecision(decision, slot), target, source, game,
                possible, selected, min, max, forced, direct, reason, normalizeSemantic(semantic, slot));
    }
    @Override public Map<String, Object> encode(World world, Map<String, Object> decision, Target target, Ability source, Game game,
                                               List<UUID> possible, int selected, int min, int max, boolean forced, UUID direct, String reason) {
        long slot = JackTargetEncoder.slot(source, target);
        Map<String, Object> normalized = normalizeDecision(decision, slot);
        Map<String, Object> result = original.encode(world, normalized, target, source, game, possible, selected, min, max, forced, direct, reason);
        result.put("schema", "spellbench-jack-general-target-features/v1");
        result.put("variant", VARIANT); result.put("target_slot", slot);
        result.put("normalized_decision_sha256", JackModeEncoder.hash(normalized));
        result.put("decision_sha256", JackModeEncoder.hash(decision));
        return result;
    }
}
