package spellbench.kit.xmage;

import mage.player.cabt.CardResolver;
import mage.player.ai.encoder.ActionEncoder;
import mage.player.spellbench.Warmup;
import spellbench.kit.core.Json;
import spellbench.kit.core.ObsCompare;
import spellbench.kit.core.Sampler;
import spellbench.models.exp1.GameAccess;
import spellbench.models.exp1.RemoteModelEvaluator;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.List;
import java.util.Map;

/** Reproduce the saved Immolator callback, preserving the full public comparison. */
public final class PublicReplayEffectsCheck {
    private static final String IMMOLATOR = "o-a61e43fc8571f472";
    private static final String SAILOR = "o-b4f1ddc92ffccee7";
    private static final class ReachedOriginalInference extends Error { }

    private static void require(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }

    private static Map<String, Object> anchor(Map<String, Object> record) {
        return Json.obj(Json.obj(record, "anchor"), "decision");
    }

    private static World build(Map<String, Object> record) {
        Map<String, Object> decision = anchor(record);
        KitContext.reset(); GameAccess.reset(); KitRandom.installBoot();
        KitRandom random = KitRandom.install(new byte[32], new byte[32]);
        WorldBuilder.Spec spec = new WorldBuilder.Spec();
        spec.gameStart = Json.obj(record, "game_start");
        spec.observation = Json.obj(Json.copy(decision.get("observation")));
        spec.history = Json.obj(decision, "x_history");
        WorldBuilder.restoreVisibleNames(spec.observation, spec.history);
        spec.random = random;
        spec.sample = Sampler.sample(spec.gameStart, spec.observation, random.stream("sampler"));
        spec.viewerFactory = Puppet::new; spec.otherFactory = Puppet::new;
        return WorldBuilder.build(spec);
    }

    private static void callback(Map<String, Object> record, boolean expected) {
        try {
            ModelReplay.run(record, new RemoteModelEvaluator(features -> { throw new ReachedOriginalInference(); }), 2);
            throw new AssertionError("callback returned without original inference");
        } catch (ReachedOriginalInference success) {
            require(expected, "missing evidence reached inference");
        } catch (IllegalArgumentException failure) {
            require(!expected && failure.getMessage().startsWith("callback replay observation differs:"),
                    "unexpected replay refusal: " + failure);
        }
    }

    private static void refused(Map<String, Object> record) {
        try { build(record); throw new AssertionError("contradictory effect evidence was accepted"); }
        catch (IllegalArgumentException expected) {
            require(expected.getMessage().startsWith("public effect replay:"), "unexpected refusal: " + expected);
        }
    }

    public static void main(String[] args) throws Exception {
        require(ActionEncoder.vocabLoaded() && ActionEncoder.ACTION_DIM == 1024, "pinned Exp1 action vocabulary is required");
        Runner.quietLogs(); KitRandom.installBoot(); Warmup.framework();
        new CardResolver().resolve("Plains");
        Map<String, Object> fixture = Json.parseObject(new String(Files.readAllBytes(Paths.get(args[0])), StandardCharsets.UTF_8));
        Map<String, Object> record = Json.obj(fixture, "record");
        Map<String, Object> missing = Json.obj(Json.copy(record));
        Json.obj(anchor(missing), "x_history").remove("public_effects");
        callback(missing, false);
        World world = build(record);
        Map<String, Object> observation = Json.obj(anchor(record), "observation");
        require(ObsCompare.diff(observation, RoundTrip.project(world, RoundTrip.flagsFrom(anchor(record)),
                Json.str(observation, "priority_seat"), Json.arr(observation, "known")), 8).isEmpty(),
                "anchor public observation differs");
        require(world.game.getPermanent(world.idToUuid.get(IMMOLATOR)).getPower().getValue() == 3,
                "prowess was not restored");
        require(world.game.getPermanent(world.idToUuid.get(SAILOR)).getPower().getValue() == 0,
                "Fleeting Distraction was not restored");
        require("world:play".equals(world.random.idScope()), "restoration changed the play ID scope");
        world.game.getState().removeEotEffects(world.game);
        world.game.applyEffects();
        require(world.game.getPermanent(world.idToUuid.get(IMMOLATOR)).getPower().getValue() == 2
                && world.game.getPermanent(world.idToUuid.get(SAILOR)).getPower().getValue() == 1,
                "native end-of-turn cleanup did not expire both modifiers");
        callback(record, true);

        Map<String, Object> duplicate = Json.obj(Json.copy(record));
        List<Object> effects = Json.arr(Json.obj(anchor(duplicate), "x_history"), "public_effects");
        effects.add(Json.copy(effects.get(0)));
        refused(duplicate);
        Map<String, Object> contradicted = Json.obj(Json.copy(record));
        Map<String, Object> witness = Json.obj(Json.arr(Json.obj(anchor(contradicted), "x_history"), "public_effects").get(0));
        Json.obj(Json.obj(witness, "after"), "characteristics").put("power", 100L);
        refused(contradicted);
        Map<String, Object> stale = Json.obj(Json.copy(record));
        Json.obj(anchor(stale), "observation").put("turn", 10L);
        refused(stale);
        Map<String, Object> expired = Json.obj(Json.copy(record));
        Map<String, Object> expiredObs = Json.obj(anchor(expired), "observation");
        expiredObs.put("phase_step", "cleanup");
        for (Object player : Json.arr(expiredObs, "players")) {
            for (Object item : Json.arr(Json.obj(player), "battlefield")) {
                Map<String, Object> card = Json.obj(item), ch = Json.obj(card, "characteristics");
                if (IMMOLATOR.equals(Json.str(card, "object_id"))) { ch.put("power", 2L); ch.put("toughness", 2L); }
                if (SAILOR.equals(Json.str(card, "object_id"))) ch.put("power", 1L);
            }
        }
        refused(expired);
        System.out.println("public temporary effects, native expiry, full saved callback comparison and refusals: PASS");
    }
}
