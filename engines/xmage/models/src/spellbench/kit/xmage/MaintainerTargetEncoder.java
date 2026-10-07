package spellbench.kit.xmage;

import mage.MageObject;
import mage.abilities.Ability;
import mage.abilities.Mode;
import mage.abilities.Modes;
import mage.abilities.mana.ManaOptions;
import mage.constants.Outcome;
import mage.constants.TurnPhase;
import mage.game.Game;
import mage.players.Player;
import mage.target.Target;
import spellbench.kit.core.Json;
import spellbench.kit.core.ObsIndex;

import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Proxy;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

/** Original sequential general-target rules, bound to actual permitted callback replay. */
final class MaintainerTargetEncoder implements ModelReplay.TargetCapture {
    static final String RULE_VARIANT = "original general target order, sequential STOP gates, single and same-name direct returns, "
            + "first 64 slots and minimum/crew completion; permitted callback replay; "
            + "refusal instead of model-error fallback; acting-player named-source spell targets only; "
            + "cost, provided-card and divided-target callbacks unqualified";
    static final String VARIANT = RULE_VARIANT + "; " + MaintainerManaReplay.VARIANT;
    private final Map<String, Object> start;
    private final ModelReplay.ManaCapture payments;
    private final MaintainerModeEncoder modes;
    private final MaintainerDialogEncoder dialogs;

    MaintainerTargetEncoder(Map<String, Object> start, ModelReplay.ManaCapture payments) {
        if (payments == null) throw new IllegalArgumentException("original target replay requires original payment rules");
        this.start = start; this.payments = payments;
        modes = new MaintainerModeEncoder(start, true, payments); dialogs = new MaintainerDialogEncoder(start, payments);
    }
    @Override public ModelReplay.ManaCapture paymentRules() { return payments; }
    @Override public ManaOptions available(Player viewer, Game game) { return modes.available(viewer, game); }
    @Override public ManaOptions available(Player viewer, Game game, boolean fast) { return dialogs.available(viewer, game, fast); }
    @Override public Mode earlier(World world, Map<String, Object> decision, Modes available, Ability source,
                                  Game game, Map<String, Object> semantic) {
        return modes.earlier(world, decision, available, source, game, semantic);
    }
    @Override public boolean earlierUse(World world, Map<String, Object> decision, Outcome outcome, String message,
                                        Ability source, Game game, Map<String, Object> semantic) {
        return dialogs.earlierUse(world, decision, outcome, message, source, game, semantic);
    }
    @Override public int earlierX(World world, Map<String, Object> decision, int min, int max, boolean mana,
                                  Ability source, Game game, Map<String, Object> semantic) {
        return dialogs.earlierX(world, decision, min, max, mana, source, game, semantic);
    }
    @Override public Map<String, Object> encode(World world, Map<String, Object> decision, Modes available, Ability source, Game game) {
        throw new IllegalArgumentException("target feature capture reached an unrecorded mode callback");
    }
    @Override public Map<String, Object> encodeUse(World world, Map<String, Object> decision, Outcome outcome, String message,
                                                  Ability source, Game game) {
        throw new IllegalArgumentException("target feature capture reached an unrecorded binary callback");
    }
    @Override public Map<String, Object> encodeX(World world, Map<String, Object> decision, int min, int max, boolean mana,
                                                Ability source, Game game) {
        throw new IllegalArgumentException("target feature capture reached an unrecorded X callback");
    }

    static String pin(String name) {
        String value = System.getProperty("spellbench.maintainer." + name);
        if (value == null || !value.matches("[a-f0-9]{64}")) throw new IllegalArgumentException("target source pin missing: " + name);
        return value;
    }
    static Class<?> original(String name) throws ReflectiveOperationException {
        Class<?> type = Class.forName("spellbench.models.maintainer." + name);
        if (!MaintainerModeEncoder.SOURCE.equals(type.getField("SOURCE_SHA256").get(null))) {
            throw new IllegalArgumentException("target class differs from the original callback: " + name);
        }
        return type;
    }
    @SuppressWarnings("unchecked")
    @Override public boolean select(Player viewer, Outcome outcome, Target target, Ability source, Game game, ModelReplay.TargetPick picker) {
        try {
            Class<?> rules = original("TargetRules"), callback = Class.forName("spellbench.models.maintainer.TargetRules$Picker");
            Object listener = Proxy.newProxyInstance(callback.getClassLoader(), new Class<?>[]{callback}, (proxy, method, args) -> {
                if (!"choose".equals(method.getName()) || args == null || args.length != 7) {
                    throw new IllegalArgumentException("unexpected original target picker call");
                }
                return picker.choose((List<UUID>) args[0], (Integer) args[1], (Integer) args[2], (Integer) args[3],
                        (Boolean) args[4], (UUID) args[5], (String) args[6]);
            });
            return (Boolean) rules.getMethod("select", Outcome.class, Target.class, Ability.class, Game.class, callback)
                    .invoke(rules.getConstructor(Player.class).newInstance(viewer), outcome, target, source, game, listener);
        } catch (ReflectiveOperationException e) {
            Throwable cause = e instanceof InvocationTargetException ? e.getCause() : e;
            if (cause instanceof RuntimeException) throw (RuntimeException) cause;
            if (cause instanceof Error) throw (Error) cause;
            throw new IllegalArgumentException("original target loop failed", cause);
        }
    }

    static long slot(Ability source, Target target) {
        if(source==null)return 0;
        long index = 0;
        for (UUID id : source.getModes().getSelectedModes()) {
            Mode mode = source.getModes().get(id); if (mode == null) continue;
            for (Target candidate : mode.getTargets()) { if (candidate == target) return index; index++; }
        }
        index = 0;
        for (Target candidate : source.getTargets()) { if (candidate == target) return index; index++; }
        return 0;
    }
    static final class Binding {
        final Map<UUID, String> permitted;
        final List<Object> targets = new ArrayList<>(), names = new ArrayList<>();
        final Map<UUID, Long> ids = new HashMap<>();
        final Map<UUID, Map<String, Object>> semantics = new HashMap<>();
        Binding(World world, Map<String, Object> decision, Target target, Ability source, Game game,
                List<UUID> possible, int selected, int minimum, int maximum) throws Exception {
            Map<String, Object> obs = Json.obj(decision, "observation"), context = Json.obj(decision, "context");
            if (!world.viewer.equals(Json.str(obs, "viewer")) || !world.viewer.equals(Json.str(decision, "acting_seat"))
                    || !"choice".equals(Json.str(context, "kind"))
                    || source!=null && !world.player(world.viewer).equals(source.getControllerId()) || possible.isEmpty() || possible.size() > 4097
                    || selected < 0 || minimum < 0 || maximum < minimum || maximum > 4096 || selected > maximum) {
                throw new IllegalArgumentException("general target callback exceeds its acting-player scope or envelope");
            }
            ObsIndex visible = new ObsIndex(obs);
            Map<String, Object> reference = Json.obj(context, "source");
            if(source==null) {
                if(!(target instanceof mage.target.common.TargetDiscard) || game.getTurnStepType()!=mage.constants.PhaseStep.CLEANUP
                        || !world.player(world.viewer).equals(game.getActivePlayerId()) || !MaintainerGeneralTargetEncoder.cleanupMenu(decision,world.viewer,true)
                        || target.getTargets().size()!=selected || target.getMinNumberOfTargets()!=minimum || target.getMaxNumberOfTargets()!=maximum)
                    throw new IllegalArgumentException("source-free target lacks its actual cleanup discard callback");
                for(UUID id:possible)if(id==null || !world.viewerPlayer().getHand().contains(id) || game.getCard(id)==null
                        || !world.player(world.viewer).equals(game.getCard(id).getOwnerId()))
                    throw new IllegalArgumentException("cleanup target escaped the actual named own hand");
            } else if (reference == null || !Json.canonical(reference).equals(Json.canonical(visible.ref(Json.str(reference, "object_id"))))) {
                throw new IllegalArgumentException("target source differs from its visible reference");
            }
            permitted = MaintainerModeEncoder.namedAliases(world, decision);
            UUID sourceId = null;
            if (source != null) for (Map.Entry<UUID, String> entry : permitted.entrySet())
                if (entry.getValue().equals(Json.str(reference, "object_id"))) sourceId = entry.getKey();
            if (source!=null && (sourceId == null || !(sourceId.equals(source.getSourceId()) || game.getStack().getStackObject(sourceId) != null
                    && source.getSourceId().equals(game.getStack().getStackObject(sourceId).getSourceId())))) {
                throw new IllegalArgumentException("target callback has another actual source");
            }
            Set<UUID> unique = new HashSet<>();
            for (UUID id : possible) {
                if (!unique.add(id)) throw new IllegalArgumentException("original targets repeat an object or STOP");
                if (id == null) { targets.add(null); names.add(null); continue; }
                String seat = world.seatOf(id); MageObject object = game.getObject(id);
                if (seat != null) {
                    if (object != null && !seat.equals(object.getName())) throw new IllegalArgumentException("rebuilt player name changed");
                    targets.add(Json.map("player", seat)); names.add(object == null ? null : object.getName());
                } else {
                    String alias = permitted.get(id); Map<String, Object> ref = alias == null ? null : visible.ref(alias);
                    if (ref == null || object == null || !object.getName().equals(Json.str(ref, "card_name"))) {
                        throw new IllegalArgumentException("original target is not a named permitted object");
                    }
                    targets.add(Json.map("object", ref)); names.add(object.getName());
                }
            }
            Set<Long> publicIds = new HashSet<>(); long slot = slot(source, target);
            for (Object item : Json.arr(decision, "candidates")) {
                Map<String, Object> candidate = Json.obj(item), semantic = Json.obj(candidate, "semantic");
                Object cid = candidate.get("candidate_id"); String kind = Json.str(semantic, "kind");
                if (!(cid instanceof Long) || (Long) cid < 0 || (Long) cid > 9007199254740991L || !publicIds.add((Long) cid)
                        || !Json.canonical(reference).equals(Json.canonical(semantic.get("source")))
                        || !Long.valueOf(selected).equals(semantic.get("selected_count")) || !Long.valueOf(slot).equals(semantic.get("slot"))) {
                    throw new IllegalArgumentException("target action has another source, slot or selected count");
                }
                UUID id;
                if ("choose_target".equals(kind)) {
                    id = Dialogs.uuidOf(world, semantic);
                    if (id == null || !possible.contains(id) || !Long.valueOf(minimum).equals(semantic.get("minimum"))
                            || !Long.valueOf(maximum).equals(semantic.get("maximum"))
                            || !Json.canonical(targets.get(possible.indexOf(id))).equals(Json.canonical(semantic.get("target")))) {
                        throw new IllegalArgumentException("public target differs from the original order, range or visible object");
                    }
                } else if ("finish_target_selection".equals(kind) && possible.contains(null) && target.isChosen(game)) id = null;
                else throw new IllegalArgumentException("original spell targets exclude unrelated or unavailable actions");
                if (ids.containsKey(id)) throw new IllegalArgumentException("public target aliases an original object or STOP");
                ids.put(id, (Long) cid); semantics.put(id, semantic);
            }
            for (UUID id : possible) if (!ids.containsKey(id)) throw new IllegalArgumentException("an original target or STOP was not offered");
        }
    }

    @Override public UUID earlier(World world, Map<String, Object> decision, Target target, Ability source, Game game,
                                  List<UUID> possible, int selected, int minimum, int maximum,
                                  boolean forced, UUID direct, String reason, Map<String, Object> semantic) {
        try {
            Binding bound = new Binding(world, decision, target, source, game, possible, selected, minimum, maximum);
            UUID pick = "finish_target_selection".equals(Json.str(semantic, "kind")) ? null : Dialogs.uuidOf(world, semantic);
            if (!bound.semantics.containsKey(pick) || !Json.canonical(bound.semantics.get(pick)).equals(Json.canonical(semantic))
                    || forced && !java.util.Objects.equals(pick, direct)
                    || !forced && !possible.subList(0, Math.min(64, possible.size())).contains(pick)) {
                throw new IllegalArgumentException("recorded target differs from the original direct return or first 64 slots");
            }
            return pick;
        } catch (RuntimeException e) { throw e; }
        catch (Exception e) { throw new IllegalStateException("original recorded target binding failed", e); }
    }
    @Override public Map<String, Object> encode(World world, Map<String, Object> decision, Target target, Ability source, Game game,
                                               List<UUID> possible, int selected, int minimum, int maximum,
                                               boolean forced, UUID direct, String reason) {
        try {
            if (!world.viewer.equals(Json.str(start, "seat"))) throw new IllegalArgumentException("target start belongs to another seat");
            for (String flag : world.flags) if (flag.startsWith("unsupported:") || flag.startsWith("horizon:")) {
                throw new IllegalArgumentException("unsupported target replay: " + flag);
            }
            Binding bound = new Binding(world, decision, target, source, game, possible, selected, minimum, maximum);
            int count = Math.min(64, possible.size());
            Map<String, Object> result = Json.map("schema", "spellbench-maintainer-target-features/v1",
                    "decision_sha256", MaintainerModeEncoder.hash(decision), "game_start_sha256", MaintainerModeEncoder.hash(start),
                    "encoder_source_sha256", pin("encoderSourceSha256"), "candidate_source_sha256", pin("candidateSourceSha256"),
                    "target_rules_source_sha256", pin("targetRulesSourceSha256"), "mode_rules_source_sha256", pin("modeRulesSourceSha256"),
                    "dialog_rules_source_sha256", pin("dialogRulesSourceSha256"), "mana_payment_rules_source_sha256", payments.sourceSha256(),
                    "embedding_cache_sha256", pin("embeddingSha256"), "original_callback_sha256", MaintainerModeEncoder.SOURCE,
                    "variant", VARIANT, "mana_payment_variant", MaintainerManaReplay.VARIANT, "world_flags", world.flags,
                    "target_count", (long) possible.size(), "candidate_count", (long) count, "original_targets", bound.targets,
                    "original_names", bound.names, "selected_count", (long) selected,
                    "minimum", (long) minimum, "maximum", (long) maximum);
            if (forced) {
                if (!possible.contains(direct) || !bound.ids.containsKey(direct)) throw new IllegalArgumentException("original direct target is unavailable");
                result.putAll(Json.map("kind", "maintainer-target-forced", "forced_candidate_id", bound.ids.get(direct),
                        "forced_original_index", (long) possible.indexOf(direct), "reason", reason));
                return result;
            }
            Class<?> encoder = Class.forName("spellbench.models.maintainer.StateSequenceBuilder");
            Object state = encoder.getMethod("buildBaseState", Game.class, TurnPhase.class, int.class, UUID.class, Map.class)
                    .invoke(null, game, game.getPhase() == null ? null : game.getPhase().getType(), 256, world.player(world.viewer), bound.permitted);
            float[][] tokens = (float[][]) state.getClass().getField("tokens").get(state);
            int[] padding = (int[]) state.getClass().getField("mask").get(state), tokenIds = (int[]) state.getClass().getField("tokenIds").get(state);
            if (tokens.length != 256 || padding.length != 256 || tokenIds.length != 256) throw new IllegalArgumentException("target state shape changed");
            List<Object> rows = new ArrayList<>(), masks = new ArrayList<>(), tokenRefs = new ArrayList<>();
            for (int i = 0; i < 256; i++) {
                if (padding[i] != 0 && padding[i] != 1 || tokenIds[i] < 0 || tokenIds[i] >= 65536) throw new IllegalArgumentException("target state mask or token ID changed");
                rows.add(MaintainerModeEncoder.numbers(tokens[i], 128)); masks.add(padding[i] == 1); tokenRefs.add((long) tokenIds[i]);
            }
            Class<?> codec = original("CandidateEncoder"); Object candidates = codec.getConstructor(Player.class).newInstance(world.viewerPlayer());
            if (!"target".equals(codec.getMethod("head", String.class).invoke(null, "SELECT_TARGETS"))) throw new IllegalArgumentException("original target head changed");
            List<Object> features = new ArrayList<>(), actionIds = new ArrayList<>(), legal = new ArrayList<>(), refs = new ArrayList<>();
            for (int i = 0; i < 64; i++) {
                float[] values = new float[48]; int actionId = 0;
                if (i < count) {
                    UUID id = possible.get(i);
                    actionId = (Integer) codec.getMethod("candidateId", String.class, Game.class, Ability.class, Object.class)
                            .invoke(candidates, "SELECT_TARGETS", game, source, id);
                    values = (float[]) codec.getMethod("candidateFeatures", String.class, Game.class, Ability.class, Object.class, state.getClass())
                            .invoke(candidates, "SELECT_TARGETS", game, source, id, state);
                    if (actionId <= 0 || actionId >= 65536) throw new IllegalArgumentException("original target ID changed");
                    refs.add(Json.map("index", (long) i, "candidate_id", bound.ids.get(id), "target", bound.targets.get(i)));
                }
                features.add(MaintainerModeEncoder.numbers(values, 48)); actionIds.add((long) actionId); legal.add(i < count);
            }
            result.putAll(Json.map("kind", "candidates", "head", "target", "sequence", rows, "padding", masks,
                    "token_ids", tokenRefs, "candidate_features", features, "candidate_ids", actionIds,
                    "candidate_mask", legal, "candidate_refs", refs));
            return result;
        } catch (RuntimeException e) { throw e; }
        catch (Exception e) { throw new IllegalStateException("original target encoding failed", e); }
    }
}
