package spellbench.kit.core;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * The frozen kit entries (A1 result review, change 6): kit-mad-1 (H1), kit-mad-k (H2) and kit-mcts (H3). An entry's
 * identity is its name plus a digest of its whole configuration: the bot and how its decisions are dispatched, K, every
 * budget, the truncation scoring, the horizon policy and the approximation flags policy. The front reports the
 * identity in {@code hello} ({@code bot.name}, {@code bot.version} = kit version + "+" + digest) and logs the
 * configuration at {@code game_start}. Any override of a frozen value (a budget, K, the skill) makes a different
 * configuration: its name gets the suffix {@code -custom} and its digest changes, so a modified configuration can never
 * report a frozen entry's identity.
 */
public final class Entries {

    public static final String KIT_VERSION = "0.2.0";

    private Entries() {
    }

    /** Policies every entry shares (design Sections 3.3, 3.4, 5.1, 5.6, 6.5; E4 outcome; review changes 3 and 4). */
    static Map<String, Object> commonPolicies() {
        return Json.map(
                "dialogs", "ComputerPlayer heuristics (identical in upstream MAD and MCTS)",
                "mulligan", "ComputerPlayer.chooseMulligan on a pregame world",
                "continuation", "saved anchor rebuilt from inputs; earlier dialogs of the resolution replayed from own answers",
                "horizon", "a world with a horizon-flagged stack object or dropped pending triggers is not searched; the "
                        + "front answers the declining candidate (wrapper)",
                "unsupported_states", "a world with an unsupported flag is not searched; the front declines (wrapper)",
                "non_stack_payload", "a chosen action that does not use the stack and asks a dialog while it executes is "
                        + "unsupported; the next ranked candidate answers (wrapper)",
                "approximation_flags", Arrays.asList("approximate:watchers_reset (every world)",
                        "approximate:unexplained_characteristics", "approximate:activation_usage_other_seat",
                        "approximate:first_strike_step_unknown", "approximate:token_characteristics"),
                "fallback", "ranked, else declining, else lowest candidate id; always an offered candidate");
    }

    static Map<String, Object> madBudgets() {
        return Json.map("nodes", 5000L, "options", 2000L, "operations", 20000L);
    }

    /** The frozen configuration of {@code entry} (h1, h2, h3). */
    public static Map<String, Object> frozen(String entry) {
        Map<String, Object> c;
        switch (entry) {
            case "h1":
                c = Json.map("name", "kit-mad-1", "bot", "mad", "worlds", 1L, "skill", 6L,
                        "budgets", madBudgets(), "aggregation", "single world",
                        "priority", "ComputerPlayer7 search in the main phases and declare steps; elsewhere its own pass, "
                                + "answered without a world",
                        "combat", "ComputerPlayer6 declareAttackers/declareBlockers on the world",
                        "truncation", "MAD: a horizon or a budget stop scores the node by GameStateEvaluator2 (a leaf)");
                break;
            case "h2":
                c = Json.map("name", "kit-mad-k", "bot", "mad", "worlds", 4L, "skill", 6L,
                        "budgets", madBudgets(), "aggregation", "vote per priority key, ties by exact score sums, then "
                                + "the lowest candidate id; combat vote per combat key",
                        "priority", "ComputerPlayer7 search in the main phases and declare steps; elsewhere its own pass, "
                                + "answered without a world",
                        "combat", "ComputerPlayer6 declareAttackers/declareBlockers on each world",
                        "truncation", "MAD: a horizon or a budget stop scores the node by GameStateEvaluator2 (a leaf)");
                break;
            case "h3":
                c = Json.map("name", "kit-mcts", "bot", "mcts", "worlds", 1L, "skill", 6L,
                        "budgets", Json.map("iterations", 30L, "rollout", 300L, "operations", 20000L, "options", 2000L),
                        "aggregation", "visits per priority key (one world)",
                        "priority", "MCTS at every priority decision with more than one candidate (upstream dispatch)",
                        "combat", "MCTS selectAttackers/selectBlockers (upstream dispatch)",
                        "truncation", "a rollout stopped by the rollout cap, the operation cap or a horizon counts as a "
                                + "completed iteration and scores a win when the decider's GameStateEvaluator2 score "
                                + "exceeds its score at the decision (design 5.6); labelled truncated");
                break;
            default:
                throw new IllegalArgumentException("unknown entry " + entry);
        }
        c.put("policies", commonPolicies());
        return c;
    }

    /**
     * The entry's configuration with the command-line overrides applied: {@code worlds}, {@code skill} and the budgets
     * {@code nodes}, {@code options}, {@code operations}, {@code iterations}, {@code rollout}.
     */
    @SuppressWarnings("unchecked")
    public static Map<String, Object> configure(String entry, Map<String, String> opts) {
        Map<String, Object> c = frozen(entry);
        List<String> overridden = new ArrayList<>();
        if (opts.containsKey("worlds") && Long.parseLong(opts.get("worlds")) != Json.num(c, "worlds", 1)) {
            c.put("worlds", Long.parseLong(opts.get("worlds")));
            overridden.add("worlds");
        }
        if (opts.containsKey("skill") && Long.parseLong(opts.get("skill")) != Json.num(c, "skill", 6)) {
            c.put("skill", Long.parseLong(opts.get("skill")));
            overridden.add("skill");
        }
        Map<String, Object> b = new LinkedHashMap<>((Map<String, Object>) c.get("budgets"));
        for (String k : new String[]{"nodes", "options", "operations", "iterations", "rollout"}) {
            if (opts.containsKey(k) && !Long.valueOf(Long.parseLong(opts.get(k))).equals(b.get(k))) {
                b.put(k, Long.parseLong(opts.get(k)));
                overridden.add(k);
            }
        }
        c.put("budgets", b);
        if ("1".equals(opts.get("search-flagged"))) {
            c.put("search_flagged", true); // measurement mode (E4): flagged worlds are searched up to the horizon
            overridden.add("search_flagged");
        }
        if (!overridden.isEmpty()) {
            c.put("name", c.get("name") + "-custom");
            c.put("overridden", overridden);
        }
        return c;
    }

    /** Twelve hex digits of the configuration's canonical JSON. */
    public static String digest(Map<String, Object> config) {
        return Seeds.hex(Seeds.hmac("spellbench-kit-entry".getBytes(java.nio.charset.StandardCharsets.UTF_8),
                Json.canonical(config))).substring(0, 12);
    }

    public static String version(Map<String, Object> config) {
        return KIT_VERSION + "+" + digest(config);
    }
}
