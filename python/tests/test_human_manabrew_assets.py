"""The Manabrew client's symbol route (served from a local cache filled from Scryfall) and the rules-text table.

Nothing here reaches the network: Scryfall is a stub. The recorded-game check is skipped without the records.
"""

from __future__ import annotations

import gzip
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from spellbench.human import text
from spellbench.human.manabrew import build_cards, decks, serve_client, view
from spellbench.human.manabrew.serve_client import SymbolCache

SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><circle r="16"/></svg>'


class Upstream:
    """A stand-in for svgs.scryfall.io: serves ``files`` and counts the requests."""

    def __init__(self, files: dict[str, bytes | None] | None = None, fail: Exception | None = None) -> None:
        self.files = files if files is not None else {}
        self.fail = fail
        self.calls: list[tuple[str, float]] = []

    def __call__(self, file: str) -> bytes | None:
        self.calls.append((file, time.monotonic()))
        if self.fail is not None:
            raise self.fail
        return self.files.get(file, SVG)


# ---- symbol route ----------------------------------------------------------------------------------------------


def test_symbol_is_fetched_once_and_then_served_from_the_folder(tmp_path: Path) -> None:
    upstream = Upstream()
    cache = SymbolCache(tmp_path / "symbols", upstream)
    assert cache.get("W.svg") == SVG
    assert cache.get("W.svg") == SVG
    assert [call[0] for call in upstream.calls] == ["W.svg"]
    assert (tmp_path / "symbols" / "W.svg").read_bytes() == SVG
    assert not list((tmp_path / "symbols").glob("*.part"))
    again = Upstream()  # a new process finds the file already there and sends nothing
    assert SymbolCache(tmp_path / "symbols", again).get("W.svg") == SVG
    assert again.calls == []


@pytest.mark.parametrize("name", ["", "W", "W.png", "../W.svg", "..%2fW.svg", "a/b.svg", "a\\b.svg", ".svg",
                                  "W.svg.part", "\u00bd.svg", "X" * 17 + ".svg", "w.svg\n", "con:.svg"])
def test_only_symbol_file_names_are_looked_up(tmp_path: Path, name: str) -> None:
    upstream = Upstream()
    assert SymbolCache(tmp_path, upstream).get(name) is None
    assert upstream.calls == []


def test_every_symbol_of_the_training_decks_is_a_servable_file_name() -> None:
    symbols = set()
    for card in view.CARDS.values():
        symbols |= set(re.findall(r"\{([^}]+)\}", card["mana_cost"] + card["text"]))
    assert {"T", "W", "U", "B", "R", "G", "C", "X", "R/G", "2"} <= symbols
    for code in symbols:  # the client's file name: the code without its slashes (api/scryfall.ts manaSymbolUrl)
        assert serve_client.SYMBOL_FILE.fullmatch(code.replace("/", "") + ".svg"), code


def test_missing_symbol_and_bad_replies_are_not_asked_for_again_soon(tmp_path: Path) -> None:
    upstream = Upstream({"NOPE.svg": None, "HTML.svg": b"<html>sorry</html>",
                         "BIG.svg": b"<svg>" + b"x" * serve_client.SYMBOL_MAX_BYTES + b"</svg>"})
    cache = SymbolCache(tmp_path, upstream)
    for name in ("NOPE.svg", "HTML.svg", "BIG.svg"):
        assert cache.get(name) is None
        assert cache.get(name) is None
    assert [call[0] for call in upstream.calls] == ["NOPE.svg", "HTML.svg", "BIG.svg"]
    assert list(tmp_path.iterdir()) == []
    cache.failed["NOPE.svg"] = 0.0  # the retry time has passed
    assert cache.get("NOPE.svg") is None
    assert len(upstream.calls) == 4


def test_network_failure_stops_further_downloads_for_a_while(tmp_path: Path) -> None:
    upstream = Upstream(fail=urllib.error.URLError("no network"))
    cache = SymbolCache(tmp_path, upstream)
    assert cache.get("W.svg") is None
    assert cache.get("U.svg") is None  # no second download attempt while the network is known to be down
    assert len(upstream.calls) == 1
    cache.offline_until = 0.0
    assert cache.get("U.svg") is None
    assert len(upstream.calls) == 2


def test_downloads_are_serialised_and_spaced(tmp_path: Path) -> None:
    upstream = Upstream()
    cache = SymbolCache(tmp_path, upstream)
    names = ["W.svg", "U.svg", "B.svg", "R.svg", "G.svg", "W.svg", "U.svg"]
    threads = [threading.Thread(target=cache.get, args=(name,)) for name in names]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(call[0] for call in upstream.calls) == ["B.svg", "G.svg", "R.svg", "U.svg", "W.svg"]
    times = sorted(call[1] for call in upstream.calls)
    assert all(b - a >= serve_client.SYMBOL_GAP_S * 0.9 for a, b in zip(times, times[1:]))


def test_prewarm_fetches_the_common_symbols_once(tmp_path: Path) -> None:
    upstream = Upstream()
    cache = SymbolCache(tmp_path, upstream)
    cache.prewarm()
    cache.prewarm()
    assert sorted(call[0] for call in upstream.calls) == sorted(serve_client.SYMBOL_PREWARM)
    assert {"W.svg", "U.svg", "B.svg", "R.svg", "G.svg", "C.svg", "T.svg", "Q.svg"} <= set(serve_client.SYMBOL_PREWARM)
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(serve_client.SYMBOL_PREWARM)


def test_unwritable_folder_still_serves_and_does_not_refetch(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("not a folder")
    upstream = Upstream()
    cache = SymbolCache(blocker / "symbols", upstream)
    assert cache.get("T.svg") == SVG
    assert cache.get("T.svg") == SVG
    assert len(upstream.calls) == 1


def test_fetch_symbol_asks_scryfall_with_a_generic_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = []

    class Reply:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, limit):
            return SVG[:limit]

    def fake_urlopen(request, timeout):
        seen.append((request.full_url, dict(request.header_items()), timeout))
        return Reply()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert serve_client.fetch_symbol("WU.svg") == SVG
    url, headers, timeout = seen[0]
    assert url == "https://svgs.scryfall.io/card-symbols/WU.svg" and timeout <= 10
    assert headers["User-agent"] == serve_client.SYMBOL_AGENT == "spellbench-manabrew-client/1.0"

    def not_found(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(urllib.request, "urlopen", not_found)
    assert serve_client.fetch_symbol("NOPE.svg") is None

    def refused(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 503, "Unavailable", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(urllib.request, "urlopen", refused)
    with pytest.raises(urllib.error.HTTPError):
        serve_client.fetch_symbol("W.svg")


def test_client_server_serves_symbols_on_its_own_port_and_caches_them(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>")
    upstream = Upstream()
    server = ThreadingHTTPServer(("127.0.0.1", 0), serve_client.make_handler(
        dist, b"window.__MANABREW_RUNTIME__ = {};\n", SymbolCache(tmp_path / "cache", upstream)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        for _ in range(2):
            with urllib.request.urlopen(base + "/scryfall-symbols/R.svg") as reply:
                assert reply.status == 200
                assert reply.headers["Content-Type"] == "image/svg+xml"
                assert reply.headers["Cross-Origin-Resource-Policy"] == "same-origin"
                assert reply.read() == SVG
        assert [call[0] for call in upstream.calls] == ["R.svg"]
        for bad in ("/scryfall-symbols/", "/scryfall-symbols/..%2f..%2fconfig.js", "/scryfall-symbols/%C2%BD.svg",
                    "/scryfall-symbols/a%2fb.svg", "/scryfall-symbols/W.png"):
            with pytest.raises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(base + bad)
            assert error.value.code == 404, bad
        assert [call[0] for call in upstream.calls] == ["R.svg"]  # nothing went upstream for a bad name
        with urllib.request.urlopen(base + "/config.js") as reply:  # the other routes are unchanged
            assert reply.read().startswith(b"window.__MANABREW_RUNTIME__")
        with urllib.request.urlopen(base + "/preset_decks/index.json") as reply:
            assert len(json.loads(reply.read())) == 8
        with urllib.request.urlopen(base + "/some/client/route") as reply:
            assert reply.read() == b"<html></html>"
    finally:
        server.shutdown()
        server.server_close()


def test_default_symbol_folder_is_beside_the_served_files(tmp_path: Path) -> None:
    (tmp_path / "scryfall-symbols").mkdir()
    (tmp_path / "scryfall-symbols" / "W.svg").write_bytes(SVG)
    handler = serve_client.make_handler(tmp_path, b"")
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:  # a symbol file already in <dist>/scryfall-symbols is served with no download
        with urllib.request.urlopen(f"http://127.0.0.1:{server.server_address[1]}/scryfall-symbols/W.svg") as reply:
            assert reply.read() == SVG
    finally:
        server.shutdown()
        server.server_close()


# ---- rules-text table ------------------------------------------------------------------------------------------

# The keys cards.json had before it was built from Scryfall: none may go.
OLD_KEYS = (
    "Avenging Hunter", "Azorius Guildgate", "Balustrade Spy", "Basilisk Gate", "Bird Token", "Black Mage's Rod",
    "Blood Fountain", "Blood Token", "Brainstorm", "Burning-Tree Emissary", "Cast Down", "Chain Lightning",
    "Citadel Gate", "Cleansing Wildfire", "Clockwork Percussionist", "Clue Token", "Counterspell", "Cryogen Relic",
    "Dispel", "Dread Return", "Drossforge Bridge", "Eldrazi Spawn Token", "Elf Warrior Token",
    "Elves of Deep Shadow", "Elvish Mystic", "End the Festivities", "Eviscerator's Insight",
    "Experimental Synthesizer", "Faerie Miscreant", "Faerie Seer", "Faithless Looting", "Fanatical Offering",
    "Fiery Temper", "Fireblast", "Food Token", "Force Spike", "Forest", "Fyndhorn Elves", "Galvanic Blast",
    "Gatecreeper Vine", "Generous Ent", "Goblin Bushwhacker", "Goblin Token", "Goblin Tomb Raider",
    "Grab the Prize", "Great Furnace", "Guardian of the Guildpact", "Guttersnipe", "Harrier Strix", "Heap Gate",
    "Highway Robbery", "Humbling Elder", "Hunter's Blowgun", "Ichor Wellspring", "Idyllic Beachfront", "Island",
    "Journey to Nowhere", "Krark-Clan Shaman", "Land Grant", "Lava Dart", "Lead the Stampede", "Lembas",
    "Lightning Bolt", "Llanowar Elves", "Lorien Revealed", "Lotleth Giant", "Lotus Petal", "Makeshift Munitions",
    "Map Token", "Masked Meower", "Masked Vandal", "Mesmeric Fiend", "Mistvault Bridge", "Moon-Circuit Hacker",
    "Mountain", "Myr Enforcer", "Nihil Spellbomb", "Ninja of the Deep Hours", "Nyxborn Hydra", "Of One Mind",
    "Outlaw Medic", "Overgrown Battlement", "Preordain", "Priest of Titania", "Prismatic Strands",
    "Pulse of Murasa", "Quirion Ranger", "Rally at the Hornburg", "Reckless Impulse", "Reckoner's Bargain",
    "Refurbished Familiar", "Sacred Cat", "Sagu Wildling", "Saiba Cryptomancer", "Samurai Token",
    "Saruli Caretaker", "Sea Gate", "Seat of the Synod", "Silverbluff Bridge", "Slagwoods Bridge", "Snap",
    "Sneaky Snacker", "Snow-Covered Forest", "Spell Pierce", "Spellstutter Sprite", "Spirit Token", "Squadron Hawk",
    "Swamp", "The Modern Age", "Thoughtcast", "Thraben Charm", "Timberwatch Elf", "Tinder Wall", "Toxin Analysis",
    "Treasure Token", "Troll of Khazad-dum", "Twisted Landscape", "Vault of Whispers", "Vector Glider",
    "Voldaren Epicure", "Wall of Roots", "Wellwisher", "Winding Way", "Writhing Chrysalis",
)


def test_table_covers_every_card_and_token_of_the_nine_training_decks() -> None:
    names = build_cards.deck_names()
    assert len(build_cards.TERROR) == 14 and {"Tolarian Terror", "Murmuring Mystic", "Ponder"} <= set(names)
    for name in names:
        assert name in view.CARDS, name
        assert name.split(" // ")[0] in view.CARDS
    for deck in decks.DECKS.values():
        for entry in deck:
            assert entry["name"] in view.CARDS, entry["name"]
    for token in ("Blood Token", "Bird Illusion Token", "Clue Token", "Eldrazi Spawn Token", "Food Token",
                  "Hero Token", "Human Soldier Token", "Map Token", "Sacred Cat Embalmed Token", "Samurai Token",
                  "Skeleton Token", "Treasure Token"):  # the kernel's token catalog
        assert token in view.CARDS, token
    for token in build_cards.LEGACY_TOKENS:  # tokens the old file had: the key stays
        assert token in view.CARDS


def test_old_names_keep_their_keys() -> None:
    assert [name for name in OLD_KEYS if name not in view.CARDS] == []
    for face in ("The Modern Age", "Vector Glider", "Lorien Revealed", "Troll of Khazad-dum", "Sagu Wildling"):
        assert face in view.CARDS  # the engine's own spelling (no accents), one entry per face


def test_table_entries_are_well_formed_and_plain() -> None:
    assert len(view.CARDS) >= 140
    for name, entry in view.CARDS.items():
        assert set(entry) == {"mana_cost", "type_line", "power", "toughness", "text"}, name
        assert entry["type_line"], name
        for field in ("mana_cost", "type_line", "text"):
            assert entry[field].isascii(), (name, field)  # no long dash, no curly quote, no bullet
        assert all(entry[p] is None or isinstance(entry[p], str) for p in ("power", "toughness")), name
    assert view.CARDS["Lightning Bolt"]["text"].startswith("Lightning Bolt deals 3 damage")
    assert view.CARDS["Burning-Tree Emissary"]["mana_cost"] == "{R/G}{R/G}"
    assert view.CARDS["Quirion Ranger"]["type_line"] == "Creature - Elf Ranger"
    assert view.CARDS["Skeleton Token"]["power"] == "4" and view.CARDS["Skeleton Token"]["toughness"] == "1"
    assert view.CARDS["Vector Glider"]["power"] == "2" and "Flying" in view.CARDS["Vector Glider"]["text"]
    assert view.CARDS["The Modern Age // Vector Glider"] == view.CARDS["The Modern Age"]


def test_modal_spell_bullets_still_label_the_modes() -> None:
    mode = {"mode_index": 1, "mode_count": 3, "source": {"card_name": "Thraben Charm"}}
    assert text.mode_label(mode) == "Mode 2: Destroy target enchantment."


def test_preset_deck_lists_carry_rules_text_and_types() -> None:
    for catalog in decks.DECKS:
        for card in decks.preset(catalog)["cards"]:
            assert card["types"] and card["manaCost"] is not None and "text" in card, card["name"]
    elves = {c["name"]: c for c in decks.preset("Elves")["cards"]}
    assert elves["Quirion Ranger"]["types"] == ["Creature"]
    assert elves["Quirion Ranger"]["text"].startswith("Return a Forest you control to its owner's hand")


def seats() -> view.Seats:
    return view.Seats("p0", "player-0", "player-1", {"player-0": "You", "player-1": "Bot"})


def test_an_unknown_name_renders_an_empty_rules_box() -> None:
    for name in ("Not A Real Card", "lightning bolt", "Lightning Bolt Token", "Lightning", ""):
        dto = view.card_dto({"object_id": "o1", "card_name": name, "full_name": name, "owner_seat": "p0",
                             "controller_seat": "p0", "characteristics": {"types": ["instant"]}}, seats(), "hand")
        assert dto["text"] == "" and dto["manaCost"] == "", name
        assert "basePower" not in dto and "baseToughness" not in dto


def test_known_name_renders_its_oracle_text() -> None:
    dto = view.card_dto({"object_id": "o1", "card_name": "Chain Lightning", "full_name": "Chain Lightning",
                         "owner_seat": "p0", "controller_seat": "p0", "characteristics": {"types": ["sorcery"]}},
                        seats(), "hand")
    assert dto["manaCost"] == "{R}" and dto["text"].startswith("Chain Lightning deals 3 damage to any target.")


# ---- the builder (Scryfall stubbed) ------------------------------------------------------------------------------

DASH = chr(0x2014)


def scry_card(name, text="", cost="", types="Creature", **extra):
    return {"name": name, "mana_cost": cost, "type_line": types, "oracle_text": text, **extra}


def fake_scryfall(cards, tokens=None, dungeons=None, missing=()):
    """A ``post`` for build_cards.build: answers name and id collections from the given objects."""
    pool = {build_cards.ascii_name(c["name"].split(" // ")[0]): c for c in cards}  # Scryfall ignores accents
    by_id = {t["id"]: t for t in (tokens or [])} | {d["id"]: d for d in (dungeons or [])}
    calls: list[dict] = []

    def post(url, body):
        calls.append(body)
        assert url == build_cards.API + "/cards/collection" and len(body["identifiers"]) <= build_cards.BATCH
        data, not_found = [], []
        for item in body["identifiers"]:
            if "name" in item:
                found = pool.get(item["name"])
            else:
                found = by_id.get(item["id"])
            if found is None or item.get("name") in missing:
                not_found.append(item)
            else:
                data.append(found)
        return {"object": "list", "data": data, "not_found": not_found}

    post.calls = calls  # type: ignore[attr-defined]
    return post


def test_builder_turns_oracle_data_into_table_entries() -> None:
    bolt = scry_card("Lightning Bolt", "Lightning Bolt deals 3 damage to any target.", "{R}", "Instant")
    charm = scry_card("Thraben Charm", f"Choose one {DASH}\n\u2022 One.\n\u2022 Two.", "{1}{W}", "Instant")
    giant = scry_card("Lotleth Giant", f"Undergrowth {DASH} When this creature enters, it deals 1 damage.", "{6}{B}",
                      f"Creature {DASH} Zombie Giant", power="6", toughness="5")
    lorien = scry_card("L\u00f3rien Revealed", "Draw three cards.", "{3}{U}{U}", "Sorcery")
    adventure = {"name": "Sagu Wildling // Roost Seek", "layout": "adventure", "card_faces": [
        scry_card("Sagu Wildling", "Flying", "{4}{G}", f"Creature {DASH} Dragon", power="3", toughness="3"),
        scry_card("Roost Seek", "Search.", "{G}", f"Sorcery {DASH} Omen")]}
    table = build_cards.build(fake_scryfall([bolt, charm, giant, lorien, adventure]),
                              ["Lightning Bolt", "Thraben Charm", "Lotleth Giant", "Lorien Revealed",
                               "Sagu Wildling // Roost Seek"])
    assert table["Lightning Bolt"] == {"mana_cost": "{R}", "type_line": "Instant", "power": None,
                                       "toughness": None, "text": "Lightning Bolt deals 3 damage to any target."}
    assert table["Thraben Charm"]["text"] == "Choose one -\n* One.\n* Two."
    assert table["Lotleth Giant"]["text"].startswith("Undergrowth - When this creature enters")
    assert table["Lotleth Giant"]["type_line"] == "Creature - Zombie Giant" and table["Lotleth Giant"]["power"] == "6"
    assert "Lorien Revealed" in table and "L\u00f3rien Revealed" not in table  # the engine's spelling
    assert table["Sagu Wildling"]["type_line"] == "Creature - Dragon"
    assert table["Roost Seek"]["type_line"] == "Sorcery - Omen"
    assert table["Sagu Wildling // Roost Seek"] == table["Sagu Wildling"]  # the full name holds the front face
    assert list(table) == sorted(table)
    assert not any(DASH in json.dumps(entry, ensure_ascii=False) for entry in table.values())


def test_builder_adds_the_tokens_a_card_and_the_initiative_make() -> None:
    hunter = scry_card("Avenging Hunter", "Trample", "{4}{G}", "Creature", all_parts=[
        {"component": "combo_piece", "id": "dungeon-1", "name": "Undercity // The Initiative",
         "type_line": f"Dungeon {DASH} Undercity // Card"},
        {"component": "combo_piece", "id": "hunter", "name": "Avenging Hunter", "type_line": "Creature"}])
    cat = scry_card("Sacred Cat", "Lifelink", "{W}", "Creature", all_parts=[
        {"component": "token", "id": "cat-1", "name": "Sacred Cat", "type_line": "Token Creature"}])
    undercity = {"id": "dungeon-1", "name": "Undercity // The Initiative", "all_parts": [
        {"component": "token", "id": "skel-1", "name": "Skeleton", "type_line": "Token Creature"},
        {"component": "token", "id": "treasure-1", "name": "Treasure", "type_line": "Token Artifact"}]}
    tokens = [
        {"id": "cat-1", "name": "Sacred Cat", "type_line": f"Token Creature {DASH} Zombie Cat", "power": "1",
         "toughness": "1", "oracle_text": "Lifelink", "mana_cost": ""},
        {"id": "skel-1", "name": "Skeleton", "type_line": f"Token Creature {DASH} Skeleton", "power": "4",
         "toughness": "1", "oracle_text": "Menace", "mana_cost": ""},
        {"id": "treasure-1", "name": "Treasure", "type_line": f"Token Artifact {DASH} Treasure",
         "oracle_text": "{T}, Sacrifice this token: Add one mana of any color.", "mana_cost": ""}]
    table = build_cards.build(fake_scryfall([hunter, cat], tokens, [undercity]), ["Avenging Hunter", "Sacred Cat"])
    assert table["Sacred Cat Embalmed Token"]["type_line"] == "Token Creature - Zombie Cat"  # the engine's name
    assert table["Skeleton Token"]["power"] == "4" and table["Treasure Token"]["type_line"] == "Token Artifact - Treasure"
    assert "Undercity // The Initiative" not in table
    for legacy in build_cards.LEGACY_TOKENS:
        assert table[legacy]["mana_cost"] == "" and table[legacy]["type_line"].startswith("Token")


def test_builder_refuses_a_name_scryfall_does_not_know_and_conflicting_tokens() -> None:
    with pytest.raises(SystemExit, match="does not know"):
        build_cards.build(fake_scryfall([]), ["Nothing Here"])
    one = scry_card("One", "", "", "Creature", all_parts=[{"component": "token", "id": "t1", "name": "Blood"}])
    two = scry_card("Two", "", "", "Creature", all_parts=[{"component": "token", "id": "t2", "name": "Blood"}])
    tokens = [{"id": "t1", "name": "Blood", "type_line": "Token Artifact", "oracle_text": "A"},
              {"id": "t2", "name": "Blood", "type_line": "Token Artifact", "oracle_text": "B"}]
    with pytest.raises(SystemExit, match="two different tokens"):
        build_cards.build(fake_scryfall([one, two], tokens), ["One", "Two"])


def test_builder_batches_names_in_requests_of_at_most_75() -> None:
    cards = [scry_card(f"Card {i:03d}") for i in range(160)]
    post = fake_scryfall(cards)
    table = build_cards.build(post, [c["name"] for c in cards])
    assert len(table) >= 160 and [len(b["identifiers"]) for b in post.calls] == [75, 75, 10]


def test_scryfall_client_spaces_requests_and_never_resends_a_cached_one(monkeypatch: pytest.MonkeyPatch,
                                                                      tmp_path: Path) -> None:
    sent = []

    class Reply:
        def __init__(self, raw):
            self.raw = raw

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return self.raw

    def fake_urlopen(request, timeout):
        sent.append((request.full_url, request.get_method(), dict(request.header_items()), time.monotonic()))
        return Reply(json.dumps({"data": [], "not_found": []}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    client = build_cards.Scryfall(tmp_path / "cache")
    client(build_cards.API + "/cards/collection", {"identifiers": [{"name": "A"}]})
    client(build_cards.API + "/cards/collection", {"identifiers": [{"name": "B"}]})
    client(build_cards.API + "/cards/collection", {"identifiers": [{"name": "A"}]})  # cached: no request
    assert len(sent) == 2
    assert sent[1][3] - sent[0][3] >= build_cards.REQUEST_GAP_S * 0.9
    url, method, headers, _ = sent[0]
    assert method == "POST" and headers["User-agent"] == build_cards.USER_AGENT == "spellbench-manabrew-cards/1.0"
    assert set(headers) == {"User-agent", "Accept", "Content-type"}  # nothing else about the machine or the person


def test_builder_writes_lf_and_a_stable_table(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cards = [scry_card("Lightning Bolt", "Bolt.", "{R}", "Instant")]
    monkeypatch.setattr(build_cards, "Scryfall", lambda cache: fake_scryfall(cards))
    monkeypatch.setattr(build_cards, "deck_names", lambda: ["Lightning Bolt"])
    out = tmp_path / "cards.json"
    assert build_cards.main(["--out", str(out)]) == 0
    raw = out.read_bytes()
    assert b"\r" not in raw and raw.endswith(b"}\n")
    assert json.loads(raw)["Lightning Bolt"]["text"] == "Bolt."


# ---- the recorded games (skipped without the records) ------------------------------------------------------------

RECORDS = Path(os.environ.get("SPELLBENCH_HUMAN_RECORDS", "E:/artifacts/chains-20261107-human-interim/engine-records/cold"))


@pytest.mark.skipif(not list(RECORDS.glob("*/engine.jsonl.gz")), reason="the recorded human games are not on this machine")
def test_every_card_name_the_engine_reported_in_the_recorded_games_has_an_entry() -> None:
    names: set[str] = set()
    for path in RECORDS.glob("*/engine.jsonl.gz"):
        raw = gzip.open(path, "rt", encoding="utf-8", errors="replace").read()
        names |= set(re.findall(r'"(?:card_name|full_name)":\s*"([^"]+)"', raw))
    assert len(names) >= 30
    assert sorted(name for name in names if name not in view.CARDS) == []
