package spellbench.kit.xmage;

import mage.abilities.ActivatedAbility;
import mage.abilities.Mode;
import mage.abilities.Modes;
import mage.abilities.common.PassAbility;
import mage.abilities.costs.CostsImpl;
import mage.abilities.costs.mana.ManaCostsImpl;
import mage.abilities.mana.ManaAbility;
import mage.choices.Choice;
import mage.choices.ChoiceImpl;
import mage.constants.Outcome;
import mage.constants.PhaseStep;
import mage.constants.RangeOfInfluence;
import mage.game.Game;
import mage.game.GameState;
import mage.game.permanent.Battlefield;
import mage.player.ai.ComputerPlayer;
import mage.players.Player;
import mage.target.Targets;

import java.lang.reflect.Field;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.util.*;
import java.util.function.BooleanSupplier;
import java.util.function.Consumer;
import java.util.function.ToIntFunction;

/** Actual extracted rules on metadata fixtures. No game, database or network is started. */
public final class JackPriorityRulesCheck {
    private static final String SOURCE = "b45257a66fc3914506fca4dd83461b6c8853d129b3e1f38b2d3aeba6137bd0c6";
    private static Class<?> rulesType;
    private static void require(boolean condition, String message) { if (!condition) throw new AssertionError(message); }
    private static void field(Object rules, String name, Object value) throws Exception {
        Field field = rulesType.getDeclaredField(name); field.setAccessible(true); field.set(rules, value);
    }
    private static Object call(Object rules, String name, Class<?>[] types, Object... values) throws Exception {
        Method method = rulesType.getDeclaredMethod(name, types); method.setAccessible(true);
        try { return method.invoke(rules, values); }
        catch (InvocationTargetException e) {
            if (e.getCause() instanceof Exception) throw (Exception) e.getCause();
            if (e.getCause() instanceof Error) throw (Error) e.getCause();
            throw e;
        }
    }
    private static final class Viewer extends ComputerPlayer {
        List<ActivatedAbility> raw = new ArrayList<>(); int lookups;
        Viewer() { super("priority-metadata", RangeOfInfluence.ALL); }
        @Override public List<ActivatedAbility> getPlayable(Game game, boolean hidden) {
            require(hidden, "original lookup flag changed"); lookups++; return new ArrayList<>(raw);
        }
    }
    private static final class Fixture {
        final Viewer viewer = new Viewer(); final GameState state = new GameState();
        final UUID id = new UUID(1, 1); final PhaseStep[] step = {PhaseStep.PRECOMBAT_MAIN};
        final int[] events = {0}; final Game[] simulation = {null}; final Game game;
        Fixture() {
            state.setPriorityPlayerId(viewer.getId());
            game = (Game) Proxy.newProxyInstance(Game.class.getClassLoader(), new Class<?>[]{Game.class}, (p, m, a) -> {
                switch (m.getName()) {
                    case "getId": return id;
                    case "getPlayer": return viewer.getId().equals(a[0]) ? viewer : null;
                    case "getState": return state;
                    case "getPhase": case "getStack": case "getPermanent": case "getCard": return null;
                    case "getTurnNum": return 1;
                    case "getActivePlayerId": return viewer.getId();
                    case "getTurnStepType": return step[0];
                    case "getBattlefield": return new Battlefield();
                    case "getRangeOfInfluence": return RangeOfInfluence.ALL;
                    case "firePriorityEvent": events[0]++; return null;
                    case "createSimulationForAI": return simulation[0];
                    default: throw new AssertionError("unexpected game access: " + m.getName());
                }
            });
        }
        Object rules() throws Exception {
            Object rules = rulesType.getConstructor(Player.class, Map.class).newInstance(viewer, Collections.emptyMap());
            prime(rules); return rules;
        }
        void prime(Object rules) throws Exception {
            Class<?> sequence = Class.forName("spellbench.models.jack.StateSequenceBuilder$SequenceOutput");
            Object empty = sequence.getConstructor(List.class, List.class, List.class).newInstance(
                    Collections.emptyList(), Collections.emptyList(), Collections.emptyList());
            field(rules, "cachedBaseState", empty); field(rules, "cachedBaseStateHash", 1);
            field(rules, "cachedBaseStateGameId", id); field(rules, "cachedBaseStatePhase", null);
            field(rules, "cachedBaseStateActivePlayerId", viewer.getId());
            field(rules, "cachedBaseStatePriorityPlayerId", state.getPriorityPlayerId());
            field(rules, "cachedBaseStateChoosingPlayerId", state.getChoosingPlayerId());
            field(rules, "cachedBaseStateTurnNum", 1); field(rules, "cachedBaseStateStepNum", state.getStepNum());
            field(rules, "cachedBaseStateApplyEffectsCounter", state.getApplyEffectsCounter()); field(rules, "cachedBaseStateStackSize", 0);
        }
    }
    private static ActivatedAbility ability(String text, UUID source, boolean mana, boolean[] valid, int[] checks, boolean complex) {
        Modes modes = new Modes();
        if (complex) modes.addMode(new Mode(new mage.abilities.effects.common.DamageTargetEffect(2)));
        require(modes.size() == (complex ? 2 : 1), "wrong mode metadata");
        return (ActivatedAbility) Proxy.newProxyInstance(ActivatedAbility.class.getClassLoader(),
                mana ? new Class<?>[]{ActivatedAbility.class, ManaAbility.class} : new Class<?>[]{ActivatedAbility.class}, (p, m, a) -> {
            switch (m.getName()) {
                case "toString": case "getRule": return text;
                case "getSourceId": case "getId": case "getOriginalId": return source;
                case "getSourceObject": case "getControllerId": return null;
                case "getTargets": return new Targets();
                case "getCosts": return new CostsImpl<>();
                case "getManaCostsToPay": return new ManaCostsImpl<>();
                case "getModes": return modes;
                case "canActivate": checks[0]++; return ActivatedAbility.ActivationStatus.withoutApprovingObject(valid[0]);
                case "copy": return p;
                case "hashCode": return System.identityHashCode(p);
                case "equals": return p == a[0];
                default: throw new AssertionError("unexpected ability access: " + m.getName());
            }
        });
    }
    @SuppressWarnings("unchecked")
    private static List<ActivatedAbility> options(Fixture f, Object rules) throws Exception {
        return (List<ActivatedAbility>) call(rules, "options", new Class<?>[]{Game.class}, f.game);
    }
    private static ChoiceImpl alternatives() {
        ChoiceImpl choice = new ChoiceImpl(true); Map<String, String> keys = new LinkedHashMap<>();
        keys.put("0", "normal cost"); keys.put("1", "alternative cost"); choice.setKeyChoices(keys); return choice;
    }
    public static void main(String[] args) throws Exception {
        rulesType = Class.forName("spellbench.models.jack.PriorityRules");
        require(SOURCE.equals(rulesType.getField("SOURCE_SHA256").get(null)), "wrong source");
        Fixture f = new Fixture(); boolean[] allowed = {true}; int[] checks = {0};
        ActivatedAbility a = ability("mana", new UUID(0, 1), true, new boolean[]{true}, new int[]{0}, false);
        ActivatedAbility b = ability("mana", new UUID(0, 2), true, new boolean[]{true}, new int[]{0}, false);
        ActivatedAbility spell = ability("spell", new UUID(0, 3), false, allowed, checks, false);
        ActivatedAbility duplicate = ability("spell", new UUID(0, 4), false, new boolean[]{true}, new int[]{0}, false);
        ActivatedAbility denied = ability("denied", new UUID(0, 5), false, new boolean[]{false}, new int[]{0}, false);
        f.viewer.raw = Arrays.asList(a, b, spell, duplicate, denied, a); Object rules = f.rules();
        List<ActivatedAbility> selected = options(f, rules);
        require(selected.size() == 4 && selected.get(0) instanceof PassAbility && selected.get(1) == a
                && selected.get(2) == b && selected.get(3) == spell, "original dedup, validation or order changed");
        options(f, rules); require(f.viewer.lookups == 1 && checks[0] == 1, "original caches did not reuse same state");
        allowed[0] = false; f.state.increaseStepNum(); f.prime(rules);
        require(options(f, rules).size() == 3 && f.viewer.lookups == 2 && checks[0] == 2, "state key reused stale validation");
        Fixture onlyPass = new Fixture(); Object passRules = onlyPass.rules();
        ToIntFunction<List<ActivatedAbility>> forbidden = list -> { throw new AssertionError("pass-only invoked chooser"); };
        require(call(passRules, "select", new Class<?>[]{Game.class, ToIntFunction.class}, onlyPass.game, forbidden) instanceof PassAbility,
                "pass-only selection changed");
        Fixture large = new Fixture();
        for (int i = 0; i < 70; i++) large.viewer.raw.add(ability("ability " + i, new UUID(0, 100 + i), false,
                new boolean[]{true}, new int[]{0}, false));
        Object largeRules = large.rules(); int[] draws = {0};
        ToIntFunction<List<ActivatedAbility>> last = list -> { draws[0]++; require(list.size() == 64
                && list.get(0) instanceof PassAbility, "original first-64 cap changed"); return 63; };
        require(call(largeRules, "select", new Class<?>[]{Game.class, ToIntFunction.class}, large.game, last)
                == large.viewer.raw.get(62) && draws[0] == 1, "selection mapped a different original slot");
        PhaseStep[] steps = {PhaseStep.UPKEEP, PhaseStep.DRAW, PhaseStep.PRECOMBAT_MAIN, PhaseStep.BEGIN_COMBAT,
                PhaseStep.DECLARE_ATTACKERS, PhaseStep.DECLARE_BLOCKERS, PhaseStep.FIRST_COMBAT_DAMAGE,
                PhaseStep.COMBAT_DAMAGE, PhaseStep.END_COMBAT, PhaseStep.POSTCOMBAT_MAIN, PhaseStep.END_TURN, PhaseStep.CLEANUP};
        for (PhaseStep step : steps) {
            onlyPass.step[0] = step; int[] count = {0, 0};
            Consumer<ActivatedAbility> activation = picked -> { require(picked instanceof PassAbility, "wrong phase action"); count[0]++; };
            Runnable passing = () -> count[1]++;
            boolean result = (Boolean) call(passRules, "dispatch", new Class<?>[]{Game.class, ToIntFunction.class, Consumer.class, Runnable.class},
                    onlyPass.game, forbidden, activation, passing);
            boolean main = step == PhaseStep.PRECOMBAT_MAIN || step == PhaseStep.POSTCOMBAT_MAIN;
            boolean combat = step == PhaseStep.DECLARE_ATTACKERS || step == PhaseStep.DECLARE_BLOCKERS;
            require(result == (main || combat) && count[0] == (main || combat ? 1 : 0)
                    && count[1] == (main ? 0 : 1), "original phase dispatch changed: " + step);
        }
        require(onlyPass.events[0] == steps.length, "original priority event changed");
        Fixture complex = new Fixture(); Object complexRules = complex.rules(); int[] simulations = {0};
        ActivatedAbility complexAbility = ability("complex", new UUID(0, 500), false, new boolean[]{true}, new int[]{0}, true);
        complex.viewer.raw.add(complexAbility);
        Class<?> marker = Class.forName("spellbench.models.jack.PriorityRules$OriginalCallbacks");
        Player copied = (Player) Proxy.newProxyInstance(Player.class.getClassLoader(), new Class<?>[]{Player.class, marker}, (p, m, values) -> {
            if ("priorityCallbackSourceSha256".equals(m.getName())) return SOURCE;
            if ("activateAbility".equals(m.getName())) {
                simulations[0]++; ChoiceImpl choice = alternatives();
                BooleanSupplier engine = () -> { choice.setChoiceByKey("0"); return true; };
                call(complexRules, "alternativeChoice", new Class<?>[]{Outcome.class, Choice.class, Game.class, BooleanSupplier.class},
                        Outcome.PutManaInPool, choice, complex.simulation[0], engine);
                return "1".equals(choice.getChoiceKey());
            }
            throw new AssertionError("unexpected simulation player access: " + m.getName());
        });
        complex.simulation[0] = (Game) Proxy.newProxyInstance(Game.class.getClassLoader(), new Class<?>[]{Game.class}, (p, m, values) -> {
            if ("getPlayer".equals(m.getName())) return copied;
            throw new AssertionError("unexpected simulation game access");
        });
        require(options(complex, complexRules).size() == 2 && simulations[0] == 3, "all alternative costs were not tested");
        Map<?, ?> valid = (Map<?, ?>) call(complexRules, "alternatives", new Class<?>[]{});
        require(Collections.singleton("1").equals(valid.get(complexAbility.getSourceId())), "validated alternative choice not retained");
        options(complex, complexRules); require(simulations[0] == 3, "cached alternative validation reran callbacks");
        field(complexRules, "currentAbility", complexAbility); ChoiceImpl actual = alternatives();
        BooleanSupplier noFallback = () -> { throw new AssertionError("validated alternative delegated to fallback"); };
        require(Boolean.TRUE.equals(call(complexRules, "alternativeChoice", new Class<?>[]{Outcome.class, Choice.class, Game.class, BooleanSupplier.class},
                Outcome.PutManaInPool, actual, complex.game, noFallback)) && "1".equals(actual.getChoiceKey()), "actual choice ignored valid alternatives");
        Fixture unported = new Fixture(); unported.viewer.raw.add(complexAbility); Object unportedRules = unported.rules();
        unported.simulation[0] = unported.game;
        try { options(unported, unportedRules); throw new AssertionError("unported copied callbacks accepted"); }
        catch (IllegalArgumentException expected) { require(expected.getMessage().contains("original copied-player"), "wrong callback refusal"); }
        System.out.println("original priority rules: PASS (order, caches, fast path, cap, 12 steps, alternatives, callback refusal)");
    }
}
