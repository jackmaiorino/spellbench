"""Neutral observations for the human-play London opening.

A subclass of the pinned projection (kernel_observation_v2.py, never edited):
it adds only what the London pregame needs. Each seat's public
`mulligans_taken` comes from the bridge's public London facts, and while the
opening is pending the observation is the protocol's pregame one (`turn` 0,
`phase_step` pregame, no active seat, no priority seat). It reads the bridge's
`support["london"]` (counts, who has kept, the phase), which carries no card
identity, and the viewer's own hand records as the pinned projection builds
them. The other seat's hand stays a count.
"""
from __future__ import annotations

from kernel_observation_v2 import KernelProjection, ProjectionError, SEATS
from spellbench.observation import validate_observation

PHASES = ("announce", "bottom", "done")


class LondonHumanProjection(KernelProjection):
    def project(self, raw: dict, support: dict, knowledge: dict | None = None) -> dict:
        result = super().project(raw, support, knowledge)
        london = support.get("london")
        if london is None:
            raise ProjectionError("the London bridge sent no public opening facts")
        taken, kept, phase = london.get("mulligans_taken"), london.get("kept"), london.get("phase")
        if (phase not in PHASES or not isinstance(taken, list) or len(taken) != 2
                or any(type(count) is not int or not 0 <= count <= 7 for count in taken)
                or not isinstance(kept, list) or len(kept) != 2 or any(type(flag) is not bool for flag in kept)):
            raise ProjectionError("malformed public opening facts")
        for native, native_seat in enumerate(SEATS):
            result["players"][SEATS.index(self.seat(native_seat))]["mulligans_taken"] = taken[native]
        if phase != "done":
            result["turn"] = 0
            result["phase_step"] = "pregame"
            result["active_seat"] = None
            result["priority_seat"] = None
            result["passed_seats"] = []
        validate_observation(result)
        return result
