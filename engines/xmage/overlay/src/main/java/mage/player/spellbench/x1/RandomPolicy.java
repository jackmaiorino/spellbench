package mage.player.spellbench.x1;

import mage.player.cabt.MagicOption;
import mage.player.cabt.MagicOptionType;
import mage.player.cabt.PendingDecision;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.SplittableRandom;
import java.util.TreeMap;

/**
 * The uniform-random driver of the research brief's probe (cabt_probe.py), ported to Java. It only records a game's
 * answers; reruns replay the recorded answers, so its own generator never touches the engine.
 */
public final class RandomPolicy {

    private static final double CANCEL_P = 0.05;

    private final SplittableRandom rng;

    public RandomPolicy(long seed) {
        this.rng = new SplittableRandom(seed);
    }

    public List<Integer> choose(PendingDecision decision) {
        List<MagicOption> opts = decision.options();
        String type = decision.selectType().name();
        int lo = decision.minCount();
        int hi = Math.min(decision.maxCount(), opts.size());
        if (type.equals("PAY_MANA")) {
            List<Integer> nonCancel = new ArrayList<>();
            List<Integer> cancel = new ArrayList<>();
            for (int i = 0; i < opts.size(); i++) {
                (opts.get(i).type() == MagicOptionType.PROMPT_CANCEL_PAYMENT ? cancel : nonCancel).add(i);
            }
            if (!cancel.isEmpty() && (nonCancel.isEmpty() || rng.nextDouble() < CANCEL_P)) {
                return Collections.singletonList(cancel.get(0));
            }
            return Collections.singletonList(nonCancel.isEmpty() ? 0 : nonCancel.get(rng.nextInt(nonCancel.size())));
        }
        if (type.equals("DECLARE_ATTACKERS") || type.equals("DECLARE_BLOCKERS")) {
            String key = type.equals("DECLARE_ATTACKERS") ? "attackerId" : "blockerId";
            Map<String, List<Integer>> groups = new TreeMap<>();
            for (int i = 0; i < opts.size(); i++) {
                Object id = opts.get(i).payload().get(key);
                groups.computeIfAbsent(String.valueOf(id), k -> new ArrayList<>()).add(i);
            }
            List<Integer> pick = new ArrayList<>();
            for (List<Integer> g : groups.values()) {
                if (rng.nextDouble() < 0.5) {
                    pick.add(g.get(rng.nextInt(g.size())));
                }
            }
            Collections.sort(pick);
            return pick;
        }
        if (hi <= 1 && lo <= 1) {
            if (lo == 0 && (opts.isEmpty() || rng.nextDouble() < 0.2)) {
                return Collections.emptyList();
            }
            return opts.isEmpty() ? Collections.emptyList() : Collections.singletonList(rng.nextInt(opts.size()));
        }
        int k = hi >= lo ? lo + rng.nextInt(hi - lo + 1) : lo;
        List<Integer> idx = new ArrayList<>();
        for (int i = 0; i < opts.size(); i++) {
            idx.add(i);
        }
        for (int i = idx.size() - 1; i > 0; i--) {
            Collections.swap(idx, i, rng.nextInt(i + 1));
        }
        List<Integer> pick = new ArrayList<>(idx.subList(0, Math.min(k, idx.size())));
        Collections.sort(pick);
        return pick;
    }
}
