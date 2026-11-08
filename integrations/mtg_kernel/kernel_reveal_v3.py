"""Strict intake of the kernel's already projected reveal-operation journal.

The native producer establishes event-time public evidence. This adapter never
receives object IDs or joins a reveal with an omniscient history. The two native
viewers have independent sequences and queues; seat remapping changes only the
public owner labels, never arrival tokens.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Callable

from spellbench.reveal_meaning_v3 import SCHEMA, RevealMeaningError, RevealReducerV3
from kernel_observation_v2 import ProjectionError

SUPPORT_SCHEMA = "kernel-reveal-support/v3"
SEATS = ("p0", "p1")


def _viewer(value) -> int:
    if type(value) is not int or value not in (0, 1):
        raise ProjectionError("invalid reveal journal viewer")
    return value


def _seat_map(seat: Callable[[str], str]) -> dict[str, str]:
    mapping = {native: seat(native) for native in SEATS}
    if set(mapping.values()) != set(SEATS):
        raise ProjectionError("invalid reveal journal seat mapping")
    return mapping


class RevealHistoryV3:
    def __init__(self) -> None:
        self.reducers = [RevealReducerV3(), RevealReducerV3()]
        self.pending: list[list[dict]] = [[], []]

    def absorb(self, support) -> None:
        """Validate both viewer batches before committing either one."""
        if type(support) is not dict or set(support) != {"schema", "viewers"} or \
                support["schema"] != SUPPORT_SCHEMA or type(support["viewers"]) is not list or \
                len(support["viewers"]) != 2:
            raise ProjectionError("malformed reveal journal support")
        batches, prepared, queued = {}, {}, {}
        for row in support["viewers"]:
            if type(row) is not dict or set(row) != {"viewer", "transcript"}:
                raise ProjectionError("malformed reveal journal viewer batch")
            viewer = _viewer(row["viewer"])
            if viewer in batches:
                raise ProjectionError("duplicate reveal journal viewer")
            batches[viewer] = row["transcript"]
            try:
                prepared[viewer] = self.reducers[viewer]._prepare(row["transcript"])
            except RevealMeaningError as error:
                # The native bridge is private. Do not reflect any offending
                # native payload through an exception or public terminal.
                raise ProjectionError("invalid public reveal operation stream") from error
            new = {}
            for operation in row["transcript"]["operations"]:
                sequence = operation["sequence"]
                if sequence >= self.reducers[viewer]._next:
                    new.setdefault(sequence, deepcopy(operation))
            queued[viewer] = list(new.values())
        for viewer in (0, 1):
            self.reducers[viewer]._commit(prepared[viewer])
            self.pending[viewer].extend(queued[viewer])

    def drain(self, viewer: int, seat: Callable[[str], str]) -> dict:
        viewer, mapping = _viewer(viewer), _seat_map(seat)
        operations = deepcopy(self.pending[viewer])
        for operation in operations:
            for event in operation["events"]:
                event["owner_seat"] = mapping[event["owner_seat"]]
        self.pending[viewer] = []
        return {"schema": SCHEMA, "operations": operations}

    def known_hand(self, viewer: int, seat: Callable[[str], str]) -> list[dict]:
        viewer, mapping = _viewer(viewer), _seat_map(seat)
        result = [{**fact, "owner_seat": mapping[fact["owner_seat"]]}
                  for fact in self.reducers[viewer].known_hand()]
        return sorted(result, key=lambda fact: (fact["owner_seat"], fact["card_name"]))
