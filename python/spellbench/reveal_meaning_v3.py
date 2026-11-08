"""Opt-in public reveal evidence and conservative hand-name constraints.

This module accepts an already player-visible transcript, never engine objects.
Producers must establish the advertised evidence before publishing an arrival.
An atomic operation is delivered whole; only its own arrivals can bind reveals.
The frozen public-history v1 and W1 entrant do not import this module.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
from typing import Any

from . import _schema
from .errors import ValidationError

SCHEMA = "x_reveal_meaning_v3"
SEATS = frozenset(_schema.SEATS)
PUBLIC_SOURCES = frozenset({"battlefield", "graveyard", "stack", "exile", "command"})


class RevealMeaningError(ValidationError):
    pass


def _fields(value: Any, expected: set[str]) -> dict:
    if type(value) is not dict or set(value) != expected:
        raise RevealMeaningError("unexpected reveal transcript fields")
    return value


def _integer(value: Any) -> int:
    try:
        return _schema.safe_int(value, "reveal sequence or count")
    except ValidationError as exc:
        raise RevealMeaningError(str(exc)) from exc


def _name(value: Any) -> str:
    try:
        return _schema.card_name(value, "reveal card name")
    except ValidationError as exc:
        raise RevealMeaningError(str(exc)) from exc


def _owner(value: Any) -> str:
    if type(value) is not str or value not in SEATS:
        raise RevealMeaningError("invalid public owner seat")
    return value


def arrival_token(operation: int, event: int) -> str:
    """A viewer's transcript positions, independent of native allocation IDs."""
    return f"arrival:{_integer(operation)}:{_integer(event)}"


class RevealReducerV3:
    """Transactional stream validation with exact duplicate-operation delivery.

    Arrival claims and unlinked existence claims may overlap. Their lower
    bounds combine by maximum, never addition. An ambiguous departure drops
    copy correspondence and keeps only conservative name counts.
    """

    def __init__(self) -> None:
        self._next = 0
        self._seen: dict[int, str] = {}
        self._arrivals: dict[str, tuple[str, str]] = {}
        self._present: Counter[tuple[str, str]] = Counter()

    @staticmethod
    def _bounds(arrivals, present) -> Counter:
        counts = Counter(arrivals.values())
        return Counter({key: max(counts[key], present[key]) for key in counts.keys() | present.keys()
                        if max(counts[key], present[key]) > 0})

    def known_hand(self) -> list[dict]:
        return [{"owner_seat": owner, "card_name": name, "minimum": count}
                for (owner, name), count in sorted(self._bounds(self._arrivals, self._present).items())]

    def absorb(self, transcript: Any) -> None:
        self._commit(self._prepare(transcript))

    def _prepare(self, transcript: Any) -> tuple:
        """Stage a batch without mutation, for atomic adapter/host validation."""
        _fields(transcript, {"schema", "operations"})
        if transcript["schema"] != SCHEMA or type(transcript["operations"]) is not list:
            raise RevealMeaningError("unsupported reveal transcript")
        arrivals, present = dict(self._arrivals), self._present.copy()
        next_sequence = self._next
        accepted: dict[int, str] = {}
        for operation in transcript["operations"]:
            _fields(operation, {"sequence", "events"})
            sequence = _integer(operation["sequence"])
            if type(operation["events"]) is not list:
                raise RevealMeaningError("operation events must be a list")
            try:
                canonical = json.dumps(operation, sort_keys=True, separators=(",", ":"), allow_nan=False)
            except (ValueError, TypeError) as exc:
                raise RevealMeaningError("operation is not canonical JSON data") from exc
            previous = accepted.get(sequence, self._seen.get(sequence))
            if previous is not None:
                if previous != canonical:
                    raise RevealMeaningError("changed duplicate operation")
                continue
            if sequence != next_sequence:
                raise RevealMeaningError("noncontiguous public operation sequence")
            self._operation(sequence, operation["events"], arrivals, present)
            accepted[sequence] = canonical
            next_sequence += 1
        return arrivals, present, accepted, next_sequence

    def _commit(self, prepared: tuple) -> None:
        # Internal callers commit only their own immediately prepared batch.
        arrivals, present, accepted, next_sequence = prepared
        self._arrivals, self._present = arrivals, present
        self._seen.update(accepted)
        self._next = next_sequence

    @classmethod
    def _operation(cls, sequence: int, events: list, arrivals: dict, present: Counter) -> None:
        # Only eligible tokens from this exact operation may establish a link.
        eligible: dict[str, tuple[str, str | None]] = {}
        unresolved_searches: set[str] = set()
        for index, event in enumerate(events):
            if type(event) is not dict:
                raise RevealMeaningError("malformed public reveal event")
            kind = event.get("kind")
            if type(kind) is not str:
                raise RevealMeaningError("invalid public reveal event kind")
            if kind == "hand_arrival":
                _fields(event, {"kind", "owner_seat", "card_name", "evidence"})
                owner = _owner(event["owner_seat"])
                evidence = event["evidence"]
                if type(evidence) is not dict:
                    raise RevealMeaningError("arrival lacks visible evidence")
                if evidence.get("kind") == "public_transfer":
                    _fields(evidence, {"kind", "from_zone"})
                    if type(evidence["from_zone"]) is not str or evidence["from_zone"] not in PUBLIC_SOURCES:
                        raise RevealMeaningError("transfer source is not continuously public")
                    name = _name(event["card_name"])
                elif evidence.get("kind") == "search_reveal":
                    _fields(evidence, {"kind"})
                    # The producer publicly identifies its search outcome.
                    # The matching reveal supplies its name in this operation.
                    if event["card_name"] is not None:
                        raise RevealMeaningError("search outcome must bind its reveal")
                    name = None
                else:
                    raise RevealMeaningError("unsupported arrival evidence")
                token = arrival_token(sequence, index)
                eligible[token] = (owner, name)
                if name is None:
                    unresolved_searches.add(token)
                else:
                    arrivals[token] = (owner, name)
            elif kind == "card_revealed":
                meaning = event.get("meaning")
                required = {"kind", "owner_seat", "card_name", "meaning"}
                if meaning == "moved":
                    required.add("arrival")
                _fields(event, required)
                owner, name = _owner(event["owner_seat"]), _name(event["card_name"])
                if meaning == "present":
                    present[(owner, name)] = max(1, present[(owner, name)])
                elif meaning == "moved":
                    token = event["arrival"]
                    if type(token) is not str or token not in eligible:
                        raise RevealMeaningError("missing or expired arrival link")
                    arrival_owner, arrival_name = eligible[token]
                    if arrival_owner != owner or arrival_name not in (None, name):
                        raise RevealMeaningError("arrival owner or name changed")
                    eligible[token] = (owner, name)
                    arrivals[token] = (owner, name)
                    unresolved_searches.discard(token)
                else:
                    raise RevealMeaningError("unknown reveal meaning")
            elif kind == "hand_departure":
                _fields(event, {"kind", "owner_seat", "card_name", "count"})
                owner, count = _owner(event["owner_seat"]), _integer(event["count"])
                if count == 0:
                    raise RevealMeaningError("departure must move at least one card")
                name = None if event["card_name"] is None else _name(event["card_name"])
                bounds = cls._bounds(arrivals, present)
                affected = {key for key in bounds if key[0] == owner and (name is None or key[1] == name)}
                for token, key in list(arrivals.items()):
                    if key in affected:
                        del arrivals[token]
                for key in affected:
                    present[key] = max(0, bounds[key] - count)
                # A named departure may be one of several copies. No native
                # copy identity can decide which arrival token survived.
                for token, (arrival_owner, arrival_name) in list(eligible.items()):
                    if arrival_owner == owner and (name is None or arrival_name in (None, name)):
                        del eligible[token]
            elif kind in {"library_shuffled", "public_correspondence_lost"}:
                _fields(event, {"kind", "owner_seat"})
                owner = _owner(event["owner_seat"])
                eligible = {token: value for token, value in eligible.items() if value[0] != owner}
            else:
                raise RevealMeaningError("unknown public reveal event")
        if unresolved_searches:
            raise RevealMeaningError("search outcome lacks its same-operation reveal")


class RevealProducerV3:
    """Mint viewer-local tokens from supplied, already public operation events.

    This boundary deliberately accepts no native object or hidden-copy field.
    An engine adapter must project and justify its evidence before calling it.
    """

    def __init__(self) -> None:
        self._next = 0
        self._validator = RevealReducerV3()

    def token(self, event_index: int) -> str:
        return arrival_token(self._next, event_index)

    def operation(self, events: list[dict]) -> dict:
        result = {"schema": SCHEMA, "operations": [{"sequence": self._next, "events": deepcopy(events)}]}
        self._validator.absorb(result)
        self._next += 1
        return result
