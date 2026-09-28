"""Live-validation state across a game's decisions (spec 11.3).

V3: seat steps, decision groups and rewinds (spec 8, 9.3; Decision 4). V7: object-id freshness (spec 5.3).
"""

from __future__ import annotations

from typing import Any, Mapping

from .violation import ValidatorViolation


class GroupTracker:
    """V3 state: `check` validates a seat decision before it is forwarded, `answered` records its answer."""

    def __init__(self) -> None:
        self._next_step = {"p0": 0, "p1": 0}
        self._next_group = {"p0": 0, "p1": 0}
        self._partial: dict[str, tuple[int, int, int] | None] = {"p0": None, "p1": None}
        # The completion index of each seat's last non-pass priority action, or None.
        self._action: dict[str, int | None] = {"p0": None, "p1": None}
        # One flag per completed group of either seat, in completion order; False once a rewind abandons it.
        self._counted: list[bool] = []
        self.answered_steps = 0

    @property
    def completed_groups(self) -> int:
        return sum(self._counted)

    @property
    def partial_seat(self) -> str | None:
        return next((seat for seat, partial in self._partial.items() if partial is not None), None)

    def answered_by(self, seat: str) -> int:
        return self._next_step[seat]

    def check(self, sd: Mapping[str, Any]) -> None:
        seat = sd["acting_seat"]
        other = "p1" if seat == "p0" else "p0"
        group, context = sd["group"], sd["context"]
        key = (group["group_id"], group["substep_index"], group["substep_count"])
        if sd["seat_step"] != self._next_step[seat]:
            raise ValidatorViolation("V3", f"{seat} seat_step {sd['seat_step']} is not {self._next_step[seat]}")
        if self._partial[other] is not None:
            raise ValidatorViolation("V3", f"a decision for {seat} while {other}'s group {self._partial[other][0]} is partial")
        partial = self._partial[seat]
        if context["rewind"]:
            if context["kind"] != "priority":
                raise ValidatorViolation("V3", "a rewind re-poses a priority decision")
            if self._action[seat] is None:
                raise ValidatorViolation("V3", f"a rewind for {seat} without a priority action to undo")
        elif partial is not None:
            if key != (partial[0], partial[1] + 1, partial[2]):
                raise ValidatorViolation("V3", f"{seat} group {partial[0]} must continue at substep {partial[1] + 1} of {partial[2]}")
            return
        expected = partial[0] + 1 if partial is not None else self._next_group[seat]
        if key[:2] != (expected, 0):
            raise ValidatorViolation("V3", f"{seat} must start group {expected} at substep 0, got {key[0]} at {key[1]}")
        if context["rewind"]:
            self._abandon(seat)

    def _abandon(self, seat: str) -> None:
        """Decision 4: the rewound action's own group and every group completed after it stop counting, once each."""
        start = self._action[seat]
        for index in range(start, len(self._counted)):
            self._counted[index] = False
        self._partial[seat] = None
        self._action[seat] = None
        other = "p1" if seat == "p0" else "p0"
        if self._action[other] is not None and self._action[other] >= start:
            self._action[other] = None          # the rewind undid the other seat's later action too (R1-11)

    def answered(self, sd: Mapping[str, Any], *, chosen_kind: str) -> None:
        seat, group, context = sd["acting_seat"], sd["group"], sd["context"]
        self._next_step[seat] += 1
        self.answered_steps += 1
        if context["kind"] == "priority":
            # A priority decision is one substep (V3 group shapes, Task 22), so its group gets this index now.
            self._action[seat] = len(self._counted) if chosen_kind != "pass" else None
        if group["substep_index"] + 1 == group["substep_count"]:
            self._partial[seat] = None
            self._next_group[seat] = group["group_id"] + 1
            self._counted.append(True)
        else:
            self._partial[seat] = (group["group_id"], group["substep_index"], group["substep_count"])


class IdTracker:
    """V7 state (spec 5.3): per viewer, an object id keeps one zone and one owner, and never returns after leaving.

    An object's owner never changes (CR 108.3), while its name, controller and characteristics may,
    so an id showing another owner names another object.
    """

    def __init__(self) -> None:
        # Per seat: the zone and owner of every id seen, the ids of the previous observation, and the ids that departed.
        self._zones: dict[str, dict[str, str]] = {"p0": {}, "p1": {}}
        self._owners: dict[str, dict[str, str]] = {"p0": {}, "p1": {}}
        self._present: dict[str, set[str]] = {"p0": set(), "p1": set()}
        self._departed: dict[str, set[str]] = {"p0": set(), "p1": set()}

    def check(self, seat: str, objects: Mapping[str, str], *, owners: Mapping[str, str] | None = None) -> None:
        """``objects`` maps each id of ``seat``'s observation to its zone, ``owners`` (when given) to its owner."""
        zones, known_owners = self._zones[seat], self._owners[seat]
        for object_id, zone in objects.items():
            if object_id in self._departed[seat]:
                raise ValidatorViolation("V7", f"object id {object_id} returned to {seat}'s observation after leaving it")
            if zones.get(object_id, zone) != zone:
                raise ValidatorViolation("V7", f"object id {object_id} appeared in zones {zones[object_id]} and {zone}")
            if owners is not None and known_owners.get(object_id, owners[object_id]) != owners[object_id]:
                raise ValidatorViolation("V7", f"object id {object_id} appeared with owners {known_owners[object_id]} "
                                               f"and {owners[object_id]}")
        self._departed[seat] |= self._present[seat] - objects.keys()
        self._present[seat] = set(objects)
        zones.update(objects)
        if owners is not None:
            known_owners.update(owners)
