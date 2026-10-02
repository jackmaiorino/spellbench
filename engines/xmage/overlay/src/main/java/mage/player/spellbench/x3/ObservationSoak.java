package mage.player.spellbench.x3;

import mage.MageObject;
import mage.cards.Card;
import mage.cards.CardWithSpellOption;
import mage.cards.DoubleFacedCard;
import mage.cards.SplitCard;
import mage.cards.repository.CardScanner;
import mage.constants.Zone;
import mage.game.ExileZone;
import mage.game.Game;
import mage.game.command.CommandObject;
import mage.game.command.Emblem;
import mage.game.permanent.Permanent;
import mage.game.permanent.PermanentToken;
import mage.game.stack.Spell;
import mage.game.stack.StackObject;
import mage.player.cabt.CabtDeckFactory;
import mage.player.cabt.CabtGameSession;
import mage.player.cabt.CardResolver;
import mage.player.cabt.InvalidSelectionException;
import mage.player.cabt.MagicOption;
import mage.player.cabt.MagicOptionType;
import mage.player.cabt.MagicSelectType;
import mage.player.cabt.PendingDecision;
import mage.player.spellbench.Secrets;
import mage.player.spellbench.Warmup;
import mage.player.spellbench.ids.ObjectIds;
import mage.player.spellbench.observe.Look;
import mage.player.spellbench.observe.Looks;
import mage.player.spellbench.observe.Observation;
import mage.player.spellbench.observe.ObservationBuilder;
import mage.player.spellbench.observe.ObservationException;
import mage.player.spellbench.observe.PriorityHolder;
import mage.player.spellbench.rng.GameRandom;
import mage.player.spellbench.server.EngineProfile;
import mage.player.spellbench.server.StrictJson;
import mage.player.spellbench.x1.DeterminismCheck;
import mage.player.spellbench.x1.RandomPolicy;
import mage.players.Player;

import java.io.BufferedWriter;
import java.io.IOException;
import java.io.OutputStream;
import java.io.OutputStreamWriter;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.text.Normalizer;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeSet;
import java.util.UUID;
import java.util.zip.GZIPOutputStream;

/**
 * X3 soak: plays seeded random two-seat games in-process (as the X1 check does) and, at every prompt, builds both
 * seats' observations with {@link ObservationBuilder}. Each game is one gzipped JSONL file: a header (the declared
 * profile and rules), one line per prompt (both observations, the acting seat's option references, and an
 * engine-side audit of internal keys, face-down objects and the names hidden from each seat), and a terminal line.
 * {@code tests/x3/check_observations.py} validates the files with the reference validator.
 * <p>
 * The audit carries internal identities and hidden names: it exists only in these local test files and never
 * reaches agents.
 * <p>
 * Usage: {@code ObservationSoak --out-dir DIR --first N --count K --pairs A:B[,C:D...] [--deck-dir DIR]
 * [--run-secret HEX] [--max-decisions N]}, or {@code ObservationSoak --selftest} (the Section 6.10 tables). A deck
 * is a catalog id or a {@code .dck} file name in the deck directory. Game g uses {@code game_secret(g)} and plays
 * pair g mod |pairs|, with starting seat p0 when g / |pairs| is even, else p1. Answers come from the X1 random
 * driver seeded by g. The working directory holds this process's card database ({@code ./db}).
 */
public final class ObservationSoak {

    private static PrintStream out;

    private ObservationSoak() {
    }

    public static void main(String[] args) throws Exception {
        out = System.out;
        System.setOut(System.err); // XMage core prints stray lines to stdout; results own the real stdout
        String outDir = null;
        String deckDir = null;
        int first = 0;
        int count = 1;
        int maxDecisions = 4000;
        List<String[]> pairs = new ArrayList<>();
        byte[] runSecret = new byte[32];
        for (int i = 0; i < 32; i++) {
            runSecret[i] = (byte) i; // the Section 16 vector run secret
        }
        for (int i = 0; i < args.length; i++) {
            switch (args[i]) {
                case "--selftest":
                    // its own process: the abilities it constructs draw ids that games must not see shifted
                    GameRandom.installBoot();
                    List<String> failures = mage.player.spellbench.observe.SelfTest.run();
                    out.println(failures.isEmpty() ? "x3 selftest: PASS" : "x3 selftest: FAIL " + failures);
                    System.exit(failures.isEmpty() ? 0 : 1);
                    return;
                case "--out-dir":
                    outDir = args[++i];
                    break;
                case "--deck-dir":
                    deckDir = args[++i];
                    break;
                case "--first":
                    first = Integer.parseInt(args[++i]);
                    break;
                case "--count":
                    count = Integer.parseInt(args[++i]);
                    break;
                case "--max-decisions":
                    maxDecisions = Integer.parseInt(args[++i]);
                    break;
                case "--run-secret":
                    runSecret = Secrets.fromHex(args[++i]);
                    break;
                case "--pairs":
                    for (String p : args[++i].split(",")) {
                        pairs.add(p.split(":"));
                    }
                    break;
                default:
                    throw new IllegalArgumentException("unknown argument " + args[i]);
            }
        }
        if (outDir == null || pairs.isEmpty()) {
            throw new IllegalArgumentException("need --out-dir and --pairs");
        }
        GameRandom.installBoot();
        int[] warm = Warmup.framework();
        System.err.println("x3: framework classes initialized " + warm[0] + ", failed " + warm[1]);
        CardScanner.scan();
        EngineProfile profile = EngineProfile.load();
        Map<String, Object> hello = profile.helloOk("x3", 0);
        @SuppressWarnings("unchecked")
        Map<String, Object> flags = (Map<String, Object>) hello.get("observation");
        CardResolver resolver = new CardResolver();
        Files.createDirectories(Paths.get(outDir));
        for (int g = first; g < first + count; g++) {
            String[] pair = pairs.get(g % pairs.size());
            int startSeat = (g / pairs.size()) % 2;
            List<CabtDeckFactory.Entry> d0 = deck(profile, deckDir, pair[0]);
            List<CabtDeckFactory.Entry> d1 = deck(profile, deckDir, pair[1]);
            byte[] secret = Secrets.gameSecret(runSecret, g);
            Path file = Paths.get(outDir, String.format("game%04d.jsonl.gz", g));
            Map<String, Object> summary = play(g, secret, pair, startSeat, d0, d1, resolver, hello, flags, file,
                    maxDecisions);
            out.println(StrictJson.canonicalString(summary));
            out.flush();
        }
        System.exit(0); // CABT's parked threads are daemons, but XMage keeps executor threads alive
    }

    private static List<CabtDeckFactory.Entry> deck(EngineProfile profile, String deckDir, String name)
            throws IOException {
        EngineProfile.CatalogDeck d = profile.deck(name);
        if (d != null) {
            List<CabtDeckFactory.Entry> entries = new ArrayList<>();
            for (mage.player.spellbench.server.Requests.Row r : d.decklist) {
                entries.add(new CabtDeckFactory.Entry(r.name, (int) r.count));
            }
            return entries;
        }
        if (deckDir == null) {
            throw new IllegalArgumentException("deck " + name + " is not in the catalog and no --deck-dir is set");
        }
        return DeterminismCheck.readDeck(Paths.get(deckDir, name + ".dck"));
    }

    private static Map<String, Object> play(int index, byte[] secret, String[] pair, int startSeat,
                                            List<CabtDeckFactory.Entry> d0, List<CabtDeckFactory.Entry> d1,
                                            CardResolver resolver, Map<String, Object> hello,
                                            Map<String, Object> flags, Path file, int maxDecisions)
            throws IOException {
        long t0 = System.nanoTime();
        GameRandom.installBoot();
        resolver.buildDeck(UUID.nameUUIDFromBytes(new byte[]{0}), d0);
        resolver.buildDeck(UUID.nameUUIDFromBytes(new byte[]{1}), d1);
        GameRandom router = GameRandom.install(secret);
        CabtGameSession.Config config = new CabtGameSession.Config()
                .playerNames("p0", "p1").decisionTimeoutSeconds(120);
        CabtGameSession session = new CabtGameSession(d0, d1, config, resolver);
        Game game = session.game();
        UUID[] seatIds = new UUID[2];
        for (UUID id : game.getPlayers().keySet()) {
            seatIds[game.getPlayer(id).getName().equals("p0") ? 0 : 1] = id;
        }
        router.assignSeat(seatIds[0], "p0");
        router.assignSeat(seatIds[1], "p1");
        game.setStartingPlayerId(seatIds[startSeat]);
        ObservationBuilder builder = new ObservationBuilder(game, new ObjectIds(secret), flags, seatIds[0],
                seatIds[1]);
        PriorityHolder holder = new PriorityHolder();
        RandomPolicy policy = new RandomPolicy(1000003L * index + 7);
        byte[] digest = Secrets.sha256("spellbench/x3/observations-v1".getBytes(StandardCharsets.US_ASCII));
        String terminal;
        String detail = null;
        int n = 0;
        int faceDown = 0;
        int looks = 0;
        try (OutputStream raw = Files.newOutputStream(file);
             BufferedWriter w = new BufferedWriter(new OutputStreamWriter(new GZIPOutputStream(raw, 1 << 16),
                     StandardCharsets.UTF_8), 1 << 16)) {
            Map<String, Object> header = new LinkedHashMap<>();
            header.put("x3", "spellbench xmage observation soak v1");
            header.put("game", index);
            header.put("secret8", Secrets.toHex(secret).substring(0, 16));
            header.put("decks", Arrays.<Object>asList(pair[0], pair[1]));
            header.put("starting_seat", startSeat == 0 ? "p0" : "p1");
            header.put("hello_ok", hello);
            digest = write(w, header, digest);
            CabtGameSession.Event event = session.start();
            while (true) {
                if (event.kind() != CabtGameSession.Event.Kind.DECISION) {
                    terminal = event.kind() == CabtGameSession.Event.Kind.GAME_OVER ? "game_over" : "game_error";
                    detail = event.kind() == CabtGameSession.Event.Kind.GAME_OVER ? event.winner()
                            : event.errorMessage();
                    break;
                }
                if (n >= maxDecisions) {
                    terminal = "truncated";
                    break;
                }
                String seat = event.playerName();
                int k = seat.equals("p0") ? 0 : 1;
                PendingDecision decision = event.decision();
                boolean priority = decision.selectType() == MagicSelectType.PRIORITY;
                String prioritySeat = holder.holder(seat, priority);
                List<Look> shown = Looks.fromPrompt(game, seatIds[k], decision);
                Observation[] obs = new Observation[2];
                try {
                    for (int v = 0; v < 2; v++) {
                        obs[v] = builder.build(ObservationBuilder.SEATS.get(v), prioritySeat,
                                v == k ? shown : Collections.<Look>emptyList());
                    }
                } catch (ObservationException e) {
                    terminal = "halted";
                    detail = e.cause + " (" + e.getMessage() + ")";
                    break;
                }
                Map<String, Object> line = new LinkedHashMap<>();
                line.put("i", n);
                line.put("acting", seat);
                line.put("select_type", decision.selectType().name());
                line.put("priority", priority);
                Map<String, Object> observations = new LinkedHashMap<>();
                observations.put("p0", obs[0].json());
                observations.put("p1", obs[1].json());
                line.put("observations", observations);
                line.put("option_refs", optionRefs(game, decision, obs[k]));
                Map<String, Object> audit = new LinkedHashMap<>();
                audit.put("p0", obs[0].audit());
                audit.put("p1", obs[1].audit());
                List<Object> fd = faceDownAudit(game, seatIds);
                faceDown += fd.size();
                looks += shown.size();
                audit.put("face_down", fd);
                Map<String, Object> leak = new LinkedHashMap<>();
                for (int v = 0; v < 2; v++) {
                    leak.put(ObservationBuilder.SEATS.get(v),
                            leakNames(game, seatIds, v, v == k ? shown : Collections.<Look>emptyList()));
                }
                audit.put("leak_names", leak);
                line.put("audit", audit);
                List<Integer> answer = null;
                CabtGameSession.Event next = null;
                for (int attempt = 0; attempt < 20 && next == null; attempt++) {
                    answer = policy.choose(decision);
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
                line.put("answer", new ArrayList<Object>(answer));
                digest = write(w, line, digest);
                boolean passed = priority && answer.size() == 1
                        && decision.options().get(answer.get(0)).type() == MagicOptionType.PASS_PRIORITY;
                holder.answered(seat, priority, passed);
                n++;
                event = next;
            }
            Map<String, Object> end = new LinkedHashMap<>();
            end.put("terminal", terminal);
            end.put("detail", detail);
            end.put("decisions", n);
            end.put("turn", game.getTurnNum());
            digest = write(w, end, digest);
        } finally {
            session.finish();
            GameRandom.installBoot();
        }
        Map<String, Object> s = new LinkedHashMap<>();
        s.put("game", index);
        s.put("decks", pair[0] + ":" + pair[1]);
        s.put("starting_seat", startSeat == 0 ? "p0" : "p1");
        s.put("decisions", n);
        s.put("terminal", terminal);
        s.put("detail", detail);
        s.put("turn", game.getTurnNum());
        s.put("face_down_sightings", faceDown);
        s.put("looks", looks);
        s.put("ms", (System.nanoTime() - t0) / 1_000_000);
        s.put("digest", "sha256:" + Secrets.toHex(digest));
        return s;
    }

    private static byte[] write(BufferedWriter w, Map<String, Object> line, byte[] digest) throws IOException {
        String s = StrictJson.canonicalString(line);
        w.write(s);
        w.write('\n');
        return Secrets.sha256(digest, s.getBytes(StandardCharsets.UTF_8));
    }

    /**
     * Every object id the prompt's options name, as the acting seat's reference (what X4's candidates will carry),
     * or why it has none: a player, an id that is no object (an ability or mode id), or an object the observation
     * does not hold.
     */
    private static List<Object> optionRefs(Game game, PendingDecision decision, Observation obs) {
        List<Object> out = new ArrayList<>();
        for (int i = 0; i < decision.options().size(); i++) {
            MagicOption option = decision.options().get(i);
            for (UUID id : Looks.optionIds(option)) {
                Map<String, Object> r = new LinkedHashMap<>();
                r.put("option", i);
                Map<String, Object> target = obs.target(id);
                if (target != null) {
                    r.put("target", target);
                } else {
                    Zone zone = game.getState().getZone(id);
                    r.put("target", null);
                    r.put("unresolved_zone", zone == null ? null : zone.name().toLowerCase());
                }
                out.add(r);
            }
        }
        return out;
    }

    /** Every face-down object on the battlefield, the stack and in exile, with the seat XMage lets look (D4). */
    private static List<Object> faceDownAudit(Game game, UUID[] seatIds) {
        List<Object> out = new ArrayList<>();
        for (Permanent p : game.getBattlefield().getAllPermanents()) {
            if (p.isFaceDown(game)) {
                out.add(faceDownEntry(ObjectIds.internalKey(p.getId(), p.getZoneChangeCounter(game)), "battlefield",
                        seatOf(seatIds, p.getControllerId())));
            }
        }
        for (StackObject so : game.getStack()) {
            if (so instanceof Spell && ((Spell) so).isFaceDown(game)) {
                out.add(faceDownEntry(ObjectIds.internalKey(so.getId(), so.getZoneChangeCounter(game)), "stack",
                        seatOf(seatIds, so.getControllerId())));
            }
        }
        for (ExileZone zone : game.getExile().getExileZones()) {
            for (Card c : zone.getCards(game)) {
                if (c.isFaceDown(game)) {
                    out.add(faceDownEntry(ObjectIds.internalKey(c.getId(), c.getZoneChangeCounter(game)), "exile",
                            seatOf(seatIds, c.getOwnerId())));
                }
            }
        }
        return out;
    }

    private static Map<String, Object> faceDownEntry(String key, String zone, String visibleTo) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("key", key);
        m.put("zone", zone);
        m.put("visible_to", visibleTo);
        return m;
    }

    private static String seatOf(UUID[] seatIds, UUID id) {
        return seatIds[0].equals(id) ? "p0" : seatIds[1].equals(id) ? "p1" : null;
    }

    /**
     * Names (with every face and full name) of cards hidden from viewer v that no object visible to v shares: the
     * other seat's hand, both libraries, and face-down objects v may not look at, minus the names of everything v
     * sees (its hand, public zones, the stack and its sources, the command zone, the cards shown to it). None of
     * them may appear anywhere in v's observation.
     */
    private static List<Object> leakNames(Game game, UUID[] seatIds, int v, List<Look> shown) {
        UUID viewer = seatIds[v];
        TreeSet<String> hidden = new TreeSet<>();
        TreeSet<String> visible = new TreeSet<>();
        List<UUID> shownIds = new ArrayList<>();
        for (Look l : shown) {
            Card c = game.getCard(l.cardId);
            shownIds.add(l.cardId);
            if (c != null && c.getMainCard() != null) {
                shownIds.add(c.getMainCard().getId());
                addNames(visible, c.getMainCard());
            }
        }
        for (UUID pid : seatIds) {
            Player p = game.getPlayer(pid);
            for (Card c : p.getLibrary().getCards(game)) {
                if (!shownIds.contains(c.getId())) {
                    addNames(hidden, c);
                }
            }
            for (Card c : p.getHand().getCards(game)) {
                if (pid.equals(viewer)) {
                    addNames(visible, c);
                } else if (!shownIds.contains(c.getId())) {
                    addNames(hidden, c);
                }
            }
            for (Card c : p.getGraveyard().getCards(game)) {
                addNames(visible, c);
            }
        }
        for (Permanent p : game.getBattlefield().getAllPermanents()) {
            if (p.isFaceDown(game) && !viewer.equals(p.getControllerId())) {
                addNames(hidden, p.getMainCard());
                if (p instanceof PermanentToken) {
                    hidden.add(nfc(((PermanentToken) p).getToken().getName()));
                }
            } else {
                addNames(visible, p);
                addNames(visible, p.getMainCard());
            }
        }
        for (StackObject so : game.getStack()) {
            if (so instanceof Spell) {
                Spell s = (Spell) so;
                if (s.isFaceDown(game) && !viewer.equals(s.getControllerId())) {
                    addNames(hidden, s.getCard().getMainCard());
                } else {
                    addNames(visible, s);
                    addNames(visible, s.getCard().getMainCard());
                }
            } else {
                MageObject src = game.getObject(so.getSourceId());
                if (src == null) {
                    src = game.getLastKnownInformation(so.getSourceId(), Zone.BATTLEFIELD);
                }
                boolean hiddenSource = src instanceof Permanent && ((Permanent) src).isFaceDown(game)
                        && !viewer.equals(((Permanent) src).getControllerId());
                if (src != null && !hiddenSource) {
                    addNames(visible, src);
                }
            }
        }
        for (ExileZone zone : game.getExile().getExileZones()) {
            for (Card c : zone.getCards(game)) {
                if (c.isFaceDown(game) && !viewer.equals(c.getOwnerId())) {
                    addNames(hidden, c.getMainCard());
                } else {
                    addNames(visible, c);
                }
            }
        }
        for (CommandObject c : game.getState().getCommand()) {
            visible.add(nfc(c.getName()));
            if (c instanceof Emblem && ((Emblem) c).getSourceObject() != null) {
                visible.add(nfc(((Emblem) c).getSourceObject().getName() + " Emblem"));
                addNames(visible, ((Emblem) c).getSourceObject());
            }
        }
        hidden.removeAll(visible);
        hidden.remove("");
        return new ArrayList<Object>(hidden);
    }

    private static void addNames(TreeSet<String> set, MageObject o) {
        if (o == null) {
            return;
        }
        set.add(nfc(o.getName()));
        if (o instanceof Card) {
            Card main = ((Card) o).getMainCard();
            if (main != null) {
                set.add(nfc(main.getName()));
                if (main instanceof SplitCard) {
                    set.addAll(Arrays.asList(nfc(main.getName()).split(" // ")));
                } else if (main instanceof DoubleFacedCard) {
                    String l = ((DoubleFacedCard) main).getLeftHalfCard().getName();
                    String r = ((DoubleFacedCard) main).getRightHalfCard().getName();
                    set.add(nfc(l));
                    set.add(nfc(r));
                    set.add(nfc(l + " // " + r));
                } else if (main instanceof CardWithSpellOption) {
                    String s = ((CardWithSpellOption) main).getSpellCard().getName();
                    set.add(nfc(s));
                    set.add(nfc(main.getName() + " // " + s));
                }
            }
        }
    }

    private static String nfc(String s) {
        return s == null ? "" : Normalizer.normalize(s, Normalizer.Form.NFC);
    }
}
