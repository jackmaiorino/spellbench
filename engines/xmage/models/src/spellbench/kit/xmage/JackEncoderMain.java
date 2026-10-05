package spellbench.kit.xmage;

import mage.player.cabt.CardResolver;
import mage.player.spellbench.Warmup;
import spellbench.kit.core.Json;
import spellbench.kit.core.Seeds;
import spellbench.models.jack.EmbeddingCache;

import java.io.BufferedReader;
import java.io.FileDescriptor;
import java.io.FileOutputStream;
import java.io.InputStreamReader;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.Map;

/** Private float-feature pipe from received permitted priority records. */
public final class JackEncoderMain {
    private JackEncoderMain() { }
    public static void main(String[] args) throws Exception {
        if (args.length != 6) {
            throw new IllegalArgumentException("usage: RECORD_OR_STDIO EMBEDDINGS EMBEDDINGS_SHA256 ENCODER_SHA256 CANDIDATE_SHA256 SEED_RECORD");
        }
        System.setProperty("spellbench.jack.embeddingFile", args[1]);
        System.setProperty("spellbench.jack.embeddingSha256", args[2]);
        System.setProperty("spellbench.jack.encoderSourceSha256", args[3]);
        System.setProperty("spellbench.jack.candidateSourceSha256", args[4]);
        if (!args[3].matches("[a-f0-9]{64}") || !args[4].matches("[a-f0-9]{64}")) {
            throw new IllegalArgumentException("both staged encoder identities must be SHA-256");
        }
        Class.forName("spellbench.models.jack.StateSequenceBuilder").getMethod("buildBaseState",
                mage.game.Game.class, mage.constants.TurnPhase.class, int.class, java.util.UUID.class, Map.class);
        Class<?> candidates = Class.forName("spellbench.models.jack.CandidateEncoder");
        candidates.getConstructor(mage.players.Player.class);
        candidates.getMethod("priorityId", mage.game.Game.class, mage.abilities.Ability.class);
        candidates.getMethod("priorityFeatures", mage.game.Game.class, mage.abilities.Ability.class,
                Class.forName("spellbench.models.jack.StateSequenceBuilder$SequenceOutput"));
        int embeddingCount = EmbeddingCache.size();
        PrintStream out = new PrintStream(new FileOutputStream(FileDescriptor.out), true, "UTF-8");
        System.setOut(System.err);
        Runner.quietLogs();
        KitRandom.installBoot();
        Warmup.framework();
        new CardResolver().resolve("Plains");
        boolean stdio = "--stdio".equals(args[0]);
        if (!stdio) {
            Map<String, Object> record = Json.parseObject(new String(Files.readAllBytes(Paths.get(args[0])), StandardCharsets.UTF_8));
            Map<String, Object> seeds = Json.parseObject(new String(Files.readAllBytes(Paths.get(args[5])), StandardCharsets.UTF_8));
            out.println(Json.canonical(encode(record, seeds)));
            return;
        }
        if (!"--request-seeds".equals(args[5])) throw new IllegalArgumentException("stdio requires per-request seeds");
        out.println(Json.canonical(Json.map("ready", true, "encoder", "jack-permitted-priority",
                "encoder_source_sha256", args[3], "candidate_source_sha256", args[4], "embedding_cache_sha256", args[2],
                "embedding_count", (long) embeddingCount)));
        BufferedReader in = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        String line;
        while ((line = in.readLine()) != null) {
            Map<String, Object> record = null;
            try {
                record = Json.parseObject(line);
                out.println(Json.canonical(Json.map("id", record.get("id"), "ok", true,
                        "encoded", encode(record, record))));
            } catch (Exception | LinkageError e) {
                out.println(Json.canonical(Json.map("id", record == null ? null : record.get("id"),
                        "ok", false, "error", e.toString())));
            }
        }
    }

    private static Map<String, Object> encode(Map<String, Object> record, Map<String, Object> seeds) throws Exception {
        return JackEncoder.encode(Json.obj(record, "game_start"), Json.obj(record, "decision"),
                seed(Json.str(seeds, "world_seed")), seed(Json.str(seeds, "id_seed")));
    }

    private static byte[] seed(String value) {
        if (value == null || !value.matches("[a-f0-9]{64}")) throw new IllegalArgumentException("Jack seeds require 32-byte hexadecimal strings");
        return Seeds.unhex(value);
    }
}
