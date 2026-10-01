package mage.player.spellbench.x1;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import mage.cards.repository.CardScanner;
import mage.game.Game;
import mage.player.cabt.CabtDeckFactory;
import mage.player.cabt.CabtGameSession;
import mage.player.cabt.CardResolver;
import mage.player.cabt.InvalidSelectionException;
import mage.player.spellbench.Secrets;
import mage.player.spellbench.ids.ObjectIds;
import mage.players.Player;

import java.io.BufferedWriter;
import java.io.IOException;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.TreeSet;
import java.util.UUID;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * X1 determinism check: plays scripted two-seat games in one JVM and prints one summary line per game with a
 * transcript digest. A game spec is {@code record:<game_secret hex>:<answers file>} (a seeded random driver
 * picks answers and writes them) or {@code replay:<game_secret hex>:<answers file>} (answers come from the file).
 * <p>
 * The transcript is the CABT-driven decision stream: per decision the acting seat, CABT's observation and
 * options, the per-viewer object ids of Section 5.3 for every object the observation names, and the answer;
 * then the terminal. {@code digest} chains SHA-256 over every record. {@code content_digest} chains the same
 * records with XMage UUIDs blanked and the minted ids dropped, which separates "the ids differ" from "the game
 * differs" in the negative control.
 * <p>
 * Usage: {@code DeterminismCheck --deck0 A.dck --deck1 B.dck --out-dir DIR [--max-decisions N]
 * [--answer-seed S] --game SPEC [--game SPEC ...]} or {@code DeterminismCheck --selftest}. The working
 * directory holds this process's card database ({@code ./db}).
 */
public final class DeterminismCheck {

    private static final Gson GSON = new GsonBuilder().disableHtmlEscaping().serializeNulls().create();
    private static final Pattern UUID_RE = Pattern.compile("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}");
    private static PrintStream out;

    private DeterminismCheck() {
    }

    public static void main(String[] args) throws Exception {
        out = System.out;
        System.setOut(System.err); // XMage core prints stray lines to stdout; results own the real stdout
        List<String> games = new ArrayList<>();
        String deck0 = null;
        String deck1 = null;
        String outDir = null;
        int maxDecisions = 6000;
        long answerSeed = 1;
        for (int i = 0; i < args.length; i++) {
            switch (args[i]) {
                case "--selftest":
                    System.exit(SelfTest.run(out) ? 0 : 1);
                    return;
                case "--scan-only":
                    // builds ./db once; each engine process then works on its own copy (design D3)
                    CardScanner.scan();
                    out.println("x1: card database built");
                    System.exit(0);
                    return;
                case "--deck0":
                    deck0 = args[++i];
                    break;
                case "--deck1":
                    deck1 = args[++i];
                    break;
                case "--out-dir":
                    outDir = args[++i];
                    break;
                case "--max-decisions":
                    maxDecisions = Integer.parseInt(args[++i]);
                    break;
                case "--answer-seed":
                    answerSeed = Long.parseLong(args[++i]);
                    break;
                case "--game":
                    games.add(args[++i]);
                    break;
                default:
                    throw new IllegalArgumentException("unknown argument " + args[i]);
            }
        }
        if (deck0 == null || deck1 == null || outDir == null || games.isEmpty()) {
            throw new IllegalArgumentException("need --deck0, --deck1, --out-dir and at least one --game");
        }
        boolean patched = RouterBridge.available();
        if (patched) {
            RouterBridge.installBoot();
            int[] n = mage.player.spellbench.Warmup.framework();
            System.err.println("x1: boot router installed; framework classes initialized " + n[0] + ", failed " + n[1]);
        }
        long t0 = System.nanoTime();
        CardScanner.scan();
        System.err.println("x1: card database ready in " + (System.nanoTime() - t0) / 1_000_000 + " ms");
        List<CabtDeckFactory.Entry> d0 = readDeck(Paths.get(deck0));
        List<CabtDeckFactory.Entry> d1 = readDeck(Paths.get(deck1));
        CardResolver resolver = new CardResolver();
        Files.createDirectories(Paths.get(outDir));
        String header = GSON.toJson(header(deck0, deck1));
        for (int k = 0; k < games.size(); k++) {
            String[] spec = games.get(k).split(":", 3);
            boolean record = spec[0].equals("record");
            if (!record && !spec[0].equals("replay")) {
                throw new IllegalArgumentException("game spec must start with record: or replay:");
            }
            byte[] secret = Secrets.fromHex(spec[1]);
            Path answers = Paths.get(spec[2]);
            Path transcript = Paths.get(outDir, String.format("game%02d-%s.jsonl", k, spec[1].substring(0, 8)));
            JsonObject summary = play(k, patched, secret, record, answers, transcript, header, d0, d1, resolver,
                    maxDecisions, answerSeed);
            out.println(GSON.toJson(summary));
            out.flush();
        }
        System.exit(0); // CABT's parked threads are daemons, but XMage keeps executor threads alive
    }

    private static JsonObject play(int index, boolean patched, byte[] secret, boolean record, Path answersPath,
                                   Path transcriptPath, String header, List<CabtDeckFactory.Entry> d0,
                                   List<CabtDeckFactory.Entry> d1, CardResolver resolver, int maxDecisions,
                                   long answerSeed) throws IOException {
        List<List<Integer>> answers = record ? new ArrayList<>() : readAnswers(answersPath);
        RandomPolicy policy = new RandomPolicy(answerSeed);
        CabtGameSession.Config config = new CabtGameSession.Config()
                .playerNames("Player0", "Player1").decisionTimeoutSeconds(120);
        Object router = null;
        if (patched) {
            // classes first initialized here draw boot ids, never this game's stream
            RouterBridge.installBoot();
            resolver.buildDeck(UUID.nameUUIDFromBytes(new byte[]{0}), d0);
            resolver.buildDeck(UUID.nameUUIDFromBytes(new byte[]{1}), d1);
            router = RouterBridge.install(secret);
        } else {
            // stock XMage: CABT's own best-effort seeding of the JVM-global generator
            config.seed(java.nio.ByteBuffer.wrap(secret, 0, 8).getLong());
        }
        long t0 = System.nanoTime();
        CabtGameSession session = new CabtGameSession(d0, d1, config, resolver);
        Game game = session.game();
        List<UUID> playerIds = new ArrayList<>(game.getPlayers().keySet());
        if (patched) {
            RouterBridge.assignSeat(router, playerIds.get(0), "p0");
            RouterBridge.assignSeat(router, playerIds.get(1), "p1");
        }
        ObjectIds ids = new ObjectIds(secret);
        byte[] d = Secrets.sha256("spellbench/x1/transcript-v1".getBytes(StandardCharsets.US_ASCII), utf8(header));
        byte[] c = d.clone();
        String terminal;
        String detail = null;
        int n = 0;
        try (BufferedWriter w = Files.newBufferedWriter(transcriptPath, StandardCharsets.UTF_8)) {
            w.write(header);
            w.write('\n');
            CabtGameSession.Event event = session.start();
            while (true) {
                if (event.kind() != CabtGameSession.Event.Kind.DECISION) {
                    terminal = event.kind() == CabtGameSession.Event.Kind.GAME_OVER ? "game_over" : "game_error";
                    detail = event.kind() == CabtGameSession.Event.Kind.GAME_OVER ? event.winner() : event.errorMessage();
                    break;
                }
                if (n >= maxDecisions) {
                    terminal = "truncated";
                    break;
                }
                String seat = event.playerName().equals("Player0") ? "p0" : "p1";
                JsonObject rec = new JsonObject();
                rec.addProperty("i", n);
                rec.addProperty("seat", seat);
                rec.add("observation", GSON.toJsonTree(event.observation()));
                String content = GSON.toJson(rec);
                rec.add("ids", mintIds(ids, seat, game, content));
                List<Integer> answer;
                CabtGameSession.Event next = null;
                if (record) {
                    answer = null;
                    for (int attempt = 0; attempt < 20 && next == null; attempt++) {
                        answer = policy.choose(event.decision());
                        try {
                            next = session.select(answer);
                        } catch (InvalidSelectionException e) {
                            next = null;
                        }
                    }
                    if (next == null) {
                        terminal = "driver_stuck";
                        break;
                    }
                    answers.add(answer);
                } else {
                    if (n >= answers.size()) {
                        terminal = "replay_divergence";
                        detail = "more decisions than recorded answers";
                        break;
                    }
                    answer = answers.get(n);
                    try {
                        next = session.select(answer);
                    } catch (InvalidSelectionException e) {
                        terminal = "replay_divergence";
                        detail = "recorded answer " + answer + " invalid at decision " + n;
                        break;
                    }
                }
                JsonArray a = new JsonArray();
                answer.forEach(a::add);
                rec.add("answer", a);
                String line = GSON.toJson(rec);
                w.write(line);
                w.write('\n');
                d = Secrets.sha256(d, utf8(line));
                c = Secrets.sha256(c, utf8(scrub(content) + "|" + a));
                n++;
                event = next;
            }
            JsonObject end = new JsonObject();
            end.addProperty("terminal", terminal);
            end.addProperty("detail", detail);
            end.addProperty("decisions", n);
            end.addProperty("turn", game.getTurnNum());
            JsonArray life = new JsonArray();
            for (UUID id : playerIds) {
                Player p = game.getPlayer(id);
                life.add(p == null ? null : p.getLife());
            }
            end.add("life", life);
            String endLine = GSON.toJson(end);
            w.write(endLine);
            w.write('\n');
            d = Secrets.sha256(d, utf8(endLine));
            c = Secrets.sha256(c, utf8(scrub(endLine)));
        } finally {
            session.finish();
            if (patched) {
                RouterBridge.installBoot();
            }
        }
        if (record) {
            writeAnswers(answersPath, answers);
        }
        JsonObject s = new JsonObject();
        s.addProperty("game", index);
        s.addProperty("mode", record ? "record" : "replay");
        s.addProperty("build", patched ? "patched" : "stock");
        s.addProperty("secret", Secrets.toHex(secret).substring(0, 8));
        s.addProperty("decisions", n);
        s.addProperty("terminal", terminal);
        s.addProperty("detail", detail);
        s.addProperty("turn", game.getTurnNum());
        s.addProperty("ms", (System.nanoTime() - t0) / 1_000_000);
        s.addProperty("digest", "sha256:" + Secrets.toHex(d));
        s.addProperty("content_digest", "sha256:" + Secrets.toHex(c));
        if (patched) {
            s.add("streams", GSON.toJsonTree(RouterBridge.usage(router)));
        }
        return s;
    }

    /**
     * Per-viewer ids (Section 5.3) for every XMage object the record names; the internal key carries the zone
     * change counter, so an object gets a fresh id on every zone change.
     */
    private static JsonArray mintIds(ObjectIds ids, String viewer, Game game, String text) {
        TreeSet<String> uuids = new TreeSet<>();
        Matcher m = UUID_RE.matcher(text);
        while (m.find()) {
            uuids.add(m.group());
        }
        JsonArray arr = new JsonArray();
        for (String u : uuids) {
            UUID id = UUID.fromString(u);
            JsonArray pair = new JsonArray();
            pair.add(u);
            pair.add(ids.visible(viewer, ObjectIds.internalKey(id, game.getState().getZoneChangeCounter(id))));
            arr.add(pair);
        }
        return arr;
    }

    private static String scrub(String s) {
        return UUID_RE.matcher(s).replaceAll("U");
    }

    private static byte[] utf8(String s) {
        return s.getBytes(StandardCharsets.UTF_8);
    }

    private static JsonObject header(String deck0, String deck1) throws IOException {
        JsonObject h = new JsonObject();
        h.addProperty("x1", "spellbench xmage determinism transcript v1");
        h.addProperty("deck0_sha256", Secrets.toHex(Secrets.sha256(Files.readAllBytes(Paths.get(deck0)))));
        h.addProperty("deck1_sha256", Secrets.toHex(Secrets.sha256(Files.readAllBytes(Paths.get(deck1)))));
        return h;
    }

    /**
     * XMage .dck: "N [SET:NUM] Name" or "N Name"; sideboard ("SB:") and metadata lines are ignored (BO1).
     */
    static List<CabtDeckFactory.Entry> readDeck(Path path) throws IOException {
        List<CabtDeckFactory.Entry> entries = new ArrayList<>();
        for (String raw : Files.readAllLines(path, StandardCharsets.UTF_8)) {
            String line = raw.trim();
            if (line.isEmpty() || line.startsWith("SB:") || line.startsWith("NAME:") || line.startsWith("LAYOUT")
                    || line.startsWith("#")) {
                continue;
            }
            int sp = line.indexOf(' ');
            int count = Integer.parseInt(line.substring(0, sp));
            String name = line.substring(sp + 1).trim();
            if (name.startsWith("[")) {
                name = name.substring(name.indexOf(']') + 1).trim();
            }
            entries.add(new CabtDeckFactory.Entry(name, count));
        }
        return entries;
    }

    private static List<List<Integer>> readAnswers(Path path) throws IOException {
        List<List<Integer>> answers = new ArrayList<>();
        for (String line : Files.readAllLines(path, StandardCharsets.US_ASCII)) {
            List<Integer> a = new ArrayList<>();
            for (String part : line.trim().split(",")) {
                if (!part.isEmpty()) {
                    a.add(Integer.parseInt(part));
                }
            }
            answers.add(a);
        }
        return answers;
    }

    private static void writeAnswers(Path path, List<List<Integer>> answers) throws IOException {
        StringBuilder sb = new StringBuilder();
        for (List<Integer> a : answers) {
            for (int i = 0; i < a.size(); i++) {
                sb.append(i == 0 ? "" : ",").append(a.get(i));
            }
            sb.append('\n');
        }
        Files.write(path, sb.toString().getBytes(StandardCharsets.US_ASCII));
    }

    static String hex(byte[] b) {
        return Secrets.toHex(b);
    }

    static byte[] runSecretVector() {
        byte[] r = new byte[32];
        for (int i = 0; i < 32; i++) {
            r[i] = (byte) i;
        }
        return r;
    }

    static String first8(byte[] b) {
        return Secrets.toHex(Arrays.copyOf(b, 8));
    }
}
