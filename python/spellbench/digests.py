"""Host-computed identifiers and the per-game digest chain (spec 4.3, 11.8, 12.1).

Each identifier is ``"sha256:"`` plus the lowercase hex SHA-256 of canonical JSON.
"""

from __future__ import annotations

import hashlib
import unicodedata
from typing import Any, Iterable, Mapping, NoReturn, Sequence

from .errors import ValidationError
from .wire import canonical_json_dumps

GAME_DIGEST_DOMAIN = b"spellbench/v2/game-digest"
_U32_MAX = (1 << 32) - 1
_ROW_FIELDS = frozenset({"count", "name"})


def _fail(context: str, detail: str) -> NoReturn:
    raise ValidationError(f"{context}: {detail}")


def _card_name(value: Any, context: str) -> str:
    """An Oracle name: a nonempty string in Unicode NFC (spec 4.4). The error names the card."""
    if type(value) is not str or not value:
        _fail(context, "a card name is a nonempty string")
    if not unicodedata.is_normalized("NFC", value):
        _fail(context, f"card name {value!r} is not in Unicode NFC")
    return value


def _sha256_id(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_dumps(value)).hexdigest()


def deck_rows(decklist: Sequence[Mapping[str, Any]], context: str = "decklist") -> list[dict[str, Any]]:
    """The checked rows of a decklist (spec 12.1) as ``{"count", "name"}``, sorted by name in code point order.

    ``context`` starts every error message, so a caller can name the deck, for example
    ``"catalog[0] (Burn).decklist"``.
    """
    if not isinstance(decklist, (list, tuple)) or not decklist:
        _fail(context, "a decklist is a nonempty array of rows")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(decklist):
        where = f"{context}[{index}]"
        if not isinstance(row, Mapping) or set(row) != _ROW_FIELDS:
            _fail(where, "a deck row is an object with exactly the fields count and name")
        name = _card_name(row["name"], f"{where}.name")
        count = row["count"]
        if type(count) is not int or not 1 <= count <= _U32_MAX:
            _fail(f"{where}.count", f"a count is an integer from 1 to {_U32_MAX}")
        if name in seen:
            _fail(f"{where}.name", f"card name {name!r} appears twice")
        seen.add(name)
        rows.append({"count": count, "name": name})
    return sorted(rows, key=lambda entry: entry["name"])


def deck_id(decklist: Sequence[Mapping[str, Any]]) -> str:
    """``deck_id`` (spec 4.3): over the rows of :func:`deck_rows`."""
    return _sha256_id(deck_rows(decklist))


def _distinct_names(names: Iterable[str]) -> list[str]:
    if isinstance(names, str):
        _fail("names", "a card-name domain is an array of names, not one string")
    checked = [_card_name(name, f"names[{index}]") for index, name in enumerate(names)]
    return sorted(set(checked))


def domain_id(names: Sequence[str]) -> str:
    """``card_name_domain.domain_id`` (spec 4.3): over the distinct names, sorted in code point order."""
    return _sha256_id(_distinct_names(names))


def card_name_domain(names: Iterable[str]) -> dict[str, Any]:
    """The ``rules.card_name_domain`` object (spec 12.2): the distinct names, sorted, with their ``domain_id``."""
    distinct = _distinct_names(names)
    return {"domain_id": _sha256_id(distinct), "names": distinct}


def _minus_request_id(message: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in message.items() if key != "request_id"}


class GameDigest:
    """SHA-256 chain over one game's engine traffic (spec 11.8); agent traffic never enters it."""

    def __init__(self, reset_request: Mapping[str, Any]) -> None:
        self._d = hashlib.sha256(GAME_DIGEST_DOMAIN + canonical_json_dumps(_minus_request_id(reset_request))).digest()
        self._last_request: tuple[str, bytes] | None = None
        self._last_answered = False
        self._adjudicated = False

    def _chain(self, message: Mapping[str, Any]) -> None:
        self._d = hashlib.sha256(self._d + canonical_json_dumps(_minus_request_id(message))).digest()

    def add_response(self, response: Mapping[str, Any]) -> None:
        self._chain(response)

    def add_step(self, request: Mapping[str, Any], response: Mapping[str, Any] | None) -> None:
        key = (request["request_id"], canonical_json_dumps(request))
        if key == self._last_request:  # a retransmission and its cached response are chained once
            if not self._last_answered and response is not None:
                self._chain(response)
                self._last_answered = True
            return
        self._last_request, self._last_answered = key, response is not None
        self._chain(request)
        if response is not None:
            self._chain(response)

    def add_adjudication(self, *, classification: str, outcome: str, reason: str, winner: str | None) -> None:
        if self._adjudicated:
            raise ValueError("a game has at most one adjudication record")
        self._adjudicated = True
        self._chain({"adjudication": {"classification": classification, "outcome": outcome,
                                      "reason": reason, "winner": winner}})

    def chain_hex(self) -> str:
        return self._d.hex()

    def value(self) -> str:
        return "sha256:" + self._d.hex()
