package spellbench.models.maintainer;

import mage.constants.RangeOfInfluence;
import mage.game.Game;
import mage.game.GameState;
import mage.player.ai.ComputerPlayer;
import mage.players.Player;
import java.lang.reflect.Proxy;
import java.util.*;
import java.util.function.DoubleSupplier;

/** Actual original tensors and chooser, metadata worlds and synthetic paired predictions. */
public final class MaintainerNeuralSelectionCheck {
    static void require(boolean value, String reason) { if (!value) throw new AssertionError(reason); }
    static void refused(Runnable run) {
        try { run.run(); } catch (IllegalArgumentException expected) { return; }
        throw new AssertionError("expected refusal");
    }
    static final class World {
        final Player viewer, other = new ComputerPlayer("other", RangeOfInfluence.ALL);
        final GameState state = new GameState(); final Game game;
        final mage.players.Players players = new mage.players.Players();
        int builds;
        World() { this(new ComputerPlayer("viewer", RangeOfInfluence.ALL)); }
        World(Player viewer) {
            this.viewer = viewer;
            players.addPlayer(viewer); players.addPlayer(other);
            game = (Game) Proxy.newProxyInstance(Game.class.getClassLoader(), new Class<?>[]{Game.class}, (obj, method, args) -> {
                switch (method.getName()) {
                    case "equals": return obj == args[0];
                    case "hashCode": return System.identityHashCode(obj);
                    case "toString": return "metadata neural world";
                    case "getPlayer": return viewer.getId().equals(args[0]) ? viewer : other.getId().equals(args[0]) ? other : null;
                    case "getPlayers": return players;
                    case "getOpponents": return Collections.singleton(other.getId());
                    case "getState": return state;
                    case "getId": return new UUID(0, 77);
                    case "getPhase": return null;
                    case "getTurnNum": return 1;
                    case "getActivePlayerId": return viewer.getId();
                    case "getStartingLife": builds++; return 20;
                    case "getBattlefield": return state.getBattlefield();
                    case "getStack": return state.getStack();
                    case "getExile": return state.getExile();
                    default: throw new AssertionError("unexpected neural world read: " + method.getName());
                }
            });
        }
        PriorityRules rules() { return new PriorityRules(viewer, Collections.emptyMap()); }
        OriginalNeuralSelection.Admission admission() {
            return (g, p) -> { if (g != game || p != viewer) throw new IllegalArgumentException("unadmitted world"); };
        }
    }
    static final class Backend implements OriginalNeuralSelection.Model {
        final String profile; final long seed; int calls, closes;
        OriginalNeuralSelection.Request request;
        float[] scores = new float[64]; boolean invalid, throwing; Runnable after = () -> {};
        Backend(String profile, long seed) { this.profile = profile; this.seed = seed; Arrays.fill(scores, 1f/64); }
        public String callbackSourceSha256() { return OriginalNeuralSelection.SOURCE_SHA256; }
        public String profile() { return profile; } public long seed() { return seed; }
        public OriginalNeuralSelection.Prediction score(OriginalNeuralSelection.Request r, double left) {
            require(left > 0, "model lost decision allowance"); calls++; request = r; after.run();
            if (throwing) throw new IllegalArgumentException("model unavailable");
            return new OriginalNeuralSelection.Prediction(invalid ? new float[]{1} : scores, 0.375f);
        }
        public void close() { closes++; }
    }
    static List<Integer> choose(OriginalNeuralSelection selection, World w, int size, int maximum, int minimum) {
        List<String> options = new ArrayList<>(); for (int i = 0; i < size; i++) options.add("option-" + i);
        return selection.genericChoose(options, maximum, minimum, StateSequenceBuilder.ActionType.SELECT_CHOICE, w.game, null);
    }
    public static void main(String[] args) {
        World w = new World(); Backend backend = new Backend(OriginalNeuralSelection.GREEDY, 12);
        OriginalNeuralSelection.Session session = new OriginalNeuralSelection.Session(backend, backend.profile, backend.seed, () -> 10);
        PriorityRules rules = w.rules(); OriginalNeuralSelection selection = new OriginalNeuralSelection(w.viewer, rules, session, w.admission());
        require(choose(selection, w, 0, 1, 1).isEmpty(), "empty shortcut changed");
        require(choose(selection, w, 1, 0, 0).equals(Arrays.asList(0)), "original singleton shortcut changed");
        require(backend.calls == 0 && w.builds == 0, "shortcut encoded/inferred");
        backend.scores[3] = 0.75f;
        require(choose(selection, w, 70, 99, 80).equals(prefix(3, 64)), "prefix/clamps/greedy order changed");
        require(backend.request.count == 64 && backend.request.minimum == 64 && backend.request.maximum == 64
                && backend.request.pickIndex == 0 && backend.request.head.equals("action"), "original model arguments changed");
        int builds = w.builds; float[][] tokens = backend.request.tokens(); tokens[0][0] = 999;
        int[] ids = backend.request.actionIds(); ids[0] = -1;
        require(backend.request.tokens()[0][0] != 999 && backend.request.actionIds()[0] != -1, "request leaked mutable data");
        choose(selection, w, 2, 1, 1);
        require(w.builds == builds && backend.request.tokens()[0][0] != 999, "cached original state mutated/rebuilt");
        require(session.lastValue() == 0.375f, "paired value lost");
        int calls = backend.calls; require(choose(selection, w, 2, 0, 0).isEmpty(), "zero picks changed");
        require(backend.calls == calls + 1, "original zero-pick scoring skipped");
        int[] mask = backend.request.candidateMask(); require(mask[0] == 1 && mask[1] == 1 && mask[2] == 0, "original padded mask changed");
        require(backend.request.features().length == 64 && backend.request.features()[0].length == 48, "original feature shape changed");
        session.close(); session.close(); require(backend.closes == 1, "close not idempotent");
        refused(() -> choose(selection, w, 1, 1, 1));

        // Interleaved copied players consume one original Java Random stream, without reseeding.
        Backend sampled = new Backend(OriginalNeuralSelection.SAMPLED, 45);
        OriginalNeuralSelection.Session shared = new OriginalNeuralSelection.Session(sampled, sampled.profile, sampled.seed, () -> 10);
        OriginalNeuralSelection root = new OriginalNeuralSelection(w.viewer, w.rules(), shared, w.admission());
        World copied = new World(w.viewer.copy()); OriginalNeuralSelection copy = root.forCopy(copied.viewer, copied.rules(), copied.admission());
        PolicySelector expected = new PolicySelector(false, sampled.seed); int[] m = new int[64]; m[0] = m[1] = 1;
        for (int i = 0; i < 20; i++) {
            List<Integer> got = i % 2 == 0 ? choose(root, w, 2, 1, 1) : choose(copy, copied, 2, 1, 1);
            require(got.equals(Arrays.asList(expected.choose(sampled.scores, m, 2, 1, true)[0])), "copy reset or split shared RNG");
        }
        refused(() -> choose(root, copied, 1, 1, 1)); require(sampled.closes == 1, "ownership refusal did not close shared model");
        refused(() -> choose(copy, copied, 1, 1, 1));

        for (String failure : Arrays.asList("admission", "shape", "model", "deadline")) {
            Backend b = new Backend(OriginalNeuralSelection.GREEDY, 2); double[] remaining = {10};
            OriginalNeuralSelection.Session s = new OriginalNeuralSelection.Session(b, b.profile, b.seed, () -> remaining[0]);
            OriginalNeuralSelection.Admission admit = w.admission();
            if (failure.equals("admission")) admit = (g, p) -> { throw new IllegalArgumentException("not sampled"); };
            if (failure.equals("shape")) b.invalid = true;
            if (failure.equals("model")) b.throwing = true;
            if (failure.equals("deadline")) b.after = () -> remaining[0] = 0;
            OriginalNeuralSelection n = new OriginalNeuralSelection(w.viewer, w.rules(), s, admit);
            refused(() -> choose(n, w, 2, 1, 1)); require(b.closes == 1, failure + " did not fail closed");
            refused(() -> choose(n, w, 1, 1, 1));
            if (failure.equals("admission")) require(b.calls == 0, "unadmitted inference ran");
        }
        refused(() -> new OriginalNeuralSelection.Session(new Backend(OriginalNeuralSelection.GREEDY, 1),
                OriginalNeuralSelection.SAMPLED, 1, () -> 10));
        System.out.println("PASS MaintainerNeuralSelectionCheck: original tensors/prefix/cache, paired value, shared copy RNG, admission and deadline refusals");
    }
    static List<Integer> prefix(int first, int count) {
        List<Integer> expected = new ArrayList<>(); expected.add(first);
        for (int i = 0; i < count; i++) if (i != first) expected.add(i); return expected;
    }
}
