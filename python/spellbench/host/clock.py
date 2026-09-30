"""Per-seat clocks, caps and the stalling window (spec 11.4).

Times are integer milliseconds measured by the caller; nothing here reads a clock.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

STALLING_WINDOW = 250
CAP_NAMES = ("max_seat_decisions_per_turn", "max_seat_decisions_per_game", "max_seat_steps_per_game")


@dataclass
class SeatClock:
    bank_ms: int
    increment_ms: int
    max_decision_ms: int
    remaining_ms: int = field(init=False)

    def __post_init__(self) -> None:
        self.remaining_ms = self.bank_ms

    def budget_ms(self) -> int:
        return min(self.max_decision_ms, self.remaining_ms)

    def charge(self, elapsed_ms: int) -> bool:
        """Subtract one decision's time, then add the increment; False when it was a timeout."""
        if elapsed_ms > self.max_decision_ms or elapsed_ms > self.remaining_ms:
            return False
        self.remaining_ms = self.remaining_ms - elapsed_ms + self.increment_ms
        return True


class SeatCaps:
    def __init__(self, *, per_turn: int, groups_per_game: int, steps_per_game: int) -> None:
        self._limits = dict(zip(CAP_NAMES, (per_turn, groups_per_game, steps_per_game)))
        self._turn: dict[str, int | None] = {"p0": None, "p1": None}
        self._counts = {seat: dict.fromkeys(CAP_NAMES, 0) for seat in ("p0", "p1")}

    def record(self, seat: str, *, turn: int, completed_group: bool) -> str | None:
        """Count one answered decision; the name of the cap it reaches (count equals cap), or None."""
        counts = self._counts[seat]
        if self._turn[seat] != turn:
            self._turn[seat] = turn
            counts["max_seat_decisions_per_turn"] = 0
        counts["max_seat_decisions_per_turn"] += 1
        counts["max_seat_steps_per_game"] += 1
        if completed_group:
            counts["max_seat_decisions_per_game"] += 1
        for name in CAP_NAMES:
            if counts[name] >= self._limits[name]:
                return name
        return None


def is_real_choice(candidate_count: int, chosen_kind: str) -> bool:
    return candidate_count >= 2 and chosen_kind != "pass"


@dataclass(frozen=True)
class CapRuling:
    kind: str
    loser_seat: str | None


class StallingWindow:
    def __init__(self, size: int = STALLING_WINDOW) -> None:
        self._entries: deque[tuple[str, bool]] = deque(maxlen=size)

    def record(self, seat: str, *, real_choice: bool) -> None:
        self._entries.append((seat, real_choice))

    def counts(self) -> dict[str, int]:
        """Each seat's real choices in the window."""
        real = {"p0": 0, "p1": 0}
        for seat, choice in self._entries:
            real[seat] += choice
        return real

    def ruling(self, capped_seat: str) -> CapRuling:
        real = self.counts()
        if real["p0"] == real["p1"] == 0:
            return CapRuling(kind="draw", loser_seat=None)
        if real["p0"] == real["p1"]:
            return CapRuling(kind="forfeit", loser_seat=capped_seat)
        return CapRuling(kind="forfeit", loser_seat="p0" if real["p0"] > real["p1"] else "p1")
