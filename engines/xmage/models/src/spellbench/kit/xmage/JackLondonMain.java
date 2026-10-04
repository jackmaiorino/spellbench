package spellbench.kit.xmage;

import mage.abilities.Ability;
import mage.abilities.Mode;
import mage.abilities.Modes;
import mage.abilities.costs.mana.ManaCost;
import mage.cards.Cards;
import mage.choices.Choice;
import mage.constants.Outcome;
import mage.constants.TurnPhase;
import mage.game.Game;
import mage.game.permanent.Permanent;
import mage.players.Player;
import mage.player.cabt.CardResolver;
import mage.player.spellbench.Warmup;
import mage.target.Target;
import mage.target.TargetAmount;
import mage.target.TargetCard;
import spellbench.kit.core.Json;
import spellbench.kit.core.Sampler;
import spellbench.kit.core.Seeds;
import spellbench.models.jack.EmbeddingCache;

import java.io.*;
import java.lang.reflect.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

/** Original private Jack London loop, with paired-policy/chooser RPC owned by Python. */
public final class JackLondonMain {
    static final String SOURCE = "b45257a66fc3914506fca4dd83461b6c8853d129b3e1f38b2d3aeba6137bd0c6";
    static final String VARIANT = "original April London loop; rerank the shrinking whole hand for each engine one-card bottom callback; original card_select head and complete sequential chooser draw per callback; named own hand only; model-error fallback refuses; native and complete games unqualified";
    private static BufferedReader input;
    private static PrintStream output;
    private static String requestId;
    private static long calls;
    private static final List<Object> rounds = new ArrayList<>();

    private static Class<?> original(String name) throws Exception {
        Class<?> result = Class.forName("spellbench.models.jack." + name);
        if (!SOURCE.equals(result.getField("SOURCE_SHA256").get(null))) throw new IllegalArgumentException("original Jack London source changed");
        return result;
    }
    private static final class Frames {
        final World world;
        final Map<String, Object> decision;
        final Map<UUID, String> permitted;
        Object state, codec;
        Map<String, Object> base;
        Class<?> candidateClass;
        Object cacheKey;
        Frames(World world, Map<String, Object> decision) throws Exception {
            this.world = world; this.decision = decision;
            permitted = JackModeEncoder.namedAliases(world, decision);
        }
        void initialize() throws Exception {
            Object currentKey = original("LondonRules").getMethod("baseCacheKey", Game.class).invoke(null, world.game);
            if (state != null && currentKey.equals(cacheKey)) return;
            cacheKey = currentKey;
            Class<?> encoder = Class.forName("spellbench.models.jack.StateSequenceBuilder");
            Game game = world.game;
            state = encoder.getMethod("buildBaseState", Game.class, TurnPhase.class, int.class, UUID.class, Map.class)
                    .invoke(null, game, game.getPhase() == null ? null : game.getPhase().getType(), 256, world.player(world.viewer), permitted);
            float[][] tokens = (float[][]) state.getClass().getField("tokens").get(state);
            int[] mask = (int[]) state.getClass().getField("mask").get(state), ids = (int[]) state.getClass().getField("tokenIds").get(state);
            if (tokens.length != 256 || mask.length != 256 || ids.length != 256) throw new IllegalArgumentException("combat base state shape changed");
            List<Object> rows = new ArrayList<>(), masks = new ArrayList<>(), tokenIds = new ArrayList<>();
            for (int i = 0; i < 256; i++) {
                if (mask[i] != 0 && mask[i] != 1 || ids[i] < 0 || ids[i] >= 65536) throw new IllegalArgumentException("combat base token or mask changed");
                rows.add(JackModeEncoder.numbers(tokens[i], 128)); masks.add(mask[i] == 1); tokenIds.add((long) ids[i]);
            }
            base = Json.map("kind", "candidates", "sequence", rows, "padding", masks, "token_ids", tokenIds);
            candidateClass = original("CandidateEncoder");
            codec = candidateClass.getConstructor(Player.class).newInstance(world.viewerPlayer());
        }
        List<Integer> rank(List<?> cards) throws Exception {
            initialize(); int count = cards.size();
            String type = "LONDON_MULLIGAN";
            if (count < 2 || count > 64 || !"card_select".equals(candidateClass.getMethod("head", String.class).invoke(null, type))) {
                throw new IllegalArgumentException("London ranking changed its original head or whole-hand shape");
            }
            List<Object> features = new ArrayList<>(), ids = new ArrayList<>(), mask = new ArrayList<>(), refs = new ArrayList<>();
            for (int i = 0; i < 64; i++) {
                int id = 0; float[] values = new float[48];
                if (i < count) {
                    mage.cards.Card card = (mage.cards.Card) cards.get(i);
                    String alias = world.uuidToId.get(card.getId());
                    if (alias == null || !permitted.containsKey(card.getId()) || !world.viewerPlayer().getHand().contains(card.getId())) {
                        throw new IllegalArgumentException("London candidate is not a named own-hand card");
                    }
                    id = (Integer) candidateClass.getMethod("candidateId", String.class, Game.class, Ability.class, Object.class)
                            .invoke(codec, type, world.game, null, card);
                    values = (float[]) candidateClass.getMethod("candidateFeatures", String.class, Game.class, Ability.class, Object.class, state.getClass())
                            .invoke(codec, type, world.game, null, card, state);
                    if (id <= 0 || id >= 65536) throw new IllegalArgumentException("London vocabulary changed");
                    refs.add(alias);
                }
                features.add(JackModeEncoder.numbers(values, 48)); ids.add((long) id); mask.add(i < count);
            }
            Map<String, Object> encoded = new LinkedHashMap<>(base);
            encoded.putAll(Json.map("head", "card_select", "candidate_features", features, "candidate_ids", ids, "candidate_mask", mask));
            long call = ++calls;
            Map<String, Object> frame = Json.map("id", requestId, "event", "choose", "call", call, "type", type,
                    "candidate_count", (long) count, "picks", (long) count, "sequential", true,
                    "candidate_refs", refs, "features", encoded, "decision_sha256", JackModeEncoder.hash(decision));
            output.println(Json.canonical(frame));
            String line = input.readLine();
            if (line == null) throw new IllegalArgumentException("London transport EOF");
            Map<String, Object> response = Json.parseObject(line);
            if (!requestId.equals(response.get("id")) || !Long.valueOf(call).equals(response.get("call")) || !Boolean.TRUE.equals(response.get("ok"))) {
                throw new IllegalArgumentException("London received a stale or failed ranking");
            }
            List<Integer> selected = new ArrayList<>(); Set<Integer> seen = new HashSet<>();
            for (Object value : Json.arr(response, "indices")) {
                if (!(value instanceof Long) || (Long) value < 0 || (Long) value >= count || !seen.add(((Long) value).intValue())) {
                    throw new IllegalArgumentException("London received an invalid or repeated original index");
                }
                selected.add(((Long) value).intValue());
            }
            if (selected.size() != count) throw new IllegalArgumentException("London lost full-hand sequential draws");
            Map<String, Object> receipt = new LinkedHashMap<>(frame);
            receipt.remove("id"); receipt.remove("event"); receipt.remove("features");
            receipt.put("indices", response.get("indices")); rounds.add(receipt);
            return selected;
        }
    }
    private static Map<String, Object> plan(Map<String, Object> record) throws Exception {
        calls = 0; rounds.clear();
        Map<String, Object> decision = Json.obj(record, "decision"), obs = Json.obj(decision, "observation"), group = Json.obj(decision, "group");
        String viewer = Json.str(obs, "viewer");
        long count = Json.num(group, "substep_count", -1L);
        if (!"pregame".equals(Json.str(obs, "phase_step")) || !viewer.equals(Json.str(decision, "acting_seat"))
                || Json.num(group, "substep_index", -1L) != 0L || count < 1 || count > 64) {
            throw new IllegalArgumentException("London needs the initial acting-viewer pregame group");
        }
        for (Object offered : Json.arr(decision, "candidates")) {
            Map<String, Object> semantic = Json.obj(Json.obj(offered), "semantic");
            if (!"order_pick".equals(Json.str(semantic, "kind")) || !"mulligan_bottom".equals(Json.str(semantic, "purpose"))
                    || semantic.get("source") != null || Json.num(semantic, "position", -1L) != 0L
                    || Json.num(semantic, "count", -1L) != count) throw new IllegalArgumentException("London actions differ from the original group");
        }
        KitContext.reset(); KitRandom.installBoot();
        List<String> names = WorldBuilder.restoreVisibleNames(obs, Json.obj(decision, "x_history"));
        KitRandom random = KitRandom.install(Seeds.unhex(Json.str(record, "world_seed")), Seeds.unhex(Json.str(record, "id_seed")));
        WorldBuilder.Spec spec = new WorldBuilder.Spec();
        spec.gameStart = Json.obj(record, "game_start"); spec.observation = obs; spec.random = random;
        spec.sample = Sampler.sample(spec.gameStart, obs, random.stream("sampler"));
        spec.mode = WorldBuilder.Mode.PREGAME; spec.history = Json.obj(decision, "x_history");
        spec.viewerFactory = seat -> new KitMad(seat, 6); spec.otherFactory = Puppet::new;
        World world = WorldBuilder.build(spec); world.flags.addAll(names);
        for (String flag : world.flags) if (flag.startsWith("unsupported:") || flag.startsWith("horizon:")) throw new IllegalArgumentException("unsupported London world: " + flag);
        Player own = world.viewerPlayer();
        if (own.getHand().size() < count || own.getHand().size() > 64) throw new IllegalArgumentException("London hand cannot satisfy the original bottom count");
        Class<?> rules = original("LondonRules"), callback = Class.forName("spellbench.models.jack.LondonRules$Picker");
        List<Object> bottomed = new ArrayList<>();
        Set<UUID> moved = new HashSet<>();
        Frames frames = new Frames(world, decision);
        for (int position = 0; position < count; position++) {
        for (UUID id : moved) frames.permitted.remove(id);
        Object picker = Proxy.newProxyInstance(callback.getClassLoader(), new Class<?>[]{callback}, (proxy, method, args) -> {
            if (!"rank".equals(method.getName()) || args == null || args.length != 1) throw new IllegalArgumentException("unexpected London ranking call");
            return frames.rank((List<?>) args[0]);
        });
        Object original = rules.getConstructor(Player.class, callback).newInstance(own, picker);
        mage.target.common.TargetCardInHand target = new mage.target.common.TargetCardInHand(new mage.filter.FilterCard());
        target.setTargetController(own.getId());
        try {
            if (!Boolean.TRUE.equals(rules.getMethod("chooseLondonMulliganCards", Target.class, Game.class).invoke(original, target, world.game))) {
                throw new IllegalArgumentException("original London selection failed");
            }
        } catch (InvocationTargetException e) { throw new IllegalArgumentException("original London callback failed", e.getCause()); }
        if (target.getTargets().size() != 1) throw new IllegalArgumentException("London original engine callback requires exactly one card");
        for (UUID id : target.getTargets()) {
            String alias = world.uuidToId.get(id);
            if (alias == null || !own.getHand().contains(id)) throw new IllegalArgumentException("London bottom target is not in own hand");
            bottomed.add(alias);
            moved.add(id);
        }
        if (!own.putCardsOnBottomOfLibrary(new mage.cards.CardsImpl(target.getTargets()), world.game, null, true)) {
            throw new IllegalArgumentException("London original engine bottom movement failed");
        }
        }
        if (bottomed.size() != count) throw new IllegalArgumentException("London target application lost bottom cards");
        return Json.map("decision_sha256", JackModeEncoder.hash(decision), "request_sha256", JackModeEncoder.hash(record),
                "bottomed", bottomed, "rounds", new ArrayList<>(rounds), "neural_calls", calls,
                "world_flags", world.flags, "variant", VARIANT);
    }
    public static void main(String[] args) throws Exception {
        if (args.length != 5) throw new IllegalArgumentException("usage: EMBEDDINGS EMBEDDINGS_SHA ENCODER_SHA CANDIDATE_SHA LONDON_RULES_SHA");
        System.setProperty("spellbench.jack.embeddingFile", args[0]);
        String[] names = {"embeddingSha256", "encoderSourceSha256", "candidateSourceSha256", "londonRulesSourceSha256"};
        for (int i = 0; i < names.length; i++) {
            if (!args[i+1].matches("[a-f0-9]{64}")) throw new IllegalArgumentException("London source pins must be SHA-256");
            System.setProperty("spellbench.jack." + names[i], args[i+1]);
        }
        original("CandidateEncoder"); original("LondonRules");
        int embeddings = EmbeddingCache.size();
        output = new PrintStream(new FileOutputStream(FileDescriptor.out), true, "UTF-8");
        System.setOut(System.err); Runner.quietLogs(); KitRandom.installBoot(); Warmup.framework(); new CardResolver().resolve("Plains");
        output.println(Json.canonical(Json.map("ready", true, "encoder", "jack-permitted-london",
                "embedding_cache_sha256", args[1], "encoder_source_sha256", args[2], "candidate_source_sha256", args[3],
                "london_rules_source_sha256", args[4], "original_callback_sha256", SOURCE, "variant", VARIANT, "embedding_count", (long) embeddings)));
        input = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        String line; long last = 0;
        while ((line = input.readLine()) != null) {
            try {
                Map<String, Object> record = Json.parseObject(line); requestId = Json.str(record, "id");
                if (requestId == null || !requestId.matches("[1-9][0-9]*") || Long.parseLong(requestId) <= last) throw new IllegalArgumentException("stale Jack London request");
                last = Long.parseLong(requestId);
                for (String name : new String[]{"world_seed", "id_seed"}) if (!Json.str(record, name).matches("[a-f0-9]{64}")) throw new IllegalArgumentException("London seeds must be 32-byte hex");
                output.println(Json.canonical(Json.map("id", requestId, "event", "result", "ok", true, "result", plan(record))));
            } catch (Exception | LinkageError e) {
                output.println(Json.canonical(Json.map("id", requestId, "event", "result", "ok", false, "error", e.toString()))); break;
            }
        }
    }
}
