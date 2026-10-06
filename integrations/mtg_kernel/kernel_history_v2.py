"""Per-viewer public event history (`x_public_history_v1`) from the private bridge.

The bridge's private support carries the omniscient slice of committed events,
observation notes and newly allocated objects since its previous production
decision. This module is the only reader of that slice. It keeps native
identities inside the environment and queues, per viewer, only what that
viewer could observe. `drain` hands a viewer its queue when it next decides.

The same stream drives each viewer's knowledge tracker (spec Section 6.7):
library facts by position, mirroring the kernel's own per-observer library
knowledge, and name-level facts about the other seat's hand.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from kernel_observation_v2 import ProjectionError

SCHEMA = "x_public_history_v1"
NATIVE_SEATS = (0, 1)
PUBLIC_ZONES = frozenset({"battlefield", "graveyard", "stack", "exile", "command"})
HIDDEN_ZONES = frozenset({"hand", "library"})
ZONES = PUBLIC_ZONES | HIDDEN_ZONES


def _zone(value: Any) -> str:
    if not isinstance(value, str) or value.lower() not in ZONES:
        raise ProjectionError("unknown native history zone")
    return value.lower()


def _seat(value: Any) -> int:
    if type(value) is not int or value not in NATIVE_SEATS:
        raise ProjectionError("invalid native history seat")
    return value


def _object(value: Any) -> int:
    if type(value) is not int or value < 0:
        raise ProjectionError("invalid native history object")
    return value


class PublicHistory:
    """Omniscient bookkeeping plus one pending event queue per native seat."""

    def __init__(self):
        self.events_seen = 0
        self.notes_seen = 0
        self.objects: list[dict] = []
        self.zones: dict[int, str] = {}
        # Moves seen per object. A reference carries the count after its own
        # event, so drain links it to the current object only when nothing
        # has moved the card since: never across a later zone change.
        self.moves: dict[int, int] = {}
        self.turns = 0
        self.starter: int | None = None
        self.pending: dict[int, list[dict]] = {seat: [] for seat in NATIVE_SEATS}
        # Knowledge, per viewer: library[viewer][owner] maps a position from
        # the top to {"native", "name", "how"}; hand[viewer][owner] lists
        # {"name", "how", "native"} facts about the other seat's hand, where
        # "native" is None once the viewer can no longer tell which copy.
        self.library = {viewer: {owner: {} for owner in NATIVE_SEATS} for viewer in NATIVE_SEATS}
        self.hand = {viewer: {owner: [] for owner in NATIVE_SEATS} for viewer in NATIVE_SEATS}
        # Library facts captured by removal notes, consumed by the event that
        # moves the removed card (a known card drawn becomes a hand fact).
        self.removed: list[tuple[int, dict[int, dict]]] = []

    # -- intake ---------------------------------------------------------------

    def absorb(self, history: Any) -> None:
        """Consume one contiguous private slice, in commit order."""
        if not isinstance(history, dict) or set(history) != {
                "events_from", "events", "notes_from", "notes", "objects_from", "objects"}:
            raise ProjectionError("malformed private history slice")
        if (history["events_from"], history["notes_from"], history["objects_from"]) != (
                self.events_seen, self.notes_seen, len(self.objects)):
            raise ProjectionError("private history slice is not contiguous")
        for entry in history["objects"]:
            if not isinstance(entry, dict) or entry.get("object") != len(self.objects):
                raise ProjectionError("private history objects are not dense")
            owner = _seat(entry["owner"])
            if not isinstance(entry.get("card_name"), str):
                raise ProjectionError("private history object has no name")
            self.objects.append({"owner": owner, "card_name": entry["card_name"],
                                 "is_token": entry["is_token"] is True, "copy": entry["copy"] is True})
            # Cards begin in their owner's library; tokens and spell copies
            # get their zone from the event that creates them.
            if not entry["is_token"] and not entry["copy"]:
                self.zones[entry["object"]] = "library"
        notes = list(history["notes"])
        cursor = 0
        for offset, event in enumerate(history["events"]):
            index = self.events_seen + offset
            positions, after = [], []
            while cursor < len(notes) and notes[cursor]["history_len"] <= index:
                note = notes[cursor]
                cursor += 1
                if note["kind"] in ("library_removal", "library_insertion"):
                    positions.append(note)
                if (note["kind"] == "hand_card_revealed" and note["history_len"] == index and
                        self.zones.get(note.get("object")) != "hand"):
                    # Anchored to this event but made once its card reached
                    # the hand: the kernel commits the event after the move.
                    after.append(note)
                    continue
                self._note(note)
            self._event(event, positions)
            self.removed = []
            for note in after:
                self._note(note)
        for note in notes[cursor:]:
            self._note(note)
        self.events_seen += len(history["events"])
        self.notes_seen += len(notes)

    def _card(self, native: int) -> dict:
        try:
            return self.objects[native]
        except IndexError as exc:
            raise ProjectionError("history references an unexported object") from exc

    def _moved(self, native: int, zone: str) -> None:
        self.zones[native] = zone
        self.moves[native] = self.moves.get(native, 0) + 1

    def _ref(self, native: int, *, named: bool) -> dict | None:
        """A card reference resolved per viewer at drain time; None if unnamed."""
        if not named:
            return None
        card = self._card(native)
        return {"native": native, "seq": self.moves.get(native, 0),
                "card_name": card["card_name"], "owner": card["owner"]}

    def _emit(self, viewers, event: dict) -> None:
        for seat in viewers:
            self.pending[seat].append(event)

    def _event(self, raw: Any, positions: list[dict]) -> None:
        if not isinstance(raw, dict) or len(raw) != 1:
            raise ProjectionError("malformed native committed event")
        (kind, body), = raw.items()
        if kind == "Draw":
            player = _seat(body["player"])
            native = body["object"]
            if native is None:
                return  # an empty-library draw moves nothing; the loss is public
            native = _object(native)
            self._moved(native, "hand")
            self._library_to_hand(native, player)
            for seat in NATIVE_SEATS:
                self.pending[seat].append({"kind": "draw", "seat": player,
                                           "card": self._ref(native, named=seat == player)})
        elif kind == "ZoneChange":
            native = _object(body["object"])
            source, target = _zone(body["from"]), _zone(body["to"])
            self._moved(native, target)
            card = self._card(native)
            self._hand_move(native, card, source, target)
            public = source in PUBLIC_ZONES or target in PUBLIC_ZONES
            where = {}
            for note in positions:
                if _seat(note["owner"]) != card["owner"]:
                    continue
                if note["kind"] == "library_removal" and source == "library":
                    where["from"] = note["position"]
                elif note["kind"] == "library_insertion" and target == "library":
                    where["to"] = note["position"]
            for seat in NATIVE_SEATS:
                event = {"kind": "zone_move", "card": self._ref(native, named=public or seat == card["owner"]),
                         "owner": card["owner"], "from": {"zone": source}, "to": {"zone": target}}
                if "from" in where:
                    event["from"]["position_from_top"] = where["from"]
                if "to" in where:
                    event["to"]["position_from_top"] = where["to"]
                self.pending[seat].append(event)
        elif kind == "SpellCast":
            native = _object(body["spell"])
            card = self._card(native)
            if card["copy"]:
                self._moved(native, "stack")
                return  # a copy is not a card; the stack in the observation shows it
            source = self.zones.get(native)
            if source is None:
                raise ProjectionError("cast spell has no tracked zone")
            if source == "stack":
                return
            self._moved(native, "stack")
            self._hand_move(native, card, source, "stack")
            self._emit(NATIVE_SEATS, {"kind": "zone_move", "card": self._ref(native, named=True),
                                      "owner": card["owner"], "from": {"zone": source}, "to": {"zone": "stack"}})
        elif kind == "CreateToken":
            native = _object(body["object"])
            self._moved(native, "battlefield")
            self._emit(NATIVE_SEATS, {"kind": "token_created", "card": self._ref(native, named=True),
                                      "controller": _seat(body["controller"])})
        elif kind == "UpkeepBegan":
            # The observation's turn number counts rounds: it advances when
            # the game's starting player, the first to have an upkeep, begins
            # a turn again.
            player = _seat(body["player"])
            if self.starter is None:
                self.starter = player
            if player == self.starter:
                self.turns += 1
            self._emit(NATIVE_SEATS, {"kind": "turn_began", "turn": self.turns, "active": player})
        # Every other committed event changes only public board state, which
        # the observation already shows; its order is not needed.

    def _note(self, note: dict) -> None:
        kind = note["kind"]
        if kind == "library_randomized":
            owner = _seat(note["owner"])
            for viewer in NATIVE_SEATS:
                self.library[viewer][owner] = {}
            self._emit(NATIVE_SEATS, {"kind": "library_shuffled", "owner": owner})
        elif kind == "library_looked":
            observer, owner = _seat(note["observer"]), _seat(note["owner"])
            looked = [(position, _object(native)) for position, native in note["positions"]]
            if type(looked) is not list or any(type(position) is not int or position < 0 for position, _ in looked):
                raise ProjectionError("invalid native look positions")
            known = self.library[observer][owner]
            gone = {position for position, _ in looked}
            natives = {native for _, native in looked}
            self.library[observer][owner] = {position: fact for position, fact in known.items()
                                             if position not in gone and fact["native"] not in natives}
            for position, native in looked:
                self._know(observer, owner, position, native, "looked_at")
            cards = [{"card": self._ref(native, named=True), "position_from_top": position}
                     for position, native in looked]
            self.pending[observer].append({"kind": "looked_at", "owner": owner, "cards": cards})
        elif kind == "library_reordered":
            owner = _seat(note["owner"])
            ordered = [_object(native) for native in note["ordered"]]
            revealed = {_seat(observer) for observer in note["revealed_to"]}
            for viewer in NATIVE_SEATS:
                self.library[viewer][owner] = {position: fact for position, fact in self.library[viewer][owner].items()
                                               if position >= len(ordered)}
                if viewer in revealed:
                    for position, native in enumerate(ordered):
                        self._know(viewer, owner, position, native, "looked_at")
            self._emit(NATIVE_SEATS, {"kind": "library_rearranged", "owner": owner,
                                      "top_count": len(ordered), "bottom_count": 0})
            for observer in note["revealed_to"]:
                cards = [{"card": self._ref(native, named=True), "position_from_top": position}
                         for position, native in enumerate(ordered)]
                self.pending[_seat(observer)].append({"kind": "looked_at", "owner": owner, "cards": cards})
        elif kind == "library_scried":
            owner = _seat(note["owner"])
            top = [_object(native) for native in note["retained_top"]]
            bottom = [_object(native) for native in note["ordered_bottom"]]
            self._scried(owner, top, bottom)
            self._emit(NATIVE_SEATS, {"kind": "library_rearranged", "owner": owner,
                                      "top_count": len(top), "bottom_count": len(bottom)})
            cards = [{"card": self._ref(native, named=True), "position_from_top": position}
                     for position, native in enumerate(top)]
            cards += [{"card": self._ref(native, named=True), "position_from_bottom": len(bottom) - 1 - position}
                      for position, native in enumerate(bottom)]
            if cards:
                self.pending[owner].append({"kind": "looked_at", "owner": owner, "cards": cards})
        elif kind == "hand_card_revealed":
            observer, owner = _seat(note["observer"]), _seat(note["owner"])
            native = _object(note["object"])
            self._revealed_in_hand(observer, owner, native)
            self.pending[observer].append({"kind": "card_revealed", "owner": owner, "zone": "hand",
                                           "card": self._ref(native, named=True)})
        elif kind == "library_removal":
            owner, position = _seat(note["owner"]), self._position(note["position"])
            captured = {}
            for viewer in NATIVE_SEATS:
                known = self.library[viewer][owner]
                if position in known:
                    captured[viewer] = known[position]
                self.library[viewer][owner] = {(spot - 1 if spot > position else spot): fact
                                               for spot, fact in known.items() if spot != position}
            self.removed.append((owner, captured))
        elif kind == "library_insertion":
            owner, position = _seat(note["owner"]), self._position(note["position"])
            for viewer in NATIVE_SEATS:
                self.library[viewer][owner] = {(spot + 1 if spot >= position else spot): fact
                                               for spot, fact in self.library[viewer][owner].items()}
        else:
            raise ProjectionError("unknown native observation note")

    # -- knowledge (spec Section 6.7) ---------------------------------------------

    @staticmethod
    def _position(value: Any) -> int:
        if type(value) is not int or value < 0:
            raise ProjectionError("invalid native library position")
        return value

    def _know(self, viewer: int, owner: int, position: int, native: int, how: str) -> None:
        card = self._card(native)
        if card["owner"] != owner:
            raise ProjectionError("library fact names another owner's card")
        self.library[viewer][owner][position] = {"native": native, "name": card["card_name"], "how": how}

    def library_count(self, owner: int) -> int:
        return sum(1 for native, zone in self.zones.items()
                   if zone == "library" and self.objects[native]["owner"] == owner)

    def _scried(self, owner: int, top: list[int], bottom: list[int]) -> None:
        """Mirror the kernel's scry update: tail facts shift up by the bottom
        count; the owner learns the result; another viewer keeps a fact only
        for a single scried card it already knew, whose destination is public."""
        prefix, length = len(top) + len(bottom), self.library_count(owner)
        if prefix > length:
            raise ProjectionError("scry exceeds the tracked library")
        for viewer in NATIVE_SEATS:
            old = self.library[viewer][owner]
            updated = {position - len(bottom): fact for position, fact in old.items() if position >= prefix}
            if viewer == owner:
                self.library[viewer][owner] = updated
                for position, native in enumerate(top):
                    self._know(viewer, owner, position, native, "looked_at")
                for offset, native in enumerate(bottom):
                    self._know(viewer, owner, length - len(bottom) + offset, native, "looked_at")
                continue
            if prefix == 1 and 0 in old and old[0]["native"] == (top + bottom)[0]:
                updated[length - 1 if bottom else 0] = old[0]
            self.library[viewer][owner] = updated

    def _library_to_hand(self, native: int, owner: int) -> None:
        """A known library card that reaches its owner's hand stays known
        to the other seat by name (`tracked`)."""
        for removed_owner, captured in self.removed:
            if removed_owner != owner:
                continue
            for viewer, fact in captured.items():
                if viewer != owner and fact["native"] == native:
                    self.hand[viewer][owner].append({"name": fact["name"], "how": "tracked", "native": native})

    def _revealed_in_hand(self, viewer: int, owner: int, native: int) -> None:
        if viewer == owner:
            return
        entries, name = self.hand[viewer][owner], self._card(native)["card_name"]
        if any(entry["native"] == native for entry in entries):
            return
        for entry in entries:
            # A name-level fact may already describe this copy; binding it
            # never claims more copies than the viewer can be sure of.
            if entry["native"] is None and entry["name"] == name:
                entry["native"] = native
                return
        entries.append({"name": name, "how": "revealed", "native": native})

    def _hand_move(self, native: int, card: dict, source: str, target: str) -> None:
        owner = card["owner"]
        if card["is_token"] or card["copy"]:
            return
        if target == "hand" and source != "hand":
            if source in PUBLIC_ZONES:
                for viewer in NATIVE_SEATS:
                    if viewer != owner:
                        self.hand[viewer][owner].append({"name": card["card_name"], "how": "from_public_zone",
                                                         "native": native})
            elif source == "library":
                self._library_to_hand(native, owner)
            return
        if source != "hand" or target == "hand":
            return
        for viewer in NATIVE_SEATS:
            if viewer == owner:
                continue
            entries = self.hand[viewer][owner]
            if target in PUBLIC_ZONES:
                # The card is identified as it leaves: drop that fact, else
                # one fact with its name.
                match = next((entry for entry in entries if entry["native"] == native), None)
                if match is None:
                    match = next((entry for entry in entries if entry["native"] is None and
                                  entry["name"] == card["card_name"]), None)
                if match is None:
                    match = next((entry for entry in entries if entry["name"] == card["card_name"]), None)
                if match is not None:
                    entries.remove(match)
                continue
            # An unidentified card left to a hidden zone: each name loses one
            # fact, and no remaining fact can still be tied to one copy.
            seen, kept = set(), []
            for entry in reversed(entries):
                if entry["name"] in seen:
                    kept.append({**entry, "native": None})
                else:
                    seen.add(entry["name"])
            self.hand[viewer][owner] = list(reversed(kept))

    def knowledge(self, native_viewer: int) -> dict:
        """The viewer's current facts plus the omniscient hand contents the
        projection checks them against. Native ids stay inside the adapter."""
        truth = {owner: Counter(self.objects[native]["card_name"] for native, zone in self.zones.items()
                                if zone == "hand" and self.objects[native]["owner"] == owner)
                 for owner in NATIVE_SEATS}
        return {"library": {owner: dict(self.library[native_viewer][owner]) for owner in NATIVE_SEATS},
                "hand": {owner: [dict(entry) for entry in self.hand[native_viewer][owner]] for owner in NATIVE_SEATS
                         if owner != native_viewer},
                "hand_truth": truth}

    # -- per-viewer output ------------------------------------------------------

    def drain(self, native_viewer: int, projection) -> dict:
        """The viewer's queued events in wire form; empties the queue.

        A card gets the viewer-local id it has in the current observation only
        if it has not moved since the event; otherwise its id is null, so ids
        never link a card across a zone change. Seats use the projection's
        seat mapping. No native id or counter leaves this method.
        """
        current = {}
        for (arena_id, _zcc, _zone_name), ref in projection.stable_refs.items():
            current[arena_id] = ref["object_id"]
        events, self.pending[native_viewer] = self.pending[native_viewer], []
        seat = lambda native: projection.seat(f"p{native}")

        def card(ref):
            if ref is None:
                return None
            linked = self.moves.get(ref["native"], 0) == ref["seq"]
            return {"object_id": current.get(ref["native"]) if linked else None, "card_name": ref["card_name"],
                    "owner_seat": seat(ref["owner"])}

        wire = []
        for event in events:
            kind = event["kind"]
            if kind == "draw":
                wire.append({"kind": kind, "seat": seat(event["seat"]), "card": card(event["card"])})
            elif kind == "zone_move":
                wire.append({"kind": kind, "card": card(event["card"]), "owner_seat": seat(event["owner"]),
                             "from": dict(event["from"]), "to": dict(event["to"])})
            elif kind == "token_created":
                wire.append({"kind": kind, "card": card(event["card"]), "controller_seat": seat(event["controller"])})
            elif kind == "turn_began":
                wire.append({"kind": kind, "turn": event["turn"], "active_seat": seat(event["active"])})
            elif kind == "library_shuffled":
                wire.append({"kind": kind, "owner_seat": seat(event["owner"])})
            elif kind == "library_rearranged":
                wire.append({"kind": kind, "owner_seat": seat(event["owner"]),
                             "top_count": event["top_count"], "bottom_count": event["bottom_count"]})
            elif kind == "looked_at":
                wire.append({"kind": kind, "owner_seat": seat(event["owner"]),
                             "cards": [{**{key: value for key, value in entry.items() if key != "card"},
                                        "card": card(entry["card"])} for entry in event["cards"]]})
            elif kind == "card_revealed":
                wire.append({"kind": kind, "owner_seat": seat(event["owner"]), "zone": event["zone"],
                             "card": card(event["card"])})
        return {"schema": SCHEMA, "events": wire}
