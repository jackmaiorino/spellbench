package spellbench.kit.xmage;

import spellbench.kit.core.Json;
import spellbench.models.magezero.v02.search.MCTSDefaults;
import java.util.Map;

/** Request settings boundaries without a checkpoint, sampled world or game. */
public final class MageZeroSearchSettingsCheck {
    private static int checks;
    private static Map<String, Object> source() {
        return Json.map("profile", "original-source-time-or-visits", "searchBudget", 1000L,
                "searchTimeout", "4", "backpropDiscount", "0.99", "priorTemp", "1.5", "priorBonus", "0.1",
                "noNoise", true, "dirichletNoiseEps", "0", "selectionTemperature", "0",
                "noPolicyPriority", true, "noPolicyTarget", true, "noPolicyUse", true, "noPolicyOpponent", true);
    }
    private static void refuses(Map<String, Object> values) {
        try { MageZeroSearchMain.settings(values); }
        catch (IllegalArgumentException expected) { checks++; return; }
        throw new IllegalStateException("unbound MageZero settings were accepted");
    }
    private static void changed(String key, Object value) {
        Map<String, Object> values = source(); values.put(key, value); refuses(values);
    }
    public static void main(String[] args) {
        MCTSDefaults actual = MageZeroSearchMain.settings(source());
        if (actual.searchBudget != 1000 || actual.searchTimeout != 4
                || !actual.noPolicyPriority || !actual.noPolicyTarget || !actual.noPolicyUse || !actual.noPolicyOpponent
                || actual.priorTemp != 1.5 || actual.priorBonus != 0.1 || actual.backpropDiscount != 0.99) {
            throw new IllegalStateException("original source settings changed");
        }
        checks++;
        Map<String, Object> diagnostic = source();
        diagnostic.put("profile", "minimum-visits-diagnostic"); diagnostic.put("searchBudget", 6L);
        diagnostic.put("searchTimeout", "600");
        for (String key : new String[]{"noPolicyPriority", "noPolicyTarget", "noPolicyUse", "noPolicyOpponent"}) {
            diagnostic.put(key, false);
        }
        actual = MageZeroSearchMain.settings(diagnostic);
        if (actual.searchBudget != 6 || actual.noPolicyPriority || actual.noPolicyTarget || actual.noPolicyUse || actual.noPolicyOpponent) {
            throw new IllegalStateException("diagnostic profile differs");
        }
        checks++;
        diagnostic.put("priorBonus", "2"); refuses(diagnostic);
        Map<String, Object> incomplete = source(); incomplete.remove("noPolicyUse"); refuses(incomplete);
        changed("searchBudget", true); changed("searchTimeout", 4L); changed("priorTemp", "NaN");
        changed("noNoise", false); changed("selectionTemperature", "1"); changed("searchTimeout", "0");
        changed("noPolicyTarget", 1L); changed("profile", "automatic-defaults");
        System.out.println("{\"passed\":true,\"checks\":" + checks
                + ",\"scope\":\"MageZero request settings only; no weights, search or game qualification\"}");
    }
}
