package spellbench.kit.xmage;

import mage.abilities.Ability;
import mage.cards.Cards;
import mage.constants.Outcome;
import mage.constants.TurnPhase;
import mage.game.Game;
import mage.players.Player;
import mage.target.Target;
import mage.target.TargetCard;
import mage.target.common.TargetCardInHand;
import mage.target.common.TargetCardInLibrary;
import spellbench.kit.core.Json;

import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Proxy;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

/** Original provided-card groups and features; the owner chooses a seeded physical copy. */
class JackCardSetEncoder extends JackGeneralTargetEncoder implements ModelReplay.CardSetCapture {
    static final String RULE_VARIANT = "original provided-card filtering, library/hand name groups, first available representatives, "
            + "sequential STOP gates, first 64 groups and minimum completion; original card_select head; "
            + "permitted callback replay; refusal instead of model-error fallback; "
            + "owned MT19937 copy stream derived from game start, singleton copies direct; "
            + "chooseTarget(Cards) only, inherited choose(Cards), divided and opponent callbacks unqualified";
    static final String VARIANT = RULE_VARIANT + "; " + JackManaReplay.VARIANT;
    private final Map<String, Object> start;

    JackCardSetEncoder(Map<String, Object> start, ModelReplay.ManaCapture payments) {
        super(start, payments); this.start = start;
    }
    @Override public Map<String, Object> encode(World world, Map<String, Object> decision, Target target, Ability source, Game game,
                                               List<UUID> possible, int selected, int minimum, int maximum,
                                               boolean forced, UUID direct, String reason) {
        throw new IllegalArgumentException("card-set capture reached an unrecorded general target callback");
    }
    @SuppressWarnings("unchecked")
    @Override public boolean selectCards(Player viewer, Outcome outcome, Cards cards, TargetCard target, Ability source, Game game,
                                         ModelReplay.CardSetPick picker) {
        try {
            Class<?> rules = JackTargetEncoder.original("CardSetRules"), callback = Class.forName("spellbench.models.jack.CardSetRules$Picker");
            Object listener = Proxy.newProxyInstance(callback.getClassLoader(), new Class<?>[]{callback}, (proxy, method, args) -> {
                if (!"choose".equals(method.getName()) || args == null || args.length != 6) {
                    throw new IllegalArgumentException("unexpected original card-set picker call");
                }
                return picker.choose((List<List<UUID>>) args[0], (Integer) args[1], (Integer) args[2], (Integer) args[3],
                        (Boolean) args[4], (Boolean) args[5]);
            });
            return (Boolean) rules.getMethod("select", Outcome.class, Cards.class, TargetCard.class, Ability.class, Game.class, callback)
                    .invoke(rules.getConstructor(Player.class).newInstance(viewer), outcome, cards, target, source, game, listener);
        } catch (ReflectiveOperationException e) {
            Throwable cause = e instanceof InvocationTargetException ? e.getCause() : e;
            if (cause instanceof RuntimeException) throw (RuntimeException) cause;
            if (cause instanceof Error) throw (Error) cause;
            throw new IllegalArgumentException("original provided-card loop failed", cause);
        }
    }

    private static final class Groups {
        final JackTargetEncoder.Binding bound;
        final List<Object> refs = new ArrayList<>();
        final List<UUID> flat = new ArrayList<>(), representatives = new ArrayList<>();
        Groups(World world, Map<String, Object> decision, TargetCard target, Ability source, Game game,
               List<List<UUID>> groups, int selected, int minimum, int maximum, boolean forced, boolean deduplicated) throws Exception {
            if (groups == null || groups.isEmpty() || groups.size() > 4097 || forced != (groups.size() == 1)
                    || deduplicated != (target instanceof TargetCardInLibrary || target instanceof TargetCardInHand)) {
                throw new IllegalArgumentException("provided-card group type or direct return changed");
            }
            Set<String> names = new HashSet<>();
            for (int i = 0; i < groups.size(); i++) {
                List<UUID> group = groups.get(i);
                if (group == null || !deduplicated && group.size() > 1) throw new IllegalArgumentException("original card group changed");
                if (group.isEmpty()) {
                    if (i != 0 || selected < minimum) throw new IllegalArgumentException("card STOP precedes its original minimum");
                    flat.add(null); representatives.add(null); continue;
                }
                String name = null;
                for (UUID id : group) {
                    if (id == null || game.getCard(id) == null) throw new IllegalArgumentException("original group contains a missing card");
                    String current = game.getCard(id).getName();
                    if (name != null && !name.equals(current)) throw new IllegalArgumentException("original name group mixes cards");
                    name = current; flat.add(id);
                }
                if (deduplicated && !names.add(name)) throw new IllegalArgumentException("original card name appears in multiple groups");
                representatives.add(group.get(0));
            }
            if (flat.isEmpty() || flat.size() > 4097 || representatives.stream().allMatch(id -> id == null)) {
                throw new IllegalArgumentException("provided-card frame has no original card choices");
            }
            for (Object value : Json.arr(decision, "candidates")) {
                String kind = Json.str(Json.obj(Json.obj(value), "semantic"), "kind");
                if (!"select_object".equals(kind) && !"finish_selection".equals(kind)
                        && !"choose_target".equals(kind) && !"finish_target_selection".equals(kind)) {
                    throw new IllegalArgumentException("provided-card frame has an unrelated wire action");
                }
            }
            bound = new JackTargetEncoder.Binding(world, JackGeneralTargetEncoder.normalizeDecision(decision, JackTargetEncoder.slot(source, target)),
                    target, source, game, flat, selected, minimum, maximum);
            int position = 0;
            for (List<UUID> group : groups) {
                List<Object> members = new ArrayList<>();
                if (group.isEmpty()) position++;
                else for (UUID ignored : group) members.add(bound.targets.get(position++));
                refs.add(members);
            }
        }
        List<Object> ids(List<UUID> group) {
            List<Object> result = new ArrayList<>();
            if (group.isEmpty()) result.add(bound.ids.get(null));
            else for (UUID id : group) result.add(bound.ids.get(id));
            return result;
        }
    }

    @Override public UUID earlierCards(World world, Map<String, Object> decision, TargetCard target, Ability source, Game game,
                                       List<List<UUID>> groups, int selected, int minimum, int maximum,
                                       boolean forced, boolean deduplicated, Map<String, Object> semantic) {
        try {
            Groups binding = new Groups(world, decision, target, source, game, groups, selected, minimum, maximum, forced, deduplicated);
            String kind = Json.str(semantic, "kind");
            UUID pick = "finish_selection".equals(kind) || "finish_target_selection".equals(kind) ? null : Dialogs.uuidOf(world, semantic);
            boolean offered = false;
            for (List<UUID> group : groups.subList(0, Math.min(64, groups.size()))) {
                if (pick == null ? group.isEmpty() : group.contains(pick)) offered = true;
            }
            Map<String, Object> normalized = JackGeneralTargetEncoder.normalizeSemantic(semantic, JackTargetEncoder.slot(source, target));
            if (!offered || !binding.bound.semantics.containsKey(pick)
                    || !Json.canonical(binding.bound.semantics.get(pick)).equals(Json.canonical(normalized))) {
                throw new IllegalArgumentException("recorded card differs from its original group or visible action");
            }
            return pick;
        } catch (RuntimeException e) { throw e; }
        catch (Exception e) { throw new IllegalStateException("original card prefix binding failed", e); }
    }

    @Override public Map<String, Object> encodeCards(World world, Map<String, Object> decision, TargetCard target, Ability source, Game game,
                                                    List<List<UUID>> groups, int selected, int minimum, int maximum,
                                                    boolean forced, boolean deduplicated) {
        try {
            if (!world.viewer.equals(Json.str(start, "seat"))) throw new IllegalArgumentException("card start belongs to another seat");
            for (String flag : world.flags) if (flag.startsWith("unsupported:") || flag.startsWith("horizon:")) {
                throw new IllegalArgumentException("unsupported card replay: " + flag);
            }
            Groups binding = new Groups(world, decision, target, source, game, groups, selected, minimum, maximum, forced, deduplicated);
            int count = Math.min(64, groups.size());
            List<Object> ids = new ArrayList<>();
            for (List<UUID> group : groups) ids.add(binding.ids(group));
            Map<String, Object> result = Json.map("schema", "spellbench-jack-card-set-features/v1",
                    "decision_sha256", JackModeEncoder.hash(decision), "game_start_sha256", JackModeEncoder.hash(start),
                    "encoder_source_sha256", JackTargetEncoder.pin("encoderSourceSha256"), "candidate_source_sha256", JackTargetEncoder.pin("candidateSourceSha256"),
                    "target_rules_source_sha256", JackTargetEncoder.pin("targetRulesSourceSha256"), "mode_rules_source_sha256", JackTargetEncoder.pin("modeRulesSourceSha256"),
                    "dialog_rules_source_sha256", JackTargetEncoder.pin("dialogRulesSourceSha256"), "mana_payment_rules_source_sha256", paymentRules().sourceSha256(),
                    "card_set_rules_source_sha256", JackTargetEncoder.pin("cardSetRulesSourceSha256"), "embedding_cache_sha256", JackTargetEncoder.pin("embeddingSha256"),
                    "original_callback_sha256", JackModeEncoder.SOURCE, "variant", VARIANT, "mana_payment_variant", JackManaReplay.VARIANT,
                    "world_flags", world.flags, "group_count", (long) groups.size(), "candidate_count", (long) count,
                    "original_groups", binding.refs, "public_group_ids", ids, "deduplicated", deduplicated,
                    "selected_count", (long) selected, "minimum", (long) minimum, "maximum", (long) maximum);
            if (forced) {
                result.putAll(Json.map("kind", "jack-card-set-forced", "forced_group_index", 0L)); return result;
            }
            Class<?> encoder = Class.forName("spellbench.models.jack.StateSequenceBuilder");
            Object state = encoder.getMethod("buildBaseState", Game.class, TurnPhase.class, int.class, UUID.class, Map.class)
                    .invoke(null, game, game.getPhase() == null ? null : game.getPhase().getType(), 256, world.player(world.viewer), binding.bound.permitted);
            float[][] tokens = (float[][]) state.getClass().getField("tokens").get(state);
            int[] padding = (int[]) state.getClass().getField("mask").get(state), tokenIds = (int[]) state.getClass().getField("tokenIds").get(state);
            if (tokens.length != 256 || padding.length != 256 || tokenIds.length != 256) throw new IllegalArgumentException("card state shape changed");
            List<Object> rows = new ArrayList<>(), masks = new ArrayList<>(), tokenRefs = new ArrayList<>();
            for (int i = 0; i < 256; i++) {
                if (padding[i] != 0 && padding[i] != 1 || tokenIds[i] < 0 || tokenIds[i] >= 65536) throw new IllegalArgumentException("card state mask or token ID changed");
                rows.add(JackModeEncoder.numbers(tokens[i], 128)); masks.add(padding[i] == 1); tokenRefs.add((long) tokenIds[i]);
            }
            Class<?> codec = JackTargetEncoder.original("CandidateEncoder"); Object candidates = codec.getConstructor(Player.class).newInstance(world.viewerPlayer());
            if (!"card_select".equals(codec.getMethod("head", String.class).invoke(null, "SELECT_CARD"))) throw new IllegalArgumentException("original card head changed");
            List<Object> features = new ArrayList<>(), actionIds = new ArrayList<>(), legal = new ArrayList<>(), refs = new ArrayList<>();
            for (int i = 0; i < 64; i++) {
                float[] values = new float[48]; int actionId = 0;
                if (i < count) {
                    UUID id = binding.representatives.get(i);
                    actionId = (Integer) codec.getMethod("candidateId", String.class, Game.class, Ability.class, Object.class)
                            .invoke(candidates, "SELECT_CARD", game, source, id);
                    values = (float[]) codec.getMethod("candidateFeatures", String.class, Game.class, Ability.class, Object.class, state.getClass())
                            .invoke(candidates, "SELECT_CARD", game, source, id, state);
                    if (actionId <= 0 || actionId >= 65536) throw new IllegalArgumentException("original card ID changed");
                    refs.add(Json.map("index", (long) i, "candidate_ids", ids.get(i), "cards", binding.refs.get(i)));
                }
                features.add(JackModeEncoder.numbers(values, 48)); actionIds.add((long) actionId); legal.add(i < count);
            }
            result.putAll(Json.map("kind", "candidates", "head", "card_select", "sequence", rows, "padding", masks,
                    "token_ids", tokenRefs, "candidate_features", features, "candidate_ids", actionIds,
                    "candidate_mask", legal, "candidate_refs", refs));
            return result;
        } catch (RuntimeException e) { throw e; }
        catch (Exception e) { throw new IllegalStateException("original provided-card encoding failed", e); }
    }
}
