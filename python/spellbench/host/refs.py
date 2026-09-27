"""V2, V4 and V6: the acting seat's view, reference equality and face-down names (spec 5.1, 6.8, 11.3).

- ``check_seat`` (V2): ``observation.viewer`` is ``acting_seat``.
- ``check_references`` (V4): object ids are unique within the observation,
  and every non-null reference (inside the observation, in a candidate's
  semantic, or ``context.source``) equals the held object with its id, field
  for field; a reference to an id the observation does not hold fails, since
  absent objects become null (spec 5.1).
- ``check_face_down`` (V6): a face-down object on the battlefield or the
  stack whose controller is not the viewer has a null ``card_name``, and a
  record a null ``full_name``.

Inputs are seat decisions that already passed V1, so every field has its
type. Details start with the path of the offending value, relative to the
seat decision.
"""

from __future__ import annotations

from typing import Any, Mapping

from ..candidates import object_references
from ..observation import observation_objects, observation_references, zone_records
from .violation import ValidatorViolation


def check_seat(seat_decision: Mapping[str, Any]) -> None:
    """V2: the observation is the acting seat's own view."""
    viewer = seat_decision["observation"]["viewer"]
    acting_seat = seat_decision["acting_seat"]
    if viewer != acting_seat:
        raise ValidatorViolation("V2", f"observation.viewer {viewer} is not acting_seat {acting_seat}")


def _held(observation: Mapping[str, Any]) -> dict[str, dict]:
    """The observation's objects by id (V4's uniqueness rule)."""
    held: dict[str, dict] = {}
    for path, reference in observation_objects(observation):
        if reference["object_id"] in held:
            raise ValidatorViolation("V4", f"object id {reference['object_id']} appears twice in the observation ({path})")
        held[reference["object_id"]] = reference
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
    """V6: a face-down object another seat controls is nameless (spec 6.8, 11.3).

    On the battlefield and the stack only the controller may see the face
    (CR 708.5), so a record the viewer does not control hides ``card_name``
    and ``full_name``, a stack entry ``card_name`` (it has no ``full_name``).
    """
    viewer = seat_decision["acting_seat"]   # the seat the decision is forwarded to; V2 makes it the observation's viewer
    observation = seat_decision["observation"]
    for path, _, record in zone_records(observation):
        if record["zone"] != "battlefield" or not record["face_down"] or record["controller_seat"] == viewer:
            continue
        for field in ("card_name", "full_name"):
            if record[field] is not None:
                raise ValidatorViolation("V6", f"observation.{path}.{field} must be null: the viewer {viewer} does not "
                                               "control this face-down object")
    for index, entry in enumerate(observation["stack"]):
        if entry["face_down"] and entry["controller_seat"] != viewer and entry["card_name"] is not None:
            raise ValidatorViolation("V6", f"observation.stack[{index}].card_name must be null: the viewer {viewer} does "
                                           "not control this face-down object")
