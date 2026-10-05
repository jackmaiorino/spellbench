package spellbench.kit.xmage;

import mage.abilities.Ability;
import mage.abilities.mana.ManaOptions;
import mage.constants.Outcome;
import mage.constants.TurnPhase;
import mage.game.Game;
import mage.game.stack.StackObject;
import mage.players.Player;
import spellbench.kit.core.Json;
import spellbench.kit.core.ObsIndex;

import java.lang.reflect.InvocationTargetException;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

/** Original binary and X callbacks on the verified permitted replay. */
final class JackDialogEncoder implements ModelReplay.DialogCapture {
    static final String VARIANT = "original choose-use feasibility gates, YES/NO IDs and order; original X cap, "
            + "conditional mana bounds and integer order; permitted callback replay; "
            + "refusal instead of heuristic fallback; automatic mana production and other callbacks unqualified";
    private final Map<String, Object> start;
    private final ModelReplay.ManaCapture payments;
    static final String PAYMENT_VARIANT = VARIANT + "; " + JackManaReplay.VARIANT;

    JackDialogEncoder(Map<String, Object> start) { this(start, null); }
    JackDialogEncoder(Map<String, Object> start, ModelReplay.ManaCapture payments) { this.start = start; this.payments = payments; }
    @Override public ModelReplay.ManaCapture paymentRules() { return payments; }

    private static String pin(String name) {
        String value = System.getProperty("spellbench.jack." + name);
        if (value == null || !value.matches("[a-f0-9]{64}")) throw new IllegalArgumentException("dialog source pin missing: " + name);
        return value;
    }

    static Class<?> rulesClass() throws Exception {
        Class<?> type = Class.forName("spellbench.models.jack.DialogRules");
        if (!JackModeEncoder.SOURCE.equals(type.getField("SOURCE_SHA256").get(null))) {
            throw new IllegalArgumentException("dialog rules differ from the original callback");
        }
        return type;
    }

    private static Object rules(Player viewer) throws Exception {
        return rulesClass().getConstructor(Player.class).newInstance(viewer);
    }

    private static RuntimeException failed(String context, Exception error) {
        Throwable cause = error instanceof InvocationTargetException ? error.getCause() : error;
        return new IllegalArgumentException(context, cause);
    }

    private static Object binaryValue(Map<String, Object> semantic) {
        String kind = Json.str(semantic, "kind");
        if ("choose_boolean".equals(kind)) return semantic.get("value");
        if ("optional_cost".equals(kind) && semantic.get("cost") instanceof String
                && !((String) semantic.get("cost")).isEmpty()) return semantic.get("pay");
        if ("choose_cast_method".equals(kind)) {
            String method = Json.str(semantic, "method");
            if ("normal".equals(method)) return Boolean.FALSE;
            if ("evoke".equals(method) || "alternative".equals(method)) return Boolean.TRUE;
        }
        return null;
    }

    @Override public ManaOptions available(Player viewer, Game game, boolean fast) {
        return originalManaAvailable(viewer, game, fast);
    }

    static ManaOptions originalManaAvailable(Player viewer, Game game, boolean fast) {
        try {
            pin("dialogRulesSourceSha256");
            Object rules = rules(viewer);
            return (ManaOptions) rules.getClass().getMethod(fast ? "getManaAvailableFast" : "getManaAvailable", Game.class)
                    .invoke(rules, game);
        } catch (Exception e) { throw failed("original mana availability failed", e); }
    }

    private static final class Binding {
        final Map<UUID, String> permitted;
        final Map<Object, Long> ids = new HashMap<>();
        final Map<Object, Map<String, Object>> semantics = new HashMap<>();
        final boolean numeric;
        int minimum, maximum, offeredMaximum;

        Binding(World world, Map<String, Object> decision, Ability source, Game game, boolean numeric) throws Exception {
            this(world,decision,source,game,numeric,"x_value");
        }
        Binding(World world, Map<String, Object> decision, Ability source, Game game, boolean numeric,String purpose) throws Exception {
            this.numeric = numeric;
            Map<String, Object> obs = Json.obj(decision, "observation"), context = Json.obj(decision, "context");
            if (!world.viewer.equals(Json.str(decision, "acting_seat")) || !world.viewer.equals(Json.str(obs, "viewer"))
                    || !"choice".equals(Json.str(context, "kind"))) {
                throw new IllegalArgumentException("dialog belongs to another acting viewer or callback");
            }
            permitted = JackModeEncoder.namedAliases(world, decision);
            Object reference = context.get("source");
            if (source == null || source.getSourceId() == null) {
                if (reference != null) throw new IllegalArgumentException("dialog has a different actual source");
            } else {
                Map<String, Object> ref = Json.obj(reference);
                if (ref == null || !Json.canonical(ref).equals(Json.canonical(new ObsIndex(obs).ref(Json.str(ref, "object_id"))))) {
                    throw new IllegalArgumentException("dialog source differs from its visible reference");
                }
                boolean matches = false;
                for (Map.Entry<UUID, String> entry : permitted.entrySet()) {
                    if (!entry.getValue().equals(Json.str(ref, "object_id"))) continue;
                    StackObject stack = game.getStack().getStackObject(entry.getKey());
                    if (entry.getKey().equals(source.getSourceId()) || stack != null
                            && source.getSourceId().equals(stack.getSourceId())) matches = true;
                }
                if (!matches) throw new IllegalArgumentException("dialog has a different permitted actual source");
            }
            List<Object> offered = Json.arr(decision, "candidates");
            if (offered.isEmpty() || offered.size() > 4096) throw new IllegalArgumentException("dialog offered action bound exceeded");
            Set<Long> used = new HashSet<>();
            String family = null;
            Map<String, Object> base = null;
            for (Object item : offered) {
                Map<String, Object> candidate = Json.obj(item), semantic = Json.obj(candidate, "semantic");
                Object id = candidate.get("candidate_id");
                if (!(id instanceof Long) || (Long) id < 0 || (Long) id > 9007199254740991L || !used.add((Long) id)
                        || !Json.canonical(reference).equals(Json.canonical(semantic.get("source")))) {
                    throw new IllegalArgumentException("dialog candidate is aliased or belongs to another source");
                }
                String kind = Json.str(semantic, "kind");
                Object value;
                if (numeric) {
                    if (!"choose_number".equals(kind) || !purpose.equals(Json.str(semantic, "purpose"))
                            || !(semantic.get("value") instanceof Long) || !(semantic.get("minimum") instanceof Long)
                            || !(semantic.get("maximum") instanceof Long)) {
                        throw new IllegalArgumentException("X root has a different numeric callback");
                    }
                    long lo = (Long) semantic.get("minimum"), hi = (Long) semantic.get("maximum"), x = (Long) semantic.get("value");
                    long effective="amount".equals(purpose) && hi==Integer.MAX_VALUE?Math.max(lo,10):hi;
                    if (lo < ("amount".equals(purpose)?Integer.MIN_VALUE:0) || hi < lo || hi > Integer.MAX_VALUE
                            || effective - lo + 1 > 4096 || x < lo || x > effective) {
                        throw new IllegalArgumentException("X root has an invalid offered range");
                    }
                    minimum = (int) lo; maximum = (int) hi; offeredMaximum=(int)effective;value = (int) x;
                } else {
                    value = binaryValue(semantic);
                    if (!(value instanceof Boolean)) throw new IllegalArgumentException("dialog root is not binary");
                }
                Map<String, Object> shared = Json.obj(Json.copy(semantic));
                shared.remove(numeric || "choose_boolean".equals(kind) ? "value" : "optional_cost".equals(kind) ? "pay" : "method");
                if (family != null && (!family.equals(kind) || !Json.canonical(shared).equals(Json.canonical(base)))) {
                    throw new IllegalArgumentException("dialog actions disagree on their callback metadata");
                }
                family = kind; base = shared;
                if (ids.put(value, (Long) id) != null) throw new IllegalArgumentException("dialog has repeated semantic values");
                semantics.put(value, semantic);
            }
            if (numeric && (long) offeredMaximum - minimum + 1 != ids.size()) {
                throw new IllegalArgumentException("X root omits part of its offered range");
            }
        }

        Long id(Object value) {
            Long id = ids.get(value);
            if (id == null) throw new IllegalArgumentException("original dialog choice is absent from the offered actions");
            return id;
        }
    }

    private static Boolean forced(World world, Outcome outcome, String message, Ability source, Game game) throws Exception {
        Object rules = rules(world.viewerPlayer());
        return (Boolean) rules.getClass().getMethod("forcedUse", Outcome.class, String.class, Ability.class, Game.class)
                .invoke(rules, outcome, message, source, game);
    }

    private static int[] range(World world, Binding bound, int min, int max, boolean mana, Ability source, Game game) throws Exception {
        if (min < 0 || bound.minimum != min || bound.maximum > Math.max(min, max)) {
            throw new IllegalArgumentException("offered X bounds differ from the actual callback");
        }
        Object rules = rules(world.viewerPlayer());
        int[] range = (int[]) rules.getClass().getMethod("xRange", int.class, int.class, boolean.class, Ability.class, Game.class)
                .invoke(rules, min, max, mana, source, game);
        if (range.length != 2 || range[0] != min || range[1] < range[0] || range[1] > bound.maximum) {
            throw new IllegalArgumentException("original X range is absent from the offered callback");
        }
        return range;
    }

    /** Validate actual callback choices before the original player's inference, without encoding again. */
    static Map<Object,Map<String,Object>> replayChoices(World world,Map<String,Object> decision,String kind,Object[] args,Game game) {
        try {
            boolean amount="amount".equals(kind),numeric="x".equals(kind) || amount;
            if (!numeric && !"use".equals(kind)) throw new IllegalArgumentException("unconnected original dialog callback");
            if(amount && (args.length!=3 || !(args[0] instanceof Integer) || !(args[1] instanceof Integer)))
                throw new IllegalArgumentException("original amount callback lacks exact integer bounds");
            Ability source=(Ability)args[amount?2:numeric?3:2];
            Binding bound=new Binding(world,decision,source,game,numeric,amount?"amount":"x_value");
            List<Object> values=new ArrayList<>();
            if (numeric) {
                int[] limits;
                if(amount) {
                    if(bound.minimum!=(Integer)args[0] || bound.maximum!=(Integer)args[1])
                        throw new IllegalArgumentException("offered amount bounds differ from actual inherited callback");
                    limits=new int[]{bound.minimum,bound.offeredMaximum};
                } else limits=range(world,bound,(Integer)args[0],(Integer)args[1],(Boolean)args[2],source,game);
                for(long x=limits[0];x<=limits[1];x++) values.add((int)x);
            } else {
                Boolean fixed=forced(world,(Outcome)args[0],(String)args[1],source,game);
                if (fixed!=null) values.add(fixed);
                else {values.add(Boolean.TRUE);values.add(Boolean.FALSE);}
            }
            Map<Object,Map<String,Object>> choices=new LinkedHashMap<>();
            for(Object value:values) choices.put(value,Json.map("candidate_id",bound.id(value),
                    "semantic_echo",Json.copy(bound.semantics.get(value))));
            return choices;
        } catch(RuntimeException failure) {throw failure;}
        catch(Exception failure) {throw failed("original replay choice binding failed",failure);}
    }

    @Override public boolean earlierUse(World world, Map<String, Object> decision, Outcome outcome, String message,
                                        Ability source, Game game, Map<String, Object> semantic) {
        try {
            Binding bound = new Binding(world, decision, source, game, false);
            Object value = binaryValue(semantic);
            Boolean forced = forced(world, outcome, message, source, game);
            if (!(value instanceof Boolean) || forced != null && !forced.equals(value)
                    || !Json.canonical(semantic).equals(Json.canonical(bound.semantics.get(value)))) {
                throw new IllegalArgumentException("recorded binary choice differs from the original callback");
            }
            if (forced == null && bound.ids.size() != 2) throw new IllegalArgumentException("original YES/NO pair is not offered");
            return (Boolean) value;
        } catch (RuntimeException e) { throw e; }
        catch (Exception e) { throw failed("original recorded binary binding failed", e); }
    }

    @Override public int earlierX(World world, Map<String, Object> decision, int min, int max, boolean mana,
                                  Ability source, Game game, Map<String, Object> semantic) {
        try {
            Binding bound = new Binding(world, decision, source, game, true);
            int[] range = range(world, bound, min, max, mana, source, game);
            Object value = semantic.get("value");
            if (!(value instanceof Long) || (Long) value < range[0] || (Long) value > range[1]
                    || !Json.canonical(semantic).equals(Json.canonical(bound.semantics.get(Math.toIntExact((Long) value))))) {
                throw new IllegalArgumentException("recorded X differs from its original range");
            }
            return Math.toIntExact((Long) value);
        } catch (RuntimeException e) { throw e; }
        catch (Exception e) { throw failed("original recorded X binding failed", e); }
    }

    private Map<String, Object> base(World world, Map<String, Object> decision, String callback) {
        if (!world.viewer.equals(Json.str(start, "seat"))) throw new IllegalArgumentException("dialog start belongs to another seat");
        for (String flag : world.flags) if (flag.startsWith("unsupported:") || flag.startsWith("horizon:")) {
            throw new IllegalArgumentException("unsupported original dialog replay: " + flag);
        }
        Map<String, Object> result = Json.map("schema", "spellbench-jack-dialog-features/v1", "callback", callback,
                "decision_sha256", JackModeEncoder.hash(decision), "game_start_sha256", JackModeEncoder.hash(start),
                "encoder_source_sha256", pin("encoderSourceSha256"), "candidate_source_sha256", pin("candidateSourceSha256"),
                "dialog_rules_source_sha256", pin("dialogRulesSourceSha256"), "embedding_cache_sha256", pin("embeddingSha256"),
                "original_callback_sha256", JackModeEncoder.SOURCE, "variant", payments == null ? VARIANT : PAYMENT_VARIANT, "world_flags", world.flags);
        if (payments != null) {
            result.put("mana_payment_rules_source_sha256", payments.sourceSha256());
            result.put("mana_payment_variant", JackManaReplay.VARIANT);
        }
        return result;
    }

    @Override public Map<String, Object> encodeUse(World world, Map<String, Object> decision, Outcome outcome, String message,
                                                 Ability source, Game game) {
        try {
            Binding bound = new Binding(world, decision, source, game, false);
            Map<String, Object> result = base(world, decision, "choose_use");
            Boolean forced = forced(world, outcome, message, source, game);
            List<Object> values = new ArrayList<>();
            if (forced != null) {
                values.add(forced);
                result.putAll(Json.map("kind", "jack-dialog-forced", "reason", "original_mana_feasibility_gate",
                        "forced_candidate_id", bound.id(forced), "forced_value", forced,
                        "candidate_count", 1L, "original_values", values));
                return result;
            }
            values.add(Boolean.TRUE); values.add(Boolean.FALSE);
            bound.id(Boolean.TRUE); bound.id(Boolean.FALSE);
            encodeCandidates(world, bound, source, game, "CHOOSE_USE", values, result);
            return result;
        } catch (RuntimeException e) { throw e; }
        catch (Exception e) { throw failed("original binary encoding failed", e); }
    }

    @Override public Map<String, Object> encodeX(World world, Map<String, Object> decision, int min, int max, boolean mana,
                                               Ability source, Game game) {
        try {
            Binding bound = new Binding(world, decision, source, game, true);
            int[] range = range(world, bound, min, max, mana, source, game);
            Map<String, Object> result = base(world, decision, "announce_x");
            result.putAll(Json.map("original_minimum", (long) min, "original_maximum", (long) max,
                    "is_mana_pay", mana, "real_minimum", (long) range[0], "real_maximum", (long) range[1]));
            List<Object> values = new ArrayList<>();
            for (long x = range[0]; x <= range[1]; x++) values.add((int) x);
            if (values.size() == 1) {
                Object value = values.get(0);
                result.putAll(Json.map("kind", "jack-dialog-forced", "reason", "original_x_single_value",
                        "forced_candidate_id", bound.id(value), "forced_value", value,
                        "candidate_count", 1L, "original_values", values));
                return result;
            }
            encodeCandidates(world, bound, source, game, "ANNOUNCE_X", values, result);
            return result;
        } catch (RuntimeException e) { throw e; }
        catch (Exception e) { throw failed("original X encoding failed", e); }
    }

    private static void encodeCandidates(World world, Binding bound, Ability source, Game game, String type,
                                         List<Object> values, Map<String, Object> result) throws Exception {
        if (values.size() < 2 || values.size() > 64) throw new IllegalArgumentException("original dialog candidate bound exceeded");
        Class<?> encoder = Class.forName("spellbench.models.jack.StateSequenceBuilder");
        Object state = encoder.getMethod("buildBaseState", Game.class, TurnPhase.class, int.class, UUID.class, Map.class)
                .invoke(null, game, game.getPhase() == null ? null : game.getPhase().getType(),
                        256, world.player(world.viewer), bound.permitted);
        float[][] tokens = (float[][]) state.getClass().getField("tokens").get(state);
        int[] padding = (int[]) state.getClass().getField("mask").get(state);
        int[] tokenIds = (int[]) state.getClass().getField("tokenIds").get(state);
        if (tokens.length != 256 || padding.length != 256 || tokenIds.length != 256) {
            throw new IllegalArgumentException("original dialog state has the wrong shape");
        }
        List<Object> rows = new ArrayList<>(), masks = new ArrayList<>(), ids = new ArrayList<>();
        for (int i = 0; i < 256; i++) {
            if (padding[i] != 0 && padding[i] != 1 || tokenIds[i] < 0 || tokenIds[i] >= 65536) {
                throw new IllegalArgumentException("original dialog state has invalid padding or token IDs");
            }
            rows.add(JackModeEncoder.numbers(tokens[i], 128)); masks.add(padding[i] == 1); ids.add((long) tokenIds[i]);
        }
        Class<?> codec = Class.forName("spellbench.models.jack.CandidateEncoder");
        if (!JackModeEncoder.SOURCE.equals(codec.getField("SOURCE_SHA256").get(null))
                || !"action".equals(codec.getMethod("head", String.class).invoke(null, type))) {
            throw new IllegalArgumentException("dialog candidates have a different original source or head");
        }
        Object candidates = codec.getConstructor(Player.class).newInstance(world.viewerPlayer());
        Object rules = rules(world.viewerPlayer());
        List<Object> features = new ArrayList<>(), actionIds = new ArrayList<>(), legal = new ArrayList<>(), refs = new ArrayList<>();
        for (int i = 0; i < 64; i++) {
            float[] row = new float[48]; int id = 0;
            if (i < values.size()) {
                Object value = values.get(i);
                id = bound.numeric ? (Integer) codec.getMethod("candidateId", String.class, Game.class, Ability.class, Object.class)
                        .invoke(candidates, type, game, source, value)
                        : (Integer) rules.getClass().getMethod("useId", boolean.class).invoke(rules, value);
                row = (float[]) codec.getMethod("candidateFeatures", String.class, Game.class, Ability.class, Object.class, state.getClass())
                        .invoke(candidates, type, game, source, value, state);
                if (id <= 0 || id >= 65536) throw new IllegalArgumentException("original dialog ID is invalid");
                refs.add(Json.map("index", (long) i, "value", value, "candidate_id", bound.id(value)));
            }
            features.add(JackModeEncoder.numbers(row, 48)); actionIds.add((long) id); legal.add(i < values.size());
        }
        result.putAll(Json.map("kind", "candidates", "head", "action", "candidate_count", (long) values.size(),
                "original_values", values, "sequence", rows, "padding", masks, "token_ids", ids,
                "candidate_features", features, "candidate_ids", actionIds, "candidate_mask", legal, "candidate_refs", refs));
    }
}
