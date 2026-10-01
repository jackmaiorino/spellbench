package mage.player.spellbench.server;

import mage.cards.repository.CardScanner;
import mage.player.cabt.CabtDeckFactory;
import mage.player.cabt.CardResolver;
import mage.player.cabt.DeckValidation;
import mage.player.spellbench.Warmup;
import mage.player.spellbench.rng.GameRandom;

import java.io.BufferedInputStream;
import java.io.ByteArrayOutputStream;
import java.io.FileDescriptor;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.PrintStream;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * The XMage engine's environment-role server for protocol v2 (Sections 2, 4, 9). One process, at most one
 * active game; NDJSON on stdin and stdout; diagnostics on stderr.
 * <p>
 * {@code System.out} is redirected to stderr before anything else runs: XMage core prints stray lines, and one on
 * stdout would corrupt the stream (design draft Section 3.3). The working directory holds this process's own
 * card database ({@code ./db}, design D3).
 * <p>
 * Usage: {@code java -cp lib/* mage.player.spellbench.server.EngineServer}
 */
public final class EngineServer {

    static final int MAX_LINE_BYTES = 8 * 1024 * 1024;
    private static final int MAX_MESSAGE_CHARS = 500;

    private final EngineProfile profile;
    private final CardResolver resolver;
    private final Set<String> usedGameIds = new HashSet<>();
    private GameSession game;

    // the one-entry retransmission cache of Section 4.1: the last request that parsed, as its raw line
    private String cachedId;
    private byte[] cachedLine;
    private byte[] cachedResponse;

    EngineServer(EngineProfile profile, CardResolver resolver) {
        this.profile = profile;
        this.resolver = resolver;
    }

    public static void main(String[] args) throws Exception {
        OutputStream protocolOut = new FileOutputStream(FileDescriptor.out);
        System.setOut(new PrintStream(new FileOutputStream(FileDescriptor.err), true));
        GameRandom.installBoot();
        mage.player.spellbench.decide.Exchange.hashWarmup(); // X4h test hook: a no-op unless set
        int[] warmed = Warmup.framework();
        System.err.println("xmage-spellbench: framework classes initialized " + warmed[0] + ", failed " + warmed[1]);
        CardScanner.scan();
        EngineServer server = new EngineServer(EngineProfile.load(), new CardResolver());
        mage.player.spellbench.ManaCostCache.snapshot(); // every game starts from this cache state (X5)
        server.serve(new BufferedInputStream(System.in, 1 << 16), protocolOut);
        System.exit(0); // XMage keeps executor threads alive
    }

    void serve(InputStream in, OutputStream out) throws IOException {
        while (true) {
            byte[] answer;
            Line line = readLine(in);
            if (line == null) {
                return;
            }
            if (line.error != null) {
                answer = error("", "malformed_json", line.error);
            } else {
                answer = handle(line.bytes);
            }
            out.write(answer);
            out.flush();
        }
    }

    /** Answers one request line (terminator stripped) with one response line. */
    byte[] handle(byte[] line) {
        Map<String, Object> value;
        try {
            value = StrictJson.parseObject(line);
        } catch (StrictJson.NotAnObject e) {
            return error("", "malformed_request", e.getMessage());
        } catch (StrictJson.Malformed e) {
            return error("", "malformed_json", e.getMessage());
        }
        Object requestId = value.get("request_id");
        if (!(requestId instanceof String) || ((String) requestId).isEmpty()) {
            return error("", "malformed_request", "request_id must be a nonempty string (spec 4.1)");
        }
        String id = (String) requestId;
        Object protocol = value.get("protocol");
        if (!(protocol instanceof String)) {
            return error(id, "malformed_request", "protocol must be a string (spec 4.1)");
        }
        if (!Requests.PROTOCOL.equals(protocol)) {
            return error(id, "protocol_mismatch", "protocol must be \"spellbench/v2\"");
        }
        Object type = value.get("request_type");
        Handler handler = handlerFor(type);
        if (handler == null) {
            return error(id, "malformed_request", "unknown request_type " + type);
        }
        Object request;
        try {
            request = handler.parse(value);
        } catch (Requests.Invalid e) {
            return error(id, "malformed_request", e.getMessage()); // never cached (spec 4.1)
        }
        if (id.equals(cachedId)) {
            if (Arrays.equals(cachedLine, line)) {
                return cachedResponse; // a retransmission: no side effects
            }
            return error(id, "request_id_reuse_mismatch", "request_id " + id + " was just used with another payload");
        }
        byte[] response = handler.answer(request);
        cachedId = id;
        cachedLine = line;
        cachedResponse = response;
        return response;
    }

    private interface Handler {
        Object parse(Map<String, Object> value) throws Requests.Invalid;

        byte[] answer(Object request);
    }

    private Handler handlerFor(Object type) {
        if ("hello".equals(type)) {
            return handler(Requests::hello, r -> answerHello((Requests.Hello) r));
        }
        if ("reset".equals(type)) {
            return handler(Requests::reset, r -> answerReset((Requests.Reset) r));
        }
        if ("step".equals(type)) {
            return handler(Requests::step, r -> answerStep((Requests.Step) r));
        }
        if ("validate_deck".equals(type)) {
            return handler(Requests::validateDeck, r -> answerValidateDeck((Requests.ValidateDeck) r));
        }
        if ("probe_resample".equals(type)) {
            return handler(Requests::probe, r -> error(((Requests.Probe) r).requestId, "unsupported_request",
                    "this engine has no probe (spec 9.7)"));
        }
        return null;
    }

    private interface Parser {
        Object parse(Map<String, Object> value) throws Requests.Invalid;
    }

    private interface Answer {
        byte[] answer(Object request);
    }

    private static Handler handler(Parser parser, Answer answer) {
        return new Handler() {
            @Override
            public Object parse(Map<String, Object> value) throws Requests.Invalid {
                return parser.parse(value);
            }

            @Override
            public byte[] answer(Object request) {
                return answer.answer(request);
            }
        };
    }

    // ----------------------------------------------------------------------------------------------

    private byte[] answerHello(Requests.Hello h) {
        return line(profile.helloOk(h.requestId, h.protocolMinor));
    }

    private byte[] answerReset(Requests.Reset r) {
        String id = r.requestId;
        if (usedGameIds.contains(r.gameId)) {
            return error(id, "malformed_request", "game_id " + r.gameId + " was used by an earlier reset of this process");
        }
        if (game != null && game.terminal == null) {
            return error(id, "game_already_active", "game " + game.gameId + " is still active");
        }
        if (!EngineProfile.FORMATS.contains(r.format)) {
            return error(id, "unsupported_format", "format " + r.format + " is not one of " + EngineProfile.FORMATS);
        }
        List<List<Requests.Row>> rows = new ArrayList<>();
        for (int k = 0; k < 2; k++) {
            String refusal = refusal(r.seats[k]);
            if (refusal != null) {
                return error(id, "unsupported_deck", "the " + Requests.SEATS.get(k) + " deck: " + refusal);
            }
            rows.add(rowsOf(r.seats[k]));
        }
        for (int k = 0; k < 2; k++) {
            String expected = Digests.deckId(rows.get(k));
            if (!expected.equals(r.seats[k].deckId)) {
                return error(id, "deck_id_mismatch", "the " + Requests.SEATS.get(k)
                        + " deck_id does not match its list, whose deck_id is " + expected);
            }
        }
        String ruleRefusal = unsupportedRule(r.rules);
        if (ruleRefusal != null) {
            return error(id, "unsupported_rule", ruleRefusal);
        }
        usedGameIds.add(r.gameId);
        try {
            game = GameSession.create(r, entries(rows.get(0)), entries(rows.get(1)), resolver);
            game.start();
        } catch (RuntimeException e) {
            // an engine fault never emits a partial decision: the game ends halted (Section 9.5)
            e.printStackTrace(System.err);
            game = GameSession.halted(r.gameId, "engine_error");
        }
        return respond(id);
    }

    private byte[] answerStep(Requests.Step s) {
        String id = s.requestId;
        if (game == null) {
            return error(id, "step_before_reset", "no game has been reset");
        }
        if (!s.gameId.equals(game.gameId)) {
            return error(id, "game_id_mismatch", "this engine's game is " + game.gameId);
        }
        if (game.terminal != null) {
            return error(id, "game_already_terminal", "game " + game.gameId + " has ended");
        }
        if (s.expectedStep != game.step) {
            return error(id, "expected_step_mismatch", "the pending decision's step is " + game.step);
        }
        if (s.candidateId >= game.pending.semantics.size()) {
            return error(id, "candidate_id_out_of_range", "candidate_id " + s.candidateId + " is outside the "
                    + game.pending.semantics.size() + " candidates");
        }
        if (!StrictJson.canonicalString(s.semanticEcho).equals(game.pending.semantics.get((int) s.candidateId))) {
            return error(id, "semantic_echo_mismatch", "semantic_echo differs from candidate " + s.candidateId);
        }
        game.answer((int) s.candidateId);
        return respond(id);
    }

    private byte[] answerValidateDeck(Requests.ValidateDeck v) {
        if (!EngineProfile.FORMATS.contains(v.format)) {
            return error(v.requestId, "unsupported_format", "format " + v.format + " is not one of " + EngineProfile.FORMATS);
        }
        String refusal = refusal(v.deck);
        if (refusal != null) {
            return error(v.requestId, "unsupported_deck", refusal);
        }
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("response_type", "deck_ok");
        m.put("protocol", Requests.PROTOCOL);
        m.put("request_id", v.requestId);
        return line(m);
    }

    /** Why the engine cannot play a deck (Section 9.2), or null. */
    private String refusal(Requests.Deck deck) {
        if (deck.catalogId != null) {
            return profile.deck(deck.catalogId) == null
                    ? "catalog_id " + deck.catalogId + " is not in this engine's catalog" : null;
        }
        DeckValidation validation = resolver.validateDeck(entries(deck.decklist));
        if (validation.isValid()) {
            return null;
        }
        List<String> names = new ArrayList<>();
        for (DeckValidation.Entry e : validation.failures()) {
            names.add(e.requestedName());
        }
        return "cards this engine cannot play: " + String.join(", ", names);
    }

    private List<Requests.Row> rowsOf(Requests.Deck deck) {
        return deck.catalogId != null ? profile.deck(deck.catalogId).decklist : deck.decklist;
    }

    private static String unsupportedRule(Requests.Rules rules) {
        if (!Arrays.asList("london", "none").contains(rules.mulligan)) {
            return "rules.mulligan " + rules.mulligan + " is not supported";
        }
        if (!"host_assigned".equals(rules.startingPlayer)) {
            return "rules.starting_player " + rules.startingPlayer + " is not in rules_supported (host_assigned)";
        }
        if (!rules.extensions.isEmpty()) {
            return "rules.extensions " + rules.extensions + " are not declared in hello_ok.extensions";
        }
        if (rules.probe) {
            return "rules.probe: this engine has no probe (spec 9.7)";
        }
        return null;
    }

    private static List<CabtDeckFactory.Entry> entries(List<Requests.Row> rows) {
        List<CabtDeckFactory.Entry> out = new ArrayList<>();
        for (Requests.Row r : rows) {
            out.add(new CabtDeckFactory.Entry(r.name, (int) r.count));
        }
        return out;
    }

    /** The decision or terminal that answers a reset or step. */
    private byte[] respond(String requestId) {
        Map<String, Object> m = new LinkedHashMap<>();
        if (game.terminal != null) {
            m.put("response_type", "terminal");
            m.put("protocol", Requests.PROTOCOL);
            m.put("request_id", requestId);
            m.put("game_id", game.gameId);
            m.putAll(game.terminal);
            m.put("step_count", game.step);
            m.put("decision_count", game.decisionCount);
            m.put("provenance", profile.provenance());
            return line(m);
        }
        m.put("response_type", "decision");
        m.put("protocol", Requests.PROTOCOL);
        m.put("request_id", requestId);
        m.put("game_id", game.gameId);
        m.put("step", game.step);
        m.put("seat_decision", game.pending.seatDecision);
        m.put("provenance", profile.provenance());
        return line(m);
    }

    // ----------------------------------------------------------------------------------------------

    static byte[] error(String requestId, String code, String message) {
        String text = message == null ? code : message.replaceAll("\\s+", " ").trim();
        if (text.length() > MAX_MESSAGE_CHARS) {
            text = text.substring(0, MAX_MESSAGE_CHARS);
        }
        Map<String, Object> err = new LinkedHashMap<>();
        err.put("code", code);
        err.put("message", text);
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("response_type", "error");
        m.put("protocol", Requests.PROTOCOL);
        m.put("request_id", requestId);
        m.put("error", err);
        return line(m);
    }

    private static byte[] line(Map<String, Object> message) {
        byte[] body = StrictJson.canonical(message);
        byte[] out = Arrays.copyOf(body, body.length + 1);
        out[body.length] = '\n';
        return out;
    }

    /** One framed line, or null at clean EOF; an oversized or unterminated line carries an error. */
    static final class Line {
        final byte[] bytes;
        final String error;

        Line(byte[] bytes, String error) {
            this.bytes = bytes;
            this.error = error;
        }
    }

    static Line readLine(InputStream in) throws IOException {
        ByteArrayOutputStream buf = new ByteArrayOutputStream();
        boolean tooLong = false;
        int b;
        int count = 0;
        while ((b = in.read()) != -1) {
            if (b == '\n') {
                if (tooLong) {
                    return new Line(null, "line exceeds " + MAX_LINE_BYTES + " bytes");
                }
                byte[] line = buf.toByteArray();
                if (line.length > 0 && line[line.length - 1] == '\r') {
                    line = Arrays.copyOf(line, line.length - 1);
                }
                return new Line(line, null);
            }
            if (++count > MAX_LINE_BYTES) {
                tooLong = true;
                buf.reset();
            } else {
                buf.write(b);
            }
        }
        if (count == 0) {
            return null;
        }
        return new Line(null, tooLong ? "line exceeds " + MAX_LINE_BYTES + " bytes" : "line missing \\n terminator before EOF");
    }
}
