package spellbench.models.draftzero.gnn;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;

/** Java 8 and played-configuration helpers for the staged DraftZero graph network sources. */
public final class GnnCompat {
    private GnnCompat() { }

    /** Java 9's List.of: an unmodifiable list that refuses null elements. */
    @SafeVarargs
    public static <T> List<T> listOf(T... items) {
        for (T item : items) if (item == null) throw new NullPointerException("List.of element");
        return Collections.unmodifiableList(new ArrayList<>(Arrays.asList(items)));
    }

    /** BenchSearch's heuristic leaf (GameStateEvaluator3) is not the played configuration. */
    public static double heuristicLeafRefused() {
        throw new IllegalStateException("the graph network's played search scores leaves with its value head only");
    }
}
