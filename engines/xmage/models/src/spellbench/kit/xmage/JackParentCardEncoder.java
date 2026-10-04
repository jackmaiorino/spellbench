package spellbench.kit.xmage;

import mage.abilities.Ability;
import mage.cards.Cards;
import mage.constants.Outcome;
import mage.game.Game;
import mage.players.Player;
import mage.target.TargetCard;
import spellbench.kit.core.Json;

import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Proxy;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/** Original April inherited card policy, distinct from the neural card callback. */
final class JackParentCardEncoder extends JackCardSetEncoder implements ModelReplay.ParentCardCapture {
    static final String RULE_VARIANT = "original inherited choose(Cards) good/bad target sorting, UUID ties and target.add application; "
            + "original April base, selector, comparator and permanent scoring; empty planning queues; "
            + "permitted callback replay; implicit completion bound to offered STOP; "
            + "no model or neural chooser/copy RNG; divided and opponent callbacks unqualified";
    static final String VARIANT = RULE_VARIANT + "; " + JackManaReplay.VARIANT;
    static final String[] HELPERS = {"ParentCardRules", "ParentTargetsSelector", "ParentTargetsComparator", "ParentPermanentScore", "ParentArtificialScoring"};
    static final String[] PINS = {"parentCardRulesSourceSha256", "parentSelectorSourceSha256", "parentComparatorSourceSha256", "parentPermanentSourceSha256", "parentScoringSourceSha256"};
    static final String[] FIELDS = {"parent_card_rules_source_sha256", "parent_selector_source_sha256", "parent_comparator_source_sha256", "parent_permanent_source_sha256", "parent_scoring_source_sha256"};
    static final String[] ORIGINALS = {
            "7c5ecab1cf4796886cb0c505560b239556a91582bef721f651b07760603d78f4",
            "d50b426cc9fba71c7c6c1a2c6fd392d89cb96d209b5bb41e38d74d2343b13f70",
            "cf32e14a3e4ef75307d877b578c9bca816ecca0f4f88895f4234e9464694e05c",
            "25c5f984c70602772a6e2df7f38ac2814c115677fd7760cfca595928acc1e5c7",
            "d210d4a977e5de4c9fdeff22e4a049887864bcdd603656501e592ac452bc8952"};
    private final Map<String, Object> start;

    JackParentCardEncoder(Map<String, Object> start, ModelReplay.ManaCapture payments) {
        super(start, payments); this.start = start;
    }
    static Class<?> parentRules() throws ReflectiveOperationException {
        for (int i = 0; i < HELPERS.length; i++) {
            Class<?> helper = Class.forName("spellbench.models.jack." + HELPERS[i]);
            if (!ORIGINALS[i].equals(helper.getField("SOURCE_SHA256").get(null))) {
                throw new IllegalArgumentException("parent card helper differs from its April source");
            }
            JackTargetEncoder.pin(PINS[i]);
        }
        Class<?> rules = Class.forName("spellbench.models.jack.ParentCardRules");
        if (!"b271d46971c0273dc01a1bd76d085e16e62fbb48a8c93b2700315ea696e46cf4".equals(rules.getField("PARENT6_SHA256").get(null))
                || !"d198011baada4145a94016371a6f067483a4b6c2d7acd2286f532c2286cc7fc2".equals(rules.getField("PARENT7_SHA256").get(null))) {
            throw new IllegalArgumentException("parent card inheritance differs from the original empty-queue path");
        }
        return rules;
    }
    @SuppressWarnings("unchecked")
    @Override public boolean selectParentCards(Player viewer, Outcome outcome, Cards cards, TargetCard target, Ability source, Game game,
                                               ModelReplay.ParentCardPick picker) {
        try {
            Class<?> rules = parentRules(), callback = Class.forName("spellbench.models.jack.ParentCardRules$Picker");
            Object listener = Proxy.newProxyInstance(callback.getClassLoader(), new Class<?>[]{callback}, (proxy, method, args) -> {
                if (!"choose".equals(method.getName()) || args == null || args.length != 6) throw new IllegalArgumentException("unexpected original parent picker call");
                picker.choose((List<UUID>) args[0], (UUID) args[1], (Integer) args[2], (Integer) args[3], (Integer) args[4], (String) args[5]);
                return null;
            });
            return (Boolean) rules.getMethod("select", Outcome.class, TargetCard.class, Ability.class, Game.class, Cards.class, callback)
                    .invoke(rules.getConstructor(Player.class).newInstance(viewer), outcome, target, source, game, cards, listener);
        } catch (ReflectiveOperationException e) {
            Throwable cause = e instanceof InvocationTargetException ? e.getCause() : e;
            if (cause instanceof RuntimeException) throw (RuntimeException) cause;
            if (cause instanceof Error) throw (Error) cause;
            throw new IllegalArgumentException("original parent card loop failed", cause);
        }
    }
    private static JackTargetEncoder.Binding bind(World world, Map<String, Object> decision, TargetCard target, Ability source, Game game,
                                                  List<UUID> possible, UUID chosen, int selected, int min, int max, String rule) throws Exception {
        if (possible == null || !possible.contains(chosen) || selected >= max
                || !("good_target".equals(rule) || "bad_target".equals(rule) || "implicit_finish".equals(rule))
                || (chosen == null) != "implicit_finish".equals(rule)) throw new IllegalArgumentException("original parent selection or completion changed");
        for (Object value : Json.arr(decision, "candidates")) {
            String kind = Json.str(Json.obj(Json.obj(value), "semantic"), "kind");
            if (!"select_object".equals(kind) && !"finish_selection".equals(kind)
                    && !"choose_target".equals(kind) && !"finish_target_selection".equals(kind)) throw new IllegalArgumentException("unrelated parent card wire action");
        }
        for (UUID id : possible) if (id != null && (world.seatOf(id) != null || game.getCard(id) == null)) {
            throw new IllegalArgumentException("parent card list contains a player or missing card");
        }
        return new JackTargetEncoder.Binding(world, JackGeneralTargetEncoder.normalizeDecision(decision, JackTargetEncoder.slot(source, target)),
                target, source, game, possible, selected, min, max);
    }
    @Override public void earlierParentCards(World world, Map<String, Object> decision, TargetCard target, Ability source, Game game,
                                            List<UUID> possible, UUID chosen, int selected, int min, int max, String rule, Map<String, Object> semantic) {
        try {
            JackTargetEncoder.Binding binding = bind(world, decision, target, source, game, possible, chosen, selected, min, max, rule);
            if (!Json.canonical(binding.semantics.get(chosen)).equals(Json.canonical(
                    JackGeneralTargetEncoder.normalizeSemantic(semantic, JackTargetEncoder.slot(source, target))))) {
                throw new IllegalArgumentException("recorded parent card differs from the original determined choice");
            }
        } catch (RuntimeException e) { throw e; }
        catch (Exception e) { throw new IllegalStateException("original parent prefix binding failed", e); }
    }
    @Override public Map<String, Object> encodeCards(World world, Map<String, Object> decision, TargetCard target, Ability source, Game game,
                                                   List<List<UUID>> groups, int selected, int min, int max, boolean forced, boolean deduplicated) {
        throw new IllegalArgumentException("parent encoder reached a neural card root; use the original card-set encoder");
    }
    @Override public Map<String, Object> encodeParentCards(World world, Map<String, Object> decision, TargetCard target, Ability source, Game game,
                                                         List<UUID> possible, UUID chosen, int selected, int min, int max, String rule) {
        try {
            if (!world.viewer.equals(Json.str(start, "seat"))) throw new IllegalArgumentException("parent start belongs to another seat");
            for (String flag : world.flags) if (flag.startsWith("unsupported:") || flag.startsWith("horizon:")) throw new IllegalArgumentException("unsupported parent replay: " + flag);
            JackTargetEncoder.Binding binding = bind(world, decision, target, source, game, possible, chosen, selected, min, max, rule);
            List<Object> ids = new ArrayList<>(); for (UUID id : possible) ids.add(binding.ids.get(id));
            Map<String, Object> result = Json.map("schema", "spellbench-jack-parent-card-features/v1", "kind", "jack-parent-card-choice",
                    "decision_sha256", JackModeEncoder.hash(decision), "game_start_sha256", JackModeEncoder.hash(start),
                    "encoder_source_sha256", JackTargetEncoder.pin("encoderSourceSha256"), "candidate_source_sha256", JackTargetEncoder.pin("candidateSourceSha256"),
                    "target_rules_source_sha256", JackTargetEncoder.pin("targetRulesSourceSha256"), "mode_rules_source_sha256", JackTargetEncoder.pin("modeRulesSourceSha256"),
                    "dialog_rules_source_sha256", JackTargetEncoder.pin("dialogRulesSourceSha256"), "mana_payment_rules_source_sha256", paymentRules().sourceSha256(),
                    "card_set_rules_source_sha256", JackTargetEncoder.pin("cardSetRulesSourceSha256"), "embedding_cache_sha256", JackTargetEncoder.pin("embeddingSha256"),
                    "original_callback_sha256", JackModeEncoder.SOURCE, "variant", VARIANT, "mana_payment_variant", JackManaReplay.VARIANT,
                    "world_flags", world.flags, "original_targets", binding.targets, "public_target_ids", ids,
                    "chosen_index", (long) possible.indexOf(chosen), "chosen_candidate_id", binding.ids.get(chosen), "rule", rule,
                    "selected_count", (long) selected, "minimum", (long) min, "maximum", (long) max);
            for (int i = 0; i < FIELDS.length; i++) result.put(FIELDS[i], JackTargetEncoder.pin(PINS[i]));
            return result;
        } catch (RuntimeException e) { throw e; }
        catch (Exception e) { throw new IllegalStateException("original parent card binding failed", e); }
    }
}
