package spellbench.kit.xmage;

import mage.abilities.keyword.KickerAbility;
import mage.constants.Zone;
import mage.game.permanent.Permanent;
import mage.game.permanent.PermanentToken;
import mage.game.stack.Spell;
import mage.game.stack.StackAbility;
import mage.game.stack.StackObject;
import mage.player.spellbench.observe.KitBridge;
import spellbench.kit.core.Json;
import spellbench.kit.core.Sampler;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * Rebuild public stack objects the kit used to refuse (optional-cost spells, a reflexive trigger) and resolve them,
 * and rebuild tokens as the pool's classes.
 */
public final class PublicStackRebuildCheck {
    private static void require(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }

    private static World build(Map<String, Object> fixture, Map<String, Object> history) {
        KitContext.reset();
        KitRandom.installBoot();
        KitRandom random = KitRandom.install(new byte[32], new byte[32]);
        WorldBuilder.Spec spec = new WorldBuilder.Spec();
        spec.gameStart = Json.obj(Json.obj(Json.copy(fixture)), "game_start");
        spec.observation = Json.obj(Json.obj(Json.copy(fixture)), "observation");
        spec.random = random;
        spec.sample = Sampler.sample(spec.gameStart, spec.observation, random.stream("sampler"));
        spec.mode = WorldBuilder.Mode.PRIORITY;
        spec.history = history;
        spec.viewerFactory = Puppet::new;
        spec.otherFactory = Puppet::new;
        return WorldBuilder.build(spec);
    }

    private static Map<String, Object> cast(Map<String, Object> fixture, String name, Map<String, Object> fact) {
        for (Object o : Json.arr(Json.obj(fixture, "observation"), "stack")) {
            Map<String, Object> e = Json.obj(o);
            if (name.equals(Json.str(e, "card_name"))) {
                return Json.map("stack_casts", Json.map(Json.str(e, "object_id"), fact));
            }
        }
        throw new AssertionError("fixture has no " + name);
    }

    private static boolean searched(World world) {
        for (String flag : world.flags) {
            if (flag.startsWith("horizon:") || flag.startsWith("unsupported:")) return false;
        }
        return true;
    }

    private static Spell spell(World world, String name) {
        for (StackObject entry : world.game.getStack()) {
            if (entry instanceof Spell && entry.getName().equals(name)) return (Spell) entry;
        }
        throw new AssertionError("rebuilt stack has no " + name);
    }

    private static void thinkTwice(Map<String, Object> fixture) {
        World unknown = build(fixture, null);
        require(!searched(unknown) && unknown.flags.contains("approximate:optional_cost_state"),
                "a flashback spell without cast history was searched");
        for (String method : new String[] {"normal", "flashback"}) {
            World world = build(fixture, cast(fixture, "Think Twice", Json.map("method", method)));
            require(searched(world) && world.flags.contains("history:stack_cast"), method + " cast stayed unsearched");
            Spell spell = spell(world, "Think Twice");
            boolean flashback = "flashback".equals(method);
            require(spell.getFromZone() == (flashback ? Zone.GRAVEYARD : Zone.HAND), method + " spell has the wrong origin");
            UUID card = spell.getCard().getId();
            require(spell.resolve(world.game), method + " Think Twice did not resolve");
            Zone after = world.game.getState().getZone(card);
            require(after == (flashback ? Zone.EXILED : Zone.GRAVEYARD), method + " Think Twice went to " + after);
        }
        World wrong = build(fixture, cast(fixture, "Think Twice", Json.map("method", "plot")));
        require(!searched(wrong), "an unsupported cast method was searched");
    }

    private static void burstLightning(Map<String, Object> fixture) {
        require(!searched(build(fixture, null)), "a kicker spell without cast history was searched");
        require(!searched(build(fixture, cast(fixture, "Burst Lightning", Json.map("method", "normal")))),
                "a kicker spell without its payment count was searched");
        for (long kicked = 0; kicked <= 1; kicked++) {
            World world = build(fixture, cast(fixture, "Burst Lightning", Json.map("method", "normal", "kicker", kicked)));
            require(searched(world), "a known kicker payment stayed unsearched");
            Spell spell = spell(world, "Burst Lightning");
            require(KickerAbility.getKickedCounter(world.game, spell.getSpellAbility()) == kicked,
                    "rebuilt kicker count differs from the history");
            UUID target = spell.getSpellAbility().getTargets().getFirstTarget();
            Permanent creature = world.game.getPermanent(target);
            require(creature != null && creature.getName().equals("Goblin Boarders"), "public target changed");
            int before = creature.getDamage();
            require(spell.resolve(world.game), "Burst Lightning did not resolve");
            require(creature.getDamage() - before == (kicked == 1 ? 4 : 2), "kicked state did not set the damage");
        }
        require(!searched(build(fixture, cast(fixture, "Burst Lightning", Json.map("method", "normal", "kicker", 2L)))),
                "an impossible kicker count was searched");
    }

    private static void faebloomTrick(Map<String, Object> fixture) {
        World world = build(fixture, null);
        require(world.flags.contains("register:reflexive_trigger") && searched(world),
                "the audited reflexive trigger was not rebuilt: " + world.flags);
        StackObject top = world.game.getStack().peek();
        require(top instanceof StackAbility && world.game.getObject(top.getSourceId()).getName().equals("Faebloom Trick"),
                "wrong top stack object");
        UUID target = top.getStackAbility().getTargets().getFirstTarget();
        Permanent creature = world.game.getPermanent(target);
        require(creature != null && creature.getName().equals("Elementalist Adept") && !creature.isTapped(),
                "public target changed");
        require(top.resolve(world.game) && creature.isTapped(), "the reflexive trigger did not tap its target");
        require(WorldBuilder.reflexiveTrigger("Faebloom Trick", "tap target creature.") == null
                && WorldBuilder.reflexiveTrigger("Unknown", "tap target creature an opponent controls.") == null,
                "an unaudited reflexive trigger was rebuilt");
    }

    /** A Cat token is the pool's 1/1 Cat11Token, under an anthem too, never another set's same-named class. */
    private static void catToken(Map<String, Object> fixture, int power) {
        World world = build(fixture, null);
        String id = null;
        for (Object player : Json.arr(Json.obj(fixture, "observation"), "players")) {
            for (Object o : Json.arr(Json.obj(player), "battlefield")) {
                if ("Cat Token".equals(Json.str(Json.obj(o), "card_name"))) id = Json.str(Json.obj(o), "object_id");
            }
        }
        require(id != null, "fixture has no Cat token");
        Permanent cat = world.game.getPermanent(world.idToUuid.get(id));
        require(cat instanceof PermanentToken
                && "Cat11Token".equals(((PermanentToken) cat).getToken().getClass().getSimpleName()),
                "Cat token rebuilt as " + (cat instanceof PermanentToken ? ((PermanentToken) cat).getToken().getClass() : cat));
        require(cat.getPower().getValue() == power && cat.getToughness().getValue() == power,
                "Cat token is " + cat.getPower().getValue() + "/" + cat.getToughness().getValue());
        List<Object> keywords = KitBridge.keywords(cat.getAbilities(world.game));
        require(keywords != null && keywords.isEmpty(), "Cat token has keywords " + keywords);
        for (String flag : world.flags) {
            require(!flag.startsWith("approximate:token_characteristics"), "Cat token flagged " + flag);
        }
    }

    public static void main(String[] args) throws Exception {
        Map<String, Object> fixtures = Json.parseObject(new String(
                Files.readAllBytes(Paths.get(args[0])), StandardCharsets.UTF_8));
        thinkTwice(Json.obj(fixtures, "think_twice"));
        burstLightning(Json.obj(fixtures, "burst_lightning"));
        faebloomTrick(Json.obj(fixtures, "faebloom_trick"));
        catToken(Json.obj(fixtures, "plain_cat"), 1);
        catToken(Json.obj(fixtures, "arahbo_cat"), 2);
        System.out.println("Optional-cost spells and a reflexive trigger rebuilt from public history and resolved,"
                + " and pool token classes rebuilt: PASS");
    }
}
