"""Watching a run while it plays (COMPUTE-POLICY.md item 6): unused capacity and throughput below the qualified rate.

:class:`IdleMonitor` turns the executor's observations into warnings;
:func:`warning_sink` writes each one to the run's unhashed ``throughput.jsonl``
at once.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Callable, TextIO

# Unused capacity is flagged once it lasts this many consecutive windows.
IDLE_WINDOWS = 2
# A window finishing fewer than this share of the qualified rate's games is slow.
RATE_FLOOR_PERCENT = 50
# A rate window lasts until it expects at least this many games.
RATE_MIN_GAMES = 8


def warning_sink(path: Path, *, stream: TextIO | None = None) -> Callable[[str], None]:
    """A callback writing each warning at once: one JSON line ``{"warning": text}`` appended to ``path``
    (unhashed, never in the manifest's files), flushed and synced, and echoed to ``stream`` when given."""

    def write(text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="ascii", newline="\n") as handle:
            handle.write(json.dumps({"warning": text}, ensure_ascii=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        if stream is not None:
            stream.write(text + "\n")
            stream.flush()

    return write


class IdleMonitor:
    """Flags eligible capacity that stays unused while games wait.

    Idle slots: a tick is idle when fewer than ``slots`` games run while
    games are queued. Only unbroken idle ticks spanning ``IDLE_WINDOWS``
    windows of ``window_s`` seconds warn (120 s by default: the policy's two
    consecutive 60-second windows); a busy tick, or one with nothing queued,
    ends the stretch. Tick on a timer (every few seconds) and after filling
    free slots, never only when a game finishes: a tick taken between a game
    ending and its slot's refill sees a free slot, so a monitor ticked only
    then would warn about a healthy run.

    Slow throughput: with ``qualified_rate`` (games per second, see
    ``Allocation.qualified_rate``) and the run's finished game count
    (``completed``), each window that finishes fewer than
    ``RATE_FLOOR_PERCENT`` percent of the expected games while games stay
    queued is slow, and ``IDLE_WINDOWS`` slow windows in a row warn. A rate
    window lasts at least ``window_s`` and until it expects
    ``RATE_MIN_GAMES`` games, so long games are not judged in windows where
    none would finish.

    ``cpu`` (for example ``CpuSampler.sample``) is sampled once a window;
    warnings quote its latest value. ``on_warning`` receives each warning as
    it happens (:func:`warning_sink` writes it to disk at once); ``tick``
    also returns it.
    """

    def __init__(
        self,
        slots: int,
        *,
        window_s: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
        qualified_rate: float | None = None,
        cpu: Callable[[], float | None] | None = None,
        on_warning: Callable[[str], None] | None = None,
    ) -> None:
        if type(slots) is not int or slots < 1:
            raise ValueError(f"slots must be a positive integer, got {slots!r}")
        if not window_s > 0:
            raise ValueError(f"window_s must be positive, got {window_s!r}")
        if qualified_rate is not None and not qualified_rate > 0:
            raise ValueError(f"qualified_rate must be positive, got {qualified_rate!r}")
        self.slots = slots
        self.window_s = window_s
        self._clock = clock
        self._cpu = cpu
        self._on_warning = on_warning
        self._idle_since: float | None = None
        self._rate = qualified_rate
        self._rate_window_s = None if qualified_rate is None else max(window_s, RATE_MIN_GAMES / qualified_rate)
        self._window: tuple[float, int] | None = None  # (start, completed at start)
        self._window_queued = True
        self._slow_windows = 0
        self._cpu_at: float | None = None
        self._cpu_busy: float | None = None

    def tick(self, *, running: int, queued: int, completed: int | None = None) -> str | None:
        """Record one observation; returns the warning (several joined by ' | ') when one is due."""
        now = self._clock()
        if self._cpu is not None and (self._cpu_at is None or now - self._cpu_at >= self.window_s):
            self._cpu_busy, self._cpu_at = self._cpu(), now
        warnings = []
        if running >= self.slots or queued <= 0:
            self._idle_since = None
        else:
            if self._idle_since is None:
                self._idle_since = now
            if now - self._idle_since >= IDLE_WINDOWS * self.window_s:
                self._idle_since = now
                warnings.append(
                    f"idle capacity: fewer than {self.slots} games ran while games were queued "
                    f"for two consecutive {self.window_s:.0f} s windows" + self._cpu_note()
                )
        if self._rate is not None and completed is not None:
            warnings.extend(self._rate_tick(now, queued, completed))
        for text in warnings:
            if self._on_warning is not None:
                self._on_warning(text)
        return " | ".join(warnings) if warnings else None

    def _rate_tick(self, now: float, queued: int, completed: int) -> list[str]:
        assert self._rate is not None and self._rate_window_s is not None
        if self._window is None:
            self._window, self._window_queued = (now, completed), queued > 0
            return []
        self._window_queued = self._window_queued and queued > 0
        start, done_at_start = self._window
        elapsed = now - start
        if elapsed < self._rate_window_s:
            return []
        done, expected = completed - done_at_start, self._rate * elapsed
        slow = self._window_queued and done * 100 < expected * RATE_FLOOR_PERCENT
        self._slow_windows = self._slow_windows + 1 if slow else 0
        self._window, self._window_queued = (now, completed), queued > 0
        if self._slow_windows < IDLE_WINDOWS:
            return []
        self._slow_windows = 0
        return [
            f"throughput below the qualified rate: {done} games finished in the last {elapsed:.0f} s against "
            f"{expected:.1f} expected, for two consecutive windows" + self._cpu_note()
        ]

    def _cpu_note(self) -> str:
        if self._cpu is None:
            return ""
        return "; machine CPU unknown" if self._cpu_busy is None else f"; machine CPU {self._cpu_busy:.0%} busy"
