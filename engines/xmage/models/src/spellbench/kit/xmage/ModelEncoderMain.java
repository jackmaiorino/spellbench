package spellbench.kit.xmage;

import mage.player.cabt.CardResolver;
import mage.player.spellbench.Warmup;
import spellbench.kit.core.Json;
import spellbench.kit.core.Seeds;

import java.io.FileDescriptor;
import java.io.FileOutputStream;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.Map;

/** Small encoder check from a recorded, permitted priority decision. */
public final class ModelEncoderMain {
    public static void main(String[] args) throws Exception {
        if (args.length != 3) {
            throw new IllegalArgumentException("usage: DECISION.json WORLD_SEED ID_SEED");
        }
        PrintStream out = new PrintStream(new FileOutputStream(FileDescriptor.out), true, "UTF-8");
        System.setOut(System.err);
        Runner.quietLogs();
        KitRandom.installBoot();
        Warmup.framework();
        new CardResolver().resolve("Plains");
        Map<String, Object> record = Json.parseObject(new String(Files.readAllBytes(Paths.get(args[0])), StandardCharsets.UTF_8));
        Map<String, Object> decision = Json.obj(record, "decision");
        if (!"priority".equals(Json.str(Json.obj(decision, "context"), "kind"))) {
            throw new IllegalArgumentException("only the priority encoder slice is implemented");
        }
        out.println(Json.canonical(ModelEncoder.priority(Json.obj(record, "game_start"), decision,
                Seeds.unhex(args[1]), Seeds.unhex(args[2]))));
    }
}
