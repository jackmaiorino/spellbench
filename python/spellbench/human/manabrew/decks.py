"""The Pauper decks Basilisk 2 trained with, as the Manabrew client's table deck list.

``pauper_decks.json`` holds the eight deck lists the board's engine deals (its hello_ok catalog). The client reads
its starter decks from ``/preset_decks/index.json`` and ``/preset_decks/<id>.json``; ``serve_client`` answers those
paths from here, so the table offers exactly these decks. A pick reaches the room as the deck's label, which
``catalog_id`` maps back to the board's deck.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .view import CARDS

DECKS: dict[str, list[dict[str, Any]]] = json.loads(
    Path(__file__).with_name("pauper_decks.json").read_text(encoding="utf-8"))["decks"]
ORDER = ("Wildfire", "Rally", "Affinity", "Elves", "Spy", "Burn", "CawGates", "Faeries")
ALL_DECKS = ORDER  # every deck the board deals; ``ORDER`` is what a session offers (``exclude`` narrows it)
SUFFIX = " (Basilisk 2 training deck)"
COLORS = {"Wildfire": "text-green-400", "Rally": "text-red-400", "Affinity": "text-blue-400",
          "Elves": "text-green-400", "Spy": "text-green-400", "Burn": "text-red-400", "CawGates": "text-sky-400",
          "Faeries": "text-blue-400"}


def card_names(deck_name: str) -> list[str]:
    """The distinct card names of a board deck's list (main deck), in list order."""
    return list(dict.fromkeys(row["name"] for row in DECKS[deck_name]))


def exclude(names: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    """Leave decks out of this process's table: the client is not offered them (``preset_index``), a pick of one is
    not a training deck (``catalog_id``), and a drawn deck never is one (``ORDER``). A name that is not a board deck
    is an error. Called once at start-up by the session and by the client server (``--exclude-decks``)."""
    global ORDER
    unknown = [n for n in names if n not in ALL_DECKS]
    if unknown:
        raise ValueError(f"not board decks: {', '.join(unknown)}")
    ORDER = tuple(d for d in ALL_DECKS if d not in names)
    if not ORDER:
        raise ValueError("every deck was excluded")
    return ORDER


def label(catalog_id: str) -> str:
    return catalog_id + SUFFIX


def catalog_id(deck_name: str | None) -> str | None:
    """The board deck a table pick names, or None for any other deck."""
    if not deck_name:
        return None
    base = deck_name[:-len(SUFFIX)] if deck_name.endswith(SUFFIX) else deck_name
    return base if base in DECKS and base in ORDER else None


def preset_id(catalog: str) -> str:
    return "spellbench_" + catalog.lower()


def preset_index() -> list[str]:
    return [preset_id(deck) for deck in ORDER if deck in DECKS]


def preset(catalog: str) -> dict[str, Any]:
    """One deck in the client's preset-deck file shape (name, count, set and number per card)."""
    cards = []
    for entry in DECKS[catalog]:
        info = CARDS.get(entry["name"], {})
        types = (info.get("type_line") or "").split(" - ")[0].replace("Token ", "").split()
        cards.append({"name": entry["name"], "count": entry["count"], "set": "", "cardNumber": "",
                      "manaCost": info.get("mana_cost", ""), "types": types, "text": info.get("text", ""),
                      "uris": {}})
    lands = {"Mountain", "Forest", "Island", "Swamp", "Plains", "Snow-Covered Forest"}
    cover = next((c["name"] for c in cards if c["name"] not in lands and "Land" not in c["types"]), cards[0]["name"])
    return {"label": label(catalog), "desc": "A deck Basilisk 2 trained with; the session deals exactly this list.",
            "color": COLORS.get(catalog, "text-neutral-300"), "format": "pauper", "coverCardName": cover,
            "cards": cards}


def by_preset_id() -> dict[str, str]:
    return {preset_id(deck): deck for deck in DECKS}


def lobby_deck(catalog: str) -> dict[str, Any]:
    """The deck a relay seat selects for ``catalog`` (the client's Deck shape)."""
    cards = []
    for entry in DECKS[catalog]:
        info = CARDS.get(entry["name"], {})
        for _ in range(int(entry["count"])):
            cards.append({"identity": {"id": entry["name"], "name": entry["name"], "setCode": "", "cardNumber": ""},
                          "uris": {}, "color": "", "colorIdentity": [], "manaCost": info.get("mana_cost", ""),
                          "cmc": 0, "types": [], "subtypes": [], "supertypes": [], "text": info.get("text", "")})
    return {"name": label(catalog), "format": "pauper", "cards": cards, "sideboard": []}
