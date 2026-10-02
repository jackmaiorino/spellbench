package mage.player.spellbench.server;

import mage.player.spellbench.Secrets;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

/**
 * The host-computed identifiers of Section 4.3, which the engine recomputes to answer {@code deck_id_mismatch}
 * and to check {@code card_name_domain.domain_id}: SHA-256 over canonical JSON, as {@code "sha256:" + hex}.
 */
public final class Digests {

    /** Code point order (Python's str order), which differs from UTF-16 order only past the BMP. */
    static final Comparator<String> CODE_POINT = (a, b) -> {
        int i = 0;
        int j = 0;
        while (i < a.length() && j < b.length()) {
            int ca = a.codePointAt(i);
            int cb = b.codePointAt(j);
            if (ca != cb) {
                return Integer.compare(ca, cb);
            }
            i += Character.charCount(ca);
            j += Character.charCount(cb);
        }
        return Integer.compare(a.length() - i, b.length() - j);
    };

    private Digests() {
    }

    /** deck_id: the rows {"count", "name"}, sorted by name in code point order. */
    public static String deckId(List<Requests.Row> rows) {
        List<Requests.Row> sorted = new ArrayList<>(rows);
        sorted.sort((x, y) -> CODE_POINT.compare(x.name, y.name));
        List<Object> json = new ArrayList<>();
        for (Requests.Row r : sorted) {
            json.add(r.toJson());
        }
        return id(json);
    }

    /** card_name_domain.domain_id: the names, sorted in code point order. */
    public static String domainId(List<String> names) {
        List<String> sorted = new ArrayList<>(names);
        sorted.sort(CODE_POINT);
        return id(new ArrayList<Object>(sorted));
    }

    static String id(Object json) {
        return "sha256:" + Secrets.toHex(Secrets.sha256(StrictJson.canonical(json)));
    }
}
