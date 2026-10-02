"""A reference implementation of the spec 6.7 update table, one method per row.

A scenario (``fake_v2_scenario_knowledge.py``) keeps a viewer's ``known`` entries with this model:
each event of the game calls the row it belongs to, and :meth:`Knowledge.entries` writes the
result to ``world.known[viewer]`` so the next observation carries it. The model is name-level and
positional, never object-level (spec 6.7): an entry is a plain dict of the spec's seven fields
with ``object_id`` always None, and a position counted from one end converts to the other through
the library's size, which is public (a card's index from the top is
``library_count - 1 - position_from_bottom``).

A row whose event changes a library's size reads the size as it was before the event, so a
scenario calls the row's method before it moves the card in the World.
"""

from __future__ import annotations

from typing import Any

from spellbench.host.hidden import known_sort_key

from fake_v2_world import World

_POSITION = {"top": "position_from_top", "bottom": "position_from_bottom"}


def _entry(owner: str, zone: str, name: str, *, top: int | None = None, bottom: int | None = None,
           how: str) -> dict[str, Any]:
    return {"owner_seat": owner, "zone": zone, "card_name": name, "object_id": None,
            "position_from_top": top, "position_from_bottom": bottom, "how": how}


def _end(end: str) -> str:
    if end not in _POSITION:
        raise ValueError(f"an end is 'top' or 'bottom', not {end!r}")
    return end


class Knowledge:
    """A viewer's ``known`` entries (spec 6.7), updated one update-table row at a time."""

    def __init__(self, world: World, viewer: str) -> None:
        if viewer not in ("p0", "p1"):
            raise ValueError(f"a viewer is p0 or p1, not {viewer!r}")
        self._world = world
        self._viewer = viewer
        self._other = "p1" if viewer == "p0" else "p0"
        self._known: list[dict[str, Any]] = []

    # The hand rows: the other seat's hand (the viewer's own hand is never listed, spec 6.7).

    def public_to_other_hand(self, name: str) -> None:
        """Row 1: a card moves from a public zone to the other seat's hand."""
        self._known.append(_entry(self._other, "hand", name, how="from_public_zone"))

    def known_library_card_drawn(self, owner: str, end: str) -> None:
        """Row 2: a card the viewer knows at a library position moves to that library owner's hand.

        The viewer's own hand is never listed, so the knowledge of a card the viewer draws simply
        ends (it is in ``players[viewer].hand`` now).
        """
        drawn = self._take_end(owner, end)
        if drawn is not None and owner != self._viewer:
            self._known.append(_entry(owner, "hand", drawn["card_name"], how="tracked"))

    def other_hand_revealed(self, names: list[str]) -> None:
        """Row 3: the other seat's hand is revealed to the viewer."""
        self._forget_hand()
        self._known.extend(_entry(self._other, "hand", name, how="revealed") for name in names)

    def other_hand_to_public(self, name: str) -> None:
        """Row 4: a card leaves the other seat's hand to a public zone, or is revealed as it leaves."""
        self._forget_one_hand_entry(name)

    def other_hand_to_hidden(self, count: int) -> None:
        """Row 5: ``count`` cards leave the other seat's hand to a hidden zone, unidentified.

        Once per departing card, every name's count of entries c becomes max(0, c - 1).
        """
        for _ in range(count):
            for name in sorted({entry["card_name"] for entry in self._hand_entries()}):
                self._forget_one_hand_entry(name)

    def other_hand_randomized(self) -> None:
        """Row 6: the other seat's hand is shuffled into a library, exchanged or otherwise randomized."""
        self._forget_hand()

    # The library rows.

    def library_shuffled(self, owner: str) -> None:
        """Row 7: a library is shuffled."""
        self._forget_library(owner)

    def looked_at(self, owner: str, cards: list[tuple[str, str, int]], how: str) -> None:
        """Row 8: the viewer looks at or reveals library cards, or places its own at known positions.

        Each card is ``(name, end, position)``: ``position`` cards from ``end`` (0 is the end card).
        """
        for name, end, position in cards:
            if _end(end) == "top":
                self._known.append(_entry(owner, "library", name, top=position, how=how))
            else:
                self._known.append(_entry(owner, "library", name, bottom=position, how=how))

    def left_library_end(self, owner: str, end: str) -> None:
        """Row 9: a card leaves the top (or bottom) of a library."""
        self._take_end(owner, end)

    def put_on_library_end(self, owner: str, end: str, name: str | None) -> None:
        """Row 10: a card is put on the top (or bottom) of a library.

        The entries counted from that end renumber one further from it; when the viewer knows the
        card, it enters at the end: its own placement, or a card from a public zone.
        """
        field = _POSITION[_end(end)]
        for entry in self._library_entries(owner):
            if entry[field] is not None:
                entry[field] += 1
        if name is not None:
            how = "own_placement" if owner == self._viewer else "from_public_zone"
            if end == "top":
                self._known.append(_entry(owner, "library", name, top=0, how=how))
            else:
                self._known.append(_entry(owner, "library", name, bottom=0, how=how))

    def hidden_rearrangement(self, owner: str, end: str, depth: int) -> None:
        """Row 11: the ``depth`` cards at ``end`` are rearranged by a choice hidden from the viewer."""
        size = self._library_count(owner)
        for entry in self._library_entries(owner):
            if self._from_end(entry, end, size) < depth:
                self._known.remove(entry)                        # the card could have moved

    def ambiguous_insertion(self, owner: str, end: str, depth: int) -> None:
        """Row 12: a card goes into the library somewhere at or beyond ``depth`` cards from ``end``.

        ``depth`` counts positions as the library was before the insertion. An entry whose card
        lies at or beyond the insertion is forgotten, since the card may have shifted; an entry
        above it survives, renumbered by one when it counts from the other end (the library grew).
        """
        size = self._library_count(owner)
        other_end = "bottom" if _end(end) == "top" else "top"
        for entry in self._library_entries(owner):
            if self._from_end(entry, end, size) >= depth:
                self._known.remove(entry)
            elif entry[_POSITION[other_end]] is not None:
                entry[_POSITION[other_end]] += 1

    def left_unknown_position(self, owner: str) -> None:
        """Row 13: a card leaves the library from a position the viewer does not know.

        Any entry may have shifted or been the card that left, so the whole library is forgotten.
        """
        self._forget_library(owner)

    def entries(self) -> list[dict[str, Any]]:
        """The entries in the spec 6.7 order; writes them to ``world.known[viewer]`` and returns a copy."""
        ordered = sorted(self._known, key=known_sort_key)
        self._world.known[self._viewer] = [dict(entry) for entry in ordered]
        return [dict(entry) for entry in ordered]

    # Helpers.

    def _library_count(self, owner: str) -> int:
        return len(self._world.libraries[owner])

    def _hand_entries(self) -> list[dict[str, Any]]:
        return [entry for entry in self._known if entry["zone"] == "hand" and entry["owner_seat"] == self._other]

    def _library_entries(self, owner: str) -> list[dict[str, Any]]:
        return [entry for entry in self._known if entry["zone"] == "library" and entry["owner_seat"] == owner]

    def _forget_hand(self) -> None:
        self._known = [entry for entry in self._known
                       if not (entry["zone"] == "hand" and entry["owner_seat"] == self._other)]

    def _forget_library(self, owner: str) -> None:
        self._known = [entry for entry in self._known
                       if not (entry["zone"] == "library" and entry["owner_seat"] == owner)]

    def _forget_one_hand_entry(self, name: str) -> None:
        for entry in self._hand_entries():
            if entry["card_name"] == name:
                self._known.remove(entry)                        # one entry with that name, if any
                return

    def _take_end(self, owner: str, end: str) -> dict[str, Any] | None:
        """The library's end card leaves: forget its entry and renumber the entries counted from that end."""
        field = _POSITION[_end(end)]
        taken = None
        for entry in self._library_entries(owner):
            if taken is None and self._from_end(entry, end, self._library_count(owner)) == 0:
                taken = entry
                self._known.remove(entry)
            elif entry[field] is not None:
                entry[field] -= 1
        return taken

    @staticmethod
    def _from_end(entry: dict[str, Any], end: str, size: int) -> int:
        """An entry's position counted from ``end`` (0 is the card at that end); the library holds ``size`` cards."""
        if _end(end) == "top":
            if entry["position_from_top"] is not None:
                return entry["position_from_top"]
            return size - 1 - entry["position_from_bottom"]
        if entry["position_from_bottom"] is not None:
            return entry["position_from_bottom"]
        return size - 1 - entry["position_from_top"]
