"""Write ``cards.json``: rules text for the cards of the nine training decks, for the Manabrew client's card view.

Source: Oracle data from the Scryfall API (https://scryfall.com/docs/api; see NOTICE.md for its terms). The cards are
those of the eight board decks (``pauper_decks.json``) plus the ninth training deck, Terror (``TERROR``), and the
tokens those cards make (the ``all_parts`` links Scryfall gives each card; for "you take the initiative", the
Undercity's). One ``POST /cards/collection`` request carries up to 75 names, so a rebuild is a handful of requests,
spaced out, with a descriptive User-Agent that names this program and nothing else. ``--cache DIR`` keeps the raw
responses, and a request already in the cache is never sent again.

The file maps a name to ``mana_cost``, ``type_line``, ``power``, ``toughness`` and ``text``. The names are the ones
the engine reports: a card's own name (a two-faced card has one entry per face, and one under its full name that
holds its front face), and a token's name followed by " Token". Rules text is Oracle text with the repository's
plain characters: the long dash written as a hyphen and a modal bullet as "*" (``text.mode_label`` reads those
lines). A name that is not in the file shows an empty rules box.

Run: ``python -m spellbench.human.manabrew.build_cards [--cache DIR]``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import unicodedata
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping

API = "https://api.scryfall.com"
USER_AGENT = "spellbench-manabrew-cards/1.0"
REQUEST_GAP_S = 0.2  # Scryfall asks for 50 to 100 ms between requests
BATCH = 75  # identifiers per /cards/collection request
HERE = Path(__file__).parent
TARGET = HERE / "cards.json"

# The ninth training deck (Mono-Blue Terror; the board's deck list leaves it out): its distinct main-deck names.
TERROR = ("Brainstorm", "Counterspell", "Cryptic Serpent", "Deem Inferior", "Deep Analysis", "Dispel", "Island",
          "Lorien Revealed", "Mental Note", "Murmuring Mystic", "Ponder", "Sleep of the Dead", "Thought Scour",
          "Tolarian Terror")

# Scryfall token name -> the name the engine gives that token, where it is not "<name> Token".
TOKEN_NAMES = {"Sacred Cat": "Sacred Cat Embalmed Token"}

# Tokens an earlier version of this file carried that no card of the nine decks makes. Kept as they were so no key
# disappears; the Manabrew view only looks a token up by the name the engine reports.
LEGACY_TOKENS = {
    "Goblin Token": {"type_line": "Token Creature - Goblin", "power": "1", "toughness": "1", "text": ""},
    "Elf Warrior Token": {"type_line": "Token Creature - Elf Warrior", "power": "1", "toughness": "1", "text": ""},
    "Bird Token": {"type_line": "Token Creature - Bird", "power": "1", "toughness": "1", "text": "Flying"},
    "Spirit Token": {"type_line": "Token Creature - Spirit", "power": "1", "toughness": "1", "text": "Flying"},
}

_PLAIN = {0x2014: "-", 0x2013: "-", 0x2212: "-", 0x2022: "*", 0x2018: "'", 0x2019: "'"}

Post = Callable[[str, Mapping[str, Any]], Any]


def plain(text: str) -> str:
    """The repository keeps no long dash in its text: rules and type lines write it as a hyphen, a modal bullet as
    "*", curly quotes as straight ones."""
    return text.translate(_PLAIN)


def deck_names() -> list[str]:
    """Every distinct card name of the nine training decks."""
    decks = json.loads((HERE / "pauper_decks.json").read_text(encoding="utf-8"))["decks"]
    return sorted({entry["name"] for deck in decks.values() for entry in deck} | set(TERROR))


def ascii_name(name: str) -> str:
    """The engine writes names without accents ("Lorien Revealed"); Scryfall has "Lórien Revealed"."""
    return "".join(ch for ch in unicodedata.normalize("NFKD", name) if not unicodedata.combining(ch))


def _entry(face: Mapping[str, Any]) -> dict[str, Any]:
    return {"mana_cost": face.get("mana_cost") or "", "type_line": plain(face.get("type_line") or ""),
            "power": face.get("power") or None, "toughness": face.get("toughness") or None,
            "text": plain(face.get("oracle_text") or "")}


def entries(card: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """The cards.json entries one Scryfall card gives: its own name, plus each face of a two-faced card."""
    faces = card.get("card_faces") or []
    if faces and "oracle_text" not in card:
        out = {ascii_name(face["name"]): _entry(face) for face in faces}
        out[ascii_name(card["name"])] = out[ascii_name(faces[0]["name"])]  # under its full name: the front face
        return out
    return {ascii_name(card["name"]): _entry(card)}


def token_entries(token: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    name = TOKEN_NAMES.get(token["name"], token["name"] + " Token")
    return {name: _entry(token)}


def _front(name: str) -> str:
    return name.split(" // ")[0]


def build(post: Post, names: list[str] | None = None) -> dict[str, dict[str, Any]]:
    """The cards.json table for ``names`` (default: the nine decks) and the tokens they make."""
    wanted = names if names is not None else deck_names()
    found: list[Mapping[str, Any]] = []
    missing: list[str] = []
    fronts = sorted({_front(n) for n in wanted})
    for i in range(0, len(fronts), BATCH):
        reply = post(f"{API}/cards/collection", {"identifiers": [{"name": n} for n in fronts[i:i + BATCH]]})
        found += reply["data"]
        missing += [item.get("name", "?") for item in reply.get("not_found", [])]
    if missing:
        raise SystemExit(f"Scryfall does not know: {sorted(missing)}")
    table: dict[str, dict[str, Any]] = {}
    token_ids: set[str] = set()
    dungeons: set[str] = set()
    for card in found:
        table.update(entries(card))
        for part in card.get("all_parts") or []:
            if part.get("component") == "token":
                token_ids.add(part["id"])
            elif part.get("type_line", "").startswith("Dungeon"):  # "you take the initiative": the Undercity's tokens
                dungeons.add(part["id"])
    for dungeon in sorted(dungeons):
        reply = post(f"{API}/cards/collection", {"identifiers": [{"id": dungeon}]})
        token_ids.update(part["id"] for card in reply["data"] for part in card.get("all_parts") or []
                         if part.get("component") == "token")
    ids = sorted(token_ids)
    tokens: list[Mapping[str, Any]] = []
    for i in range(0, len(ids), BATCH):
        reply = post(f"{API}/cards/collection", {"identifiers": [{"id": t} for t in ids[i:i + BATCH]]})
        tokens += reply["data"]
        if reply.get("not_found"):
            raise SystemExit(f"Scryfall does not know tokens: {reply['not_found']}")
    for token in tokens:
        for name, entry in token_entries(token).items():
            if name in table and table[name] != entry:
                raise SystemExit(f"two different tokens named {name!r}: {table[name]} and {entry}")
            table[name] = entry
    for name, entry in LEGACY_TOKENS.items():
        table.setdefault(name, {"mana_cost": "", "power": None, "toughness": None, **entry})
    return {name: table[name] for name in sorted(table)}


class Scryfall:
    """POST client: one request at a time, spaced out, with the raw replies kept in ``cache`` when one is given."""

    def __init__(self, cache: Path | None = None) -> None:
        self.cache = cache
        self.last = 0.0

    def __call__(self, url: str, body: Mapping[str, Any]) -> Any:
        data = json.dumps(body, sort_keys=True).encode()
        spot = self.cache / (hashlib.sha256(url.encode() + data).hexdigest()[:20] + ".json") if self.cache else None
        if spot is not None and spot.is_file():
            return json.loads(spot.read_text(encoding="utf-8"))
        wait = self.last + REQUEST_GAP_S - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        request = urllib.request.Request(url, data=data, method="POST", headers={
            "User-Agent": USER_AGENT, "Accept": "application/json", "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
        self.last = time.monotonic()
        if spot is not None:
            spot.parent.mkdir(parents=True, exist_ok=True)
            spot.write_bytes(raw)
        return json.loads(raw)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--cache", type=Path, help="keep (and reuse) the raw Scryfall replies in this folder")
    parser.add_argument("--out", type=Path, default=TARGET)
    args = parser.parse_args(argv)
    table = build(Scryfall(args.cache))
    text = json.dumps(table, indent=1, ensure_ascii=False, sort_keys=True) + "\n"
    args.out.write_bytes(text.encode("utf-8"))  # LF on every platform, like the rest of the repository
    print(f"{len(table)} entries -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
