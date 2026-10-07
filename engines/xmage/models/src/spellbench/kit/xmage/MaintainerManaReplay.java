package spellbench.kit.xmage;

import mage.MageObject;
import mage.abilities.Ability;
import mage.abilities.ActivatedAbility;
import mage.abilities.costs.mana.ManaCost;
import mage.choices.Choice;
import mage.constants.Outcome;
import mage.game.Game;
import mage.player.ai.ComputerPlayer;
import mage.players.Player;
import mage.target.Target;

import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Field;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.Map;
import java.util.function.BooleanSupplier;

/** Original private payment rules, bound to each actual or copied acting player. */
final class MaintainerManaReplay implements ModelReplay.ManaCapture {
    static final String VARIANT = "original automatic mana producer filters and stable ordering; original activation tap reservations, "
            + "nested unpaid-mana context, color preference and tap-target rules; "
            + "permitted replay; engine-only delegation for original mana callbacks; native execution unqualified";
    private final String source;
    private final Class<?> type;
    private final Map<Player, Object> owners = new IdentityHashMap<>();

    MaintainerManaReplay(String source) {
        if (source == null || !source.matches("[a-f0-9]{64}")) throw new IllegalArgumentException("original mana rule pin required");
        this.source = source;
        try {
            type = Class.forName("spellbench.models.maintainer.ManaPaymentRules");
            if (!MaintainerModeEncoder.SOURCE.equals(type.getField("SOURCE_SHA256").get(null))) {
                throw new IllegalArgumentException("mana payment rules differ from the original callback");
            }
        } catch (ReflectiveOperationException e) { throw new IllegalArgumentException("original mana payment class unavailable", e); }
    }

    @Override public String sourceSha256() { return source; }
    private Object owner(Player player) {
        if (player == null) throw new IllegalArgumentException("acting mana player required");
        try {
            Object rules = owners.get(player);
            if (rules == null) { rules = type.getConstructor(Player.class).newInstance(player); owners.put(player, rules); }
            return rules;
        } catch (ReflectiveOperationException e) { throw new IllegalArgumentException("original mana player binding failed", e); }
    }
    private Object call(Player player, String method, Class<?>[] types, Object... args) {
        try { return type.getMethod(method, types).invoke(owner(player), args); }
        catch (ReflectiveOperationException e) {
            Throwable cause = e instanceof InvocationTargetException ? e.getCause() : e;
            if (cause instanceof RuntimeException) throw (RuntimeException) cause;
            if (cause instanceof Error) throw (Error) cause;
            throw new IllegalArgumentException("original mana rule failed: " + method, cause);
        }
    }
    @SuppressWarnings("unchecked")
    @Override public List<MageObject> producers(Player viewer, List<MageObject> original, Game game) {
        return (List<MageObject>) call(viewer, "filterProducers", new Class<?>[]{List.class, Game.class}, original, game);
    }
    @Override public boolean payment(Player viewer, ManaCost unpaid, BooleanSupplier engine) {
        return (Boolean) call(viewer, "payment", new Class<?>[]{ManaCost.class, BooleanSupplier.class}, unpaid, engine);
    }
    @Override public boolean activation(Player viewer, ActivatedAbility source, Game game, BooleanSupplier engine) {
        try {
            call(viewer, "prepareActivation", new Class<?>[]{ActivatedAbility.class, Game.class}, source, game);
            return engine.getAsBoolean();
        } finally { call(viewer, "clearActivation", new Class<?>[0]); }
    }
    // the maintainer's parent uses the ordinary engine choice methods when its planning
    // queues are empty. Payment delegation must not invoke Exp1's policy.
    private static final class EngineChoice extends ComputerPlayer {
        private static final long serialVersionUID = 1L;
        @SuppressWarnings({"rawtypes", "unchecked"})
        EngineChoice(Player viewer) {
            super(requireEnginePlayer(viewer));
            // ComputerPlayer's copy constructor resets its transient payment
            // map. Retain the actual player's ordered pending costs for the
            // original color-choice delegation, including colorless mana.
            try {
                Field costs = ComputerPlayer.class.getDeclaredField("lastUnpaidMana");
                costs.setAccessible(true);
                ((Map) costs.get(this)).putAll((Map) costs.get(viewer));
            } catch (ReflectiveOperationException e) {
                throw new IllegalArgumentException("engine pending mana state unavailable", e);
            }
        }
        private static ComputerPlayer requireEnginePlayer(Player viewer) {
            if (!(viewer instanceof ComputerPlayer)) throw new IllegalArgumentException("engine mana player required");
            return (ComputerPlayer) viewer;
        }
    }
    static boolean engineColor(Player viewer, Outcome outcome, Choice choice, Game game) {
        return new EngineChoice(viewer).choose(outcome, choice, game);
    }
    @Override public Boolean target(Player viewer, Outcome outcome, Target target, Ability source, Game game) {
        BooleanSupplier engine = () -> new EngineChoice(viewer).chooseTarget(outcome, target, source, game);
        return (Boolean) call(viewer, "target", new Class<?>[]{Outcome.class, Target.class, Ability.class, Game.class,
                BooleanSupplier.class}, outcome, target, source, game, engine);
    }
    @Override public Boolean color(Player viewer, Outcome outcome, Choice choice, Game game) {
        BooleanSupplier engine = () -> engineColor(viewer, outcome, choice, game);
        return (Boolean) call(viewer, "color", new Class<?>[]{Outcome.class, Choice.class, Game.class,
                BooleanSupplier.class}, outcome, choice, game, engine);
    }
}
