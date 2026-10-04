"""Stage Jack's private April encoder for an explicit permitted player view.

The source stays outside public Git. This prepares base-state and priority
candidate encoding; other callbacks, deck associations and games are unfinished.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from xmage_release_assets import prepare_root, validate_asset, verify


ENCODER_SHA256 = "51504c1ffffbf5db8554258b5dca28f54f26bb7760121e0098561eac0b14b916"
CALLBACK_SHA256 = "b45257a66fc3914506fca4dd83461b6c8853d129b3e1f38b2d3aeba6137bd0c6"
MULLIGAN_JAVA_SHA256 = "69e039a69c5d983f5614d6a9c7efc77a7cf9f0ca1df64851d642d0f2ad718497"
MULLIGAN_VARIANT = "original own-hand features and remaining-library multiset; library sorted by card name; no hidden order"
VARIANT = ("acting-player perspective; entity tokens limited to named permitted references; "
           "only explicitly known library cards, ordered by public object alias; "
           "pinned read-only text embeddings with no generated fallback")

CONTEXT = """
    private static final ThreadLocal<UUID> FAIR_VIEWER = new ThreadLocal<>();
    private static final ThreadLocal<Map<UUID, String>> FAIR_ALIASES = new ThreadLocal<>();

    private static java.util.Collection<? extends Card> visibleLibrary(
            java.util.Collection<? extends Card> cards) {
        List<Card> known = new ArrayList<>();
        for (Card card : cards) {
            if (FAIR_ALIASES.get().containsKey(card.getId())) known.add(card);
        }
        known.sort(java.util.Comparator.comparing(card -> FAIR_ALIASES.get().get(card.getId())));
        return known;
    }
"""


def replace_once(source: str, before: str, after: str) -> str:
    if source.count(before) != 1:
        raise ValueError("pinned Jack source lacks one unambiguous compatibility edit")
    return source.replace(before, after, 1)


def fair_source(source: str) -> str:
    if hashlib.sha256(source.encode()).hexdigest() != ENCODER_SHA256:
        raise ValueError("Jack fair port requires the pinned April encoder bytes")
    source = replace_once(source, "package mage.player.ai.rl;", "package spellbench.models.jack;")
    source = replace_once(source, "public class StateSequenceBuilder {",
                          "public class StateSequenceBuilder {" + CONTEXT)
    source = replace_once(source,
        "public static SequenceOutput buildBaseState(Game game, TurnPhase phase, int maxLen) {",
        """public static SequenceOutput buildBaseState(Game game, TurnPhase phase, int maxLen,
            UUID viewer, Map<UUID, String> permittedAliases) {
        if (viewer == null || game.getPlayer(viewer) == null || permittedAliases == null
                || FAIR_VIEWER.get() != null) {
            throw new IllegalArgumentException("explicit non-reentrant permitted viewer required");
        }
        java.util.Set<String> aliases = new java.util.HashSet<>();
        for (Map.Entry<UUID, String> entry : permittedAliases.entrySet()) {
            if (entry.getKey() == null || entry.getValue() == null || entry.getValue().isEmpty()
                    || !aliases.add(entry.getValue())) {
                throw new IllegalArgumentException("permitted object aliases must be unique and nonempty");
            }
        }
        FAIR_VIEWER.set(viewer);
        FAIR_ALIASES.set(new HashMap<>(permittedAliases));
        try {""")
    start = source.index("        Player player = game.getPlayer(game.getActivePlayerId());")
    end = source.index("\n        /*", start)
    source = source[:start] + "        Player player = game.getPlayer(viewer);\n" + source[end:]
    source = replace_once(source, "return new SequenceOutput(tokens, mask, tokenIds, uuidMap);",
        """return new SequenceOutput(tokens, mask, tokenIds, uuidMap);
        } finally {
            FAIR_ALIASES.remove();
            FAIR_VIEWER.remove();
        }""")
    source = replace_once(source, "player.getLibrary().getCards(game)",
                          "visibleLibrary(player.getLibrary().getCards(game))")
    source = replace_once(source, "for (Permanent p : perms) {",
                          "for (Permanent p : perms) {\n            if (!FAIR_ALIASES.get().containsKey(p.getId())) continue;")
    source = replace_once(source, "for (StackObject so : game.getStack()) {",
                          "for (StackObject so : game.getStack()) {\n            if (!FAIR_ALIASES.get().containsKey(so.getId())) continue;")
    source = replace_once(source, "Map<UUID, Integer> uuidMap, Card c, Zone z, Game g) {",
                          "Map<UUID, Integer> uuidMap, Card c, Zone z, Game g) {\n"
                          "        if (!FAIR_ALIASES.get().containsKey(c.getId())) return;")
    for owner in ("controllerId", "card.getOwnerId()"):
        source = replace_once(source, owner + ".equals(game.getActivePlayerId())",
                              owner + ".equals(FAIR_VIEWER.get())")
    embedding = "CardTextEmbeddings.getInstance().getEmbedding("
    if source.count(embedding) != 2:
        raise ValueError("pinned Jack source changed its text-embedding calls")
    source = source.replace(embedding, "EmbeddingCache.getEmbedding(")
    return source


def extract(source: str, start: str, end: str) -> str:
    if source.count(start) != 1 or source.count(end) != 1:
        raise ValueError("pinned Jack callback lacks unambiguous extraction boundaries")
    return source[source.index(start):source.index(end, source.index(start))].rstrip() + "\n"


def candidate_source(source: str) -> str:
    if hashlib.sha256(source.encode()).hexdigest() != CALLBACK_SHA256:
        raise ValueError("Jack priority port requires the pinned April callback bytes")
    methods = extract(source, "    private static int toVocabId(String key) {",
                      "    private double computeStepReward(")
    helpers = extract(source, "    private int getOpponentLife(Game game) {",
                      "    /**\n     * Set the current episode number for logging purposes.")
    combat = extract(source, "    static class CombatCandidate {", "\n}\n\n// Helper class to store block options")
    heads = extract(source, "    private static String headForActionType(",
                    "    private mage.player.ai.rl.PythonMLBatchManager.PredictionResult scoreCandidatesWithMetrics(")
    # The April callback reads these fields from the player object. The
    # standalone port uses the acting player already in the permitted world.
    methods = methods.replace("this.getId()", "viewer.getId()").replace("this.getLife()", "viewer.getLife()")
    methods = methods.replace("getHand()", "viewer.getHand()")
    methods = methods.replace("getManaAvailable(game)", "viewer.getManaAvailable(game)")
    helpers = helpers.replace("playerId", "viewer.getId()")
    methods = replace_once(methods, "        } catch (Exception e) {\n            return 0;\n        }",
                           "        } catch (Exception e) {\n            throw new IllegalArgumentException(\"Jack candidate ID failed\", e);\n        }")
    methods = replace_once(methods, "        } catch (Exception e) {\n            // leave zeros\n        }",
                           "        } catch (Exception e) {\n            throw new IllegalArgumentException(\"Jack candidate features failed\", e);\n        }")
    return """package spellbench.models.jack;

import mage.MageObject;
import mage.abilities.Ability;
import mage.abilities.SpellAbility;
import mage.abilities.common.PassAbility;
import mage.abilities.keyword.*;
import mage.counters.CounterType;
import mage.game.Game;
import mage.game.permanent.Permanent;
import mage.game.permanent.PermanentToken;
import mage.players.Player;
import java.util.UUID;

/** Private source extraction. Only the original priority feature path is exposed. */
public final class CandidateEncoder {
    public static final String SOURCE_SHA256 = "%s";
    private final Player viewer;
    public CandidateEncoder(Player viewer) {
        if (viewer == null) throw new IllegalArgumentException("acting player required");
        this.viewer = viewer;
    }
    public int priorityId(Game game, Ability candidate) {
        return computeCandidateActionId(StateSequenceBuilder.ActionType.ACTIVATE_ABILITY_OR_SPELL,
                game, null, candidate);
    }
    public float[] priorityFeatures(Game game, Ability candidate, StateSequenceBuilder.SequenceOutput state) {
        return computeCandidateFeatures(StateSequenceBuilder.ActionType.ACTIVATE_ABILITY_OR_SPELL,
                game, null, candidate, 48, state);
    }
    public static String head(String type) {
        return headForActionType(StateSequenceBuilder.ActionType.valueOf(type));
    }
    public int candidateId(String type, Game game, Ability source, Object candidate) {
        return computeCandidateActionId(StateSequenceBuilder.ActionType.valueOf(type), game, source, candidate);
    }
    public float[] candidateFeatures(String type, Game game, Ability source, Object candidate,
                                    StateSequenceBuilder.SequenceOutput state) {
        return computeCandidateFeatures(StateSequenceBuilder.ActionType.valueOf(type),
                game, source, candidate, 48, state);
    }
    public static Object combatCandidate(Permanent creature, Object context) {
        if (context != null && !(context instanceof UUID) && !(context instanceof Permanent)) {
            throw new IllegalArgumentException("unsupported original combat context");
        }
        return new CombatCandidate(creature, context);
    }
""" % CALLBACK_SHA256 + heads + methods + helpers + combat + "}\n"


def choice_source(source: str) -> str:
    """Extract the original float32 chooser; campaign exploration stays disabled.

    The original evaluation constructor uses greedy=true and a negative
    episode. The no-training constructor also supports sampled play. Retain
    both original selection paths, Java Random and first-index tie behavior.
    This does not port the surrounding game callback or its candidate list.
    """
    if hashlib.sha256(source.encode()).hexdigest() != CALLBACK_SHA256:
        raise ValueError("Jack chooser requires the pinned April callback bytes")
    classes = extract(source, "    private static final class BehaviorPolicyView {",
                      "    private static <K, V> Map<K, V> createLruCache(")
    classes += extract(source, "    private static final class SequentialPickResult {",
                       "    private boolean isMainExplorationEnabled() {")
    normalize = extract(source, "    private static float[] normalizePolicyScores(",
                        "    private static float[] buildUniformProbs(")
    picks = extract(source, "    private int sampleFromDistribution(",
                    "    private String explorationAnnotation(")
    return """package spellbench.models.jack;

import mage.game.Game;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Random;

/** Private exact source extraction. No training, inference or game callbacks. */
public final class PolicySelector {
    public static final String SOURCE_SHA256 = "%s";
    private static final String TURN_UNIFORM_OLD_LOGP_SOURCE = "policy";
    private final boolean greedyMode;
    private final Random stochasticRng;
    public PolicySelector(boolean greedy, long seed) {
        greedyMode = greedy;
        stochasticRng = new Random(seed);
    }
    private BehaviorPolicyView buildBehaviorPolicy(float[] scores, int[] mask, int count, Game game) {
        float[] policy = normalizePolicyScores(scores, mask, count);
        return new BehaviorPolicyView(policy, Arrays.copyOf(policy, policy.length), "policy", 0, 0);
    }
    public int[] choose(float[] scores, int[] mask, int count, int picks, boolean sequential) {
        if (scores == null || mask == null || scores.length != 64 || mask.length != 64
                || count < 1 || count > 64 || picks < 1 || picks > count || (!sequential && picks != 1)) {
            throw new IllegalArgumentException("original chooser needs its fixed 64 slots and valid pick count");
        }
        int valid = 0;
        for (int i = 0; i < 64; i++) {
            if ((mask[i] != 0 && mask[i] != 1) || (i >= count && mask[i] != 0)
                    || !Float.isFinite(scores[i]) || scores[i] < 0 || scores[i] > 1) {
                throw new IllegalArgumentException("invalid probability or original candidate mask");
            }
            valid += mask[i];
        }
        if (picks > valid) throw new IllegalArgumentException("pick count exceeds legal original candidates");
        // The original genericChoose skips model selection for one candidate.
        if (count == 1) return new int[] {0};
        List<Integer> chosen = sequential
                ? sampleSequentialWithoutReplacement(scores, mask, count, picks, null).selectedIndices
                : Arrays.asList(sampleSinglePick(scores, mask, count, null).chosenIdx);
        int[] result = new int[chosen.size()];
        boolean[] seen = new boolean[count];
        for (int i = 0; i < result.length; i++) {
            int index = chosen.get(i);
            if (index < 0 || index >= count || mask[index] != 1 || seen[index]) {
                throw new IllegalArgumentException("original chooser returned an illegal or repeated pick");
            }
            seen[index] = true;
            result[i] = index;
        }
        if (result.length != picks) throw new IllegalArgumentException("original chooser returned incomplete picks");
        return result;
    }
""" % CALLBACK_SHA256 + classes + normalize + picks + "}\n"


def mulligan_source(source: str) -> str:
    """Keep the original 71 features, with no sampled library-order feature.

    The original networks pool the deck embeddings. Preserve the remaining
    library's composition while giving it a fixed order from permitted names.
    The original evaluation has no training exploration or hard overrides.
    """
    if hashlib.sha256(source.encode()).hexdigest() != MULLIGAN_JAVA_SHA256:
        raise ValueError("Jack mulligan port requires the pinned April Java source")
    methods = extract(source, "    private float[] buildFeatureVector(",
                      "    // Logging is now handled entirely in ComputerPlayerRL.java:")
    methods = replace_once(methods,
        "            List<Card> deck = new ArrayList<>(player.getLibrary().getCards(game));",
        "            List<Card> deck = new ArrayList<>(player.getLibrary().getCards(game));\n"
        "            deck.sort(java.util.Comparator.comparing(Card::getName));")
    return """package spellbench.models.jack;
import mage.cards.Card;
import mage.game.Game;
import mage.players.Player;
import java.util.ArrayList;
import java.util.List;

/** Private original mulligan feature port. No model, training or fallback. */
public final class MulliganEncoder {
    public static final String SOURCE_SHA256 = "%s";
    private static final int MAX_HAND_SIZE = 7, MAX_DECK_SIZE = 60, NUM_EXPLICIT = 3;
    private static final int FEATURE_SIZE = 71, TOKEN_ID_VOCAB = 65536;
    public float[] features(Player player, Game game, int mulliganCount) {
        if (player == null || game == null || player.getLibrary() == null
                || mulliganCount < 0 || mulliganCount > 7
                || player.getHand().size() < 1 || player.getHand().size() > 7
                || player.getLibrary().size() > MAX_DECK_SIZE) {
            throw new IllegalArgumentException("unsupported original mulligan feature envelope");
        }
        for (Card card : player.getHand().getCards(game)) requireNamed(card);
        for (Card card : player.getLibrary().getCards(game)) requireNamed(card);
        return buildFeatureVector(player, game, mulliganCount,
                extractHandCardIds(player, game), extractDeckCardIds(player, game));
    }
    private static void requireNamed(Card card) {
        if (card == null || card.getName() == null || card.getName().isEmpty()) {
            throw new IllegalArgumentException("own permitted cards must have names");
        }
    }
""" % MULLIGAN_JAVA_SHA256 + methods + "}\n"


MODE_VARIANT = "original available-mode order, legality mask, 64-slot cap and ordinal feature; permitted callback replay; refusal instead of heuristic fallback; cost-bearing multi-mode callbacks unsupported"
MODE_MANA_VARIANT = ("original available-mode order, legality mask, 64-slot cap, ordinal and mode-cost features; "
                     "original filtered mana availability on permitted callback replay; refusal instead of heuristic fallback; "
                     "automatic mana production and other callbacks unqualified")


def mode_source(source: str) -> str:
    """Stage the original legality rule without publishing the private body."""
    if hashlib.sha256(source.encode()).hexdigest() != CALLBACK_SHA256:
        raise ValueError("Jack mode port requires the pinned April callback bytes")
    method = extract(source, "    private boolean isModeChoiceCurrentlyLegal(",
                     "    @Override\n    public int announceX(")
    method = replace_once(method, "private boolean isModeChoiceCurrentlyLegal(", "public boolean legal(")
    method = method.replace("playerId", "viewer.getId()")
    return """package spellbench.models.jack;
import mage.abilities.Ability;
import mage.game.Game;
import mage.players.Player;

/** Private original mode legality rule, evaluated on the permitted world. */
public final class ModeRules {
    public static final String SOURCE_SHA256 = "%s";
    private final Player viewer;
    public ModeRules(Player viewer) {
        if (viewer == null) throw new IllegalArgumentException("acting player required");
        this.viewer = viewer;
    }
    private void trace(String message) { }
""" % CALLBACK_SHA256 + method + "}\n"


DIALOG_VARIANT = ("original choose-use feasibility gates, YES/NO IDs and order; original X cap, "
                  "conditional mana bounds and integer order; permitted callback replay; "
                  "refusal instead of heuristic fallback; automatic mana production and other callbacks unqualified")


def dialog_source(source: str) -> str:
    """Stage original dialog and mana-availability rules outside public Git."""
    if hashlib.sha256(source.encode()).hexdigest() != CALLBACK_SHA256:
        raise ValueError("Jack dialog port requires the pinned April callback bytes")
    helpers = extract(source, "    private static boolean hasTapSourceCost(",
                      "    private Abilities<Ability> getAbilitiesForObject(")
    helpers += extract(source, "    private mage.abilities.Abilities<mage.abilities.mana.ActivatedManaAbilityImpl> filterUsableManaAbilities(",
                       "    private boolean mageObjectCanProduceManaForCurrentPayment(")
    helpers += extract(source, "    private Mana parseManaCostFromMessage(",
                       "    /**\n     * Logs every target that has been recorded on the provided ability.")
    helpers += extract(source, "    private static int toVocabId(",
                       "    private int computeCandidateActionId(")
    available = extract(source, "    @Override\n    public ManaOptions getManaAvailable(",
                        "    // CRITICAL FIX: Exclude permanents from mana producers")
    available = available.replace("    @Override\n", "")
    available = replace_once(available, "protected ManaOptions getManaAvailableFast(",
                             "public ManaOptions getManaAvailableFast(")
    gates = extract(source, "        // Mana feasibility gate: for optional additional costs",
                    "        try {\n            final int maxCandidates = StateSequenceBuilder.TrainingData.MAX_CANDIDATES;\n            final int candFeatDim = StateSequenceBuilder.TrainingData.CAND_FEAT_DIM;\n\n            // Build 2-candidate decision")
    bounds = extract(source, "            int realMin = min;\n            int realMax = max == Integer.MAX_VALUE",
                     "            if (realMin == realMax) {\n                trace(\"announceX EXIT: only one option")
    return """package spellbench.models.jack;
import mage.Mana;
import mage.ConditionalMana;
import mage.abilities.Ability;
import mage.abilities.SpellAbility;
import mage.abilities.costs.mana.ManaCostsImpl;
import mage.abilities.costs.mana.VariableManaCost;
import mage.abilities.mana.ManaAbility;
import mage.abilities.mana.ManaOptions;
import mage.cards.Card;
import mage.cards.Cards;
import mage.constants.Outcome;
import mage.constants.Zone;
import mage.game.Game;
import mage.game.permanent.Permanent;
import mage.players.Player;
import mage.players.ManaPool;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;
import java.util.UUID;

/** Private original rules; no network, heuristic choice or training. */
public final class DialogRules {
    public static final String SOURCE_SHA256 = "%s";
    private final Player viewer;
    private final UUID playerId;
    private final ManaPool manaPool;
    public DialogRules(Player viewer) {
        if (viewer == null) throw new IllegalArgumentException("acting player required");
        this.viewer = viewer;
        this.playerId = viewer.getId();
        this.manaPool = viewer.getManaPool();
    }
    private UUID getId() { return viewer.getId(); }
    private int getLife() { return viewer.getLife(); }
    private Cards getHand() { return viewer.getHand(); }
    private void trace(String message) { }
    public int useId(boolean value) {
        return toVocabId(StateSequenceBuilder.ActionType.CHOOSE_USE.name() + "_" + (value ? "YES" : "NO"));
    }
    public Boolean forcedUse(Outcome outcome, String message, Ability source, Game game) {
        if (game == null) throw new IllegalArgumentException("dialog needs its replayed game");
""" % CALLBACK_SHA256 + gates + "        return null;\n    }\n" + """
    public int[] xRange(int min, int max, boolean isManaPay, Ability source, Game game) {
        if (game == null) throw new IllegalArgumentException("X choice needs its replayed game");
""" + bounds + "        return new int[]{realMin, realMax};\n    }\n" + helpers + available + "}\n"


MANA_PAYMENT_VARIANT = ("original automatic mana producer filters and stable ordering; original activation tap reservations, "
                        "nested unpaid-mana context, color preference and tap-target rules; "
                        "permitted replay; engine-only delegation for original mana callbacks; native execution unqualified")


def mana_payment_source(source: str) -> str:
    """Extract original stateful mana plumbing; callers supply the engine delegation."""
    if hashlib.sha256(source.encode()).hexdigest() != CALLBACK_SHA256:
        raise ValueError("Jack mana payment port requires the pinned April callback bytes")
    helpers = extract(source, "    private static boolean inPlayManaContext() {",
                      "    public void setAttachedGameLogger(")
    reservations = extract(source, "            tapTargetCostReservations.clear();\n            for (mage.abilities.costs.Cost cost : freshAbility.getCosts()) {",
                           "            // Activate using the fresh ability from the real game")
    producers = extract(source, "    @Override\n    public List<MageObject> getAvailableManaProducers(",
                        "    /**\n     * Override cast() to add safety bookmarks")
    producers = producers.replace("    @Override\n", "")
    producers = replace_once(producers, "public List<MageObject> getAvailableManaProducers(Game game)",
                             "public List<MageObject> filterProducers(List<MageObject> offered, Game game)")
    producers = replace_once(producers, "super.getAvailableManaProducers(game)", "new ArrayList<>(offered)")
    payment = extract(source, "        int prevDepth = playManaDepth.get();",
                      "        if (ACTIVATION_DIAG) {\n            RLTrainer.threadLocalLogger.get().info(\n                    \"PLAYMANA: Result=")
    payment = replace_once(payment, "super.playMana(ability, unpaid, promptText, game)", "engine.getAsBoolean()")
    targets = extract(source, "        // During mana payment, avoid tapping key mana producers when a target",
                      "        // RL-only target selection. No engine fallback.")
    targets = targets.replace("super.chooseTarget(outcome, target, source, game)", "engine.getAsBoolean()")
    colors = extract(source, "        // Mana color payment: delegate to base AI logic (not a strategic decision)",
                     "        // Detect alternative cost choices (they use KEY-based choices!)")
    colors = replace_once(colors, "super.choose(outcome, choice, game)", "engine.getAsBoolean()")
    return """package spellbench.models.jack;
import mage.MageObject;
import mage.Mana;
import mage.abilities.Ability;
import mage.abilities.Abilities;
import mage.abilities.ActivatedAbility;
import mage.abilities.mana.ManaAbility;
import mage.abilities.costs.mana.ManaCost;
import mage.cards.Card;
import mage.choices.Choice;
import mage.constants.Outcome;
import mage.game.Game;
import mage.game.permanent.Permanent;
import mage.players.Player;
import mage.target.Target;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import java.util.function.BooleanSupplier;
import java.util.stream.Collectors;

/** Original mana rules and context only. No strategic policy or network. */
public final class ManaPaymentRules {
    public static final String SOURCE_SHA256 = "%s";
    private static final boolean USE_ENGINE_CHOICES = true;
    private static final boolean ACTIVATION_DIAG = false;
    private static final ThreadLocal<Integer> playManaDepth = ThreadLocal.withInitial(() -> 0);
    private static final ThreadLocal<String> currentUnpaidManaText = new ThreadLocal<>();
    private UUID abilitySourceToExcludeFromMana = null;
    private Set<UUID> tapTargetCostReservations = new HashSet<>();
    private final Player viewer;
    private final UUID playerId;
    public ManaPaymentRules(Player viewer) {
        if (viewer == null) throw new IllegalArgumentException("acting player required");
        this.viewer = viewer; this.playerId = viewer.getId();
    }
    private UUID getId() { return viewer.getId(); }
    private static void trace(String message) { }
    private static final class RLTrainer {
        static final ThreadLocal<java.util.logging.Logger> threadLocalLogger =
                ThreadLocal.withInitial(() -> java.util.logging.Logger.getLogger("spellbench.jack.mana"));
    }
    public void prepareActivation(ActivatedAbility freshAbility, Game game) {
        if (freshAbility == null || game == null) throw new IllegalArgumentException("actual activation required");
""" % CALLBACK_SHA256 + reservations + """    }
    public void clearActivation() {
        abilitySourceToExcludeFromMana = null;
        tapTargetCostReservations.clear();
    }
    public boolean payment(ManaCost unpaid, BooleanSupplier engine) {
""" + payment + "        return result;\n    }\n" + """
    public Boolean target(Outcome outcome, Target target, Ability source, Game game, BooleanSupplier engine) {
""" + targets + "        return null;\n    }\n" + """
    public Boolean color(Outcome outcome, Choice choice, Game game, BooleanSupplier engine) {
""" + colors + "        return null;\n    }\n" + helpers + producers + "}\n"


TARGET_VARIANT = ("original general target order, sequential STOP gates, single and same-name direct returns, "
                  "first 64 slots and minimum/crew completion; permitted callback replay; "
                  "refusal instead of model-error fallback; acting-player named-source spell targets only; "
                  "cost, provided-card and divided-target callbacks unqualified")


def target_source(source: str) -> str:
    """Extract the original general-target loop and force rules, with an owned picker."""
    if hashlib.sha256(source.encode()).hexdigest() != CALLBACK_SHA256:
        raise ValueError("Jack targets require the pinned April callback bytes")
    walk = extract(source, "        // RL-only target selection. No engine fallback.",
                   "    private int parseCrewOrSaddleRequiredPower(")
    beginning = walk.index("            UUID picked = null;")
    ending = walk.index("            if (picked == null) { // STOP", beginning)
    decision = walk[beginning:ending]
    names = extract(decision, "                boolean allSameName = true;",
                    "                if (allSameName && firstName != null) {")
    direct = extract(decision, "                    for (UUID id : possible) {\n                        if (id != null) {",
                     "                } else {\n                    // Non-trivial decision")
    # The final brace belongs to the original all-same-name branch.
    direct = direct.rstrip()
    if not direct.endswith("}"):
        raise ValueError("original direct target branch changed")
    replacement = ("            UUID picked = null;\n            boolean forced = possible.size() == 1;\n"
                   "            String reason = forced ? \"single_option\" : \"model\";\n"
                   "            if (forced) picked = possible.get(0);\n            else {\n" + names
                   + "                if (allSameName && firstName != null) {\n"
                   + direct + "\n                    forced = true; reason = \"same_name\";\n"
                   + "                }\n            }\n"
                   + "            UUID directPick = picked;\n"
                   + "            picked = picker.choose(new ArrayList<>(possible), chosenCount, minTargets, maxTargets,\n"
                   + "                    forced, directPick, reason);\n"
                   + "            if (forced && !java.util.Objects.equals(picked, directPick)) {\n"
                   + "                throw new IllegalArgumentException(\"original forced target changed\");\n            }\n"
                   + "            if (!forced && !possible.subList(0, Math.min(64, possible.size())).contains(picked)) {\n"
                   + "                throw new IllegalArgumentException(\"target picker escaped the original first 64 slots\");\n            }\n")
    walk = walk[:beginning] + replacement + walk[ending:]
    helpers = extract(source, "    private int parseCrewOrSaddleRequiredPower(",
                      "    @Override\n    public boolean choose(Outcome outcome, Target target, Ability source, Game game)")
    return '''package spellbench.models.jack;

import mage.MageObject;
import mage.abilities.Ability;
import mage.cards.Card;
import mage.constants.Outcome;
import mage.game.Game;
import mage.game.permanent.Permanent;
import mage.players.Player;
import mage.target.Target;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.UUID;

/** Private original loop and deterministic rules; owned inference and no training. */
public final class TargetRules {
    public static final String SOURCE_SHA256 = "%s";
    private final UUID playerId;
    public TargetRules(Player viewer) { if (viewer == null) throw new IllegalArgumentException("acting target player required"); playerId = viewer.getId(); }
    public interface Picker {
        UUID choose(List<UUID> possible, int chosenCount, int minimum, int maximum,
                    boolean forced, UUID directPick, String reason);
    }
    private static void trace(String value) { }
    public boolean select(Outcome outcome, Target target, Ability source, Game game, Picker picker) {
        if (target == null || game == null || picker == null) throw new IllegalArgumentException("actual general target callback required");
''' % CALLBACK_SHA256 + walk + helpers + "}\n"


CARD_SET_VARIANT = ("original provided-card filtering, library/hand name groups, first available representatives, "
                    "sequential STOP gates, first 64 groups and minimum completion; original card_select head; "
                    "permitted callback replay; refusal instead of model-error fallback; "
                    "owned MT19937 copy stream derived from game start, singleton copies direct; "
                    "chooseTarget(Cards) only, inherited choose(Cards), divided and opponent callbacks unqualified")


def card_set_method(source: str) -> str:
    return extract(source, "    @Override\n    public boolean chooseTarget(Outcome outcome, Cards cards, TargetCard target, Ability source, Game game) {",
                   "    @Override\n    public boolean choose(Outcome outcome, Choice choice, Game game) {")


def card_set_source(source: str) -> str:
    """Extract the original provided-card loop; delegate group/copy selection to its owner."""
    if hashlib.sha256(source.encode()).hexdigest() != CALLBACK_SHA256:
        raise ValueError("Jack provided cards require the pinned April callback bytes")
    method = card_set_method(source)
    beginning = method.index("        // CRITICAL: Filter cards by target's filter")
    ending = method.index("        boolean result = chosenCount >= minTargets;")
    walk = method[beginning:ending]
    start = walk.index("            String pickedName = null;")
    stop = walk.index("            if (picked == null) { // STOP or error", start)
    replacement = '''            List<List<UUID>> groups = new ArrayList<>();
            for (String name : remainingNames) {
                List<UUID> copies = new ArrayList<>();
                if (name != null) for (Card card : cardsByName.get(name)) {
                    if (!chosen.contains(card.getId())) copies.add(card.getId());
                }
                groups.add(copies);
            }
            UUID selected = picker.choose(groups, chosenCount, minTargets, maxTargets,
                    remainingNames.size() == 1, shouldDedupe);
            boolean offered = false;
            for (List<UUID> group : groups.subList(0, Math.min(64, groups.size()))) {
                if (selected == null ? group.isEmpty() : group.contains(selected)) offered = true;
            }
            if (!offered) throw new IllegalArgumentException("card picker escaped the original first 64 groups");
            Card picked = selected == null ? null : game.getCard(selected);
            if (selected != null && picked == null) throw new IllegalArgumentException("selected original card disappeared");

'''
    walk = walk[:start] + replacement + walk[stop:]
    walk = walk.replace("this.getId()", "viewer.getId()")
    return '''package spellbench.models.jack;

import mage.abilities.Ability;
import mage.cards.Card;
import mage.cards.Cards;
import mage.constants.Outcome;
import mage.game.Game;
import mage.players.Player;
import mage.target.TargetCard;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.UUID;

/** Private original card grouping and completion; owned inference and seeded copy choice. */
public final class CardSetRules {
    public static final String SOURCE_SHA256 = "%s";
    public static final String METHOD_SHA256 = "%s";
    private final Player viewer;
    public CardSetRules(Player viewer) { if (viewer == null) throw new IllegalArgumentException("acting card player required"); this.viewer = viewer; }
    public interface Picker {
        UUID choose(List<List<UUID>> groups, int selected, int minimum, int maximum, boolean forced, boolean deduplicated);
    }
    public boolean select(Outcome outcome, Cards cards, TargetCard target, Ability source, Game game, Picker picker) {
        if (cards == null || target == null) return false;
        if (game == null || picker == null) throw new IllegalArgumentException("actual provided-card callback required");
''' % (CALLBACK_SHA256, hashlib.sha256(method.encode()).hexdigest()) + walk + "        return chosenCount >= minTargets;\n    }\n}\n"


def stage(manifest: dict, root: Path, output: Path) -> dict:
    if manifest.get("schema") != "spellbench-xmage-release-inputs/v1":
        raise ValueError("unknown release input manifest")
    config = manifest.get("inference_backends", {}).get("jack-rl-april", {})
    if "mode_callback" in config and type(config["mode_callback"]) is not bool:
        raise ValueError("Jack mode staging needs an explicit boolean flag")
    if "dialog_callback" in config and type(config["dialog_callback"]) is not bool:
        raise ValueError("Jack dialog staging needs an explicit boolean flag")
    if "mode_mana_callback" in config and type(config["mode_mana_callback"]) is not bool:
        raise ValueError("Jack mode mana staging needs an explicit boolean flag")
    if config.get("mode_mana_callback") is True and not (
            config.get("mode_callback") is True and config.get("dialog_callback") is True):
        raise ValueError("Jack mode mana staging requires the original mode and dialog rules")
    if "mana_payment_callback" in config and type(config["mana_payment_callback"]) is not bool:
        raise ValueError("Jack mana payment staging needs an explicit boolean flag")
    if config.get("mana_payment_callback") is True and config.get("mode_mana_callback") is not True:
        raise ValueError("Jack mana payment staging requires the original filtered mana callback")
    if "target_callback" in config and type(config["target_callback"]) is not bool:
        raise ValueError("Jack target staging needs an explicit boolean flag")
    if config.get("target_callback") is True and config.get("mana_payment_callback") is not True:
        raise ValueError("Jack targets require the original payment and prefix callback rules")
    if "card_set_callback" in config and type(config["card_set_callback"]) is not bool:
        raise ValueError("Jack provided-card staging needs an explicit boolean flag")
    if config.get("card_set_callback") is True and config.get("target_callback") is not True:
        raise ValueError("Jack provided cards require the original general target and prefix rules")
    matches = [a for a in manifest.get("assets", []) if a.get("id") == config.get("state_encoder")]
    if len(matches) != 1:
        raise ValueError("Jack stage needs one private encoder asset")
    asset = matches[0]
    validate_asset(asset)
    if asset["sha256"] != ENCODER_SHA256 or asset.get("transport") != "local-file":
        raise ValueError("Jack stage requires the pinned private local encoder")
    root = prepare_root(root)
    verify(root / asset["filename"], asset)
    original = (root / asset["filename"]).read_bytes()
    modified = fair_source(original.decode("utf-8")).encode("utf-8")
    callbacks = [a for a in manifest.get("assets", []) if a.get("id") == config.get("callback_source")]
    if len(callbacks) != 1:
        raise ValueError("Jack stage needs one private callback asset")
    callback = callbacks[0]
    validate_asset(callback)
    if callback["sha256"] != CALLBACK_SHA256 or callback.get("transport") != "local-file":
        raise ValueError("Jack priority stage requires the pinned private local callback")
    verify(root / callback["filename"], callback)
    candidates = candidate_source((root / callback["filename"]).read_bytes().decode("utf-8")).encode("utf-8")
    choices = choice_source((root / callback["filename"]).read_bytes().decode("utf-8")).encode("utf-8")
    modes = (mode_source((root / callback["filename"]).read_bytes().decode("utf-8")).encode("utf-8")
             if config.get("mode_callback") is True else None)
    dialogs = (dialog_source((root / callback["filename"]).read_bytes().decode("utf-8")).encode("utf-8")
               if config.get("dialog_callback") is True else None)
    payments = (mana_payment_source((root / callback["filename"]).read_bytes().decode("utf-8")).encode("utf-8")
                if config.get("mana_payment_callback") is True else None)
    targets = (target_source((root / callback["filename"]).read_bytes().decode("utf-8")).encode("utf-8")
               if config.get("target_callback") is True else None)
    card_sets = (card_set_source((root / callback["filename"]).read_bytes().decode("utf-8")).encode("utf-8")
                 if config.get("card_set_callback") is True else None)
    mulligan = None
    if config.get("mulligan_encoder") is not None:
        matches = [a for a in manifest["assets"] if a["id"] == config["mulligan_encoder"]]
        if len(matches) != 1:
            raise ValueError("Jack mulligan stage needs one private encoder asset")
        mulligan_asset = matches[0]
        validate_asset(mulligan_asset)
        if mulligan_asset["sha256"] != MULLIGAN_JAVA_SHA256 or mulligan_asset.get("transport") != "local-file":
            raise ValueError("Jack mulligan stage requires the pinned private local source")
        verify(root / mulligan_asset["filename"], mulligan_asset)
        mulligan = mulligan_source((root / mulligan_asset["filename"]).read_text(encoding="utf-8")).encode("utf-8")
    if output.exists() or output.is_symlink():
        raise ValueError("Jack source stage needs a new owned output directory")
    output = prepare_root(output)
    with (output / "StateSequenceBuilder.java").open("xb") as stream:
        stream.write(modified)
    with (output / "CandidateEncoder.java").open("xb") as stream:
        stream.write(candidates)
    with (output / "PolicySelector.java").open("xb") as stream:
        stream.write(choices)
    if mulligan is not None:
        with (output / "MulliganEncoder.java").open("xb") as stream:
            stream.write(mulligan)
    if modes is not None:
        with (output / "ModeRules.java").open("xb") as stream:
            stream.write(modes)
    if dialogs is not None:
        with (output / "DialogRules.java").open("xb") as stream:
            stream.write(dialogs)
    if payments is not None:
        with (output / "ManaPaymentRules.java").open("xb") as stream:
            stream.write(payments)
    if targets is not None:
        with (output / "TargetRules.java").open("xb") as stream:
            stream.write(targets)
    if card_sets is not None:
        with (output / "CardSetRules.java").open("xb") as stream:
            stream.write(card_sets)
    result = {"schema": "spellbench-jack-encoder-stage/v1", "original_source_sha256": asset["sha256"],
              "staged_source_sha256": hashlib.sha256(modified).hexdigest(), "variant": VARIANT,
              "original_callback_sha256": callback["sha256"],
              "staged_candidate_sha256": hashlib.sha256(candidates).hexdigest(),
              "staged_choice_sha256": hashlib.sha256(choices).hexdigest(),
              "choice_profile": "original evaluation greedy or explicit no-training sampled selection; no campaign exploration",
              "candidate_scope": "original priority IDs and 48 features; explicit acting player; extraction failures refuse",
              "scope": "base-state and priority features; original generic candidate methods and chooser; other game callbacks, deck qualification and games unfinished",
              "private_source": True, "embedding_source": "explicit hash-pinned offline cache"}
    if mulligan is not None:
        result.update(original_mulligan_encoder_sha256=MULLIGAN_JAVA_SHA256,
                      staged_mulligan_encoder_sha256=hashlib.sha256(mulligan).hexdigest(),
                      mulligan_variant=MULLIGAN_VARIANT)
    if modes is not None:
        result.update(original_mode_callback_sha256=CALLBACK_SHA256,
                      staged_mode_rules_sha256=hashlib.sha256(modes).hexdigest(),
                      mode_variant=MODE_MANA_VARIANT if config.get("mode_mana_callback") is True else MODE_VARIANT)
        if config.get("mode_mana_callback") is True:
            result["mode_mana_callback"] = True
    if dialogs is not None:
        result.update(original_dialog_callback_sha256=CALLBACK_SHA256,
                      staged_dialog_rules_sha256=hashlib.sha256(dialogs).hexdigest(), dialog_variant=DIALOG_VARIANT)
    if payments is not None:
        result.update(original_mana_payment_callback_sha256=CALLBACK_SHA256,
                      staged_mana_payment_rules_sha256=hashlib.sha256(payments).hexdigest(),
                      mana_payment_variant=MANA_PAYMENT_VARIANT)
    if targets is not None:
        result.update(original_target_callback_sha256=CALLBACK_SHA256,
                      staged_target_rules_sha256=hashlib.sha256(targets).hexdigest(), target_variant=TARGET_VARIANT)
    if card_sets is not None:
        result.update(original_card_set_callback_sha256=CALLBACK_SHA256,
                      original_card_set_method_sha256=hashlib.sha256(card_set_method((root / callback["filename"]).read_bytes().decode("utf-8")).encode()).hexdigest(),
                      staged_card_set_rules_sha256=hashlib.sha256(card_sets).hexdigest(), card_set_variant=CARD_SET_VARIANT)
    with (output / "STAGE.json").open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(stage(json.loads(args.manifest.read_bytes()), args.inputs, args.out)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
