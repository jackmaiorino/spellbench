"""V5: hidden zones and knowledge (spec 6.3, 6.7, 7.1, 11.3).

``check_hidden_zones`` applies these rules in order. They are the checkable
part of spec 6.8 for hands and libraries: the host cannot tell whether a
``known`` entry is faithful to hidden state (spec 11.3).

1. the other seat's ``hand`` is null;
2. the viewer's ``hand`` is an array of exactly ``hand_count`` records;
3. no zone-array record has zone ``library`` (library knowledge is only in ``known``);
4. ``known`` follows spec 6.7: a hand entry names the other seat and has both
   positions null; a library entry has exactly one non-null position (a
   ``searching`` entry at most one), below its owner's ``library_count``
   (R2-25); a seat's hand entries never outnumber its ``hand_count``; only an
   entry whose ``how`` is ``looked_at``, ``revealed`` or ``searching`` carries
   an ``object_id``; the entries are in ``known_sort_key`` order;
5. candidates that reference cards in hidden zones (a library, or the other
   seat's hand) come, among themselves, in ``hidden_candidate_key`` order.

Inputs are seat decisions that already passed V1, so every field has its type
and ``players`` is p0 then p1. The order checks compare consecutive keys with
``>``, so equal keys pass them: for example two identical entries, or two
candidates referencing the same cards. Every detail starts with the path of the
offending value, relative to the seat decision.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

from .._schema import SEATS
from ..candidates import object_references
from ..observation import zone_records
from .violation import ValidatorViolation

# Spec 6.7: only a card looked at, revealed or searched in the current decision carries an object id.
_CURRENT_LOOKS = ("looked_at", "revealed", "searching")
_POSITIONS = ("position_from_top", "position_from_bottom")


def _nullable(value: Any) -> tuple:
    return (0, "") if value is None else (1, value)


def known_sort_key(entry: Mapping[str, Any]) -> tuple:
    """The spec 6.7 order of ``known`` entries, nulls first; strings compare by code point."""
    return (entry["owner_seat"], entry["zone"], entry["card_name"], _nullable(entry["position_from_top"]),
            _nullable(entry["position_from_bottom"]), entry["how"], _nullable(entry["object_id"]))


def hidden_candidate_key(semantic: Mapping[str, Any], viewer: str) -> tuple | None:
    """The spec 7.1 order of a candidate referencing cards hidden from ``viewer``, or None when it references none.

    A card in a library, or in the other seat's hand, is hidden. The key holds
    the ``(card_name, object_id)`` pair of each such reference, in
    ``object_references`` order, with a null name first.
    """
    pairs = tuple((_nullable(ref["card_name"]), ref["object_id"]) for _, ref in object_references(semantic)
                  if ref["zone"] == "library" or (ref["zone"] == "hand" and ref["owner_seat"] != viewer))
    return pairs or None


def check_hidden_zones(seat_decision: Mapping[str, Any]) -> None:
    """V5: raise ``ValidatorViolation("V5", ...)`` at the first broken rule, in the module docstring's order."""
    viewer = seat_decision["acting_seat"]   # the seat the decision is forwarded to; V2 makes it the observation's viewer
    observation = seat_decision["observation"]
    players = observation["players"]
    _check_hands(players, viewer)
    for path, _, record in zone_records(observation):
        if record["zone"] == "library":
            raise ValidatorViolation("V5", f"observation.{path}.zone is library: only known carries library knowledge")
    _check_known(observation["known"], players, viewer)
    _check_candidate_order(seat_decision["candidates"], viewer)


def _check_hands(players: Sequence[Mapping[str, Any]], viewer: str) -> None:
    """Rules 1 and 2 (spec 6.3)."""
    own = SEATS.index(viewer)
    other = 1 - own
    if players[other]["hand"] is not None:
        raise ValidatorViolation("V5", f"observation.players[{other}].hand must be null: it is the other seat's hand")
    hand, hand_count = players[own]["hand"], players[own]["hand_count"]
    if hand is None or len(hand) != hand_count:
        shown = "null" if hand is None else len(hand)
        raise ValidatorViolation("V5", f"observation.players[{own}].hand must hold hand_count {hand_count} records, got {shown}")


def _check_known(known: Sequence[Mapping[str, Any]], players: Sequence[Mapping[str, Any]], viewer: str) -> None:
    """Rule 4 (spec 6.7): each entry's shape, then the hand entries' counts, the object ids and the order."""
    for index, entry in enumerate(known):
        path = f"observation.known[{index}]"
        positions = [field for field in _POSITIONS if entry[field] is not None]
        if entry["zone"] == "hand":
            if entry["owner_seat"] == viewer:
                raise ValidatorViolation("V5", f"{path}.owner_seat is the viewer {viewer}: known never lists the viewer's own hand")
            if positions:
                raise ValidatorViolation("V5", f"{path}.{positions[0]} must be null: a hand entry has no position")
            continue
        if len(positions) > 1 or (not positions and entry["how"] != "searching"):
            allowed = "at most one" if entry["how"] == "searching" else "exactly one"
            raise ValidatorViolation("V5", f"{path} is a library entry with {len(positions)} non-null positions, not {allowed}")
        library_count = players[SEATS.index(entry["owner_seat"])]["library_count"]
        for field in positions:
            if entry[field] >= library_count:   # R2-25
                raise ValidatorViolation(
                    "V5", f"{path}.{field} is {entry[field]}, past the {library_count} cards of {entry['owner_seat']}'s library"
                )
    hand_entries = Counter(entry["owner_seat"] for entry in known if entry["zone"] == "hand")
    for index, player in enumerate(players):
        if hand_entries[player["seat"]] > player["hand_count"]:
            raise ValidatorViolation("V5", f"observation.known has {hand_entries[player['seat']]} hand entries for {player['seat']}, "
                                           f"more than observation.players[{index}].hand_count {player['hand_count']}")
    for index, entry in enumerate(known):
        if entry["object_id"] is not None and entry["how"] not in _CURRENT_LOOKS:
            raise ValidatorViolation("V5", f"observation.known[{index}].object_id must be null with how {entry['how']}: "
                                           "only cards looked at, revealed or searched now carry ids")
    for index in range(1, len(known)):
        if known_sort_key(known[index - 1]) > known_sort_key(known[index]):
            raise ValidatorViolation("V5", f"observation.known[{index - 1}] and observation.known[{index}] are out of order")


def _check_candidate_order(candidates: Sequence[Mapping[str, Any]], viewer: str) -> None:
    """Rule 5 (spec 7.1): hidden-card candidates in order among themselves; other candidates may sit between them."""
    previous: tuple[int, tuple] | None = None
    for index, candidate in enumerate(candidates):
        key = hidden_candidate_key(candidate["semantic"], viewer)
        if key is None:
            continue
        if previous is not None and previous[1] > key:
            raise ValidatorViolation("V5", f"candidates[{previous[0]}] and candidates[{index}] reference hidden-zone cards "
                                           "out of (card_name, object_id) order")
        previous = (index, key)
