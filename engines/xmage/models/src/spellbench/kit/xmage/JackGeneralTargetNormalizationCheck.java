package spellbench.kit.xmage;

import spellbench.kit.core.Json;
import java.util.Arrays;
import java.util.Map;

/** Check the public callback mapping; no engine world, private source or model is used. */
public final class JackGeneralTargetNormalizationCheck {
    private JackGeneralTargetNormalizationCheck() { }
    public static void main(String[] args) {
        Map<String, Object> source = Json.map("object_id", "source", "card_name", "Village Rites",
                "controller_seat", "p0", "owner_seat", "p0", "zone", "stack");
        Map<String, Object> object = Json.map("object_id", "creature", "card_name", "Elvish Mystic",
                "controller_seat", "p0", "owner_seat", "p0", "zone", "battlefield");
        Map<String, Object> semantic = Json.map("kind", "choose_cost_target", "source", source,
                "cost_kind", "sacrifice", "candidate", object, "selected_count", 0L, "minimum", 1L, "maximum", 1L);
        Map<String, Object> decision = Json.map("acting_seat", "p0", "context", Json.map("kind", "choice", "source", source),
                "observation", Json.map("viewer", "p0"),
                "candidates", Arrays.asList(Json.map("candidate_id", 4L, "semantic", semantic)));
        String before = Json.canonical(decision);
        Map<String, Object> expected = Json.obj(Json.copy(decision));
        Map<String, Object> mapped = Json.obj(Json.arr(expected, "candidates").get(0));
        mapped.put("semantic", Json.map("kind", "choose_target", "source", source, "slot", 3L,
                "target", Json.map("object", object), "selected_count", 0L, "minimum", 1L, "maximum", 1L));
        Map<String, Object> normalized = JackGeneralTargetEncoder.normalizeDecision(decision, 3L);
        require(Json.canonical(expected).equals(Json.canonical(normalized)), "cost target mapping changed");
        require(before.equals(Json.canonical(decision)), "mapping changed the original wire action");
        Map<String, Object> choice = Json.map("kind", "select_object", "source", source, "purpose", "discard",
                "choice", Json.map("object", object), "selected_count", 0L, "minimum", 0L, "maximum", 1L);
        Map<String, Object> finish = Json.map("kind", "finish_selection", "source", source, "purpose", "discard", "selected_count", 0L);
        Map<String, Object> group = Json.map("candidates", Arrays.asList(Json.map("candidate_id", 9L, "semantic", choice),
                Json.map("candidate_id", 10L, "semantic", finish)));
        Map<String, Object> selected = JackGeneralTargetEncoder.normalizeDecision(group, 0);
        require("choose_target".equals(Json.str(Json.obj(Json.obj(Json.arr(selected, "candidates").get(0)), "semantic"), "kind")), "object mapping changed");
        require("finish_target_selection".equals(Json.str(Json.obj(Json.obj(Json.arr(selected, "candidates").get(1)), "semantic"), "kind")), "STOP mapping changed");
        Map<String, Object> bad = Json.obj(Json.copy(group));
        Json.obj(Json.obj(Json.arr(bad, "candidates").get(1)), "semantic").put("purpose", "sacrifice");
        refuse(() -> JackGeneralTargetEncoder.normalizeDecision(bad, 0));
        Map<String, Object> shadow = Json.obj(Json.copy(choice)); shadow.put("target", Json.map("player", "p1"));
        refuse(() -> JackGeneralTargetEncoder.normalizeSemantic(shadow, 0));
        Map<String, Object> missing = Json.obj(Json.copy(semantic)); missing.remove("candidate");
        refuse(() -> JackGeneralTargetEncoder.normalizeSemantic(missing, 0));
        Map<String, Object> wrong = Json.obj(Json.copy(semantic)); wrong.put("cost_kind", true);
        refuse(() -> JackGeneralTargetEncoder.normalizeSemantic(wrong, 0));
        System.out.println("GENERAL-TARGET-NORMALIZATION-SHA256=" + JackModeEncoder.hash(normalized));
        System.out.println("General target wire normalization passes: cost/object/STOP, callback groups and immutable input; private rules unexecuted");
    }
    private static void refuse(Runnable action) {
        try { action.run(); } catch (RuntimeException expected) { return; }
        throw new IllegalStateException("invalid general callback was accepted");
    }
    private static void require(boolean condition, String message) { if (!condition) throw new IllegalStateException(message); }
}
