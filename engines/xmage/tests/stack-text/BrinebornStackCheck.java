package spellbench.kit.xmage;

import mage.counters.CounterType;
import mage.game.permanent.Permanent;
import mage.game.stack.StackObject;
import mage.game.stack.StackAbility;
import spellbench.kit.core.Json;
import spellbench.kit.core.Sampler;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.Map;
import java.util.UUID;

/** Rebuild and resolve the public stack that stopped the gen0 correctness check. */
public final class BrinebornStackCheck {
    private static void require(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
    public static void main(String[] args) throws Exception {
        Map<String, Object> fixture = Json.parseObject(new String(
                Files.readAllBytes(Paths.get(args[0])), StandardCharsets.UTF_8));
        KitContext.reset();
        KitRandom.installBoot();
        KitRandom random = KitRandom.install(new byte[32], new byte[32]);
        WorldBuilder.Spec spec = new WorldBuilder.Spec();
        spec.gameStart = Json.obj(fixture, "game_start");
        spec.observation = Json.obj(fixture, "observation");
        spec.random = random;
        spec.sample = Sampler.sample(spec.gameStart, spec.observation, random.stream("sampler"));
        spec.mode = WorldBuilder.Mode.PRIORITY;
        spec.viewerFactory = Puppet::new;
        spec.otherFactory = Puppet::new;
        World world = WorldBuilder.build(spec);
        for (String flag : world.flags) {
            require(!flag.startsWith("horizon:") && !flag.startsWith("unsupported:"), flag);
        }
        require(Register.triggersEventFree("Brineborn Cutthroat"), "audited model register missing");
        require(!Register.triggersEventFree("Unknown trigger source"), "unknown trigger became supported");
        require(!Register.triggersEventFree("Chrome Host Seedshark"), "unreviewed event-data row changed");
        require(world.game.getStack().size() == 3, "public three-object stack changed");
        StackObject trigger = world.game.getStack().peek();
        require(trigger instanceof StackAbility, "wrong top stack object kind");
        Permanent source = world.game.getPermanent(trigger.getSourceId());
        require(source != null && source.getName().equals("Brineborn Cutthroat"), "wrong counter source");
        int before = source.getCounters(world.game).getCount(CounterType.P1P1);
        StackObject counterspell = null, spell = null;
        for (StackObject entry : world.game.getStack()) {
            if (entry.getName().equals("Essence Scatter")) counterspell = entry;
            if (entry.getName().equals("Mischievous Mystic")) spell = entry;
        }
        require(counterspell != null && spell != null, "public spells missing");
        UUID counterspellId = counterspell.getId(), spellId = spell.getId();
        // This copied trigger was rebuilt without checkTrigger or its captured spellCast value.
        require(trigger.resolve(world.game), "actual pinned source-counter trigger did not resolve");
        require(source.getCounters(world.game).getCount(CounterType.P1P1) == before + 1,
                "actual trigger did not add exactly one source counter");
        require(world.game.getStack().getStackObject(counterspellId) == counterspell
                && world.game.getStack().getStackObject(spellId) == spell, "resolution changed other stack objects");
        require(counterspell.getStackAbility().getTargets().getFirstTarget().equals(spellId),
                "Essence Scatter's public target changed");
        System.out.println("Brineborn public stack reconstruction and actual counter resolution: PASS");
    }
}
