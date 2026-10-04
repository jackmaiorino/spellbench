package spellbench.kit.xmage;

import spellbench.kit.core.Json;
import java.util.Arrays;
import java.util.Collections;
import java.util.Map;

/** A changed/undeclared priority mana input refuses before reconstruction or inference. */
public final class JackManaProfileCheck {
    private static void refused(Map<String, Object> start, Map<String, Object> decision, String message) throws Exception {
        try {
            JackEncoder.encode(start, decision, new byte[32], new byte[32]);
            throw new AssertionError("invalid encoder request accepted");
        } catch (IllegalArgumentException expected) {
            if (!expected.getMessage().contains(message)) throw expected;
        }
    }

    public static void main(String[] args) throws Exception {
        String savedEncoder = System.getProperty("spellbench.jack.encoderSourceSha256");
        String savedCandidate = System.getProperty("spellbench.jack.candidateSourceSha256");
        try {
            System.clearProperty("spellbench.jack.encoderSourceSha256");
            System.clearProperty("spellbench.jack.candidateSourceSha256");
            Map<String, Object> decision = Json.map("observation", Json.map("viewer", "p0"), "acting_seat", "p0",
                    "context", Json.map("kind", "priority"), "candidates", Arrays.asList(Json.map("candidate_id", 0L,
                    "semantic", Json.map("kind", "activate_mana_ability"))));
            refused(Json.map(), decision, "declared opt-in engine profile");
            refused(Json.map("engine_profile", Json.map("decision_kinds", Collections.emptyList())), decision,
                    "declared opt-in engine profile");
            refused(Json.map("engine_profile", Json.map("decision_kinds", "activate_mana_ability")), decision,
                    "declared opt-in engine profile");
            refused(Json.map("engine_profile", Json.map("decision_kinds", Arrays.asList("activate_mana_ability"))), decision,
                    "needs both staged source identities");
            System.out.println("Jack priority-mana profile gate: PASS");
        } finally {
            if (savedEncoder == null) System.clearProperty("spellbench.jack.encoderSourceSha256");
            else System.setProperty("spellbench.jack.encoderSourceSha256", savedEncoder);
            if (savedCandidate == null) System.clearProperty("spellbench.jack.candidateSourceSha256");
            else System.setProperty("spellbench.jack.candidateSourceSha256", savedCandidate);
        }
    }
}
