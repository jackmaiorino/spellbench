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

/** Original private Jack combat loops, with paired-policy/chooser RPC owned by Python. */
public final class JackCombatMain {
    static final String SOURCE = "b45257a66fc3914506fca4dd83461b6c8853d129b3e1f38b2d3aeba6137bd0c6";
    static final String VARIANT = "original April attacker pool and DONE-last sequential selection; separate defender choice; "
            + "original descending-power attacker block order, filtered blocker pool and removal after declaration; "
            + "one cached permitted base state per callback; original attack/block heads and game-owned chooser; "
            + "refusal instead of model-error fallback; nested combat callbacks and complete games unqualified";
    private static BufferedReader input;
    private static PrintStream output;
    private static String requestId;
    private static long calls;
    private static final List<Object> rounds = new ArrayList<>();

    static final class CombatPlayer extends KitMad {
        boolean live;
        CombatPlayer(String seat) { super(seat, 6); }
        private CombatPlayer(CombatPlayer player) { super(player); live = player.live; }
        @Override public CombatPlayer copy() { return new CombatPlayer(this); }
        private void nested() { if (live) throw new IllegalArgumentException("unqualified nested Jack combat callback"); }
        @Override public boolean priority(Game game) { nested(); return super.priority(game); }
        @Override public void selectAttackers(Game game, UUID player) { nested(); super.selectAttackers(game, player); }
        @Override public void selectBlockers(Ability source, Game game, UUID player) { nested(); super.selectBlockers(source, game, player); }
        @Override protected boolean playManaHandling(Ability ability, ManaCost unpaid, Game game) {
            nested(); return super.playManaHandling(ability, unpaid, game);
        }
        @Override public boolean choose(Outcome outcome, Target target, Ability source, Game game, Map<String, Serializable> options) {
            nested(); return super.choose(outcome, target, source, game, options);
        }
        @Override public boolean chooseUse(Outcome outcome, String message, String second, String yes, String no, Ability source, Game game) {
            nested(); return super.chooseUse(outcome, message, second, yes, no, source, game);
        }
        @Override public boolean chooseTarget(Outcome outcome, Target target, Ability source, Game game) {
            nested(); return super.chooseTarget(outcome, target, source, game);
        }
        @Override public boolean chooseTarget(Outcome outcome, Cards cards, TargetCard target, Ability source, Game game) {
            nested(); return super.chooseTarget(outcome, cards, target, source, game);
        }
        @Override public boolean choose(Outcome outcome, Cards cards, TargetCard target, Ability source, Game game) {
            nested(); return super.choose(outcome, cards, target, source, game);
        }
        @Override public boolean chooseTargetAmount(Outcome outcome, TargetAmount target, Ability source, Game game) {
            nested(); return super.chooseTargetAmount(outcome, target, source, game);
        }
        @Override public boolean choose(Outcome outcome, Choice choice, Game game) {
            nested(); return super.choose(outcome, choice, game);
        }
        @Override public Mode chooseMode(Modes modes, Ability source, Game game) {
            nested(); return super.chooseMode(modes, source, game);
        }
        @Override public int announceX(int min, int max, String message, Game game, Ability source, boolean mana) {
            nested(); return super.announceX(min, max, message, game, source, mana);
        }
    }
    private static Class<?> original(String name) throws Exception {
        Class<?> result = Class.forName("spellbench.models.jack." + name);
        if (!SOURCE.equals(result.getField("SOURCE_SHA256").get(null))) throw new IllegalArgumentException("original Jack combat source changed");
        return result;
    }
    private static Object reference(World world, Object object) {
        if (object == null) return null;
        UUID id = object instanceof Permanent ? ((Permanent) object).getId() : (UUID) object;
        for (String seat : new String[]{"p0", "p1"}) if (id.equals(world.player(seat))) return Json.map("player", seat);
        String alias = world.uuidToId.get(id);
        if (alias == null || world.game.getPermanent(id) == null) {
            throw new IllegalArgumentException("combat candidate is not a permitted battlefield object");
        }
        return Json.map("object_id", alias);
    }
    private static final class Frames {
        final World world;
        final Map<String, Object> decision;
        final Map<UUID, String> permitted;
        Object state, codec;
        Map<String, Object> base;
        Class<?> candidateClass;
        Frames(World world, Map<String, Object> decision) throws Exception {
            this.world = world; this.decision = decision;
            permitted = JackModeEncoder.namedAliases(world, decision);
        }
        void initialize() throws Exception {
            if (state != null) return;
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
        @SuppressWarnings("unchecked")
        List<Integer> choose(String type, List<?> candidates, int picks, boolean sequential) throws Exception {
            initialize();
            int count = candidates.size();
            String expectedHead = "DECLARE_BLOCKS".equals(type) ? "block" : "attack";
            if (!("DECLARE_ATTACKS".equals(type) || "DECLARE_ATTACK_TARGET".equals(type) || "DECLARE_BLOCKS".equals(type))
                    || count < 1 || count > 64 || picks != (sequential ? count : 1)
                    || sequential != !"DECLARE_ATTACK_TARGET".equals(type)
                    || !expectedHead.equals(candidateClass.getMethod("head", String.class).invoke(null, type))) {
                throw new IllegalArgumentException("original combat round changed its head or selection shape");
            }
            List<Object> features = new ArrayList<>(), ids = new ArrayList<>(), mask = new ArrayList<>(), refs = new ArrayList<>();
            for (int i = 0; i < 64; i++) {
                int id = 0; float[] values = new float[48];
                if (i < count) {
                    Object candidate = candidates.get(i);
                    Permanent creature = (Permanent) candidate.getClass().getField("creature").get(candidate);
                    Object context = candidate.getClass().getField("context").get(candidate);
                    if (creature != null && (!permitted.containsKey(creature.getId()) || !creature.getControllerId().equals(world.player(world.viewer)))
                            || context instanceof Permanent && !permitted.containsKey(((Permanent) context).getId())
                            || context instanceof UUID && !world.player("p0").equals(context) && !world.player("p1").equals(context) && !permitted.containsKey((UUID) context)) {
                        throw new IllegalArgumentException("original combat candidate is not named and permitted");
                    }
                    Object encoded = candidateClass.getMethod("combatCandidate", Permanent.class, Object.class).invoke(null, creature, context);
                    id = (Integer) candidateClass.getMethod("candidateId", String.class, Game.class, Ability.class, Object.class)
                            .invoke(codec, type, world.game, null, encoded);
                    values = (float[]) candidateClass.getMethod("candidateFeatures", String.class, Game.class, Ability.class, Object.class, state.getClass())
                            .invoke(codec, type, world.game, null, encoded, state);
                    if (id <= 0 || id >= 65536) throw new IllegalArgumentException("combat candidate vocabulary changed");
                    Object c = reference(world, creature);
                    refs.add(Json.map("creature", c == null ? null : Json.str(Json.obj(c), "object_id"), "context", reference(world, context)));
                }
                features.add(JackModeEncoder.numbers(values, 48)); ids.add((long) id); mask.add(i < count);
            }
            Map<String, Object> encoded = new LinkedHashMap<>(base);
            encoded.putAll(Json.map("head", expectedHead, "candidate_features", features, "candidate_ids", ids, "candidate_mask", mask));
            long call = ++calls;
            Map<String, Object> frame = Json.map("id", requestId, "event", "choose", "call", call, "type", type,
                    "candidate_count", (long) count, "picks", (long) picks, "sequential", sequential,
                    "candidate_refs", refs, "features", encoded, "decision_sha256", JackModeEncoder.hash(decision));
            output.println(Json.canonical(frame));
            String line = input.readLine();
            if (line == null) throw new IllegalArgumentException("Jack combat transport EOF");
            Map<String, Object> response = Json.parseObject(line);
            if (!requestId.equals(response.get("id")) || !Long.valueOf(call).equals(response.get("call")) || !Boolean.TRUE.equals(response.get("ok"))) {
                throw new IllegalArgumentException("Jack combat received a stale or failed choice");
            }
            List<Integer> selected = new ArrayList<>(); Set<Integer> seen = new HashSet<>();
            for (Object value : Json.arr(response, "indices")) {
                if (!(value instanceof Long) || (Long) value < 0 || (Long) value >= count || !seen.add(((Long) value).intValue())) {
                    throw new IllegalArgumentException("Jack combat received an invalid or repeated original index");
                }
                selected.add(((Long) value).intValue());
            }
            if (selected.size() != picks) throw new IllegalArgumentException("Jack combat lost sequential choices after DONE");
            Map<String, Object> receipt = new LinkedHashMap<>(frame);
            receipt.remove("id"); receipt.remove("event"); receipt.remove("features");
            receipt.put("indices", response.get("indices")); rounds.add(receipt);
            return selected;
        }
    }
    private static Map<String, Object> plan(Map<String, Object> record) throws Exception {
        calls = 0; rounds.clear();
        Map<String, Object> decision = Json.obj(record, "decision"), obs = Json.obj(decision, "observation");
        String family = null;
        for (Object offered : Json.arr(decision, "candidates")) {
            String kind = Json.str(Json.obj(Json.obj(offered), "semantic"), "kind");
            if (!("declare_attack".equals(kind) || "declare_block".equals(kind)) || family != null && !family.equals(kind)) {
                throw new IllegalArgumentException("Jack combat needs one declaration family");
            }
            family = kind;
        }
        if (family == null || Json.num(Json.obj(decision, "group"), "substep_index", -1L) != 0L
                || !Json.str(decision, "acting_seat").equals(Json.str(obs, "viewer"))) {
            throw new IllegalArgumentException("Jack combat needs its initial acting-viewer declaration group");
        }
        boolean attack = "declare_attack".equals(family);
        KitContext.reset(); KitRandom.installBoot();
        List<String> names = WorldBuilder.restoreVisibleNames(obs, Json.obj(decision, "x_history"));
        KitRandom random = KitRandom.install(Seeds.unhex(Json.str(record, "world_seed")), Seeds.unhex(Json.str(record, "id_seed")));
        CombatPlayer[] player = new CombatPlayer[2];
        WorldBuilder.Spec spec = new WorldBuilder.Spec();
        spec.gameStart = Json.obj(record, "game_start"); spec.observation = obs; spec.random = random;
        spec.sample = Sampler.sample(spec.gameStart, obs, random.stream("sampler"));
        spec.mode = attack ? WorldBuilder.Mode.ATTACK : WorldBuilder.Mode.BLOCK;
        spec.history = Json.obj(decision, "x_history"); spec.viewerFactory = seat -> player[0] = new CombatPlayer(seat);
        spec.otherFactory = seat -> player[1] = new CombatPlayer(seat);
        World world = WorldBuilder.build(spec); world.flags.addAll(names);
        for (String flag : world.flags) if (flag.startsWith("unsupported:") || flag.startsWith("horizon:")) throw new IllegalArgumentException("unsupported Jack combat world: " + flag);
        if (world.game.isSimulation()) throw new IllegalArgumentException("original Jack combat refuses simulation roots");
        Frames frames = new Frames(world, decision);
        Class<?> rules = original("CombatRules"), callback = Class.forName("spellbench.models.jack.CombatRules$Picker");
        Object picker = Proxy.newProxyInstance(callback.getClassLoader(), new Class<?>[]{callback}, (proxy, method, args) -> {
            if (!"choose".equals(method.getName()) || args == null || args.length != 4) throw new IllegalArgumentException("unexpected original combat picker call");
            return frames.choose((String) args[0], (List<?>) args[1], (Integer) args[2], (Boolean) args[3]);
        });
        Object original = rules.getConstructor(Player.class, callback).newInstance(player[0], picker);
        player[0].live = player[1].live = true;
        try {
            if (attack) rules.getMethod("selectAttackers", Game.class, UUID.class).invoke(original, world.game, player[0].getId());
            else rules.getMethod("selectBlockers", Ability.class, Game.class, UUID.class).invoke(original, null, world.game, player[0].getId());
        } catch (InvocationTargetException e) { throw new IllegalArgumentException("original Jack combat failed", e.getCause()); }
        finally { player[0].live = player[1].live = false; }
        return Json.map("decision_sha256", JackModeEncoder.hash(decision), "combat", attack ? "attack" : "block",
                "pairs", Runner.combatPairs(world, world.game, attack), "rounds", new ArrayList<>(rounds), "neural_calls", calls,
                "world_flags", world.flags, "variant", VARIANT, "request_sha256", JackModeEncoder.hash(record));
    }
    public static void main(String[] args) throws Exception {
        if (args.length != 5) throw new IllegalArgumentException("usage: EMBEDDINGS EMBEDDINGS_SHA ENCODER_SHA CANDIDATE_SHA COMBAT_RULES_SHA");
        System.setProperty("spellbench.jack.embeddingFile", args[0]);
        String[] names = {"embeddingSha256", "encoderSourceSha256", "candidateSourceSha256", "combatRulesSourceSha256"};
        for (int i = 0; i < names.length; i++) {
            if (!args[i+1].matches("[a-f0-9]{64}")) throw new IllegalArgumentException("combat source pins must be SHA-256");
            System.setProperty("spellbench.jack." + names[i], args[i+1]);
        }
        original("CandidateEncoder"); original("CombatRules");
        int embeddings = EmbeddingCache.size();
        output = new PrintStream(new FileOutputStream(FileDescriptor.out), true, "UTF-8");
        System.setOut(System.err); Runner.quietLogs(); KitRandom.installBoot(); Warmup.framework(); new CardResolver().resolve("Plains");
        output.println(Json.canonical(Json.map("ready", true, "encoder", "jack-permitted-combat",
                "embedding_cache_sha256", args[1], "encoder_source_sha256", args[2], "candidate_source_sha256", args[3],
                "combat_rules_source_sha256", args[4], "original_callback_sha256", SOURCE, "variant", VARIANT, "embedding_count", (long) embeddings)));
        input = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        String line; long last = 0;
        while ((line = input.readLine()) != null) {
            try {
                Map<String, Object> record = Json.parseObject(line); requestId = Json.str(record, "id");
                if (requestId == null || !requestId.matches("[1-9][0-9]*") || Long.parseLong(requestId) <= last) throw new IllegalArgumentException("stale Jack combat request");
                last = Long.parseLong(requestId);
                for (String name : new String[]{"world_seed", "id_seed"}) if (!Json.str(record, name).matches("[a-f0-9]{64}")) throw new IllegalArgumentException("combat seeds must be 32-byte hex");
                output.println(Json.canonical(Json.map("id", requestId, "event", "result", "ok", true, "result", plan(record))));
            } catch (Exception | LinkageError e) {
                output.println(Json.canonical(Json.map("id", requestId, "event", "result", "ok", false, "error", e.toString()))); break;
            }
        }
    }
}
