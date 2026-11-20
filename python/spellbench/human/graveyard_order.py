"""Whether graveyard order can matter in a game, from the cards of both deck lists (``graveyard_order_cards_v1.json``).

Graveyard order is a real rule (CR 404.3): the owner of cards put into a graveyard at once orders them. In a game in
which no card reads that order, the order cannot change anything, and nobody is asked: the human-play bridge applies
the rule the bots trained with (``resolution-boundary-v1``), under which the cards keep the order the effect put them
there. In a game with a reader both players are asked, the person in one step for the whole batch.

The data is an audit: every card of a deck pool that mentions a graveyard is listed as a reader or as audited and
not a reader, with the reason. A card that is in neither list counts as unaudited (``unaudited``), which the tests
refuse for the decks the session deals.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Iterable

DATA = Path(__file__).with_name("graveyard_order_cards_v1.json")


@lru_cache(maxsize=1)
def cards() -> dict:
    data = json.loads(DATA.read_text(encoding="utf-8"))
    if data.get("schema") != "spellbench-graveyard-order-cards/v1":
        raise ValueError(f"{DATA.name}: unknown schema")
    if set(data["readers"]) & set(data["not_readers"]):
        raise ValueError(f"{DATA.name}: a card is listed both as a reader and as not a reader")
    return data


def readers(names: Iterable[str]) -> list[str]:
    """The cards among ``names`` that read graveyard order (sorted, distinct). Empty: order cannot matter."""
    return sorted(set(names) & set(cards()["readers"]))


def catalog_decks(catalog: dict) -> dict[str, list[str]]:
    """The card names of each deck of a public catalog document (``{"catalog": [{"catalog_id", "decklist"}]}``), the
    file the engine wrapper checks deck ids against and the session reads too, so both decide relevance alike."""
    return {entry["catalog_id"]: [row["name"] for row in entry["decklist"]] for entry in catalog["catalog"]}


def game_readers(decks: dict[str, list[str]], deck_ids: Iterable[str]) -> list[str]:
    """The reader cards of a game played with the decks ``deck_ids`` (``catalog_decks``)."""
    return readers(name for deck in deck_ids for name in decks[deck])


def audited(name: str) -> bool:
    data = cards()
    return name in data["readers"] or name in data["not_readers"]
