"""Extract Jack's original default priority rules into a private source stage.

Options, caches, activation tests, alternative-cost tracking and turn-step
dispatch stay distinct from feature encoding and the game-owned neural chooser.
The caller must supply original callbacks in simulation copies. This component
alone is not a complete player or a rated entry.
"""
from __future__ import annotations

import hashlib

from xmage_jack_sources import CALLBACK_SHA256, extract, replace_once

PRIORITY_VARIANT = ("original April default playable lookup, source-specific mana deduplication, "
                    "activation fast path, alternative-cost simulation and caches; "
                    "permitted base state; original step dispatch and pass-only shortcut; "
                    "simulation copies require original callback implementations; full player unfinished")


def priority_source(source: str) -> str:
    if hashlib.sha256(source.encode()).hexdigest() != CALLBACK_SHA256:
        raise ValueError("Jack priority rules require the pinned April callback bytes")
    fields = extract(source, "    protected StateSequenceBuilder.SequenceOutput currentState;",
                     "    private final List<StateSequenceBuilder.TrainingData> trainingBuffer;")
    cache = extract(source, "    private void invalidateBaseStateCache() {",
                    "    private String buildPlayableStateKey(Game game) {")
    cache = replace_once(cache,
        "StateSequenceBuilder.buildBaseState(game, turnPhase, StateSequenceBuilder.MAX_LEN);",
        "StateSequenceBuilder.buildBaseState(game, turnPhase, StateSequenceBuilder.MAX_LEN, getId(), permittedAliases);")
    playable = extract(source, "    private String buildPlayableStateKey(Game game) {",
                       "    private static float[] normalizePolicyScores(")
    playable = playable.replace("getPlayable(game, true)", "viewer.getPlayable(game, true)")
    taps = extract(source, "    private static boolean hasTapSourceCost(Ability ability) {",
                   "    private boolean isUsableManaAbilityForCurrentState(")
    lru = extract(source, "    private static <K, V> Map<K, V> createLruCache(",
                  "    private static final class SequentialPickResult {")
    simulation = extract(source, "    private Set<String> testAllAlternativeCosts(",
                         "    protected Ability calculateRLAction(")
    if simulation.count("game.createSimulationForAI()") != 2:
        raise ValueError("original priority simulation changed")
    simulation = simulation.replace("game.createSimulationForAI()", "originalSimulation(game)")
    options = extract(source, "        long actionSelectionStartNanos = System.nanoTime();",
                      "        // If Pass is the only option, genericChoose() will short-circuit")
    alternative = extract(source, "        // Detect alternative cost choices (they use KEY-based choices!)",
                          "        // Handle regular choices (modal spells, etc.) with RL model")
    alternative = replace_once(alternative, "super.choose(outcome, choice, game)", "engine.getAsBoolean()")
    dispatch = extract(source, "    protected boolean priorityPlay(Game game) {",
                       "    protected void printBattleField(Game game, String info) {")
    dispatch = replace_once(dispatch, "protected boolean priorityPlay(Game game)",
        "public boolean dispatch(Game game, ToIntFunction<List<ActivatedAbility>> chooser, Consumer<ActivatedAbility> activation, Runnable passing)")
    if dispatch.count("calculateRLAction(game)") != 4 or dispatch.count("act(game, (ActivatedAbility) currentAbility)") != 4:
        raise ValueError("original priority phase dispatch changed")
    dispatch = dispatch.replace("calculateRLAction(game)", "select(game, chooser)")
    dispatch = dispatch.replace("act(game, (ActivatedAbility) currentAbility)", "activation.accept((ActivatedAbility) currentAbility)")
    dispatch = dispatch.replace("pass(game)", "passing.run()")
    return """package spellbench.models.jack;
import mage.MageObject;
import mage.abilities.Ability;
import mage.abilities.Abilities;
import mage.abilities.ActivatedAbility;
import mage.abilities.costs.AlternativeSourceCosts;
import mage.abilities.common.PassAbility;
import mage.abilities.costs.mana.VariableManaCost;
import mage.abilities.mana.ManaAbility;
import mage.cards.Card;
import mage.choices.Choice;
import mage.constants.Outcome;
import mage.constants.TurnPhase;
import mage.constants.Zone;
import mage.game.Game;
import mage.game.GameState;
import mage.game.permanent.Permanent;
import mage.players.Player;
import mage.target.Target;
import mage.util.CardUtil;
import java.util.*;
import java.util.function.BooleanSupplier;
import java.util.function.Consumer;
import java.util.function.ToIntFunction;

/** Original default rules only. Caller owns permitted world and original callbacks. */
public final class PriorityRules {
    public static final String SOURCE_SHA256 = "%s";
    private static final boolean BASE_STATE_CACHE_ENABLED = true;
    private static final boolean ALTERNATIVE_COST_SIM_CACHE_ENABLED = true;
    private static final int ALTERNATIVE_COST_SIM_CACHE_MAX_ENTRIES = 256;
    private static final boolean PLAYABLE_CACHE_ENABLED = true;
    private static final boolean ACTIVATION_FASTPATH_ENABLED = true;
    private static final boolean SKIP_SIM_VALIDATION = false;
    private static final boolean PLAYABLE_NOCLONE_ENABLED = false;
    private static final boolean ACTIVATION_DIAG = false;
    private final Player viewer;
    private final UUID playerId;
    private final Map<UUID, String> permittedAliases;
    private Ability currentAbility;
    private final Map<UUID, Set<String>> validAlternativeCosts = new HashMap<>();
    private static final ThreadLocal<String> forcedAlternativeChoice = new ThreadLocal<>();
    private static final ThreadLocal<ChoiceTrackingData> choiceTrackingData = new ThreadLocal<>();
    public interface OriginalCallbacks {
        String priorityCallbackSourceSha256();
        default void admitOriginalSimulation(Game source, Game copied) {
            throw new IllegalArgumentException("original copied-player admission unavailable");
        }
    }
    public PriorityRules(Player viewer, Map<UUID, String> aliases) {
        if (viewer == null || aliases == null) throw new IllegalArgumentException("explicit permitted priority viewer required");
        this.viewer = viewer; this.playerId = viewer.getId(); this.permittedAliases = new HashMap<>(aliases);
    }
    private UUID getId() { return playerId; }
    public Player owner() { return viewer; }
    public Map<UUID,String> aliases() { return Collections.unmodifiableMap(new HashMap<>(permittedAliases)); }
    public void refreshPermittedAliases(Map<UUID,String> aliases) {
        if (aliases == null) throw new IllegalArgumentException("permitted aliases required");
        Set<String> names = new HashSet<>();
        for (Map.Entry<UUID,String> entry : aliases.entrySet())
            if (entry.getKey()==null || entry.getValue()==null || entry.getValue().isEmpty() || !names.add(entry.getValue()))
                throw new IllegalArgumentException("permitted aliases must be unique and named");
        if (!permittedAliases.equals(aliases)) {
            permittedAliases.clear(); permittedAliases.putAll(aliases);
            invalidateBaseStateCache(); invalidateAlternativeCostValidationCache();
            validAlternativeCosts.clear();
        }
    }
    private String getName() { return viewer.getName(); }
    private List<ActivatedAbility> getPlayableFast(Game game, boolean hidden, Zone zone, boolean duplicates) {
        throw new IllegalArgumentException("original default priority profile disables no-clone lookup");
    }
    private Game originalSimulation(Game game) {
        Game copied = game.createSimulationForAI();
        Player player = copied.getPlayer(getId());
        if (!(player instanceof OriginalCallbacks) || !SOURCE_SHA256.equals(((OriginalCallbacks) player).priorityCallbackSourceSha256()))
            throw new IllegalArgumentException("priority activation simulation requires original copied-player callbacks");
        if (!(viewer instanceof OriginalCallbacks))
            throw new IllegalArgumentException("priority source player lacks original copy admission");
        ((OriginalCallbacks) viewer).admitOriginalSimulation(game, copied);
        return copied;
    }
    public StateSequenceBuilder.SequenceOutput baseState(Game game) { return getOrBuildBaseState(game); }
    public Map<UUID, Set<String>> alternatives() {
        Map<UUID, Set<String>> copy = new HashMap<>();
        for (Map.Entry<UUID, Set<String>> entry : validAlternativeCosts.entrySet()) copy.put(entry.getKey(), new HashSet<>(entry.getValue()));
        return copy;
    }
    public ActivatedAbility select(Game game, ToIntFunction<List<ActivatedAbility>> chooser) {
        List<ActivatedAbility> all = options(game);
        if (all.size() == 1) return all.get(0);
        List<ActivatedAbility> first = Collections.unmodifiableList(new ArrayList<>(all.subList(0, Math.min(64, all.size()))));
        int index = chooser.applyAsInt(first);
        if (index < 0 || index >= first.size()) throw new IllegalArgumentException("original priority chooser returned an illegal slot");
        return first.get(index);
    }
    public List<ActivatedAbility> options(Game game) {
        if (game == null || game.getPlayer(getId()) != viewer) throw new IllegalArgumentException("priority owner differs from permitted game");
""" % CALLBACK_SHA256 + options + "        return flattenedOptions;\n    }\n" + """
    public Boolean alternativeChoice(Outcome outcome, Choice choice, Game game, BooleanSupplier engine) {
""" + alternative + "        return null;\n    }\n" + """
    private static final class ChoiceTrackingData { String choiceMade; Set<String> availableOptions; }
    private static final class GameLogger { static GameLogger create(boolean enabled) { return new GameLogger(); } }
    private static final class RLTrainer {
        static final ThreadLocal<java.util.logging.Logger> threadLocalLogger = ThreadLocal.withInitial(() -> java.util.logging.Logger.getLogger("spellbench.jack.priority"));
        static final ThreadLocal<GameLogger> threadLocalGameLogger = ThreadLocal.withInitial(() -> GameLogger.create(false));
    }
    private static final Metrics metrics = new Metrics();
    private static final class Metrics {
        void recordBaseStateCacheHit() { } void recordBaseStateCacheMiss() { }
        void recordBaseStateBuildMs(long value) { }
        void recordPlayableLookup(int count, long elapsed, boolean cached) { }
        void recordAltCostValidation(int count, long elapsed, boolean cached) { }
    }
    private static void trace(String message) { }
    private static void printBattleField(Game game, String message) { }
""" + fields + lru + cache + playable + taps + simulation + dispatch + "}\n"
