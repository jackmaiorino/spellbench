"""Per-viewer public event history (`x_public_history_v1`) from the private bridge.

The bridge's private support carries the omniscient slice of committed events,
observation notes and newly allocated objects since its previous production
decision. This module is the only reader of that slice. It keeps native
identities inside the environment and queues, per viewer, only what that
viewer could observe. `drain` hands a viewer its queue when it next decides.
"""
from __future__ import annotations

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
            positions = []
            while cursor < len(notes) and notes[cursor]["history_len"] <= index:
                note = notes[cursor]
                cursor += 1
                if note["kind"] in ("library_removal", "library_insertion"):
                    positions.append(note)
                else:
                    self._note(note)
            self._event(event, positions)
        for note in notes[cursor:]:
            if note["kind"] not in ("library_removal", "library_insertion"):
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
            for seat in NATIVE_SEATS:
                self.pending[seat].append({"kind": "draw", "seat": player,
                                           "card": self._ref(native, named=seat == player)})
        elif kind == "ZoneChange":
            native = _object(body["object"])
            source, target = _zone(body["from"]), _zone(body["to"])
            self._moved(native, target)
            card = self._card(native)
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
            self._emit(NATIVE_SEATS, {"kind": "library_shuffled", "owner": _seat(note["owner"])})
        elif kind == "library_looked":
            observer, owner = _seat(note["observer"]), _seat(note["owner"])
            cards = [{"card": self._ref(_object(native), named=True), "position_from_top": position}
                     for position, native in note["positions"]]
            self.pending[observer].append({"kind": "looked_at", "owner": owner, "cards": cards})
        elif kind == "library_reordered":
            owner = _seat(note["owner"])
            ordered = [_object(native) for native in note["ordered"]]
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
            self.pending[observer].append({"kind": "card_revealed", "owner": owner, "zone": "hand",
                                           "card": self._ref(_object(note["object"]), named=True)})
        else:
            raise ProjectionError("unknown native observation note")

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
