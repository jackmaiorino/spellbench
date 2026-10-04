package spellbench.models.exp1;

import java.util.Map;
import spellbench.kit.core.Json;

/** Check private request profile isolation without constructing a game or loading weights. */
public final class PlaySettingsCheck {
    private static int checks;
    private static void refuses(Map<String, Object> request) {
        try { PlaySettings.from(request); }
        catch (IllegalArgumentException expected) { checks++; return; }
        throw new IllegalStateException("ambiguous or changed Exp1 play settings were accepted");
    }
    public static void main(String[] args) {
        PlaySettings published = PlaySettings.from(Json.map("settings", PlaySettings.publishedValues()));
        MCTSDefaults d = published.defaults;
        if (!published.published || d.searchBudget != 96 || d.searchTimeout != 12 || d.backpropDiscount != 0.99
                || !d.noNoise || d.dirichletNoiseEps != 0.15 || d.selectionTemperature != 2
                || !d.noPolicyPriority || !d.noPolicyTarget || d.noPolicyUse || !d.noPolicyOpponent
                || d.priorTemp != 1.5 || d.priorBonus != 0.1
                || !"original_source_time_or_visits_until_legal_future".equals(published.budget().get("kind"))) {
            throw new IllegalStateException("released Exp1 play settings differ");
        }
        checks++;
        published.activate();
        if (MCTSDefaults.CURRENT != d) throw new IllegalStateException("original constructor settings not activated");
        PlaySettings.reset();
        PlaySettings diagnostic = PlaySettings.from(Json.map("visits", 6L));
        d = diagnostic.defaults;
        if (diagnostic.published || d.searchBudget != 6 || d.searchTimeout != 600 || d.backpropDiscount != 0.99
                || d.noPolicyPriority || d.noPolicyTarget || d.noPolicyUse || d.noPolicyOpponent
                || d.dirichletNoiseEps != 0 || d.selectionTemperature != 0
                || MCTSDefaults.CURRENT.searchBudget != 1000 || MCTSDefaults.CURRENT.searchTimeout != 4) {
            throw new IllegalStateException("published profile leaked into the legacy diagnostic");
        }
        checks++;
        refuses(Json.map("visits", 96L, "settings", PlaySettings.publishedValues()));
        refuses(Json.map("settings", null)); refuses(Json.map("visits", true));
        for (String key : PlaySettings.publishedValues().keySet()) {
            Map<String, Object> values = PlaySettings.publishedValues();
            values.remove(key); refuses(Json.map("settings", values));
        }
        Map<String, Object> values = PlaySettings.publishedValues(); values.put("backpropDiscount", "0.7");
        refuses(Json.map("settings", values));
        values = PlaySettings.publishedValues(); values.put("searchBudget", 96.0);
        refuses(Json.map("settings", values));
        values = PlaySettings.publishedValues(); values.put("noPolicyUse", 0L);
        refuses(Json.map("settings", values));
        System.out.println("{\"passed\":true,\"checks\":" + checks
                + ",\"scope\":\"Exp1 request settings only; no checkpoint, search or game qualification\"}");
    }
}
