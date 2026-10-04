package spellbench.kit.xmage;

import mage.abilities.Ability;
import mage.abilities.Mode;
import mage.abilities.Modes;
import mage.abilities.mana.ManaOptions;
import mage.constants.TurnPhase;
import mage.game.Game;
import mage.players.Player;
import mage.cards.Card;
import mage.game.ExileZone;
import mage.game.command.CommandObject;
import mage.game.permanent.Permanent;
import mage.game.stack.StackObject;
import mage.player.spellbench.observe.Look;
import mage.player.spellbench.observe.Observation;
import mage.player.spellbench.observe.ObservationBuilder;
import spellbench.kit.core.Json;
import spellbench.kit.core.ObsIndex;
import spellbench.kit.core.ObsCompare;
import spellbench.kit.core.Seeds;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

/** Original mode slots and features on a verified permitted callback replay. */
final class JackModeEncoder implements ModelReplay.ModeCapture {
    static final String SOURCE = "b45257a66fc3914506fca4dd83461b6c8853d129b3e1f38b2d3aeba6137bd0c6";
    static final String VARIANT = "original available-mode order, legality mask, 64-slot cap and ordinal feature; "
            + "permitted callback replay; refusal instead of heuristic fallback; cost-bearing multi-mode callbacks unsupported";
    static final String MANA_VARIANT = "original available-mode order, legality mask, 64-slot cap, ordinal and mode-cost features; "
            + "original filtered mana availability on permitted callback replay; refusal instead of heuristic fallback; "
            + "automatic mana production and other callbacks unqualified";
    private final Map<String, Object> start;
    private final boolean originalMana;

    JackModeEncoder(Map<String, Object> start) { this(start, false); }
    JackModeEncoder(Map<String, Object> start, boolean originalMana) {
        this.start = start; this.originalMana = originalMana;
    }

    @Override public ManaOptions available(Player viewer, Game game) {
        if (!originalMana) return null;
        ManaOptions available = JackDialogEncoder.originalManaAvailable(viewer, game, false);
        if (available == null) throw new IllegalArgumentException("original mode mana rules returned no availability");
        return available;
    }

    static String hash(Object value) {
        try {
            return Seeds.hex(MessageDigest.getInstance("SHA-256")
                    .digest(Json.canonical(value).getBytes(StandardCharsets.UTF_8)));
        } catch (Exception e) { throw new IllegalStateException(e); }
    }

    private static String pin(String name) {
        String value = System.getProperty("spellbench.jack." + name);
        if (value == null || !value.matches("[a-f0-9]{64}")) {
            throw new IllegalArgumentException("Jack mode needs its staged " + name);
        }
        return value;
    }

    private static Class<?> original(String name) throws Exception {
        Class<?> type = Class.forName("spellbench.models.jack." + name);
        if (!SOURCE.equals(type.getField("SOURCE_SHA256").get(null))) {
            throw new IllegalArgumentException("Jack mode codec differs from its original callback");
        }
        return type;
    }

    private static final class Binding {
        final List<Mode> all, available;
        final Map<Integer, Map<String, Object>> offered = new HashMap<>();
        final Map<Integer, Long> ids = new HashMap<>();
        final boolean[] mask;
        final List<Object> order = new ArrayList<>();
        final Map<UUID, String> permitted;
        Long finish;

        Binding(World world, Map<String, Object> decision, Modes modes, Ability source, Game game) throws Exception {
            String viewer = Json.str(Json.obj(decision, "observation"), "viewer");
            if (!world.viewer.equals(viewer) || !viewer.equals(Json.str(decision, "acting_seat"))
                    || source == null || !world.player(viewer).equals(source.getControllerId())) {
                throw new IllegalArgumentException("mode callback needs the acting viewer's actual source");
            }
            Map<String, Object> reference = Json.obj(Json.obj(decision, "context"), "source");
            ObsIndex observed = new ObsIndex(Json.obj(decision, "observation"));
            if (reference == null || !Json.canonical(reference).equals(Json.canonical(observed.ref(Json.str(reference, "object_id"))))) {
                throw new IllegalArgumentException("mode source differs from its visible reference");
            }
            permitted = namedAliases(world, decision);
            UUID id = null;
            for (Map.Entry<UUID, String> entry : permitted.entrySet()) {
                if (entry.getValue().equals(Json.str(reference, "object_id"))) id = entry.getKey();
            }
            if (id == null || !(id.equals(source.getSourceId()) || game.getStack().getStackObject(id) != null
                    && source.getSourceId().equals(game.getStack().getStackObject(id).getSourceId()))) {
                throw new IllegalArgumentException("mode callback has a different visible source");
            }
            all = new ArrayList<>(modes.values());
            available = new ArrayList<>(modes.getAvailableModes(source, game));
            if (available.size() > 4096) throw new IllegalArgumentException("mode callback exceeds the supported envelope");
            int count = Math.min(64, available.size());
            mask = new boolean[count];
            Set<Integer> used = new HashSet<>();
            for (int i = 0; i < count; i++) {
                int index = all.indexOf(available.get(i));
                if (index < 0 || !used.add(index)) throw new IllegalArgumentException("aliased original mode order");
                order.add((long) index);
            }
            Set<Long> publicIds = new HashSet<>();
            Set<Integer> publicModes = new HashSet<>();
            List<Object> candidates = Json.arr(decision, "candidates");
            if (candidates.isEmpty()) throw new IllegalArgumentException("mode root has no offered actions");
            for (Object item : candidates) {
                Map<String, Object> candidate = Json.obj(item), semantic = Json.obj(candidate, "semantic");
                Object cid = candidate.get("candidate_id");
                if (!(cid instanceof Long) || (Long) cid < 0 || (Long) cid > 9007199254740991L
                        || !publicIds.add((Long) cid)
                        || !Json.canonical(reference).equals(Json.canonical(semantic.get("source")))) {
                    throw new IllegalArgumentException("mode candidate is aliased or belongs to another source");
                }
                String kind = Json.str(semantic, "kind");
                if ("choose_spell_mode".equals(kind)) {
                    Object index = semantic.get("mode_index");
                    if (!(index instanceof Long) || (Long) index < 0 || (Long) index >= all.size()
                            || !publicModes.add(Math.toIntExact((Long) index))
                            || Json.num(semantic, "mode_count", -1) != all.size()
                            || Json.num(semantic, "selected_count", -1) != modes.getSelectedModes().size()
                            || Json.num(semantic, "minimum", -1) != modes.getMinModes()
                            || Json.num(semantic, "maximum", -1) != Math.min(modes.getMaxModes(game, source), all.size())) {
                        throw new IllegalArgumentException("mode candidate has a different index, count or range");
                    }
                    int ordinal = available.indexOf(all.get(Math.toIntExact((Long) index)));
                    if (ordinal < 0) throw new IllegalArgumentException("offered mode is absent from the actual callback");
                    if (ordinal < count) { offered.put(ordinal, semantic); ids.put(ordinal, (Long) cid); }
                } else if ("finish_selection".equals(kind) && "modes".equals(Json.str(semantic, "purpose"))) {
                    int selected = modes.getSelectedModes().size();
                    if (finish != null || Json.num(semantic, "selected_count", -1) != selected
                            || !(modes.getMaxPawPrints() > 0 ? selected > 0
                            : selected >= modes.getMinModes() || modes.isMayChooseNone() && selected == 0)) {
                        throw new IllegalArgumentException("mode finish is unavailable at the actual callback");
                    }
                    finish = (Long) cid;
                } else throw new IllegalArgumentException("mode root mixes unrelated actions");
            }
            if (count == 0 && finish == null) {
                throw new IllegalArgumentException("original exhausted mode callback has no offered finish");
            }
        }

        void applyMask(World world, Ability source, Game game, boolean originalMana) throws Exception {
            Class<?> rules = original("ModeRules");
            Object checker = rules.getConstructor(Player.class).newInstance(world.viewerPlayer());
            int legal = 0;
            for (int i = 0; i < mask.length; i++) {
                if (!originalMana && available.size() > 1 && available.get(i).getCost() != null) {
                    throw new IllegalArgumentException("original cost-bearing modes need Jack's custom mana filters");
                }
                // Preserve the original direct return before any legality check.
                mask[i] = available.size() == 1 || (Boolean) rules.getMethod("legal", Mode.class, Ability.class, Game.class)
                        .invoke(checker, available.get(i), source, game);
                if (!mask[i]) continue;
                legal++;
                if (!ids.containsKey(i)) throw new IllegalArgumentException("original selectable mode is not offered");
            }
            if (mask.length > 0 && legal == 0) {
                throw new IllegalArgumentException("original mode requires an unavailable action or heuristic fallback");
            }
        }
    }

    @Override public Mode earlier(World world, Map<String, Object> decision, Modes modes, Ability source,
                                   Game game, Map<String, Object> semantic) {
        try {
            Binding bound = new Binding(world, decision, modes, source, game);
            bound.applyMask(world, source, game, originalMana);
            if ("finish_selection".equals(Json.str(semantic, "kind")) && bound.finish != null) return null;
            for (Map.Entry<Integer, Map<String, Object>> entry : bound.offered.entrySet()) {
                if (bound.mask[entry.getKey()] && Json.canonical(entry.getValue()).equals(Json.canonical(semantic))) {
                    return bound.available.get(entry.getKey());
                }
            }
            throw new IllegalArgumentException("recorded mode is absent from the original bound slots");
        } catch (RuntimeException e) { throw e; }
        catch (Exception e) { throw new IllegalStateException("original earlier mode binding failed", e); }
    }

    @Override public Map<String, Object> encode(World world, Map<String, Object> decision, Modes modes,
                                               Ability source, Game game) {
        try {
            if (!world.viewer.equals(Json.str(start, "seat"))) throw new IllegalArgumentException("mode start belongs to another seat");
            for (String flag : world.flags) if (flag.startsWith("unsupported:") || flag.startsWith("horizon:")) {
                throw new IllegalArgumentException("unsupported mode replay: " + flag);
            }
            Binding bound = new Binding(world, decision, modes, source, game);
            Map<String, Object> result = Json.map("schema", "spellbench-jack-mode-features/v1",
                    "decision_sha256", hash(decision), "game_start_sha256", hash(start),
                    "encoder_source_sha256", pin("encoderSourceSha256"),
                    "candidate_source_sha256", pin("candidateSourceSha256"),
                    "mode_rules_source_sha256", pin("modeRulesSourceSha256"),
                    "embedding_cache_sha256", pin("embeddingSha256"), "original_callback_sha256", SOURCE,
                    "variant", originalMana ? MANA_VARIANT : VARIANT, "world_flags", world.flags,
                    "available_count", (long) bound.available.size(), "candidate_count", (long) bound.mask.length,
                    "original_mode_indices", bound.order);
            if (originalMana) {
                List<Object> costs = new ArrayList<>();
                for (int i = 0; i < bound.mask.length; i++) costs.add(bound.available.get(i).getCost() != null);
                result.put("original_mode_cost_flags", costs);
                result.put("dialog_rules_source_sha256", pin("dialogRulesSourceSha256"));
            }
            if (bound.available.size() <= 1) {
                bound.applyMask(world, source, game, originalMana);
                result.put("kind", "jack-mode-forced");
                result.put("forced_candidate_id", bound.available.isEmpty() ? bound.finish : bound.ids.get(0));
                result.put("reason", bound.available.isEmpty() ? "no_available_modes" : "single_available_mode");
                return result;
            }
            Class<?> encoder = Class.forName("spellbench.models.jack.StateSequenceBuilder");
            Object state = encoder.getMethod("buildBaseState", Game.class, TurnPhase.class, int.class, UUID.class, Map.class)
                    .invoke(null, game, game.getPhase() == null ? null : game.getPhase().getType(),
                            256, world.player(world.viewer), bound.permitted);
            float[][] tokens = (float[][]) state.getClass().getField("tokens").get(state);
            int[] padding = (int[]) state.getClass().getField("mask").get(state);
            int[] tokenIds = (int[]) state.getClass().getField("tokenIds").get(state);
            if (tokens.length != 256 || padding.length != 256 || tokenIds.length != 256) {
                throw new IllegalArgumentException("original mode state has the wrong shape");
            }
            List<Object> rows = new ArrayList<>(), masks = new ArrayList<>(), ids = new ArrayList<>();
            for (int i = 0; i < 256; i++) {
                if (padding[i] != 0 && padding[i] != 1 || tokenIds[i] < 0 || tokenIds[i] >= 65536) {
                    throw new IllegalArgumentException("original mode state has invalid padding or token IDs");
                }
                rows.add(numbers(tokens[i], 128)); masks.add(padding[i] == 1); ids.add((long) tokenIds[i]);
            }
            // The original builds its base state before checking mode costs/targets.
            bound.applyMask(world, source, game, originalMana);
            Class<?> codec = original("CandidateEncoder");
            Object candidates = codec.getConstructor(Player.class).newInstance(world.viewerPlayer());
            if (!"action".equals(codec.getMethod("head", String.class).invoke(null, "CHOOSE_MODE"))) {
                throw new IllegalArgumentException("original mode has an unexpected policy head");
            }
            List<Object> features = new ArrayList<>(), actionIds = new ArrayList<>(), legal = new ArrayList<>(), refs = new ArrayList<>();
            for (int i = 0; i < 64; i++) {
                float[] values = new float[48]; int actionId = 0;
                if (i < bound.mask.length) {
                    Mode option = bound.available.get(i);
                    actionId = (Integer) codec.getMethod("candidateId", String.class, Game.class, Ability.class, Object.class)
                            .invoke(candidates, "CHOOSE_MODE", game, source, option);
                    values = (float[]) codec.getMethod("candidateFeatures", String.class, Game.class, Ability.class,
                            Object.class, state.getClass()).invoke(candidates, "CHOOSE_MODE", game, source, option, state);
                    if (values.length != 48 || actionId <= 0 || actionId >= 65536) {
                        throw new IllegalArgumentException("original mode has an invalid feature shape or ID");
                    }
                    values[0] = i / (float) bound.mask.length;
                    if (bound.mask[i]) refs.add(Json.map("index", (long) i, "mode_index", bound.order.get(i),
                            "candidate_id", bound.ids.get(i)));
                }
                features.add(numbers(values, 48)); actionIds.add((long) actionId);
                legal.add(i < bound.mask.length && bound.mask[i]);
            }
            result.putAll(Json.map("kind", "candidates", "head", "action", "sequence", rows,
                    "padding", masks, "token_ids", ids, "candidate_features", features,
                    "candidate_ids", actionIds, "candidate_mask", legal, "candidate_refs", refs));
            return result;
        } catch (RuntimeException e) { throw e; }
        catch (Exception e) { throw new IllegalStateException("original mode encoding failed", e); }
    }

    static List<Object> numbers(float[] values, int width) {
        if (values.length != width) throw new IllegalArgumentException("original mode vector has the wrong width");
        List<Object> result = new ArrayList<>();
        for (float value : values) {
            if (!Float.isFinite(value) || Math.abs(value) > 1000000) {
                throw new IllegalArgumentException("original mode vector contains invalid numbers");
            }
            result.add((double) value);
        }
        return result;
    }

    static Map<UUID, String> namedAliases(World world, Map<String, Object> decision) throws Exception {
        Map<String, Object> obs = Json.obj(decision, "observation");
        ObsIndex index = new ObsIndex(obs);
        List<Look> looks = new ArrayList<>();
        for (Object item : Json.arr(obs, "known")) {
            Map<String, Object> known = Json.obj(item);
            UUID id = world.idToUuid.get(Json.str(known, "object_id"));
            String how = Json.str(known, "how");
            if (id == null || !("looked_at".equals(how) || "revealed".equals(how) || "searching".equals(how))) continue;
            Number top = (Number) known.get("position_from_top"), bottom = (Number) known.get("position_from_bottom");
            looks.add(new Look(id, how, top == null ? null : top.intValue(), bottom == null ? null : bottom.intValue()));
        }
        Observation visible = ObservationBuilder.forSession(world.game, new byte[32], RoundTrip.flagsFrom(decision))
                .build(world.viewer, Json.str(obs, "priority_seat"), looks);
        Map<String, Object> projected = Json.obj(Json.copy(visible.json()));
        if (!ObsCompare.diff(obs, projected, 8).isEmpty()) {
            throw new IllegalArgumentException("mode aliases differ from the verified current observation");
        }
        Map<String, String> aliases = ObsCompare.alignIds(projected, obs);
        List<UUID> objects = new ArrayList<>();
        // A spell and its underlying card share a reference. Keep the stack
        // entity first, matching the original base-state entity list.
        for (StackObject object : world.game.getStack()) objects.add(object.getId());
        for (CommandObject object : world.game.getState().getCommand()) objects.add(object.getId());
        for (Player player : world.game.getPlayers().values()) {
            for (Permanent object : world.game.getBattlefield().getAllActivePermanents(player.getId())) objects.add(object.getId());
            for (Card card : player.getHand().getCards(world.game)) objects.add(card.getId());
            for (Card card : player.getGraveyard().getCards(world.game)) objects.add(card.getId());
            for (Card card : player.getLibrary().getCards(world.game)) objects.add(card.getId());
        }
        for (ExileZone zone : world.game.getExile().getExileZones()) {
            for (Card card : zone.getCards(world.game)) objects.add(card.getId());
        }
        Map<UUID, String> result = new LinkedHashMap<>();
        Set<String> used = new HashSet<>();
        for (UUID id : objects) {
            Map<String, Object> ref = visible.reference(id);
            if (ref == null || Json.str(ref, "card_name") == null || Json.str(ref, "card_name").isEmpty()) continue;
            String alias = aliases.get(Json.str(ref, "object_id"));
            if (alias == null) throw new IllegalArgumentException("named replay entity has no public alias");
            ref.put("object_id", alias);
            if (!Json.canonical(ref).equals(Json.canonical(index.ref(alias)))) {
                throw new IllegalArgumentException("named replay reference differs from the permitted source");
            }
            if (used.add(alias)) result.put(id, alias);
        }
        for (String alias : index.ids()) {
            String name = Json.str(index.ref(alias), "card_name");
            if (name != null && !name.isEmpty() && !used.contains(alias)) {
                throw new IllegalArgumentException("named permitted entity is absent from the replay map");
            }
        }
        return result;
    }
}
