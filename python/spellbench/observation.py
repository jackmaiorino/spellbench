"""The observation (spec 6): the acting seat's board view, its schema and its reference walkers.

``validate_observation`` checks structure only (V1, spec 11.3): every field,
type and vocabulary of spec 6, plus the structural rules of spec 6.2 to 6.6
that each validator's docstring lists. Optional fields (spec 6.9) are null or
typed here; whether each follows its flag is V8's check. What the viewer may
see is V5's (the other seat's hand, ``hand_count``, a record claiming
``library``, and the shape, count and order of ``known``) and V6's (which
face-down objects must be nameless), and V4 matches every reference inside the
observation against the held objects through ``observation_objects`` and
``observation_references``. V1 also keeps a hidden identity hidden within the
observation (spec 5.1, 6.8): a nameless record has a null ``full_name`` (and,
face-down off the battlefield, null ``characteristics``), and an ability or a
pending trigger whose source is nameless is nameless too.

Every error context is the path of the offending value, for example
``observation.players[0].battlefield[0].permanent.counters``, because the
validator's halt message quotes it.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Iterator, Mapping

from ._schema import (
    I32_MAX,
    I32_MIN,
    OBSERVATION_FLAGS,  # re-exported: the flags of the optional fields (spec 6.9)
    REFERENCE_FIELDS,
    SEATS,
    array,
    as_object,
    boolean,
    card_name,
    exact_keys,
    fail,
    i32,
    name_hidden_with_source,
    nonempty,
    nullable,
    object_ref,
    quoted,
    safe_int,
    seat,
    snake,
    target_ref,
    text,
    u32,
    vocab,
)

# Spec 6.2: pregame, then the steps of a turn in order.
PHASE_STEPS = (
    "pregame",
    "untap",
    "upkeep",
    "draw",
    "precombat_main",
    "beginning_of_combat",
    "declare_attackers",
    "declare_blockers",
    "combat_damage",
    "end_of_combat",
    "postcombat_main",
    "end_step",
    "cleanup",
)
DAY_NIGHT = ("day", "night", "none")
# Spec 6.3: a player's object-record arrays, in field order.
ZONE_ARRAYS = ("hand", "battlefield", "graveyard", "exile", "command")
# Spec 6.5.
STACK_KINDS = ("spell", "activated_ability", "triggered_ability")
# Spec 6.7.
KNOWN_ZONES = ("hand", "library")
KNOWN_HOW = ("revealed", "looked_at", "from_public_zone", "own_placement", "searching", "tracked")
# Spec 6.10.
SUPERTYPES = ("basic", "legendary", "ongoing", "snow", "world")
CARD_TYPES = (
    "artifact",
    "battle",
    "conspiracy",
    "creature",
    "dungeon",
    "enchantment",
    "instant",
    "kindred",
    "land",
    "phenomenon",
    "plane",
    "planeswalker",
    "scheme",
    "sorcery",
    "vanguard",
)
COLOR_ORDER = ("white", "blue", "black", "red", "green")
CHOSEN_KINDS = ("color", "card_name", "creature_type", "card_type", "land_type", "number", "player", "mode", "other")

# The field tables of spec 6.2 to 6.7, in table order.
_OBSERVATION_FIELDS = (
    "viewer",
    "turn",
    "phase_step",
    "active_seat",
    "priority_seat",
    "passed_seats",
    "day_night",
    "players",
    "stack",
    "pending_triggers",
    "known",
)
_PLAYER_FIELDS = (
    "seat",
    "life",
    "poison",
    "counters",
    "mana_pool",
    "lands_played_this_turn",
    "mulligans_taken",
    "designations",
    "progress",
    "hand_count",
    "library_count",
    *ZONE_ARRAYS,
)
_MANA_POOL_FIELDS = ("W", "U", "B", "R", "G", "C")
_PROGRESS_FIELDS = ("dungeon", "dungeon_room", "ring_tempted", "speed")
_RECORD_FIELDS = (
    *REFERENCE_FIELDS,
    "full_name",
    "face_down",
    "token",
    "copy",
    "characteristics",
    "permanent",
    "exiled_by",
)
_CHARACTERISTICS_FIELDS = ("supertypes", "types", "subtypes", "colors", "mana_value", "power", "toughness", "keywords")
_PERMANENT_FIELDS = (
    "tapped",
    "summoning_sick",
    "damage",
    "counters",
    "attached_to",
    "attacking",
    "attack_target",
    "blocking",
    "blocked_attackers",
    "phased_out",
    "statuses",
    "class_level",
    "chosen",
)
_CHOSEN_FIELDS = ("kind", "value")
_STACK_FIELDS = (
    *REFERENCE_FIELDS,
    "stack_kind",
    "source",
    "face_down",
    "copy",
    "characteristics",
    "targets",
    "divided",
    "modes",
    "x_value",
    "text",
)
_PENDING_TRIGGER_FIELDS = ("source", "source_name", "controller_seat", "label", "optional")
_KNOWN_FIELDS = ("owner_seat", "zone", "card_name", "object_id", "position_from_top", "position_from_bottom", "how")
# Spec 4.4 and 6.10: a chosen number is an i32 written in decimal, so it may carry a sign.
_DECIMAL_RE = re.compile(r"\A(?:0|-?[1-9][0-9]*)\Z")
_I32_DIGITS = len(str(I32_MIN))  # the longest i32 in decimal; a longer string never reaches int()


def _one_of(allowed: tuple[str, ...]) -> Callable[[Any, str], str]:
    """A check for one value of a closed vocabulary."""
    return lambda value, context: vocab(value, allowed, context)


def _array_of(check: Callable[[Any, str], Any]) -> Callable[[Any, str], list[Any]]:
    """A check for an array whose every entry ``check`` accepts, each under ``context[i]``."""

    def checked(value: Any, context: str) -> list[Any]:
        items = array(value, context)
        for index, item in enumerate(items):
            check(item, f"{context}[{index}]")
        return items

    return checked


def _decimal(value: Any, context: str) -> str:
    """An i32 in decimal, without leading zeros (spec 4.4, 6.10)."""
    number = text(value, context)
    if not (_DECIMAL_RE.fullmatch(number) and len(number) <= _I32_DIGITS and I32_MIN <= int(number) <= I32_MAX):
        fail(context, f"{quoted(value)} is not an i32 in decimal")
    return value


def _nullable_target(value: Any, context: str) -> dict[str, Any] | None:
    """A target reference, or null for a target that no longer exists (spec 6.5)."""
    return nullable(value, target_ref, context)


_day_night = _one_of(DAY_NIGHT)
_seat_list = _array_of(seat)
# Subtypes, keywords, statuses and designations are normalized names (spec 6.10).
_snake_list = _array_of(snake)
_u32_list = _array_of(u32)
_supertype_list = _array_of(_one_of(SUPERTYPES))
_card_type_list = _array_of(_one_of(CARD_TYPES))
_color_list = _array_of(_one_of(COLOR_ORDER))
_object_ref_list = _array_of(object_ref)
_target_list = _array_of(_nullable_target)
# Spec 6.10: names as in spec 4.4, numbers in decimal, players as seats; colors, card types and
# subtypes in their vocabularies; a mode or another value is a plain string.
_CHOSEN_VALUES: dict[str, Callable[[Any, str], Any]] = {
    "color": _one_of(COLOR_ORDER),
    "card_name": card_name,
    "creature_type": snake,
    "card_type": _one_of(CARD_TYPES),
    "land_type": snake,
    "number": _decimal,
    "player": seat,
    "mode": text,
    "other": text,
}


def _reference(item: Mapping[str, Any]) -> dict[str, Any]:
    """The object reference (spec 5.1) at the head of a record or stack entry: its five reference fields."""
    return {key: item[key] for key in REFERENCE_FIELDS}


def validate_observation(value: Any, context: str = "observation") -> dict[str, Any]:
    """Check an observation's structure (V1, spec 6); returns the input dict.

    Beyond types (spec 6.2): ``players`` is exactly p0 then p1, ``phase_step``
    is ``pregame`` exactly when ``turn`` is 0, ``active_seat`` is null only in
    ``pregame``, and ``priority_seat`` is null in ``pregame``, where no player
    has priority.
    """
    observation = as_object(value, context)
    exact_keys(observation, _OBSERVATION_FIELDS, context)
    seat(observation["viewer"], f"{context}.viewer")
    turn = safe_int(observation["turn"], f"{context}.turn")
    phase_step = vocab(observation["phase_step"], PHASE_STEPS, f"{context}.phase_step")
    if (phase_step == "pregame") != (turn == 0):
        fail(f"{context}.phase_step", f"must be pregame exactly when turn is 0, got {phase_step!r} in turn {turn}")
    if nullable(observation["active_seat"], seat, f"{context}.active_seat") is None and phase_step != "pregame":
        fail(f"{context}.active_seat", f"is null only in pregame, got null in {phase_step}")
    if nullable(observation["priority_seat"], seat, f"{context}.priority_seat") is not None and phase_step == "pregame":
        fail(f"{context}.priority_seat", "must be null in pregame, where no player has priority")
    nullable(observation["passed_seats"], _seat_list, f"{context}.passed_seats")
    nullable(observation["day_night"], _day_night, f"{context}.day_night")
    players = array(observation["players"], f"{context}.players", min_length=2, max_length=2)
    for index, player in enumerate(players):
        _player(player, SEATS[index], f"{context}.players[{index}]")
    for index, entry in enumerate(array(observation["stack"], f"{context}.stack")):
        _stack_entry(entry, f"{context}.stack[{index}]")
    triggers = nullable(observation["pending_triggers"], array, f"{context}.pending_triggers")
    for index, trigger in enumerate(triggers or ()):
        _pending_trigger(trigger, f"{context}.pending_triggers[{index}]")
    for index, entry in enumerate(array(observation["known"], f"{context}.known")):
        _known_entry(entry, f"{context}.known[{index}]")
    return observation


def _player(value: Any, expected_seat: str, context: str) -> None:
    """A player entry (spec 6.3): the seat its position says, ``mana_pool`` exactly W U B R G C."""
    player = as_object(value, context)
    exact_keys(player, _PLAYER_FIELDS, context)
    if seat(player["seat"], f"{context}.seat") != expected_seat:
        fail(f"{context}.seat", f"must be {expected_seat} (players are p0 then p1), got {player['seat']!r}")
    i32(player["life"], f"{context}.life")
    nullable(player["poison"], u32, f"{context}.poison")
    nullable(player["counters"], _counters, f"{context}.counters")
    _mana_pool(player["mana_pool"], f"{context}.mana_pool")
    u32(player["lands_played_this_turn"], f"{context}.lands_played_this_turn")
    u32(player["mulligans_taken"], f"{context}.mulligans_taken")
    nullable(player["designations"], _snake_list, f"{context}.designations")
    nullable(player["progress"], _progress, f"{context}.progress")
    u32(player["hand_count"], f"{context}.hand_count")
    u32(player["library_count"], f"{context}.library_count")
    for zone_array in ZONE_ARRAYS:
        records = player[zone_array]
        if zone_array == "hand" and records is None:  # the other seat's hand; V5 checks whose hand is null
            continue
        for index, record in enumerate(array(records, f"{context}.{zone_array}")):
            _record(record, zone_array, expected_seat, f"{context}.{zone_array}[{index}]")


def _mana_pool(value: Any, context: str) -> None:
    pool = as_object(value, context)
    exact_keys(pool, _MANA_POOL_FIELDS, context)
    for symbol in _MANA_POOL_FIELDS:
        u32(pool[symbol], f"{context}.{symbol}")


def _progress(value: Any, context: str) -> dict[str, Any]:
    progress = as_object(value, context)
    exact_keys(progress, _PROGRESS_FIELDS, context)
    nullable(progress["dungeon"], card_name, f"{context}.dungeon")  # a dungeon is a card with an Oracle name
    nullable(progress["dungeon_room"], text, f"{context}.dungeon_room")
    u32(progress["ring_tempted"], f"{context}.ring_tempted")
    nullable(progress["speed"], u32, f"{context}.speed")
    return progress


def _counters(value: Any, context: str) -> dict[str, Any]:
    """Counters by canonical name (spec 6.10), u32 each."""
    counters = as_object(value, context)
    for name, count in counters.items():
        snake(name, context)
        u32(count, f"{context}.{name}")
    return counters


def _record(value: Any, zone_array: str, holder: str, context: str) -> None:
    """An object record (spec 6.4) in the ``zone_array`` of ``holder``'s player entry.

    Its ``zone`` is its array (a record claiming ``library`` is left for V5 to
    report, spec 6.3). A battlefield record is controlled by its player; any
    other record is owned by its player and has its owner as controller (spec
    5.1). ``permanent`` is non-null exactly on the battlefield. ``characteristics``
    is null exactly for a face-down record outside the battlefield whose name
    is hidden: its printed characteristics are hidden with its name (spec 6.4,
    6.8). A nameless record has a null ``full_name`` for the same reason. Only an
    exiled card has an exiling object (``exiled_by``).
    """
    record = as_object(value, context)
    exact_keys(record, _RECORD_FIELDS, context)
    object_ref(_reference(record), context)
    if record["zone"] not in (zone_array, "library"):
        fail(f"{context}.zone", f"must be {zone_array}, the record's array, got {record['zone']!r}")
    on_battlefield = zone_array == "battlefield"
    owner, controller = record["owner_seat"], record["controller_seat"]
    if on_battlefield:
        if controller != holder:
            fail(f"{context}.controller_seat", f"must be {holder}, whose battlefield holds it, got {controller!r}")
    elif owner != holder:
        fail(f"{context}.owner_seat", f"must be {holder}, whose {zone_array} holds it, got {owner!r}")
    elif controller != owner:
        fail(f"{context}.controller_seat", f"must be the owner {owner}, as for any object without a controller")
    if nullable(record["full_name"], card_name, f"{context}.full_name") is not None and record["card_name"] is None:
        fail(f"{context}.full_name", "must be null when card_name is null: a hidden identity hides its full name too")
    face_down = boolean(record["face_down"], f"{context}.face_down")
    boolean(record["token"], f"{context}.token")
    boolean(record["copy"], f"{context}.copy")
    hidden = face_down and not on_battlefield and record["card_name"] is None
    if record["characteristics"] is None:
        if not hidden:
            fail(f"{context}.characteristics", "is null only for a nameless face-down card off the battlefield")
    elif hidden:
        fail(f"{context}.characteristics", "must be null for a nameless face-down card off the battlefield")
    else:
        _characteristics(record["characteristics"], f"{context}.characteristics")
    if on_battlefield:
        if record["permanent"] is None:
            fail(f"{context}.permanent", "must be an object on the battlefield")
        _permanent(record["permanent"], f"{context}.permanent")
    elif record["permanent"] is not None:
        fail(f"{context}.permanent", f"must be null outside the battlefield, got an object in {zone_array}")
    if nullable(record["exiled_by"], object_ref, f"{context}.exiled_by") is not None and zone_array != "exile":
        fail(f"{context}.exiled_by", f"must be null outside exile, got an exiling object in {zone_array}")


def _characteristics(value: Any, context: str) -> None:
    """Characteristics (spec 6.4): ``colors`` in ``COLOR_ORDER`` order, power and toughness exactly on creatures."""
    characteristics = as_object(value, context)
    exact_keys(characteristics, _CHARACTERISTICS_FIELDS, context)
    _supertype_list(characteristics["supertypes"], f"{context}.supertypes")
    types = _card_type_list(characteristics["types"], f"{context}.types")
    _snake_list(characteristics["subtypes"], f"{context}.subtypes")
    colors = _color_list(characteristics["colors"], f"{context}.colors")
    positions = [COLOR_ORDER.index(color) for color in colors]
    if positions != sorted(set(positions)):
        fail(f"{context}.colors", f"must be a subset of {', '.join(COLOR_ORDER)} in that order, got {quoted(colors)}")
    u32(characteristics["mana_value"], f"{context}.mana_value")
    creature = "creature" in types
    for field in ("power", "toughness"):
        number = nullable(characteristics[field], i32, f"{context}.{field}")
        if number is not None and not creature:
            fail(f"{context}.{field}", f"must be null for a noncreature, got {number!r}")
        if number is None and creature:
            fail(f"{context}.{field}", "must be an integer for a creature, which always has power and toughness")
    nullable(characteristics["keywords"], _snake_list, f"{context}.keywords")


def _permanent(value: Any, context: str) -> None:
    """Permanent state (spec 6.4): an attack target only while attacking, blocked attackers only while blocking."""
    permanent = as_object(value, context)
    exact_keys(permanent, _PERMANENT_FIELDS, context)
    boolean(permanent["tapped"], f"{context}.tapped")
    boolean(permanent["summoning_sick"], f"{context}.summoning_sick")
    u32(permanent["damage"], f"{context}.damage")
    _counters(permanent["counters"], f"{context}.counters")
    nullable(permanent["attached_to"], target_ref, f"{context}.attached_to")
    attacking = boolean(permanent["attacking"], f"{context}.attacking")
    if nullable(permanent["attack_target"], target_ref, f"{context}.attack_target") is not None and not attacking:
        fail(f"{context}.attack_target", "must be null unless the creature is attacking")
    blocking = boolean(permanent["blocking"], f"{context}.blocking")
    if _object_ref_list(permanent["blocked_attackers"], f"{context}.blocked_attackers") and not blocking:
        fail(f"{context}.blocked_attackers", "must be empty unless the creature is blocking")
    boolean(permanent["phased_out"], f"{context}.phased_out")
    nullable(permanent["statuses"], _snake_list, f"{context}.statuses")
    nullable(permanent["class_level"], u32, f"{context}.class_level")
    chosen = nullable(permanent["chosen"], array, f"{context}.chosen")
    for index, entry in enumerate(chosen or ()):
        _chosen(entry, f"{context}.chosen[{index}]")


def _chosen(value: Any, context: str) -> None:
    """A public chosen value ``{kind, value}``, the value in the form its kind names (spec 6.10)."""
    chosen = as_object(value, context)
    exact_keys(chosen, _CHOSEN_FIELDS, context)
    kind = vocab(chosen["kind"], CHOSEN_KINDS, f"{context}.kind")
    _CHOSEN_VALUES[kind](chosen["value"], f"{context}.value")


def _stack_entry(value: Any, context: str) -> None:
    """A stack entry (spec 6.5) in zone ``stack``.

    A spell has characteristics and a null source; an ability has null
    characteristics, and is nameless when its source is, since it is named
    after its source (spec 5.1). ``divided`` holds one amount per target.
    """
    entry = as_object(value, context)
    exact_keys(entry, _STACK_FIELDS, context)
    object_ref(_reference(entry), context)
    if entry["zone"] != "stack":
        fail(f"{context}.zone", f"must be stack, got {entry['zone']!r}")
    spell = vocab(entry["stack_kind"], STACK_KINDS, f"{context}.stack_kind") == "spell"
    source = nullable(entry["source"], object_ref, f"{context}.source")
    if source is not None and spell:
        fail(f"{context}.source", "must be null for a spell")
    name_hidden_with_source(source, entry["card_name"], f"{context}.card_name")
    boolean(entry["face_down"], f"{context}.face_down")
    boolean(entry["copy"], f"{context}.copy")
    if entry["characteristics"] is None:
        if spell:
            fail(f"{context}.characteristics", "must be an object for a spell")
    elif not spell:
        fail(f"{context}.characteristics", f"must be null for an ability, got an object for a {entry['stack_kind']}")
    else:
        _characteristics(entry["characteristics"], f"{context}.characteristics")
    targets = _target_list(entry["targets"], f"{context}.targets")
    divided = nullable(entry["divided"], _u32_list, f"{context}.divided")
    if divided is not None and len(divided) != len(targets):
        fail(f"{context}.divided", f"must hold one amount per target ({len(targets)}), got {len(divided)} (CR 601.2d)")
    nullable(entry["modes"], _u32_list, f"{context}.modes")
    nullable(entry["x_value"], u32, f"{context}.x_value")
    nullable(entry["text"], text, f"{context}.text")


def _pending_trigger(value: Any, context: str) -> None:
    """A pending trigger (spec 6.6): its ``source_name`` is null when its source's name is hidden (spec 5.1, 6.8)."""
    trigger = as_object(value, context)
    exact_keys(trigger, _PENDING_TRIGGER_FIELDS, context)
    source = nullable(trigger["source"], object_ref, f"{context}.source")
    source_name = nullable(trigger["source_name"], card_name, f"{context}.source_name")
    name_hidden_with_source(source, source_name, f"{context}.source_name")
    seat(trigger["controller_seat"], f"{context}.controller_seat")
    nullable(trigger["label"], text, f"{context}.label")
    boolean(trigger["optional"], f"{context}.optional")


def _known_entry(value: Any, context: str) -> None:
    """A ``known`` entry, types only (spec 6.7): knowledge is name-level, so its name is never null.

    Its shape (whose hand, which positions, which ``how`` may carry an id),
    the counts and the order are V5's.
    """
    entry = as_object(value, context)
    exact_keys(entry, _KNOWN_FIELDS, context)
    seat(entry["owner_seat"], f"{context}.owner_seat")
    vocab(entry["zone"], KNOWN_ZONES, f"{context}.zone")
    card_name(entry["card_name"], f"{context}.card_name")
    nullable(entry["object_id"], nonempty, f"{context}.object_id")
    nullable(entry["position_from_top"], u32, f"{context}.position_from_top")
    nullable(entry["position_from_bottom"], u32, f"{context}.position_from_bottom")
    vocab(entry["how"], KNOWN_HOW, f"{context}.how")


def zone_records(observation: Mapping[str, Any]) -> Iterator[tuple[str, str, dict[str, Any]]]:
    """Every zone-array record as ``(path, seat, record)``, players in order and arrays in ``ZONE_ARRAYS`` order.

    ``seat`` is the seat of the player entry whose array holds the record:
    its owner, or its controller for a battlefield record. Paths are relative
    to the observation, for example ``players[0].hand[1]``.
    """
    for index, player in enumerate(observation["players"]):
        for zone_array in ZONE_ARRAYS:
            for position, record in enumerate(player[zone_array] or ()):
                yield f"players[{index}].{zone_array}[{position}]", player["seat"], record


def observation_objects(observation: Mapping[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Every object the observation holds, as ``(path, object reference)`` (spec 5.1, 6.7).

    Zone records come first (``zone_records`` order), then ``stack[i]``, then
    ``known[i]`` for each entry with an ``object_id``. A record or stack entry
    yields its five reference fields, never the whole record, so a reference
    elsewhere must equal it field for field; a known card yields the reference
    of spec 6.7, whose ``controller_seat`` is its ``owner_seat``.
    """
    held = [(path, _reference(record)) for path, _, record in zone_records(observation)]
    held += [(f"stack[{index}]", _reference(entry)) for index, entry in enumerate(observation["stack"])]
    for index, entry in enumerate(observation["known"]):
        if entry["object_id"] is not None:
            reference = {
                "object_id": entry["object_id"],
                "card_name": entry["card_name"],
                "owner_seat": entry["owner_seat"],
                "controller_seat": entry["owner_seat"],
                "zone": entry["zone"],
            }
            held.append((f"known[{index}]", reference))
    return held


def observation_references(observation: Mapping[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Every non-null object reference inside the observation, as ``(path, reference)`` (V4, spec 5.1, 11.3).

    Each must equal a held object: a permanent's ``attached_to`` and
    ``attack_target`` objects and its ``blocked_attackers``, a record's
    ``exiled_by``, a stack entry's ``source`` and object ``targets``, and a
    pending trigger's ``source``. Player targets and nulls are not references.
    """
    references: list[tuple[str, dict[str, Any]]] = []
    for path, _, record in zone_records(observation):
        permanent = record["permanent"]
        if permanent is not None:
            for field in ("attached_to", "attack_target"):
                target = permanent[field]
                if target is not None and "object" in target:
                    references.append((f"{path}.permanent.{field}.object", target["object"]))
            for index, attacker in enumerate(permanent["blocked_attackers"]):
                references.append((f"{path}.permanent.blocked_attackers[{index}]", attacker))
        if record["exiled_by"] is not None:
            references.append((f"{path}.exiled_by", record["exiled_by"]))
    for index, entry in enumerate(observation["stack"]):
        if entry["source"] is not None:
            references.append((f"stack[{index}].source", entry["source"]))
        for position, target in enumerate(entry["targets"]):
            if target is not None and "object" in target:
                references.append((f"stack[{index}].targets[{position}].object", target["object"]))
    for index, trigger in enumerate(observation["pending_triggers"] or ()):
        if trigger["source"] is not None:
            references.append((f"pending_triggers[{index}].source", trigger["source"]))
    return references
