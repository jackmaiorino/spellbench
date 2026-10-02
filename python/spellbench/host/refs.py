"""V2, V4 and V6: the acting seat's view, reference equality and face-down objects (spec 5.1, 6.4, 6.8, 11.3).

- ``check_seat`` (V2): ``observation.viewer`` is ``acting_seat``, and a
  priority decision's ``acting_seat`` holds priority (spec 6.2, 7.1).
- ``check_references`` (V4): object ids are unique within the observation,
  and every non-null reference (inside the observation, in a candidate's
  semantic, or ``context.source``) equals the held object with its id, field
  for field; a reference to an id the observation does not hold fails, since
  absent objects become null (spec 5.1).
- ``check_face_down`` (V6): a face-down object on the battlefield or the
  stack whose controller is not the viewer is nameless (``card_name``, and a
  record's ``full_name``, null) and shows only the face-down characteristics
  (spec 6.4): a colorless creature with no supertype, subtype or mana cost,
  no keyword but ward, and no chosen value, class level, target, division,
  mode or X that could identify the card.

Inputs are seat decisions that already passed V1, so every field has its
type. Details start with the path of the offending value, relative to the
seat decision.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, NoReturn

from ..candidates import object_references
from ..observation import observation_objects, observation_references, zone_records
from .violation import ValidatorViolation

# Spec 6.4 and 6.8 (CR 708.2): what a face-down object shows a seat that may not look at it. It has no name
# and no mana cost, so no color and mana value 0; no supertype or subtype; and it is a creature. Ward is the
# one keyword the rules give a face-down object (disguise and cloak, CR 702.168a and 701.58a). Power and
# toughness are current values after counters and effects, so they are not pinned.
FACE_DOWN_CHARACTERISTICS: dict[str, Any] = {"supertypes": [], "types": ["creature"], "subtypes": [], "colors": [],
                                             "mana_value": 0}
FACE_DOWN_KEYWORDS = (None, [], ["ward"])                           # null under a keywords flag that is off (V8)
# A face-down creature spell has no text: it chooses no target, division, mode or X (spec 6.5).
FACE_DOWN_SPELL_CHOICES: dict[str, Any] = {"targets": [], "divided": None, "modes": None, "x_value": None}


def check_seat(seat_decision: Mapping[str, Any]) -> None:
    """V2: the observation is the acting seat's own view, and a priority decision goes to the seat holding priority."""
    viewer = seat_decision["observation"]["viewer"]
    acting_seat = seat_decision["acting_seat"]
    if viewer != acting_seat:
        raise ValidatorViolation("V2", f"observation.viewer {viewer} is not acting_seat {acting_seat}")
    holder = seat_decision["observation"]["priority_seat"]
    if seat_decision["context"]["kind"] == "priority" and holder != acting_seat:
        shown = "null" if holder is None else holder
        raise ValidatorViolation("V2", f"observation.priority_seat {shown} is not acting_seat {acting_seat}: a priority "
                                       "decision goes to the seat holding priority (spec 6.2, 7.1)")


def _held(observation: Mapping[str, Any]) -> dict[str, dict]:
    """The observation's objects by id (V4's uniqueness rule)."""
    held: dict[str, dict] = {}
    paths: dict[str, str] = {}
    for path, reference in observation_objects(observation):
        if reference["object_id"] in held:
            raise ValidatorViolation("V4", f"object id {reference['object_id']} appears twice in the observation "
                                           f"({paths[reference['object_id']]} and {path})")
        held[reference["object_id"]] = reference
        paths[reference["object_id"]] = path
    return held


def check_references(seat_decision: Mapping[str, Any]) -> None:
    """V4: every reference equals the observation record with its id (spec 5.1)."""
    held = _held(seat_decision["observation"])
    references = [(f"observation.{path}", ref) for path, ref in observation_references(seat_decision["observation"])]
    for index, candidate in enumerate(seat_decision["candidates"]):
        references += [(f"candidates[{index}].semantic.{path}", ref) for path, ref in object_references(candidate["semantic"])]
    if seat_decision["context"]["source"] is not None:
        references.append(("context.source", seat_decision["context"]["source"]))
    for path, ref in references:
        record = held.get(ref["object_id"])
        if record is None:
            raise ValidatorViolation("V4", f"{path} references {ref['object_id']}, which is not in the observation")
        if dict(ref) != record:
            raise ValidatorViolation("V4", f"{path} differs from the observation record of {ref['object_id']}")


def check_face_down(seat_decision: Mapping[str, Any]) -> None:
    """V6: a face-down object another seat controls shows only its face-down characteristics (spec 6.4, 6.8, 11.3).

    On the battlefield and the stack only the controller may look at it (CR 708.5), so for any other
    viewer a record has a null ``card_name`` and ``full_name``, ``FACE_DOWN_CHARACTERISTICS``, keywords
    in ``FACE_DOWN_KEYWORDS``, and no chosen value or class level; a stack entry has a null
    ``card_name``, and a spell also those characteristics and ``FACE_DOWN_SPELL_CHOICES``.
    """
    viewer = seat_decision["acting_seat"]   # the seat the decision is forwarded to; V2 makes it the observation's viewer
    observation = seat_decision["observation"]
    for path, _, record in zone_records(observation):
        if record["zone"] != "battlefield" or not record["face_down"] or record["controller_seat"] == viewer:
            continue
        where = f"observation.{path}"
        for field in ("card_name", "full_name"):
            if record[field] is not None:
                _reject(f"{where}.{field}", "null", viewer)
        _check_face_down_characteristics(record["characteristics"], f"{where}.characteristics", viewer)
        permanent = record["permanent"]
        if permanent["chosen"]:                                     # null under a permanent_details flag that is off
            _reject(f"{where}.permanent.chosen", "empty", viewer)
        if permanent["class_level"] is not None:
            _reject(f"{where}.permanent.class_level", "null", viewer)
    for index, entry in enumerate(observation["stack"]):
        if not entry["face_down"] or entry["controller_seat"] == viewer:
            continue
        where = f"observation.stack[{index}]"
        if entry["card_name"] is not None:
            _reject(f"{where}.card_name", "null", viewer)
        if entry["stack_kind"] == "spell":                          # V1 gives a spell its characteristics
            _check_face_down_characteristics(entry["characteristics"], f"{where}.characteristics", viewer)
            for field, expected in FACE_DOWN_SPELL_CHOICES.items():
                if entry[field] != expected:
                    _reject(f"{where}.{field}", json.dumps(expected), viewer)


def _check_face_down_characteristics(characteristics: Mapping[str, Any], where: str, viewer: str) -> None:
    for field, expected in FACE_DOWN_CHARACTERISTICS.items():
        if characteristics[field] != expected:
            _reject(f"{where}.{field}", json.dumps(expected), viewer)
    if characteristics["keywords"] not in FACE_DOWN_KEYWORDS:
        _reject(f"{where}.keywords", '[], ["ward"] or null', viewer)


def _reject(path: str, expected: str, viewer: str) -> NoReturn:
    raise ValidatorViolation("V6", f"{path} must be {expected}: the viewer {viewer} does not control this face-down object")
