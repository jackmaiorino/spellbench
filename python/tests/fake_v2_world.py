"""The fake engine's board model: objects, per-viewer ids and looks, and the observation (spec 5, 6).

The v2 fake engine (``fake_v2_engine.py``) plays scenarios on this model. A scenario sets up a ``World``,
edits its public state and yields ``Posed`` decisions; the engine builds each seat decision from
``World.observation(seat)`` and resolves the candidates' references with ``World.reference`` and
``World.target``. Apart from ``run_secret.object_id`` and ``_schema.OBSERVATION_FLAGS`` the module uses
nothing from ``spellbench``, so an adapter author can read it as a reference for object ids (spec 5.3),
what is hidden (6.4, 6.8), knowledge (6.7) and the optional fields (6.9).

Conventions for scenarios:

- An object is named by its internal id, an int. Candidates hold other integers too, so there an object
  reference is written ``{"$obj": n}`` and a target ``{"object": {"$obj": n}}`` or ``{"player": seat}``.
  The World's own target fields (``StackItem.targets``, ``Obj.attached_to``, ``Obj.attack_target``) use that
  target form; its object fields (``StackItem.internal`` and ``source``, ``Obj.exiled_by``, ``Obj.blocking``,
  a pending trigger's ``"source"``) hold internal ids.
- A reference names the object in its current zone. ``move`` is a zone change (CR 400.7): the object becomes
  a new object with fresh ids, and every reference the World holds to it is severed, so a stack target, an
  attack target, an attachment, an exiling object or a trigger source that left shows as null (spec 5.1),
  and the stack item of an object that left the stack is dropped.
- ``libraries[seat]`` is the library order, index 0 on top; ``add`` puts a library card at the bottom.
  Reorder a library by editing that list (a ``move`` is a zone change).
- A multi-face card's ``name`` is the face currently up (spec 5.1). ``move`` turns the front face up; a
  scenario that plays or casts a back face sets ``name`` after the move.
- An ability on the stack is an object in zone ``"stack"`` named after its source (spec 5.1), with a
  ``StackItem`` of kind ``activated_ability`` or ``triggered_ability``. Once its ``StackItem`` is gone (the
  ability resolved), the object is outside every observation.
- Characteristics are the printed ones in ``CARDS``: the fake engine applies no continuous effects.
"""

from __future__ import annotations

from collections.abc import Callable, Generator, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from spellbench._schema import OBSERVATION_FLAGS
from spellbench.run_secret import object_id as recommended_object_id

_SEATS = ("p0", "p1")
_ZONES = ("library", "hand", "battlefield", "graveyard", "stack", "exile", "command")    # spec 5.1
# Objects here have a controller of their own (spec 5.1), and a face-down one shows the face-down 2/2 (CR 708.2).
_CONTROLLED_ZONES = ("battlefield", "stack")
_FACE_DOWN_ZONES = ("battlefield", "stack", "exile")
_MANA_SYMBOLS = ("W", "U", "B", "R", "G", "C")                                          # spec 6.3
_COLOR_ORDER = ("white", "blue", "black", "red", "green")                              # spec 6.4
_STACK_KINDS = ("spell", "activated_ability", "triggered_ability")                     # spec 6.5
_CHARACTERISTICS = ("supertypes", "types", "subtypes", "colors", "mana_value", "power", "toughness", "keywords")


def _card(types: Sequence[str], mana_value: int, *, colors: Sequence[str] = (), subtypes: Sequence[str] = (),
          supertypes: Sequence[str] = (), power: int | None = None, toughness: int | None = None,
          keywords: Sequence[str] = (), full_name: str | None = None) -> dict[str, Any]:
    """A ``CARDS`` entry: the spec 6.4 characteristics plus the Oracle ``full_name`` of a multi-face card."""
    return {"supertypes": list(supertypes), "types": list(types), "subtypes": list(subtypes), "colors": list(colors),
            "mana_value": mana_value, "power": power, "toughness": toughness, "keywords": list(keywords),
            "full_name": full_name}


_SPIKEFIELD = "Spikefield Hazard // Spikefield Cave"

# Printed characteristics by the name of the face up (spec 4.4: Oracle names in NFC).
CARDS: dict[str, dict[str, Any]] = {
    "Mountain": _card(["land"], 0, supertypes=["basic"], subtypes=["mountain"]),
    "Island": _card(["land"], 0, supertypes=["basic"], subtypes=["island"]),
    "Lightning Bolt": _card(["instant"], 1, colors=["red"]),
    "Counterspell": _card(["instant"], 2, colors=["blue"]),
    "Brainstorm": _card(["instant"], 1, colors=["blue"]),
    "Preordain": _card(["sorcery"], 1, colors=["blue"]),
    "Grizzly Bears": _card(["creature"], 2, colors=["green"], subtypes=["bear"], power=2, toughness=2),
    "Monastery Swiftspear": _card(["creature"], 1, colors=["red"], subtypes=["human", "monk"], power=1, toughness=2,
                                  keywords=["haste", "prowess"]),
    "Spellstutter Sprite": _card(["creature"], 2, colors=["blue"], subtypes=["faerie", "wizard"], power=1, toughness=1,
                                 keywords=["flash", "flying"]),
    "Chainer's Edict": _card(["sorcery"], 2, colors=["black"], keywords=["flashback"]),
    "Lim-D\u00fbl's Vault": _card(["instant"], 2, colors=["blue", "black"]),
    "Barbarian Class": _card(["enchantment"], 1, colors=["red"], subtypes=["class"]),
    "Relic of Progenitus": _card(["artifact"], 1),
    "Pithing Needle": _card(["artifact"], 1),
    "Spikefield Hazard": _card(["instant"], 1, colors=["red"], full_name=_SPIKEFIELD),     # a modal double-faced card
    "Spikefield Cave": _card(["land"], 0, full_name=_SPIKEFIELD),                         # and its back face
    "Journey to Nowhere": _card(["enchantment"], 2, colors=["white"]),                     # an exiling permanent
    "Chandra, Torch of Defiance": _card(["planeswalker"], 4, colors=["red"], supertypes=["legendary"],
                                        subtypes=["chandra"]),
    "Rancor": _card(["enchantment"], 1, colors=["green"], subtypes=["aura"], keywords=["enchant"]),
    "Fathom Seer": _card(["creature"], 2, colors=["blue"], subtypes=["illusion"], power=1, toughness=3,
                         keywords=["morph"]),
    "Fact or Fiction": _card(["instant"], 4, colors=["blue"]),                             # piles
    "Burst Lightning": _card(["instant"], 1, colors=["red"], keywords=["kicker"]),
    "Fiery Temper": _card(["instant"], 3, colors=["red"], keywords=["madness"]),
    # One card for each remaining tour feature, so no scenario borrows a card whose rules text does not fit it.
    "Chandra, Torch of Defiance Emblem": _card([], 0),          # a command-zone emblem (CR 114.3: no characteristics)
    "Forked Bolt": _card(["sorcery"], 1, colors=["red"]),       # damage divided among one or two targets
    "Ghostly Flicker": _card(["instant"], 3, colors=["blue"]),  # exactly two targets
    "Fireball": _card(["sorcery"], 1, colors=["red"]),          # X
    "Cryptic Command": _card(["instant"], 4, colors=["blue"]),  # choose two modes
    "Borrowed Hostility": _card(["instant"], 1, colors=["red"], keywords=["escalate"]),     # choose one or both modes
    "Evolving Wilds": _card(["land"], 0),                       # a library search
    "Faithless Looting": _card(["sorcery"], 1, colors=["red"], keywords=["flashback"]),     # discard two
}

# A face-down spell or permanent: a nameless, colorless 2/2 creature with no text (CR 708.2a).
_FACE_DOWN = _card(["creature"], 0, power=2, toughness=2)


@dataclass
class Obj:
    """One object during its stay in a zone; ``zone_changes`` counts its zone changes (spec 5.3)."""

    internal: int
    name: str                                    # the face currently up, a key of CARDS (spec 5.1)
    owner: str
    controller: str                              # the owner, except on the battlefield and the stack (spec 5.1)
    zone: str
    zone_changes: int = 0
    face_down: bool = False
    token: bool = False
    copy: bool = False
    # Permanent state (spec 6.4), shown on the battlefield. ``move`` resets it, and the two exile fields below.
    tapped: bool = False
    summoning_sick: bool = False
    damage: int = 0
    counters: dict[str, int] = field(default_factory=dict)
    attached_to: dict[str, Any] | None = None    # a target
    attack_target: dict[str, Any] | None = None  # a target; None while not attacking
    blocking: list[int] | None = None            # the attackers it blocks; None while not blocking
    phased_out: bool = False
    statuses: list[str] = field(default_factory=list)
    class_level: int | None = None               # a Class shows level 1 while this is None
    chosen: list[dict[str, str]] = field(default_factory=list)
    exiled_by: int | None = None                 # the object whose effect exiled this card and may return it
    face_down_visible_to: tuple[str, ...] = ()   # the seats the effect lets look at this face-down exiled card


@dataclass
class StackItem:
    """The stack entry (spec 6.5) of ``internal``, an object in zone "stack"; ``World.stack[0]`` is the bottom."""

    internal: int
    kind: str                                    # spell, activated_ability or triggered_ability
    source: int | None                           # an ability's source; None for a spell
    targets: list[dict[str, Any] | None]         # in target order
    divided: list[int] | None = None
    modes: list[int] | None = None
    x_value: int | None = None
    text: str | None = None


@dataclass(frozen=True)
class Posed:
    """One decision a scenario poses; the engine assigns candidate ids, ``seat_step`` and ``group_id`` (spec 8, 9.3).

    ``candidates`` are candidate semantics whose object references are written ``{"$obj": n}``; ``substep`` is
    ``(substep_index, substep_count)``; ``kind`` overrides the context kind the candidates imply (a
    ``mana_payment`` decision, spec 7.1); ``source`` (``{"$obj": n}`` or None), ``purpose``, ``text`` and
    ``rewind`` fill the decision's ``context``.
    """

    seat: str
    candidates: list[dict]
    substep: tuple[int, int] = (0, 1)
    kind: str | None = None
    purpose: str | None = None
    source: dict | None = None
    rewind: bool = False
    text: str | None = None
    extensions: dict = field(default_factory=dict)   # a mutable default would fail at import (R1-10)


@dataclass(frozen=True)
class Scenario:
    """A scripted game, offered as the catalog deck ``Scenario:<name>`` to an engine started with ``engine_args``.

    ``script(world)`` is a generator: it yields ``Posed`` decisions and receives each chosen ``candidate_id``.
    ``outcome`` is the terminal's ``(outcome, winner, reason)`` once the script ends.
    """

    name: str
    decklist: list[dict]
    engine_args: tuple[str, ...]
    script: Callable[[World], Generator[Posed, int, None]]
    outcome: tuple[str, str | None, str] = ("draw", None, "scenario_complete")


class World:
    """A two-player board, observed from either seat (spec 5.3, 6).

    Public state a scenario edits directly, per-player values as dicts keyed by seat: ``turn``, ``phase_step``,
    ``active_seat`` and ``priority_seat`` (1, ``precombat_main``, ``p0``, ``p0``; a pregame decision sets
    ``turn = 0``, ``phase_step = "pregame"`` and both seats to None), ``life``, ``poison``, ``counters``,
    ``mana_pool``, ``lands_played``, ``mulligans``, ``designations``, ``progress``, ``day_night``,
    ``passed_seats``, ``libraries``, ``stack`` (``StackItem`` entries, index 0 the bottom), ``pending_triggers``
    (spec 6.6 entries whose ``"source"`` is an internal id or None, in the order they go on the stack),
    ``known`` (per viewer, spec 6.7 entries; an entry for a card the viewer looks at carries ``"internal"``,
    never an ``object_id``) and ``objects`` (each ``Obj`` by internal id). ``flags`` holds the thirteen
    observation flags of spec 6.9. With its flag on, a field no scenario set shows its default (R2-12):
    ``poison`` 0, ``counters`` ``{}``, ``designations`` ``[]``, ``progress`` with no dungeon, room or speed
    and ``ring_tempted`` 0, ``day_night`` ``"none"``, ``passed_seats`` ``[]``, ``statuses`` and ``chosen`` ``[]``.
    """

    def __init__(self, game_secret: bytes, *, flags: Mapping[str, bool]) -> None:
        if type(game_secret) is not bytes or len(game_secret) != 32:
            raise ValueError("a game secret is exactly 32 raw bytes (spec 11.6)")
        if set(flags) != set(OBSERVATION_FLAGS) or any(type(value) is not bool for value in flags.values()):
            raise ValueError(f"flags must set each of the {len(OBSERVATION_FLAGS)} observation flags of spec 6.9 "
                             "to a boolean")
        self._game_secret = game_secret
        self.flags = dict(flags)
        self.turn = 1
        self.phase_step = "precombat_main"
        self.active_seat: str | None = "p0"
        self.priority_seat: str | None = "p0"
        self.life = dict.fromkeys(_SEATS, 20)
        self.poison = dict.fromkeys(_SEATS, 0)
        self.counters: dict[str, dict[str, int]] = {seat: {} for seat in _SEATS}
        self.mana_pool = {seat: dict.fromkeys(_MANA_SYMBOLS, 0) for seat in _SEATS}
        self.lands_played = dict.fromkeys(_SEATS, 0)
        self.mulligans = dict.fromkeys(_SEATS, 0)
        self.designations: dict[str, list[str]] = {seat: [] for seat in _SEATS}
        self.progress = {seat: {"dungeon": None, "dungeon_room": None, "ring_tempted": 0, "speed": None}
                         for seat in _SEATS}
        self.day_night = "none"
        self.passed_seats: list[str] = []
        self.libraries: dict[str, list[int]] = {seat: [] for seat in _SEATS}
        self.stack: list[StackItem] = []
        self.pending_triggers: list[dict[str, Any]] = []
        self.known: dict[str, list[dict[str, Any]]] = {seat: [] for seat in _SEATS}
        self.objects: dict[int, Obj] = {}            # in arrival order: move() re-inserts the object it moves
        self._next_internal = 1
        self._looks: dict[str, dict[int, str]] = {seat: {} for seat in _SEATS}    # current looks: internal to id
        self._look_counts: dict[tuple[str, int, int], int] = {}                  # (viewer, internal, stay) to n

    # Building the board.

    def add(self, name: str, *, owner: str, zone: str, controller: str | None = None, internal: int | None = None,
            **state: Any) -> int:
        """Put a new object into a zone and return its internal id; ``state`` sets other ``Obj`` fields.

        The object has been there since before this turn (summoning sick only when ``state`` says so); a library
        card goes to the bottom of its owner's library.
        """
        if name not in CARDS:
            raise ValueError(f"{name!r} is not a fixture card (see CARDS)")
        controller = _controller(owner, zone, controller)
        if internal is None:
            internal = self._next_internal
        elif type(internal) is not int or internal < 0 or internal in self.objects:
            raise ValueError(f"internal id {internal!r} is not a new nonnegative integer")
        obj = Obj(internal, name, owner, controller, zone, **state)
        _check_face_down(obj.face_down, zone)
        self._next_internal = max(self._next_internal, internal + 1)
        self.objects[internal] = obj
        if zone == "library":
            self.libraries[owner].append(internal)
        return internal

    def move(self, internal: int, zone: str, *, controller: str | None = None, library_position: int = 0,
             face_down: bool = False) -> None:
        """A zone change (CR 400.7): the object becomes a new object with fresh ids (spec 5.3).

        It arrives untapped, without damage, counters or other permanent state (summoning sick on the battlefield),
        with its front face up and ``face_down`` as given (a face-down card leaving the battlefield is revealed,
        CR 708.9), and every reference the World holds to it is severed. A library card lands ``library_position``
        cards from the top (0 is the top; the library's size without the card is the bottom).
        """
        obj = self._object(internal)
        controller = _controller(obj.owner, zone, controller)
        _check_face_down(face_down, zone)
        library = self.libraries[obj.owner]
        if zone == "library":
            bottom = len(library) - (1 if obj.zone == "library" else 0)
            if type(library_position) is not int or not 0 <= library_position <= bottom:
                raise ValueError(f"library_position runs from 0 (the top) to {bottom} (the bottom), "
                                 f"not {library_position!r}")
        self._sever(internal)
        if obj.zone == "library":
            library.remove(internal)
        obj.zone, obj.controller, obj.face_down = zone, controller, face_down
        obj.zone_changes += 1
        full_name = CARDS[obj.name]["full_name"]
        if full_name is not None:
            obj.name = full_name.split(" // ")[0]
        obj.tapped, obj.summoning_sick, obj.damage, obj.counters = False, zone == "battlefield", 0, {}
        obj.attached_to = obj.attack_target = obj.blocking = None
        obj.phased_out, obj.statuses, obj.class_level, obj.chosen = False, [], None, []
        obj.exiled_by, obj.face_down_visible_to = None, ()
        if zone == "library":
            library.insert(library_position, internal)
        del self.objects[internal]
        self.objects[internal] = obj

    def _sever(self, internal: int) -> None:
        """Every reference the World holds to this object now names an object that left (spec 5.1, 6.4 to 6.7)."""
        self.stack[:] = [item for item in self.stack if item.internal != internal]
        for item in self.stack:
            if item.source == internal:
                item.source = None
            item.targets = [_sever_target(target, internal) for target in item.targets]
        for obj in self.objects.values():
            obj.attached_to = _sever_target(obj.attached_to, internal)
            obj.attack_target = _sever_target(obj.attack_target, internal)    # still attacking; its target left
            if obj.blocking is not None:                                        # still blocking (CR 509.1h)
                obj.blocking = [attacker for attacker in obj.blocking if attacker != internal]
            if obj.exiled_by == internal:
                obj.exiled_by = None
        self.pending_triggers[:] = [{**trigger, "source": None} if trigger.get("source") == internal else trigger
                                    for trigger in self.pending_triggers]
        for seat in _SEATS:
            self._looks[seat].pop(internal, None)
            self.known[seat][:] = [{key: value for key, value in entry.items() if key != "internal"}
                                   if entry.get("internal") == internal else entry for entry in self.known[seat]]

    # Ids and references.

    def object_id(self, viewer: str, internal: int) -> str:
        """The id of an object in a zone the viewer sees, from ``"<viewer>:card-<internal>:z<zone changes>"``."""
        obj = self._object(internal)
        if _hidden(_seat(viewer), obj):
            raise ValueError(f"card-{internal} is in a zone hidden from {viewer}, where it has look ids (look())")
        return recommended_object_id(self._game_secret, f"{viewer}:card-{internal}:z{obj.zone_changes}")

    def look(self, viewer: str, internal: int) -> str:
        """Show the viewer a card in a zone hidden from it (spec 5.3) and return the card's look id.

        The id comes from ``"<viewer>:card-<internal>:z<zone changes>:look:<n>"``, where n counts the viewer's
        looks at the card during its stay in the zone, and stays the same until ``end_looks(viewer)``.
        """
        obj = self._object(internal)
        if not _hidden(_seat(viewer), obj):
            raise ValueError(f"card-{internal} is in a zone {viewer} sees; a look shows a card in a hidden zone")
        looks = self._looks[viewer]
        if internal not in looks:
            stay = (viewer, internal, obj.zone_changes)
            n = self._look_counts.get(stay, 0)
            self._look_counts[stay] = n + 1
            looks[internal] = recommended_object_id(self._game_secret,
                                                    f"{viewer}:card-{internal}:z{obj.zone_changes}:look:{n}")
        return looks[internal]

    def end_looks(self, viewer: str) -> None:
        """The effect that showed the viewer its current looks is over; a later look gets a fresh id."""
        self._looks[_seat(viewer)].clear()

    def reference(self, viewer: str, internal: int) -> dict[str, Any] | None:
        """The object reference the viewer sees (spec 5.1), or None for an object outside its observation.

        Outside are a card in a hidden zone the viewer is not looking at, and an object in zone "stack" that has
        no stack item.
        """
        obj = self._object(internal)
        if _hidden(_seat(viewer), obj):
            object_id = self._looks[viewer].get(internal)
            if object_id is None:
                return None
        elif obj.zone == "stack" and all(item.internal != internal for item in self.stack):
            return None
        else:
            object_id = self.object_id(viewer, internal)
        return {"object_id": object_id, "card_name": obj.name if _shows_name(viewer, obj) else None,
                "owner_seat": obj.owner, "controller_seat": obj.controller, "zone": obj.zone}

    def target(self, viewer: str, target: dict[str, Any] | None) -> dict[str, Any] | None:
        """A target, ``{"object": {"$obj": n}}`` or ``{"player": seat}``, as the viewer sees it (spec 5.2).

        A target whose object left, or is outside the viewer's observation, is None (spec 5.1).
        """
        _seat(viewer)
        if target is None:
            return None
        if target.keys() == {"player"}:
            return {"player": _seat(target["player"])}
        if target.keys() == {"object"}:
            if target["object"] is None:                 # severed: the object left
                return None
            reference = self.reference(viewer, _internal_of(target["object"]))
            return None if reference is None else {"object": reference}
        raise ValueError(f'a target is {{"object": {{"$obj": n}}}} or {{"player": seat}}, not {target!r}')

    # The observation.

    def observation(self, viewer: str) -> dict[str, Any]:
        """The viewer's observation (spec 6.2 to 6.7); it shares no mutable state with the World."""
        _seat(viewer)
        self._check_stack_and_libraries()
        flags = self.flags
        return deepcopy({
            "viewer": viewer,
            "turn": self.turn,
            "phase_step": self.phase_step,
            "active_seat": self.active_seat,
            "priority_seat": self.priority_seat,
            "passed_seats": self.passed_seats if flags["passed_seats"] else None,
            "day_night": self.day_night if flags["day_night"] else None,
            "players": [self._player(viewer, seat) for seat in _SEATS],
            "stack": [self._stack_entry(viewer, item) for item in self.stack],
            "pending_triggers": self._pending_triggers(viewer) if flags["pending_triggers"] else None,
            "known": self._known(viewer),
        })

    def _player(self, viewer: str, seat: str) -> dict[str, Any]:
        """Spec 6.3: the viewer sees its own hand only; zone arrays list the oldest object first."""
        flags = self.flags
        hand = self._owned("hand", seat)
        return {
            "seat": seat,
            "life": self.life[seat],
            "poison": self.poison[seat] if flags["poison"] else None,
            "counters": self.counters[seat] if flags["player_counters"] else None,
            "mana_pool": {symbol: self.mana_pool[seat][symbol] for symbol in _MANA_SYMBOLS},
            "lands_played_this_turn": self.lands_played[seat],
            "mulligans_taken": self.mulligans[seat],
            "designations": self.designations[seat] if flags["designations"] else None,
            "progress": self.progress[seat] if flags["player_progress"] else None,
            "hand_count": len(hand),
            "library_count": len(self.libraries[seat]),
            "hand": [self._record(viewer, obj) for obj in hand] if seat == viewer else None,
            "battlefield": [self._record(viewer, obj) for obj in self.objects.values()
                            if obj.zone == "battlefield" and obj.controller == seat],
            "graveyard": [self._record(viewer, obj) for obj in self._owned("graveyard", seat)],
            "exile": [self._record(viewer, obj) for obj in self._owned("exile", seat)],
            "command": [self._record(viewer, obj) for obj in self._owned("command", seat)],
        }

    def _record(self, viewer: str, obj: Obj) -> dict[str, Any]:
        """An object record (spec 6.4)."""
        reference = self.reference(viewer, obj.internal)
        characteristics = self._characteristics(viewer, obj)
        return {
            **reference,
            "full_name": (CARDS[obj.name]["full_name"]
                          if self.flags["full_name"] and reference["card_name"] is not None else None),
            "face_down": obj.face_down,
            "token": obj.token,
            "copy": obj.copy,
            "characteristics": characteristics,
            "permanent": self._permanent(viewer, obj, characteristics) if obj.zone == "battlefield" else None,
            "exiled_by": (self.reference(viewer, obj.exiled_by)
                          if self.flags["exiled_by"] and obj.exiled_by is not None else None),
        }

    def _characteristics(self, viewer: str, obj: Obj) -> dict[str, Any] | None:
        """Printed characteristics (spec 6.4); a face-down object shows the face-down 2/2 or, in exile, nothing."""
        if obj.face_down and obj.zone in _CONTROLLED_ZONES:
            card = _FACE_DOWN
        elif obj.face_down and viewer not in obj.face_down_visible_to:
            return None                                  # hidden with its name (spec 6.4, 6.8)
        else:
            card = CARDS[obj.name]
        characteristics = {name: card[name] for name in _CHARACTERISTICS}
        characteristics["colors"] = sorted(card["colors"], key=_COLOR_ORDER.index)
        if not self.flags["keywords"]:
            characteristics["keywords"] = None
        return characteristics

    def _permanent(self, viewer: str, obj: Obj, characteristics: dict[str, Any]) -> dict[str, Any]:
        """A battlefield object's permanent state (spec 6.4)."""
        details = self.flags["permanent_details"]
        class_level = None
        if details and "class" in characteristics["subtypes"]:
            class_level = 1 if obj.class_level is None else obj.class_level       # a Class enters at level 1
        blocked = [self.reference(viewer, attacker) for attacker in obj.blocking or ()]
        return {
            "tapped": obj.tapped,
            "summoning_sick": obj.summoning_sick,
            "damage": obj.damage,
            "counters": obj.counters,
            "attached_to": self.target(viewer, obj.attached_to),
            "attacking": obj.attack_target is not None,
            "attack_target": self.target(viewer, obj.attack_target),
            "blocking": obj.blocking is not None,
            "blocked_attackers": [ref for ref in blocked if ref is not None and ref["zone"] == "battlefield"],
            "phased_out": obj.phased_out,
            "statuses": obj.statuses if details else None,
            "class_level": class_level,
            "chosen": obj.chosen if details else None,
        }

    def _stack_entry(self, viewer: str, item: StackItem) -> dict[str, Any]:
        """A stack entry (spec 6.5)."""
        if item.kind not in _STACK_KINDS:
            raise ValueError(f"stack item kind {item.kind!r} is not one of {', '.join(_STACK_KINDS)}")
        spell = item.kind == "spell"
        if spell and item.source is not None:
            raise ValueError("a spell on the stack has no source (spec 6.5): give its StackItem source None")
        obj = self.objects[item.internal]
        return {
            **self.reference(viewer, item.internal),
            "stack_kind": item.kind,
            "source": None if item.source is None else self.reference(viewer, item.source),
            "face_down": obj.face_down,
            "copy": obj.copy,
            "characteristics": self._characteristics(viewer, obj) if spell else None,
            "targets": [self.target(viewer, target) for target in item.targets],
            "divided": item.divided,
            "modes": item.modes,
            "x_value": item.x_value,
            "text": item.text if self.flags["stack_text"] else None,
        }

    def _pending_triggers(self, viewer: str) -> list[dict[str, Any]]:
        """Spec 6.6: a trigger whose source is in a zone hidden from the viewer, and not shown to it, is omitted."""
        entries = []
        for trigger in self.pending_triggers:
            source = trigger["source"]
            if source is not None and _hidden(viewer, self._object(source)) and source not in self._looks[viewer]:
                continue
            entries.append({"source": None if source is None else self.reference(viewer, source),
                            "source_name": trigger["source_name"], "controller_seat": trigger["controller_seat"],
                            "label": trigger["label"], "optional": trigger["optional"]})
        return entries

    def _known(self, viewer: str) -> list[dict[str, Any]]:
        """Spec 6.7: the viewer's entries, a looked-at card's entry with its look id, in the spec's order.

        Without ``known_cards`` only the entries of the cards the viewer is looking at remain (R2-6).
        """
        looks = self._looks[viewer]
        entries = []
        for entry in self.known[viewer]:
            if entry.get("object_id") is not None:
                raise ValueError('a known entry names a looked-at card with "internal"; the World writes object_id')
            look = looks.get(entry.get("internal"))
            if look is None and not self.flags["known_cards"]:
                continue
            if look is not None:
                obj = self.objects[entry["internal"]]
                if (entry["owner_seat"], entry["zone"], entry["card_name"]) != (obj.owner, obj.zone, obj.name):
                    raise ValueError(f"the known entry for card-{obj.internal} names another owner, zone or card")
            entries.append({"owner_seat": entry["owner_seat"], "zone": entry["zone"], "card_name": entry["card_name"],
                            "object_id": look, "position_from_top": entry["position_from_top"],
                            "position_from_bottom": entry["position_from_bottom"], "how": entry["how"]})
        return sorted(entries, key=_known_sort_key)

    # Helpers.

    def _object(self, internal: int) -> Obj:
        try:
            return self.objects[internal]
        except KeyError:
            raise KeyError(f"no object with internal id {internal!r}") from None

    def _owned(self, zone: str, owner: str) -> list[Obj]:
        return [obj for obj in self.objects.values() if obj.zone == zone and obj.owner == owner]

    def _check_stack_and_libraries(self) -> None:
        """Fail loudly on a board no observation can show."""
        for item in self.stack:
            obj = self._object(item.internal)
            if obj.zone != "stack":
                raise ValueError(f"the stack item of card-{item.internal} ({obj.name}) is not on the stack; "
                                 "move() the object there first")
        for seat in _SEATS:
            if sorted(self.libraries[seat]) != sorted(obj.internal for obj in self._owned("library", seat)):
                raise ValueError(f"libraries[{seat!r}] must list exactly the cards in {seat}'s library")


def _seat(value: Any) -> str:
    if value not in _SEATS:
        raise ValueError(f"a seat is p0 or p1, not {value!r}")
    return value


def _controller(owner: str, zone: str, controller: str | None) -> str:
    """Only battlefield and stack objects may have a controller other than their owner (spec 5.1)."""
    _seat(owner)
    if zone not in _ZONES:
        raise ValueError(f"{zone!r} is not a zone")
    if controller is None:
        return owner
    if _seat(controller) != owner and zone not in _CONTROLLED_ZONES:
        raise ValueError(f"an object in the {zone} is controlled by its owner (spec 5.1)")
    return controller


def _check_face_down(face_down: bool, zone: str) -> None:
    if face_down and zone not in _FACE_DOWN_ZONES:
        raise ValueError(f"only battlefield, stack and exile objects can be face down, not a {zone} object")


def _hidden(viewer: str, obj: Obj) -> bool:
    """Libraries, the viewer's own included, and the other seat's hand are hidden zones (spec 6.8)."""
    return obj.zone == "library" or (obj.zone == "hand" and obj.owner != viewer)


def _shows_name(viewer: str, obj: Obj) -> bool:
    """A face-down object's name shows to its controller (CR 708.5) or, in exile, to the seats the effect lets look."""
    if not obj.face_down:
        return True
    if obj.zone in _CONTROLLED_ZONES:
        return viewer == obj.controller
    return viewer in obj.face_down_visible_to


def _internal_of(reference: Any) -> int:
    """The internal id of an object reference written ``{"$obj": n}``."""
    if not (isinstance(reference, dict) and reference.keys() == {"$obj"} and type(reference["$obj"]) is int):
        raise ValueError(f'an object reference is written {{"$obj": <internal id>}}, not {reference!r}')
    return reference["$obj"]


def _sever_target(target: dict[str, Any] | None, internal: int) -> dict[str, Any] | None:
    """A target naming the object that left becomes ``{"object": None}``, which shows as null (spec 5.1)."""
    if target is not None and target.get("object") is not None and _internal_of(target["object"]) == internal:
        return {"object": None}
    return target


def _nullable(value: Any) -> tuple[int, Any]:
    return (0, "") if value is None else (1, value)


def _known_sort_key(entry: Mapping[str, Any]) -> tuple:
    """Spec 6.7: owner_seat, zone, card_name, position_from_top, position_from_bottom, how, object_id; nulls first."""
    return (entry["owner_seat"], entry["zone"], entry["card_name"], _nullable(entry["position_from_top"]),
            _nullable(entry["position_from_bottom"]), entry["how"], _nullable(entry["object_id"]))
