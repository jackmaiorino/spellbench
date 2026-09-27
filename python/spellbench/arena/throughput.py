"""The useful-compute guard (COMPUTE-POLICY.md): how many games a run plays at once.

Every guarded launch plans an :class:`Allocation` before its first game:

- The probe plays the first ``PROBE_GAMES`` scheduled games with one worker
  and projects the serial time of the whole schedule from them.
- A run projected at ``SMALL_RUN_SECONDS`` or less is small: it keeps the
  resource-bounded worker count (the cap, the declared cores per game and
  the number of games) without further measurement.
- A substantial run needs a placement note (which machines were considered
  and why this one) and a scaling comparison on identical inputs: the same
  first games of the schedule played with 1, ``bound // 2`` and ``bound``
  workers. Every worker count must produce the same outputs, or the run is
  refused; the fastest count wins, the smaller on a tie. The comparison
  plays two games per top-rung worker when that costs at most
  ``QUALIFY_BUDGET_PERCENT`` percent of the serial schedule at ideal
  scaling, else one: qualification counts toward the time to a completed
  result.
- With an evidence file, a measured allocation is recorded locally and
  reused by later launches with the same host, cores, cores per game,
  worker bound and workload (the config minus run-specific fields and the
  engine files' hashes): re-measuring unchanged conditions gains nothing.

Trials are wall-clock evidence: they live only in the manifest's
``allocation`` block and the local, unhashed evidence file, never in hashed
data files. While a run plays, :class:`IdleMonitor` flags capacity that stays
unused while games wait.
"""

from __future__ import annotations

import hashlib
import math
import os
import platform
import re
import time
from dataclasses import dataclass, replace
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable

from ..errors import ProtocolError, ValidationError
from ..wire import canonical_json_dumps, strict_json_loads

SMALL_RUN_SECONDS = 120
PROBE_GAMES = 2
QUALIFY_GAMES_PER_WORKER = 2
# The scaling comparison's cost at ideal scaling, as a share of the projected serial time.
QUALIFY_BUDGET_PERCENT = 10
# Unused capacity is flagged once it lasts this many consecutive windows (COMPUTE-POLICY.md item 6).
IDLE_WINDOWS = 2
ALLOCATION_KINDS = ("small", "substantial", "unmeasured")
EVIDENCE_SCHEMA = "spellbench-throughput-evidence/v1"

_MAX_INT = (1 << 53) - 1
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_TRIAL_KEYS = ("workers", "games", "seconds_milli", "outputs_digest")
_ALLOCATION_KEYS = (
    "kind",
    "workers",
    "host",
    "cpu_count",
    "per_game_cores",
    "probe",
    "trials",
    "projected_serial_seconds",
    "placement",
    "outputs_identical",
    "qualification_seconds_milli",
    "workload",
    "reused",
)


class ThroughputError(Exception):
    """The launch guard refuses the run before its first game."""


def _exact_keys(value: dict[str, Any], keys: tuple[str, ...], context: str) -> None:
    missing, extra = set(keys) - set(value), set(value) - set(keys)
    if missing or extra:
        raise ValidationError(f"{context}: fields mismatch: missing={sorted(missing)} extra={sorted(extra)}")


def _count(value: Any, context: str, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= _MAX_INT:
        raise ValidationError(f"{context}: must be an integer in [{minimum}, 2^53 - 1]")
    return value


def _is_digest(value: Any) -> bool:
    return type(value) is str and _DIGEST.fullmatch(value) is not None


def _host_name(host: str | None) -> str:
    return (platform.node() or "unknown") if host is None else host


def _cpu_count(cpu_count: int | None) -> int:
    return (os.cpu_count() or 1) if cpu_count is None else cpu_count


@dataclass(frozen=True)
class Trial:
    """One measured play: the first ``games`` scheduled games with ``workers`` workers."""

    workers: int
    games: int
    seconds_milli: int
    outputs_digest: str

    def __post_init__(self) -> None:
        _count(self.workers, "trial.workers", 1)
        _count(self.games, "trial.games", 1)
        _count(self.seconds_milli, "trial.seconds_milli")
        if not _is_digest(self.outputs_digest):
            raise ValidationError('trial.outputs_digest: must be "sha256:" and 64 lowercase hex digits')

    def to_json(self) -> dict[str, Any]:
        return {
            "workers": self.workers,
            "games": self.games,
            "seconds_milli": self.seconds_milli,
            "outputs_digest": self.outputs_digest,
        }

    @classmethod
    def from_json(cls, value: Any, context: str = "trial") -> Trial:
        if not isinstance(value, dict):
            raise ValidationError(f"{context}: must be an object")
        _exact_keys(value, _TRIAL_KEYS, context)
        try:
            return cls(**value)
        except ValidationError as exc:
            raise ValidationError(f"{context}: {exc}") from exc


@dataclass(frozen=True)
class Allocation:
    """How many games a run plays at once, and the evidence for it (the manifest's ``allocation`` block).

    ``kind`` is ``small`` (a short schedule keeps its resource-bounded
    workers), ``substantial`` (a scaling comparison chose the workers) or
    ``unmeasured`` (no guard ran, so the run is unrated, Decision 3).
    ``qualification_seconds_milli`` is the wall time the guard spent
    measuring; ``workload`` is the identity the measurement is reused under
    (:func:`workload_id`); ``reused`` says an earlier launch on the same host,
    cores and workload measured it, and this run spent nothing on it.
    """

    kind: str
    workers: int
    host: str
    cpu_count: int
    per_game_cores: int
    probe: Trial | None = None
    trials: tuple[Trial, ...] = ()
    projected_serial_seconds: int | None = None
    placement: str | None = None
    outputs_identical: bool | None = None
    qualification_seconds_milli: int | None = None
    workload: str | None = None
    reused: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "trials", tuple(self.trials))
        _check_allocation(self)

    @property
    def measured(self) -> bool:
        """Whether the throughput guard measured this allocation (Decision 3: only such runs are rated)."""
        return self.kind != "unmeasured"

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "workers": self.workers,
            "host": self.host,
            "cpu_count": self.cpu_count,
            "per_game_cores": self.per_game_cores,
            "probe": None if self.probe is None else self.probe.to_json(),
            "trials": [trial.to_json() for trial in self.trials],
            "projected_serial_seconds": self.projected_serial_seconds,
            "placement": self.placement,
            "outputs_identical": self.outputs_identical,
            "qualification_seconds_milli": self.qualification_seconds_milli,
            "workload": self.workload,
            "reused": self.reused,
        }

    @classmethod
    def from_json(cls, value: Any, context: str = "allocation") -> Allocation:
        if not isinstance(value, dict):
            raise ValidationError(f"{context}: must be an object")
        _exact_keys(value, _ALLOCATION_KEYS, context)
        probe, trials = value["probe"], value["trials"]
        if not isinstance(trials, list):
            raise ValidationError(f"{context}.trials: must be a list")
        return cls(
            **{
                **value,
                "probe": None if probe is None else Trial.from_json(probe, f"{context}.probe"),
                "trials": tuple(Trial.from_json(item, f"{context}.trials[{index}]") for index, item in enumerate(trials)),
            }
        )

    @classmethod
    def unmeasured(
        cls, workers: int, *, cpu_count: int | None = None, per_game_cores: int = 1, host: str | None = None
    ) -> Allocation:
        """An allocation no guard measured (the library default): the run publishes as unrated."""
        return cls(
            kind="unmeasured",
            workers=workers,
            host=_host_name(host),
            cpu_count=_cpu_count(cpu_count),
            per_game_cores=per_game_cores,
        )


def _check_allocation(allocation: Allocation) -> None:
    """Field types, then the evidence each kind carries."""
    if allocation.kind not in ALLOCATION_KINDS:
        raise ValidationError(f"allocation.kind: must be one of {list(ALLOCATION_KINDS)}")
    _count(allocation.workers, "allocation.workers", 1)
    if type(allocation.host) is not str or not allocation.host:
        raise ValidationError("allocation.host: must be a nonempty string")
    _count(allocation.cpu_count, "allocation.cpu_count", 1)
    _count(allocation.per_game_cores, "allocation.per_game_cores", 1)
    if allocation.probe is not None and not isinstance(allocation.probe, Trial):
        raise ValidationError("allocation.probe: must be a trial or null")
    if not all(isinstance(trial, Trial) for trial in allocation.trials):
        raise ValidationError("allocation.trials: must hold trials")
    for name in ("projected_serial_seconds", "qualification_seconds_milli"):
        if getattr(allocation, name) is not None:
            _count(getattr(allocation, name), f"allocation.{name}")
    if allocation.placement is not None and (type(allocation.placement) is not str or not allocation.placement.strip()):
        raise ValidationError("allocation.placement: must be a nonblank string or null")
    if allocation.outputs_identical is not None and type(allocation.outputs_identical) is not bool:
        raise ValidationError("allocation.outputs_identical: must be a boolean or null")
    if allocation.workload is not None and not _is_digest(allocation.workload):
        raise ValidationError('allocation.workload: must be "sha256:" and 64 lowercase hex digits, or null')
    if type(allocation.reused) is not bool:
        raise ValidationError("allocation.reused: must be a boolean")
    if allocation.kind == "unmeasured":
        measurement = (allocation.probe, allocation.projected_serial_seconds, allocation.outputs_identical,
                       allocation.qualification_seconds_milli)
        if allocation.trials or allocation.reused or any(item is not None for item in measurement):
            raise ValidationError("allocation: an unmeasured allocation carries no measurement")
        return
    if allocation.probe is None or allocation.projected_serial_seconds is None:
        raise ValidationError(f"allocation: a {allocation.kind} allocation needs its probe and projected serial time")
    if allocation.kind == "small":
        if allocation.trials or allocation.outputs_identical is not None:
            raise ValidationError("allocation: a small allocation has no scaling comparison")
        return
    trials = allocation.trials
    if (
        not trials
        or allocation.outputs_identical is not True
        or allocation.placement is None
        or len({(trial.games, trial.outputs_digest) for trial in trials}) != 1
        or allocation.workers not in {trial.workers for trial in trials}
    ):
        raise ValidationError(
            "allocation: a substantial allocation needs a placement note and trials of identical games with "
            "identical outputs, one of them at its worker count"
        )


def resource_bound(cpu_count: int, per_game_cores: int) -> int:
    """Games that fit at once when each needs ``per_game_cores`` declared cores (spec 11.4); at least 1."""
    return max(1, cpu_count // max(1, per_game_cores))


def worker_ladder(cap: int) -> tuple[int, ...]:
    """The worker counts a substantial run compares: 1, ``cap // 2`` and ``cap``, without repeats."""
    return tuple(sorted({1, max(1, cap // 2), max(1, cap)}))


def workload_id(value: Any) -> str:
    """The identity a qualification is reused under.

    ``"sha256:"`` and the SHA-256 of the canonical JSON of what shapes the
    games: the config minus run-specific fields (such as ``tournament_dir``)
    and the engine files' SHA-256 values in command order.
    """
    try:
        data = canonical_json_dumps(value)
    except ValidationError as exc:
        raise ThroughputError(f"a workload must be canonical JSON: {exc}") from exc
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _placement_needed(projected: int | None) -> str:
    return (
        f"a substantial run (projected {projected} s serial) needs a placement note: which machines "
        "(this PC, HaleysPC, RunPod) were considered and why this one (COMPUTE-POLICY.md)"
    )


def _trial(play: Callable[[int, int], tuple[float, str]], workers: int, games: int) -> Trial:
    seconds, digest = play(workers, games)
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
        raise ThroughputError(f"playing {games} games with {workers} workers reported no usable wall time: {seconds!r}")
    try:
        return Trial(workers, games, round(seconds * 1000), digest)
    except ValidationError as exc:
        raise ThroughputError(f"playing {games} games with {workers} workers: {exc}") from exc


def _since(clock: Callable[[], float], started: float) -> int:
    return max(0, round((clock() - started) * 1000))


def _ladder_games(games_total: int, bound: int, ladder: tuple[int, ...]) -> int:
    """Games per rung: the most per top-rung worker whose comparison fits the budget, at least one each.

    At ideal scaling the comparison costs ``games * sum(1 / workers)`` game
    times against ``games_total`` for the serial schedule. The time per game
    cancels, so the choice does not depend on the probe. One game per worker
    is the floor even over budget: fewer games cannot measure the top rung.
    """
    rung_cost = sum(Fraction(1, workers) for workers in ladder)
    for per_worker in range(QUALIFY_GAMES_PER_WORKER, 0, -1):
        games = min(games_total, per_worker * bound)
        if games * rung_cost * 100 <= games_total * QUALIFY_BUDGET_PERCENT:
            return games
    return min(games_total, bound)


def _read_evidence(path: Path) -> list[Allocation]:
    """The measured allocations in a local evidence file, oldest first. It is a cache: unreadable lines are skipped."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise ThroughputError(f"cannot read the throughput evidence {path}: {exc}") from exc
    allocations = []
    for line in raw.splitlines():
        try:
            record = strict_json_loads(line)
            _exact_keys(record, ("schema", "allocation"), "evidence")
            allocation = Allocation.from_json(record["allocation"]) if record["schema"] == EVIDENCE_SCHEMA else None
        except ProtocolError:
            continue
        if allocation is not None and allocation.measured and not allocation.reused:
            allocations.append(allocation)
    return allocations


def _record_evidence(path: Path, allocation: Allocation) -> None:
    line = canonical_json_dumps({"schema": EVIDENCE_SCHEMA, "allocation": allocation.to_json()}) + b"\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "ab") as handle:
            handle.write(line)
    except OSError as exc:
        raise ThroughputError(f"cannot record the throughput evidence in {path}: {exc}") from exc


def _worker_bound(allocation: Allocation) -> int:
    """The worker bound a measured allocation was planned under: its top rung, or a small run's workers."""
    return max(trial.workers for trial in allocation.trials) if allocation.trials else allocation.workers


def _prior_allocation(path: Path, key: tuple[str, int, int, str | None, int]) -> Allocation | None:
    """The newest recorded allocation for the same host, cores, cores per game, workload and worker bound."""
    matches = [
        allocation
        for allocation in _read_evidence(path)
        if (allocation.host, allocation.cpu_count, allocation.per_game_cores, allocation.workload,
            _worker_bound(allocation)) == key
    ]
    return matches[-1] if matches else None


def plan_allocation(
    *,
    games_total: int,
    cap: int,
    per_game_cores: int,
    play: Callable[[int, int], tuple[float, str]],
    placement: str | None,
    cpu_count: int | None = None,
    host: str | None = None,
    workload: str | None = None,
    evidence: Path | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> Allocation:
    """Choose how many games run at once (COMPUTE-POLICY.md items 2 to 5).

    ``play(workers, games)`` plays the first ``games`` scheduled games with
    ``workers`` workers under a throwaway secret and returns ``(wall seconds,
    outputs digest)``. ``placement`` says which machines were considered and
    why this one; a substantial run needs it. With ``evidence`` (a local
    file, never published) and ``workload``, a measured allocation with the
    same host, cores, cores per game, worker bound and workload is reused
    under this run's placement, and a new measurement is appended. ``clock``
    times the qualification. An empty schedule is refused.
    """
    if type(games_total) is not int or games_total < 1:
        raise ThroughputError(f"the schedule has no games to qualify (games_total={games_total!r})")
    for label, value in (("cap", cap), ("per_game_cores", per_game_cores)):
        if type(value) is not int or value < 1:
            raise ThroughputError(f"{label}: must be a positive integer, got {value!r}")
    if evidence is not None and workload is None:
        raise ThroughputError("reusing throughput evidence needs the workload it was measured on")
    cpu, machine = _cpu_count(cpu_count), _host_name(host)
    note = placement if placement is not None and placement.strip() else None
    # More workers than games is never useful (COMPUTE-POLICY.md item 2).
    bound = min(cap, resource_bound(cpu, per_game_cores), games_total)
    if evidence is not None:
        prior = _prior_allocation(Path(evidence), (machine, cpu, per_game_cores, workload, bound))
        if prior is not None:
            if prior.kind == "substantial" and note is None:
                raise ThroughputError(_placement_needed(prior.projected_serial_seconds))
            return replace(prior, placement=note, reused=True)
    started = clock()
    probe = _trial(play, 1, min(PROBE_GAMES, games_total))
    projected = -(-probe.seconds_milli * games_total // (1000 * probe.games))
    common: dict[str, Any] = dict(
        host=machine, cpu_count=cpu, per_game_cores=per_game_cores, probe=probe,
        projected_serial_seconds=projected, placement=note, workload=workload,
    )
    if projected <= SMALL_RUN_SECONDS:
        allocation = Allocation(kind="small", workers=bound, qualification_seconds_milli=_since(clock, started), **common)
    else:
        if note is None:
            raise ThroughputError(_placement_needed(projected))
        ladder = worker_ladder(bound)
        if ladder == (1,):
            trials: tuple[Trial, ...] = (probe,)  # nothing to compare; replaying the probe would measure nothing new
        else:
            games = _ladder_games(games_total, bound, ladder)
            trials = tuple(_trial(play, workers, games) for workers in ladder)
        if len({trial.outputs_digest for trial in trials}) != 1:
            raise ThroughputError("worker counts changed the results of identical games; refusing to parallelize")
        best = max(trials, key=lambda trial: (trial.games / max(trial.seconds_milli, 1), -trial.workers))
        allocation = Allocation(kind="substantial", workers=best.workers, trials=trials, outputs_identical=True,
                                qualification_seconds_milli=_since(clock, started), **common)
    if evidence is not None:
        _record_evidence(Path(evidence), allocation)
    return allocation


class IdleMonitor:
    """Flags eligible capacity that stays unused while games wait (COMPUTE-POLICY.md item 6).

    A tick is idle when fewer than ``slots`` games run while games are
    queued. Only sustained idleness is flagged: unbroken idle ticks spanning
    ``IDLE_WINDOWS`` windows of ``window_s`` seconds (120 s by default, the
    policy's two consecutive 60-second windows). A busy tick, or one with
    nothing queued, ends the stretch, so the moment between one game ending
    and the next starting never counts. After a warning the stretch starts
    over: idleness that persists warns again two windows later.
    """

    def __init__(self, slots: int, *, window_s: float = 60.0, clock: Callable[[], float] = time.monotonic) -> None:
        if type(slots) is not int or slots < 1:
            raise ValueError(f"slots must be a positive integer, got {slots!r}")
        if not window_s > 0:
            raise ValueError(f"window_s must be positive, got {window_s!r}")
        self.slots = slots
        self.window_s = window_s
        self._clock = clock
        self._idle_since: float | None = None

    def tick(self, *, running: int, queued: int) -> str | None:
        """Record one observation; returns a warning when idle capacity has lasted long enough."""
        now = self._clock()
        if running >= self.slots or queued <= 0:
            self._idle_since = None
            return None
        if self._idle_since is None:
            self._idle_since = now
        if now - self._idle_since < IDLE_WINDOWS * self.window_s:
            return None
        self._idle_since = now
        return (
            f"idle capacity: fewer than {self.slots} games ran while games were queued "
            f"for two consecutive {self.window_s:.0f} s windows"
        )
