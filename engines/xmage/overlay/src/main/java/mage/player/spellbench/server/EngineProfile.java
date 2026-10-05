package mage.player.spellbench.server;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Properties;

/**
 * What this engine declares in {@code hello_ok} (Section 9.1; design draft Section 3.7) and repeats as
 * {@code provenance}. The identity strings come from {@code engine-identity.properties}, which
 * {@code scripts/build.sh} writes from the same pins and patch hashes as {@code BUILD-MANIFEST.json}; the catalog
 * from {@code catalog.json}.
 */
public final class EngineProfile {

    public static final String NAME = "xmage-spellbench";
    public static final String VERSION = "0.1.0";

    static final List<String> FORMATS = Arrays.asList("fdn-limited-bo1", "standard-2022-25-bo1");

    /**
     * The kinds the decision mapper ({@code decide.SeatPlayer}) can emit (task X4). Not declared: the reserved kinds;
     * {@code choose_starting_player} (starts are host-assigned); {@code activate_mana_ability} unless explicitly
     * enabled for ordinary priority; {@code choose_cost_option} and {@code optional_cast}
     * (XMage reaches them through yes/no and card choices the mapper poses as other kinds).
     */
    static final List<String> DECISION_KINDS = Arrays.asList(
            "pass", "play_land", "cast_spell", "activate_ability", "special_action",
            "choose_target", "finish_target_selection", "choose_cost_target", "choose_cast_method",
            "choose_spell_mode", "choose_option", "choose_color", "choose_number", "choose_boolean",
            "choose_name", "select_object", "finish_selection", "optional_cost", "mulligan", "order_pick",
            "arrange_card", "choose_replacement", "declare_attack", "declare_block", "distribute", "choose_pile");

    public final String rulesSnapshotId;
    public final String cardPoolIdentity;
    public final String sourceRevision;
    public final List<CatalogDeck> catalog;
    /** Frozen when the profile is loaded; cost payment still uses engine_autopay. */
    public final boolean priorityMana;
    private final List<String> decisionKinds;

    /** A catalog deck, its rows in file order, and the formats it is offered for. */
    public static final class CatalogDeck {
        public final String catalogId;
        public final String name;
        public final List<String> formats;
        public final List<Requests.Row> decklist;

        CatalogDeck(String catalogId, String name, List<String> formats, List<Requests.Row> decklist) {
            this.catalogId = catalogId;
            this.name = name;
            this.formats = formats;
            this.decklist = decklist;
        }
    }

    private EngineProfile(String rulesSnapshotId, String cardPoolIdentity, String sourceRevision,
                          List<CatalogDeck> catalog, boolean priorityMana) {
        this.rulesSnapshotId = rulesSnapshotId;
        this.cardPoolIdentity = cardPoolIdentity;
        this.sourceRevision = sourceRevision;
        this.catalog = catalog;
        this.priorityMana = priorityMana;
        List<String> kinds = new ArrayList<>(DECISION_KINDS);
        if (priorityMana) {
            kinds.add(kinds.indexOf("activate_ability"), "activate_mana_ability");
        }
        this.decisionKinds = Collections.unmodifiableList(kinds);
    }

    @SuppressWarnings("unchecked")
    public static EngineProfile load() throws IOException {
        String setting = System.getProperty("spellbench.priorityMana", "false");
        if (!"true".equals(setting) && !"false".equals(setting)) {
            throw new IOException("spellbench.priorityMana must be true or false");
        }
        boolean priorityMana = "true".equals(setting);
        Properties identity = new Properties();
        try (InputStream in = resource("engine-identity.properties")) {
            identity.load(in);
        }
        List<CatalogDeck> catalog = new ArrayList<>();
        byte[] bytes;
        try (InputStream in = resource("catalog.json")) {
            bytes = readAll(in);
        }
        try {
            // the file is a top-level array; wrap it so the strict reader (objects only) accepts it
            byte[] wrapped = ("{\"decks\":" + new String(bytes, StandardCharsets.UTF_8).trim() + "}")
                    .getBytes(StandardCharsets.UTF_8);
            List<Object> decks = (List<Object>) StrictJson.parseObject(wrapped).get("decks");
            for (Object d : decks) {
                Map<String, Object> deck = (Map<String, Object>) d;
                catalog.add(new CatalogDeck((String) deck.get("catalog_id"), (String) deck.get("name"),
                        (List<String>) deck.get("formats"),
                        Requests.decklist(deck.get("decklist"), "catalog " + deck.get("catalog_id"))));
            }
        } catch (StrictJson.Malformed | Requests.Invalid e) {
            throw new IOException("catalog.json: " + e.getMessage(), e);
        }
        return new EngineProfile(identity.getProperty("rules_snapshot_id"),
                identity.getProperty("card_pool_identity"), identity.getProperty("source_revision"), catalog,
                priorityMana);
    }

    public CatalogDeck deck(String catalogId) {
        for (CatalogDeck d : catalog) {
            if (d.catalogId.equals(catalogId)) {
                return d;
            }
        }
        return null;
    }

    public Map<String, Object> provenance() {
        Map<String, Object> p = new LinkedHashMap<>();
        p.put("engine_name", NAME);
        p.put("engine_version", VERSION);
        p.put("rules_snapshot_id", rulesSnapshotId);
        p.put("card_pool_identity", cardPoolIdentity);
        return p;
    }

    /** The hello_ok fields after the envelope (Section 9.1). */
    public Map<String, Object> helloOk(String requestId, long protocolMinor) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("response_type", "hello_ok");
        m.put("protocol", Requests.PROTOCOL);
        m.put("request_id", requestId);
        m.put("protocol_minor", Math.min(protocolMinor, 0L));
        Map<String, Object> engine = new LinkedHashMap<>();
        engine.put("name", NAME);
        engine.put("version", VERSION);
        engine.put("source_revision", sourceRevision);
        engine.put("rules_snapshot_id", rulesSnapshotId);
        engine.put("card_pool_identity", cardPoolIdentity);
        m.put("engine", engine);
        m.put("formats", new ArrayList<Object>(FORMATS));
        m.put("deck_sources", Arrays.<Object>asList("catalog", "decklist"));
        List<Object> decks = new ArrayList<>();
        for (CatalogDeck d : catalog) {
            Map<String, Object> deck = new LinkedHashMap<>();
            deck.put("catalog_id", d.catalogId);
            deck.put("name", d.name);
            List<Object> rows = new ArrayList<>();
            for (Requests.Row r : d.decklist) {
                Map<String, Object> row = new LinkedHashMap<>();
                row.put("name", r.name);
                row.put("count", r.count);
                rows.add(row);
            }
            deck.put("decklist", rows);
            decks.add(deck);
        }
        m.put("catalog", decks);
        Map<String, Object> rules = new LinkedHashMap<>();
        rules.put("mulligan", Arrays.<Object>asList("london", "none"));
        rules.put("starting_player", Arrays.<Object>asList("host_assigned"));
        m.put("rules_supported", rules);
        m.put("observation", observationFlags());
        m.put("decision_kinds", new ArrayList<Object>(decisionKinds));
        Map<String, Object> defaults = new LinkedHashMap<>();
        defaults.put("trigger_order", null);
        defaults.put("replacement_order", null);
        defaults.put("combat_damage_assignment", null);
        defaults.put("mana_payment", "engine_autopay");
        m.put("engine_defaults", defaults);
        m.put("rewind", true);
        Map<String, Object> fairness = new LinkedHashMap<>();
        fairness.put("noninterference_probe", false);
        m.put("fairness", fairness);
        m.put("extensions", new ArrayList<Object>());
        return m;
    }

    /** Section 6.9 flags, conservative (design draft Section 3.7); one flips on only with a faithfulness audit. */
    static Map<String, Object> observationFlags() {
        Map<String, Object> f = new LinkedHashMap<>();
        f.put("poison", true);
        f.put("player_counters", false);
        f.put("designations", false);
        f.put("player_progress", true);
        f.put("day_night", true);
        f.put("passed_seats", true);
        f.put("pending_triggers", true);
        f.put("keywords", true);
        f.put("full_name", true);
        f.put("exiled_by", false);
        f.put("stack_text", false);
        f.put("permanent_details", false);
        f.put("known_cards", false);
        return f;
    }

    private static InputStream resource(String name) throws IOException {
        InputStream in = EngineProfile.class.getResourceAsStream("/mage/player/spellbench/" + name);
        if (in == null) {
            throw new IOException("missing resource mage/player/spellbench/" + name);
        }
        return in;
    }

    private static byte[] readAll(InputStream in) throws IOException {
        java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream();
        byte[] buf = new byte[8192];
        int n;
        while ((n = in.read(buf)) > 0) {
            out.write(buf, 0, n);
        }
        return out.toByteArray();
    }
}
