package mage.player.spellbench.server;

import java.io.IOException;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import mage.player.spellbench.observe.ObservationBuilder;
import mage.player.spellbench.ids.ObjectIds;

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
        String savedText = System.getProperty("spellbench.stackText");
        try {
            System.clearProperty("spellbench.stackText");
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
            EngineProfile noText = EngineProfile.load();
            System.setProperty("spellbench.stackText", "true");
            EngineProfile text = EngineProfile.load();
            System.setProperty("spellbench.stackText", "false");
            require(!noText.stackText && text.stackText, "stack text setting not frozen");
            require(Boolean.FALSE.equals(((Map<?, ?>) noText.helloOk("no-text", 0).get("observation")).get("stack_text")),
                    "default profile changed");
            require(Boolean.TRUE.equals(((Map<?, ?>) text.helloOk("text", 0).get("observation")).get("stack_text")),
                    "enabled profile lost its frozen text setting");
            require(Boolean.TRUE.equals(EngineProfile.observationFlags(text.stackText).get("stack_text")),
                    "game observations differ from their hello declaration");
            // Valid declarations must also be accepted by the actual builder's
            // implemented-field contract. No game is used by its constructor.
            new ObservationBuilder(null, new ObjectIds(new byte[32]), EngineProfile.observationFlags(text.stackText),
                    UUID.nameUUIDFromBytes(new byte[]{0}), UUID.nameUUIDFromBytes(new byte[]{1}));
            for (String invalid : new String[]{"", "TRUE", "yes", "1"}) {
                System.setProperty("spellbench.stackText", invalid);
                try {
                    EngineProfile.load();
                    throw new AssertionError("invalid text setting accepted: " + invalid);
                } catch (IOException expected) {
                    require(expected.getMessage().contains("spellbench.stackText"), "unexpected text failure");
                }
            }
            System.setProperty("spellbench.stackText", "false");
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
            if (savedText == null) System.clearProperty("spellbench.stackText");
            else System.setProperty("spellbench.stackText", savedText);
        }
    }
}
