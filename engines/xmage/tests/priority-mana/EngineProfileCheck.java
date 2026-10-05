package mage.player.spellbench.server;

import java.io.IOException;
import java.util.List;
import java.util.Map;

/** Profile declarations stay bound to the engine's startup setting. Does not start XMage or use a database. */
public final class EngineProfileCheck {
    private static void require(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }

    @SuppressWarnings("unchecked")
    private static void check(EngineProfile profile, boolean enabled) {
        Map<String, Object> hello = profile.helloOk("profile-check", 0);
        List<Object> kinds = (List<Object>) hello.get("decision_kinds");
        require(profile.priorityMana == enabled, "profile setting changed");
        require(kinds.contains("activate_mana_ability") == enabled, "wrong mana declaration");
        require("engine_autopay".equals(((Map<String, Object>) hello.get("engine_defaults")).get("mana_payment")),
                "cost payment default changed");
        // A caller changing a returned hello cannot mutate later declarations.
        kinds.clear();
        require(((List<?>) profile.helloOk("again", 0).get("decision_kinds")).contains("pass"),
                "hello exposed mutable profile state");
    }

    public static void main(String[] args) throws Exception {
        String saved = System.getProperty("spellbench.priorityMana");
        try {
            System.clearProperty("spellbench.priorityMana");
            EngineProfile defaultProfile = EngineProfile.load();
            check(defaultProfile, false);
            System.setProperty("spellbench.priorityMana", "true");
            EngineProfile enabledProfile = EngineProfile.load();
            check(defaultProfile, false);
            check(enabledProfile, true);
            System.setProperty("spellbench.priorityMana", "false");
            check(enabledProfile, true);
            check(EngineProfile.load(), false);
            for (String invalid : new String[]{"", "TRUE", "yes", "1"}) {
                System.setProperty("spellbench.priorityMana", invalid);
                try {
                    EngineProfile.load();
                    throw new AssertionError("invalid setting accepted: " + invalid);
                } catch (IOException expected) {
                    require(expected.getMessage().contains("spellbench.priorityMana"), "unexpected failure");
                }
            }
            System.out.println("priority-mana profile: PASS");
        } finally {
            if (saved == null) System.clearProperty("spellbench.priorityMana");
            else System.setProperty("spellbench.priorityMana", saved);
        }
    }
}
