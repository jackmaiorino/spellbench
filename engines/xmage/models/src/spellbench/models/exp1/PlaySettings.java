package spellbench.models.exp1;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;
import spellbench.kit.core.Json;

/** Separate the qualified visit diagnostic from the released final-eval play settings. */
public final class PlaySettings {
    public static final String PUBLISHED = "published-exp1-final-eval-fair-v1";
    public final MCTSDefaults defaults;
    public final boolean published;
    public final Map<String, Object> values;

    private PlaySettings(MCTSDefaults defaults, boolean published, Map<String, Object> values) {
        this.defaults = defaults;
        this.published = published;
        this.values = values == null ? null : Collections.unmodifiableMap(new LinkedHashMap<>(values));
    }

    public static Map<String, Object> publishedValues() {
        return Json.map("profile", PUBLISHED, "searchBudget", 96L, "searchTimeout", "12",
                "backpropDiscount", "0.99", "priorTemp", "1.5", "priorBonus", "0.1",
                "noNoise", true, "dirichletNoiseEps", "0.15", "selectionTemperature", "2",
                "noPolicyPriority", true, "noPolicyTarget", true, "noPolicyUse", false, "noPolicyOpponent", true);
    }

    public static PlaySettings diagnostic(int visits) {
        if (visits < 2 || visits > 1000) throw new IllegalArgumentException("search visits must be 2..1000");
        MCTSDefaults d = new MCTSDefaults();
        d.searchBudget = visits; d.searchTimeout = 600;
        d.noNoise = true;
        d.noPolicyPriority = d.noPolicyTarget = d.noPolicyUse = d.noPolicyOpponent = false;
        d.priorTemp = 1.5; d.priorBonus = 0.1; d.backpropDiscount = 0.99;
        d.selectionTemperature = 0; d.dirichletNoiseEps = 0;
        return new PlaySettings(d, false, null);
    }

    public static PlaySettings from(Map<String, Object> record) {
        if (!record.containsKey("settings")) {
            Object count = record.get("visits");
            if (!(count instanceof Number) || ((Number) count).doubleValue() != ((Number) count).intValue()) {
                throw new IllegalArgumentException("integer visit budget required");
            }
            return diagnostic(((Number) count).intValue());
        }
        if (record.containsKey("visits")) throw new IllegalArgumentException("ambiguous Exp1 stopping profiles");
        Map<String, Object> values = Json.obj(record, "settings");
        if (values == null || !publishedValues().equals(values)) {
            throw new IllegalArgumentException("Exp1 published profile requires every exact released play setting");
        }
        MCTSDefaults d = new MCTSDefaults();
        d.searchBudget = 96; d.searchTimeout = 12; d.backpropDiscount = 0.99;
        d.priorTemp = 1.5; d.priorBonus = 0.1;
        d.noNoise = true; d.dirichletNoiseEps = 0.15; d.selectionTemperature = 2;
        d.noPolicyPriority = d.noPolicyTarget = d.noPolicyOpponent = true; d.noPolicyUse = false;
        return new PlaySettings(d, true, values);
    }

    public void activate() {
        // Constructors and original simulated opponent players read CURRENT.
        // Apply the released settings before constructing the permitted world.
        if (published) MCTSDefaults.CURRENT = defaults;
    }
    public static void reset() { MCTSDefaults.CURRENT = new MCTSDefaults(); }
    public Map<String, Object> budget() {
        return published ? Json.map("kind", "original_source_time_or_visits_until_legal_future",
                "requested", (long) defaults.searchBudget, "timeout_seconds", "12")
                : Json.map("kind", "minimum_root_visits_until_legal_future", "requested", (long) defaults.searchBudget);
    }
}
