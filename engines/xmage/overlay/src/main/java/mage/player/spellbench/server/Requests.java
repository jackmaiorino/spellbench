package mage.player.spellbench.server;

import java.text.Normalizer;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * Strict request validation (protocol v2 Sections 4.1, 4.2, 9), field for field as P's reference host and fake
 * engine check it ({@code python/spellbench/messages.py}). Every failure is {@link Invalid}, answered
 * {@code malformed_request}.
 */
public final class Requests {

    public static final String PROTOCOL = "spellbench/v2";
    public static final List<String> SEATS = Arrays.asList("p0", "p1");
    static final List<String> OPPONENT_DECKLIST = Arrays.asList("visible", "hidden");
    static final List<String> MULLIGAN = Arrays.asList("london", "none");
    static final List<String> STARTING_PLAYER = Arrays.asList("host_assigned", "toss_winner_chooses");
    private static final Pattern DECK_ID = Pattern.compile("sha256:[0-9a-f]{64}");
    private static final Pattern GAME_SECRET = Pattern.compile("[0-9a-f]{64}");
    private static final Pattern EXTENSION = Pattern.compile("x_[a-z0-9_]+");
    private static final long U32_MAX = 0xFFFFFFFFL;

    /** A request that is valid JSON but not a valid request: {@code malformed_request}. */
    public static final class Invalid extends Exception {
        private static final long serialVersionUID = 1L;

        Invalid(String where, String message) {
            super(where + ": " + message);
        }
    }

    private Requests() {
    }

    /** A deck row: an Oracle name in NFC and a count. */
    public static final class Row {
        public final String name;
        public final long count;

        Row(String name, long count) {
            this.name = name;
            this.count = count;
        }

        public Map<String, Object> toJson() {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("count", count);
            m.put("name", name);
            return m;
        }
    }

    /** {@code {deck_id, catalog_id}} or {@code {deck_id, decklist}}; validate_deck has no deck_id. */
    public static final class Deck {
        public final String deckId;
        public final String catalogId;
        public final List<Row> decklist;

        Deck(String deckId, String catalogId, List<Row> decklist) {
            this.deckId = deckId;
            this.catalogId = catalogId;
            this.decklist = decklist;
        }
    }

    public static final class Rules {
        public String opponentDecklist;
        public String mulligan;
        public String startingPlayer;
        public String startingSeat;
        public List<String> cardNameDomain;
        public List<String> extensions;
        public boolean probe;
    }

    public static final class Hello {
        public String requestId;
        public long protocolMinor;
    }

    public static final class Reset {
        public String requestId;
        public String gameId;
        public String format;
        public Deck[] seats = new Deck[2];
        public Rules rules;
        public byte[] gameSecret;
        public long maxDecisions;
        public long maxSteps;
    }

    public static final class Step {
        public String requestId;
        public String gameId;
        public long expectedStep;
        public long candidateId;
        public Map<String, Object> semanticEcho;
    }

    public static final class ValidateDeck {
        public String requestId;
        public String format;
        public Deck deck;
    }

    public static final class Probe {
        public String requestId;
        public String gameId;
        public long samples;
    }

    // ----------------------------------------------------------------------------------------------

    public static Hello hello(Map<String, Object> v) throws Invalid {
        message(v, "hello", "request_type", "hello", "protocol_minor");
        Hello h = new Hello();
        h.requestId = nonempty(v.get("request_id"), "hello.request_id");
        h.protocolMinor = u32(v.get("protocol_minor"), "hello.protocol_minor");
        return h;
    }

    public static Reset reset(Map<String, Object> v) throws Invalid {
        message(v, "reset", "request_type", "reset",
                "game_id", "format", "seats", "rules", "game_secret", "max_decisions", "max_steps");
        Reset r = new Reset();
        r.requestId = nonempty(v.get("request_id"), "reset.request_id");
        r.gameId = nonempty(v.get("game_id"), "reset.game_id");
        r.format = nonempty(v.get("format"), "reset.format");
        List<Object> seats = array(v.get("seats"), "reset.seats");
        if (seats.size() != 2) {
            throw new Invalid("reset.seats", "must hold the p0 deck and the p1 deck");
        }
        for (int k = 0; k < 2; k++) {
            String where = "reset.seats[" + k + "]";
            Map<String, Object> entry = object(seats.get(k), where, "seat", "deck");
            if (!SEATS.get(k).equals(entry.get("seat"))) {
                throw new Invalid(where + ".seat", "must be " + SEATS.get(k) + " (seats list p0 then p1)");
            }
            r.seats[k] = wireDeck(entry.get("deck"), where + ".deck");
        }
        r.rules = rules(v.get("rules"), "reset.rules");
        Object secret = v.get("game_secret");
        if (!(secret instanceof String) || !GAME_SECRET.matcher((String) secret).matches()) {
            throw new Invalid("reset.game_secret", "must be 64 lowercase hex digits"); // never quoted
        }
        r.gameSecret = hex((String) secret);
        r.maxDecisions = safeInt(v.get("max_decisions"), "reset.max_decisions");
        r.maxSteps = safeInt(v.get("max_steps"), "reset.max_steps");
        return r;
    }

    public static Step step(Map<String, Object> v) throws Invalid {
        message(v, "step", "request_type", "step", "game_id", "expected_step", "selection");
        Step s = new Step();
        s.requestId = nonempty(v.get("request_id"), "step.request_id");
        s.gameId = nonempty(v.get("game_id"), "step.game_id");
        s.expectedStep = safeInt(v.get("expected_step"), "step.expected_step");
        Map<String, Object> sel = object(v.get("selection"), "step.selection", "candidate_id", "semantic_echo");
        s.candidateId = u32(sel.get("candidate_id"), "step.selection.candidate_id");
        s.semanticEcho = asObject(sel.get("semantic_echo"), "step.selection.semantic_echo");
        return s;
    }

    public static ValidateDeck validateDeck(Map<String, Object> v) throws Invalid {
        message(v, "validate_deck", "request_type", "validate_deck", "format", "deck");
        ValidateDeck d = new ValidateDeck();
        d.requestId = nonempty(v.get("request_id"), "validate_deck.request_id");
        d.format = nonempty(v.get("format"), "validate_deck.format");
        Map<String, Object> deck = asObject(v.get("deck"), "validate_deck.deck");
        if (deck.keySet().equals(Collections.singleton("catalog_id"))) {
            d.deck = new Deck(null, nonempty(deck.get("catalog_id"), "validate_deck.deck.catalog_id"), null);
        } else if (deck.keySet().equals(Collections.singleton("decklist"))) {
            d.deck = new Deck(null, null, decklist(deck.get("decklist"), "validate_deck.deck.decklist"));
        } else {
            throw new Invalid("validate_deck.deck", "must be exactly {catalog_id} or {decklist}");
        }
        return d;
    }

    public static Probe probe(Map<String, Object> v) throws Invalid {
        message(v, "probe_resample", "request_type", "probe_resample", "game_id", "samples");
        Probe p = new Probe();
        p.requestId = nonempty(v.get("request_id"), "probe_resample.request_id");
        p.gameId = nonempty(v.get("game_id"), "probe_resample.game_id");
        p.samples = u32(v.get("samples"), "probe_resample.samples");
        return p;
    }

    // ----------------------------------------------------------------------------------------------

    private static Deck wireDeck(Object value, String where) throws Invalid {
        Map<String, Object> deck = asObject(value, where);
        Set<String> keys = deck.keySet();
        boolean catalog = keys.equals(new HashSet<>(Arrays.asList("deck_id", "catalog_id")));
        boolean list = keys.equals(new HashSet<>(Arrays.asList("deck_id", "decklist")));
        if (!catalog && !list) {
            throw new Invalid(where, "must be exactly {deck_id, catalog_id} or {deck_id, decklist}");
        }
        String deckId = text(deck.get("deck_id"), where + ".deck_id");
        if (!DECK_ID.matcher(deckId).matches()) {
            throw new Invalid(where + ".deck_id", "must be \"sha256:\" and 64 lowercase hex digits");
        }
        if (catalog) {
            return new Deck(deckId, nonempty(deck.get("catalog_id"), where + ".catalog_id"), null);
        }
        return new Deck(deckId, null, decklist(deck.get("decklist"), where + ".decklist"));
    }

    /** Section 12.1 rows, in the order given: nonempty, exact fields, NFC names, counts 1..u32, no repeat. */
    static List<Row> decklist(Object value, String where) throws Invalid {
        List<Object> rows = array(value, where);
        if (rows.isEmpty()) {
            throw new Invalid(where, "a decklist is a nonempty array of rows");
        }
        List<Row> out = new ArrayList<>();
        Set<String> seen = new HashSet<>();
        for (int k = 0; k < rows.size(); k++) {
            String at = where + "[" + k + "]";
            Map<String, Object> row = object(rows.get(k), at, "count", "name");
            String name = cardName(row.get("name"), at + ".name");
            Object count = row.get("count");
            if (!(count instanceof Long) || (Long) count < 1 || (Long) count > U32_MAX) {
                throw new Invalid(at + ".count", "a count is an integer from 1 to " + U32_MAX);
            }
            if (!seen.add(name)) {
                throw new Invalid(at + ".name", "card name " + name + " appears twice");
            }
            out.add(new Row(name, (Long) count));
        }
        return out;
    }

    private static Rules rules(Object value, String where) throws Invalid {
        Map<String, Object> r = object(value, where, "opponent_decklist", "mulligan", "starting_player",
                "starting_seat", "card_name_domain", "extensions", "probe");
        Rules out = new Rules();
        out.opponentDecklist = vocab(r.get("opponent_decklist"), OPPONENT_DECKLIST, where + ".opponent_decklist");
        out.mulligan = vocab(r.get("mulligan"), MULLIGAN, where + ".mulligan");
        out.startingPlayer = vocab(r.get("starting_player"), STARTING_PLAYER, where + ".starting_player");
        Object seat = r.get("starting_seat");
        if (out.startingPlayer.equals("host_assigned")) {
            if (!(seat instanceof String) || !SEATS.contains(seat)) {
                throw new Invalid(where + ".starting_seat", "must be p0 or p1 with host_assigned");
            }
            out.startingSeat = (String) seat;
        } else if (seat != null) {
            throw new Invalid(where + ".starting_seat", "must be null with toss_winner_chooses");
        }
        Map<String, Object> domain = object(r.get("card_name_domain"), where + ".card_name_domain",
                "domain_id", "names");
        List<Object> names = array(domain.get("names"), where + ".card_name_domain.names");
        List<String> checked = new ArrayList<>();
        Set<String> seen = new HashSet<>();
        for (int k = 0; k < names.size(); k++) {
            String n = cardName(names.get(k), where + ".card_name_domain.names[" + k + "]");
            if (!seen.add(n)) {
                throw new Invalid(where + ".card_name_domain.names[" + k + "]", n + " appears twice");
            }
            checked.add(n);
        }
        String expected = Digests.domainId(checked);
        if (!expected.equals(text(domain.get("domain_id"), where + ".card_name_domain.domain_id"))) {
            throw new Invalid(where + ".card_name_domain.domain_id",
                    "does not match the names, whose domain_id is " + expected);
        }
        out.cardNameDomain = checked;
        List<Object> ext = array(r.get("extensions"), where + ".extensions");
        out.extensions = new ArrayList<>();
        for (int k = 0; k < ext.size(); k++) {
            String n = text(ext.get(k), where + ".extensions[" + k + "]");
            if (!EXTENSION.matcher(n).matches()) {
                throw new Invalid(where + ".extensions[" + k + "]", n + " is not an extension name (x_[a-z0-9_]+)");
            }
            if (out.extensions.contains(n)) {
                throw new Invalid(where + ".extensions[" + k + "]", n + " appears twice");
            }
            out.extensions.add(n);
        }
        Object probe = r.get("probe");
        if (!(probe instanceof Boolean)) {
            throw new Invalid(where + ".probe", "must be a boolean");
        }
        out.probe = (Boolean) probe;
        return out;
    }

    // ----------------------------------------------------------------------------------------------

    /** Exactly the envelope and {@code fields}; the type tag must match (the protocol is checked earlier). */
    private static void message(Map<String, Object> v, String where, String tagKey, String tag, String... fields)
            throws Invalid {
        String[] all = new String[fields.length + 3];
        all[0] = tagKey;
        all[1] = "protocol";
        all[2] = "request_id";
        System.arraycopy(fields, 0, all, 3, fields.length);
        exactKeys(v, where, all);
        if (!tag.equals(v.get(tagKey))) {
            throw new Invalid(where + "." + tagKey, "must be \"" + tag + "\"");
        }
        if (!PROTOCOL.equals(v.get("protocol"))) {
            throw new Invalid(where + ".protocol", "must be \"" + PROTOCOL + "\"");
        }
    }

    private static Map<String, Object> object(Object value, String where, String... fields) throws Invalid {
        Map<String, Object> m = asObject(value, where);
        exactKeys(m, where, fields);
        return m;
    }

    private static void exactKeys(Map<String, Object> m, String where, String... fields) throws Invalid {
        Set<String> want = new HashSet<>(Arrays.asList(fields));
        for (String k : m.keySet()) {
            if (!want.contains(k)) {
                throw new Invalid(where, "unknown field " + k);
            }
        }
        for (String k : fields) {
            if (!m.containsKey(k)) {
                throw new Invalid(where, "missing field " + k);
            }
        }
    }

    @SuppressWarnings("unchecked")
    static Map<String, Object> asObject(Object value, String where) throws Invalid {
        if (!(value instanceof Map)) {
            throw new Invalid(where, "must be an object");
        }
        return (Map<String, Object>) value;
    }

    @SuppressWarnings("unchecked")
    private static List<Object> array(Object value, String where) throws Invalid {
        if (!(value instanceof List)) {
            throw new Invalid(where, "must be an array");
        }
        return (List<Object>) value;
    }

    private static String text(Object value, String where) throws Invalid {
        if (!(value instanceof String)) {
            throw new Invalid(where, "must be a string");
        }
        return (String) value;
    }

    private static String nonempty(Object value, String where) throws Invalid {
        String t = text(value, where);
        if (t.isEmpty()) {
            throw new Invalid(where, "must be a nonempty string");
        }
        return t;
    }

    private static String vocab(Object value, List<String> allowed, String where) throws Invalid {
        String t = text(value, where);
        if (!allowed.contains(t)) {
            throw new Invalid(where, t + " is not one of " + allowed);
        }
        return t;
    }

    static String cardName(Object value, String where) throws Invalid {
        String t = nonempty(value, where);
        if (!Normalizer.isNormalized(t, Normalizer.Form.NFC)) {
            throw new Invalid(where, "card name " + t + " is not in Unicode NFC");
        }
        return t;
    }

    private static long safeInt(Object value, String where) throws Invalid {
        if (!(value instanceof Long) || (Long) value < 0) {
            throw new Invalid(where, "must be an integer in [0, 2^53 - 1]");
        }
        return (Long) value;
    }

    private static long u32(Object value, String where) throws Invalid {
        if (!(value instanceof Long) || (Long) value < 0 || (Long) value > U32_MAX) {
            throw new Invalid(where, "must be a u32");
        }
        return (Long) value;
    }

    private static byte[] hex(String h) {
        byte[] out = new byte[h.length() / 2];
        for (int k = 0; k < out.length; k++) {
            out[k] = (byte) Integer.parseInt(h.substring(2 * k, 2 * k + 2), 16);
        }
        return out;
    }
}
