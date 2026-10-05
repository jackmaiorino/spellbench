package spellbench.kit.xmage;

import mage.abilities.AbilitiesImpl;
import mage.abilities.Ability;
import mage.abilities.ActivatedAbility;
import mage.abilities.common.PassAbility;
import mage.cards.Card;
import mage.constants.AbilityType;
import mage.constants.RangeOfInfluence;
import mage.game.Game;
import mage.game.permanent.Battlefield;
import mage.player.ai.ComputerPlayer;
import mage.players.Player;
import mage.abilities.costs.mana.ManaCostsImpl;
import mage.target.Targets;
import spellbench.kit.core.Json;
import spellbench.kit.core.ObsIndex;

import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Proxy;
import java.util.*;

/** Exact public binding checks on metadata only. No native game, database or model. */
public final class JackPriorityBindingCheck {
    private static void require(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
    private static void refuse(Runnable action, String message) {
        try { action.run(); } catch (IllegalArgumentException expected) { return; }
        throw new AssertionError(message);
    }
    @SuppressWarnings("unchecked")
    private static <T> T proxy(Class<T> type, InvocationHandler handler) {
        return (T) Proxy.newProxyInstance(type.getClassLoader(), new Class<?>[]{type}, (object, method, args) -> {
            if ("toString".equals(method.getName())) return "metadata " + type.getSimpleName();
            if ("hashCode".equals(method.getName())) return System.identityHashCode(object);
            if ("equals".equals(method.getName())) return object == args[0];
            return handler.invoke(object, method, args);
        });
    }
    private static ActivatedAbility ability(UUID source, long identity, AbilityType type) {
        return proxy(ActivatedAbility.class, (object, method, args) -> {
            switch (method.getName()) {
                case "getSourceId": return source;
                case "getId": case "getOriginalId": return new UUID(0, identity);
                case "getAbilityType": return type;
                case "getRule": return "test ability";
                case "getTargets": return new Targets();
                case "isUsesStack": return type != AbilityType.ACTIVATED_MANA;
                case "getManaCostsToPay": return new ManaCostsImpl<>();
                default: throw new AssertionError("unexpected ability access: " + method.getName());
            }
        });
    }
    private static Card card(ActivatedAbility ability) {
        AbilitiesImpl<Ability> abilities = new AbilitiesImpl<>(); abilities.add(ability);
        return proxy(Card.class, (object, method, args) -> {
            switch (method.getName()) {
                case "getAbilities": return abilities;
                case "getSecondCardFace": return null;
                case "getMainCard": return object;
                case "getName": return "Forest";
                default: throw new AssertionError("unexpected card access: " + method.getName());
            }
        });
    }
    public static void main(String[] args) throws Exception {
        Map<UUID, Card> cards = new LinkedHashMap<>();
        Player viewer = new ComputerPlayer("metadata viewer", RangeOfInfluence.ALL);
        mage.players.Players players = new mage.players.Players(); players.addPlayer(viewer);
        Battlefield battlefield = new Battlefield();
        Game game = proxy(Game.class, (object, method, values) -> {
            if ("getPermanent".equals(method.getName())) return null;
            if ("getCard".equals(method.getName()) || "getObject".equals(method.getName())) return cards.get(values[0]);
            if ("getPlayer".equals(method.getName())) return players.get(values[0]);
            if ("getPlayers".equals(method.getName())) return players;
            if ("getBattlefield".equals(method.getName())) return battlefield;
            throw new AssertionError("unexpected game access: " + method.getName());
        });
        World world = new World(game, "p0", 0, null);
        world.seatPlayer.put("p0", viewer.getId());
        Map<String, Object> start = Json.map("seat", "p0", "agent_seed", 7L,
                "engine_profile", Json.map("decision_kinds", Arrays.asList("activate_mana_ability")));
        List<ActivatedAbility> original = new ArrayList<>(); original.add(new PassAbility());
        List<Object> refs = new ArrayList<>();
        for (int i = 0; i < 70; i++) {
            UUID source = new UUID(0, i+1); String alias = "card-" + i;
            ActivatedAbility action = ability(source, i+100, i < 2 ? AbilityType.ACTIVATED_MANA : AbilityType.PLAY_LAND);
            cards.put(source, card(action)); world.bind(alias, source); original.add(action);
            refs.add(Json.map("object_id", alias, "card_name", "Forest", "owner_seat", "p0", "controller_seat", "p0", "zone", "battlefield"));
        }
        Map<String, Object> obs = Json.map("viewer", "p0", "players", Arrays.asList(Json.map("hand", Collections.emptyList(),
                "battlefield", refs, "graveyard", Collections.emptyList(), "exile", Collections.emptyList(), "command", Collections.emptyList())),
                "stack", Collections.emptyList(), "known", Collections.emptyList());
        ObsIndex index = new ObsIndex(obs); List<Object> offered = new ArrayList<>();
        offered.add(Json.map("candidate_id", 1000L, "semantic", Json.map("kind", "pass")));
        for (int i = 1; i < original.size(); i++) {
            ActivatedAbility action = original.get(i);
            Map<String, Object> semantic = i <= 2 ? Mapping.priorityManaSemantic(world, game, action, index)
                    : Mapping.prioritySemantic(world, game, action, index);
            offered.add(Json.map("candidate_id", (long)i, "semantic", semantic));
        }
        Collections.reverse(offered);
        Map<String, Object> decision = Json.map("acting_seat", "p0", "seat_step", 3L,
                "context", Json.map("kind", "priority"), "observation", obs, "candidates", offered);
        JackPriorityBinding.Plan plan = JackPriorityBinding.bind(start, decision, world, original);
        require(plan.abilities.size() == 64 && plan.abilities.get(63) == original.get(63), "original 64-slot cap changed");
        require(plan.select(1, decision).get("candidate_id").equals(1L), "offered order replaced original order");
        require(plan.select(63, decision).get("candidate_id").equals(63L), "original last slot changed");
        List<Object> independent = plan.references(); Json.obj(independent.get(1)).put("candidate_id", 70L);
        require(plan.select(1, decision).get("candidate_id").equals(1L), "returned reference mutated plan");
        try { plan.abilities.clear(); throw new AssertionError("mutable action prefix"); }
        catch (UnsupportedOperationException expected) { }
        Map<String, Object> stale = Json.obj(Json.copy(decision)); stale.put("seat_step", 4L);
        refuse(() -> plan.select(1, stale), "stale decision selected");
        refuse(() -> plan.select(64, decision), "slot beyond cap selected");

        List<ActivatedAbility> swapped = Arrays.asList(original.get(0), original.get(2), original.get(1));
        JackPriorityBinding.Plan swappedPlan = JackPriorityBinding.bind(start, decision, world, swapped);
        require(swappedPlan.select(1, decision).get("candidate_id").equals(2L)
                && swappedPlan.select(2, decision).get("candidate_id").equals(1L), "equal-text mana source order lost");
        world.uuidToId.remove(original.get(70).getSourceId());
        require(JackPriorityBinding.bind(start, decision, world, original).abilities.size() == 64, "unselected tail was revalidated");
        world.bind("card-69", original.get(70).getSourceId());

        Map<String, Object> reassigned = Json.obj(Json.copy(decision));
        List<Object> reordered = Json.arr(reassigned, "candidates"); Collections.reverse(reordered);
        for (Object value : reordered) { Map<String, Object> candidate = Json.obj(value);
            candidate.put("candidate_id", (Long)candidate.get("candidate_id") + 2000L); }
        require(JackPriorityBinding.bind(start, reassigned, world, swapped).select(1, reassigned).get("candidate_id").equals(2002L),
                "reassigned public IDs changed original slots");

        for (String failure : Arrays.asList("missing", "wrong-index", "duplicate-id", "duplicate-semantic", "wrong-viewer")) {
            Map<String, Object> changed = Json.obj(Json.copy(decision)); List<Object> choices = Json.arr(changed, "candidates");
            if (failure.equals("wrong-viewer")) Json.obj(changed, "observation").put("viewer", "p1");
            else if (failure.equals("duplicate-id")) Json.obj(choices.get(0)).put("candidate_id", 1L);
            else if (failure.equals("duplicate-semantic")) choices.add(Json.map("candidate_id", 9999L, "semantic", Json.copy(Json.obj(Json.obj(choices.get(0)), "semantic"))));
            else for (Iterator<Object> it = choices.iterator(); it.hasNext();) {
                Map<String, Object> c = Json.obj(it.next());
                if (c.get("candidate_id").equals(1L)) {
                    if (failure.equals("missing")) it.remove(); else Json.obj(c, "semantic").put("ability_index", 1L);
                }
            }
            refuse(() -> JackPriorityBinding.bind(start, changed, world, original), "accepted " + failure);
        }
        Map<String, Object> undeclared = Json.map("seat", "p0");
        refuse(() -> JackPriorityBinding.bind(undeclared, decision, world, Collections.singletonList(original.get(0))),
                "undeclared offered mana accepted even on pass-only path");
        world.flags.add("horizon:incomplete");
        refuse(() -> JackPriorityBinding.bind(start, decision, world, original), "incomplete world accepted"); world.flags.clear();
        world.uuidToId.remove(original.get(1).getSourceId());
        refuse(() -> JackPriorityBinding.bind(start, decision, world, original), "unobserved source accepted");
        world.bind("card-0", original.get(1).getSourceId());
        Json.obj(refs.get(0)).put("card_name", "");
        refuse(() -> JackPriorityBinding.bind(start, decision, world, original), "unnamed source accepted");
        Json.obj(refs.get(0)).put("card_name", "Forest");

        ActivatedAbility unmatched = ability(original.get(1).getSourceId(), 99999L, AbilityType.ACTIVATED_NONMANA);
        Map<String, Object> synthetic = Json.obj(Json.copy(decision));
        Json.arr(synthetic, "candidates").add(Json.map("candidate_id", 5000L, "semantic", Mapping.prioritySemantic(world, game, unmatched, index)));
        refuse(() -> JackPriorityBinding.bind(start, synthetic, world, Arrays.asList(original.get(0), unmatched)),
                "legacy synthetic Oracle index became an original action");

        Map<String, Object> pins = Json.map("embedding_cache_sha256", repeat('a'), "encoder_source_sha256", repeat('b'),
                "candidate_source_sha256", repeat('c'), "priority_rules_source_sha256", repeat('d'));
        Map<String, Object> frame = JackPriorityBinding.encode(start, decision, world, Collections.singletonList(original.get(0)), null, pins);
        require(frame.get("features") == null && frame.get("candidate_count").equals(1L)
                && frame.get("game_start_sha256").equals(JackPriorityBinding.hash(start))
                && frame.get("full_priority_player_qualified").equals(false), "pass-only frame identity changed");
        if (args.length > 0 && args[0].equals("--staged-codec")) {
            // This optional local check uses the actual private codec, without model inference.
            Class<?> stateType = Class.forName("spellbench.models.jack.StateSequenceBuilder$SequenceOutput");
            List<float[]> tokens = new ArrayList<>(); List<Integer> masks = new ArrayList<>(), ids = new ArrayList<>();
            for (int i = 0; i < 256; i++) { float[] token = new float[128]; token[9] = i == 0 ? 0.75f : 0;
                tokens.add(token); masks.add(i == 0 ? 0 : 1); ids.add(i == 0 ? 27 : 0); }
            Object state = stateType.getConstructor(List.class, List.class, List.class).newInstance(tokens, masks, ids);
            Map<String, Object> encoded = JackPriorityBinding.encode(start, decision, world, swapped, state, pins);
            Map<String, Object> features = Json.obj(encoded, "features");
            require(Json.arr(Json.arr(features, "sequence").get(0)).get(9).equals(0.75)
                    && Json.arr(features, "padding").get(0).equals(false)
                    && Json.arr(features, "padding").get(1).equals(true), "original float or mask direction changed");
            Class<?> codec = Class.forName("spellbench.models.jack.CandidateEncoder");
            Object encoder = codec.getConstructor(Player.class).newInstance(viewer);
            for (int slot = 0; slot < swapped.size(); slot++) {
                ActivatedAbility action = swapped.get(slot);
                int id = (Integer)codec.getMethod("priorityId", Game.class, Ability.class).invoke(encoder, game, action);
                float[] vector = (float[])codec.getMethod("priorityFeatures", Game.class, Ability.class, stateType).invoke(encoder, game, action, state);
                require(Json.arr(features, "candidate_ids").get(slot).equals((long)id), "original codec action ID changed");
                List<Object> row = Json.arr(Json.arr(features, "candidate_features").get(slot));
                for (int column = 0; column < 48; column++) require(row.get(column).equals((double)vector[column]), "original feature changed");
            }
            for (int slot = swapped.size(); slot < 64; slot++) {
                require(Json.arr(features, "candidate_ids").get(slot).equals(0L)
                        && Json.arr(features, "candidate_mask").get(slot).equals(false), "candidate padding changed");
            }
            if (args.length > 1) java.nio.file.Files.write(java.nio.file.Paths.get(args[1]),
                    Json.canonical(Json.map("start", start, "decision", decision, "frame", encoded)).getBytes(java.nio.charset.StandardCharsets.UTF_8));
            System.out.println("actual original private candidate codec and cached state serialization: PASS");
        }
        System.out.println("original priority exact binding: PASS; 64-slot cap, source order, public IDs, stale/refusal cases and no-inference pass");
    }
    private static String repeat(char c) { char[] chars = new char[64]; Arrays.fill(chars, c); return new String(chars); }
}
