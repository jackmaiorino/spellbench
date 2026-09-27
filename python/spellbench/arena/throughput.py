"""The useful-compute guard (COMPUTE-POLICY.md): how many games a run plays at once.

Every guarded launch plans an :class:`Allocation` before its first game.

- Qualification plays games sampled across the schedule (``sample``, for
  example one game of each matchup in turn: :func:`sample_order`), never
  repeats of one game. ``play(workers, indices)`` plays the given games with
  that many workers and reports each game's own time, digest and ledger
  bytes (:class:`PlayedGame`).
- A run is substantial when its projected serial time exceeds
  ``SMALL_RUN_SECONDS`` and its scaling comparison fits the budget. The
  comparison plays the same ``QUALIFY_GAMES_PER_WORKER * bound`` games with
  1, ``bound // 2`` and ``bound`` workers; at ideal scaling it may cost at
  most ``QUALIFY_BUDGET_PERCENT`` percent of the serial schedule, because
  qualification counts toward the time to a completed result. The probe is
  the 1-worker rung. The fastest rung by busy time wins
  (``workers * games / summed game seconds``; on identical games the spread
  in game lengths cancels, where a batch's wall time is dominated by its
  slowest games), the smaller on a tie. A substantial run needs a
  :class:`Placement` naming every machine with a disposition. Outputs that
  change with the worker count are refused; outputs that change when the
  1-worker rung is replayed (bots that read the clock) are recorded instead.
- Every other run is small: it keeps the resource-bounded worker count after
  a short probe, and it is unmeasured for the rated rule (Decision 3),
  because nobody compared its outputs across worker counts.
- With an evidence file, a qualification is recorded locally and reused by
  later launches with the same host, cores, cores per game, worker bound,
  machine, workload and size class, for between half and twice as many
  games: re-measuring unchanged conditions gains nothing.
- The allocation carries a byte budget (ARTIFACT-LAW.md clause 1): ledger
  rows projected from the probe plus the pinned files, under a cap. A launch
  that would leave less than ``RESERVE_BYTES`` free on a target volume is
  refused.

Trials and machine facts are wall-clock evidence: they live only in the
manifest's ``allocation`` block and the local, unhashed evidence file, never
in hashed data files. While a run plays, :class:`IdleMonitor` flags capacity
that stays unused and throughput that falls below the qualified rate.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, replace
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence, TextIO

from ..errors import ProtocolError, ValidationError
from ..wire import canonical_json_dumps, strict_json_loads

SMALL_RUN_SECONDS = 120
# The probe of a schedule too small for a scaling comparison.
PROBE_GAMES = 2
# Games every rung plays, per worker of the top rung.
QUALIFY_GAMES_PER_WORKER = 2
# The scaling comparison's cost at ideal scaling, as a share of the projected serial time.
QUALIFY_BUDGET_PERCENT = 12
# Unused capacity is flagged once it lasts this many consecutive windows (COMPUTE-POLICY.md item 6).
IDLE_WINDOWS = 2
# A window finishing fewer than this share of the qualified rate's games is slow.
RATE_FLOOR_PERCENT = 50
# A rate window lasts until it expects at least this many games.
RATE_MIN_GAMES = 8
# Free space every target volume keeps (ARTIFACT-LAW.md clause 1).
RESERVE_BYTES = 60 * 2**30
ALLOCATION_KINDS = ("small", "substantial", "unmeasured")
ALLOCATION_LABELS = {"small": "small run, unmeasured", "substantial": "substantial run, measured", "unmeasured": "unmeasured"}
# The placements COMPUTE-POLICY.md item 1 names: the operator's main PC, HaleysPC and RunPod.
PLACEMENT_MACHINES = ("main-pc", "haleyspc", "runpod")
PLACEMENT_DISPOSITIONS = ("used", "unavailable", "slower", "not_authorized")
EVIDENCE_SCHEMA = "spellbench-throughput-evidence/v1"

_MAX_INT = (1 << 53) - 1
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_ROLE = re.compile(r"[a-z][a-z0-9_]*")
_PLACEMENT_ITEM = re.compile(r"\s*([A-Za-z][A-Za-z0-9-]*)\s*=\s*([a-z_]+)\s*:\s*(.*\S)\s*")
_PLACEMENT_FORM = (
    "a placement names each of main-pc, haleyspc and runpod once, as '<machine>=<disposition>: <reason>' "
    f"separated by ';', each disposition one of {', '.join(PLACEMENT_DISPOSITIONS)} and at least one used, for "
    "example 'main-pc=used: fastest measured; haleyspc=slower: half the speed per game; runpod=not_authorized: "
    "no spending authority' (COMPUTE-POLICY.md item 1)"
)
_TRIAL_KEYS = ("workers", "games", "indices", "seconds_milli", "busy_milli", "row_bytes", "outputs_digest")
_ALLOCATION_KEYS = (
    "kind", "label", "workers", "host", "cpu_count", "per_game_cores", "games_total", "probe", "trials",
    "projected_serial_seconds", "placement", "outputs_identical", "outputs_note", "qualification_seconds_milli",
    "workload", "reused", "machine", "budget",
)


class ThroughputError(Exception):
    """The launch guard refuses the run before its first game."""


def _exact_keys(value: dict[str, Any], keys: Sequence[str], context: str) -> None:
    missing, extra = set(keys) - set(value), set(value) - set(keys)
    if missing or extra:
        raise ValidationError(f"{context}: fields mismatch: missing={sorted(missing)} extra={sorted(extra)}")


def _object(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError(f"{context}: must be an object")
    return value


def _count(value: Any, context: str, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= _MAX_INT:
        raise ValidationError(f"{context}: must be an integer in [{minimum}, 2^53 - 1]")
    return value


def _text(value: Any, context: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValidationError(f"{context}: must be a nonblank string")
    return value


def _is_digest(value: Any) -> bool:
    return type(value) is str and _DIGEST.fullmatch(value) is not None


def _host_name(host: str | None) -> str:
    return (platform.node() or "unknown") if host is None else host


def _cgroup_cpus(text: str | None) -> int | None:
    """The CPUs a cgroup v2 ``cpu.max`` quota allows (``"<quota> <period>"``), or None without a quota."""
    parts = (text or "").split()
    if len(parts) != 2 or not all(part.isdigit() for part in parts) or int(parts[1]) == 0:
        return None
    return max(1, math.ceil(int(parts[0]) / int(parts[1])))


def _cpu_count(cpu_count: int | None) -> int:
    """The given count, else the CPUs this process may use, bounded by a Linux container's quota (RunPod)."""
    if cpu_count is not None:
        return cpu_count
    count = (getattr(os, "process_cpu_count", None) or os.cpu_count)() or 1
    if sys.platform.startswith("linux"):
        try:
            quota = _cgroup_cpus(Path("/sys/fs/cgroup/cpu.max").read_text(encoding="ascii"))
        except (OSError, UnicodeDecodeError):
            quota = None
        if quota is not None:
            count = min(count, quota)
    return count


# ---------------------------------------------------------------------------
# Records: played games, trials, placement, machine facts, budget, allocation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlayedGame:
    """One game a qualification played, as ``play`` reports it (one per requested index, in order).

    ``seconds`` runs from the game's dispatch to its result, so a worker's
    start-up counts; ``digest`` is ``"sha256:"`` and the hex SHA-256 of the
    game's canonical ledger row (the bytes the run would hash); ``row_bytes``
    is that row's size in the ledger, newline included.
    """

    index: int
    seconds: float
    digest: str
    row_bytes: int


@dataclass(frozen=True)
class Trial:
    """One measured call: the sampled games ``indices`` played with ``workers`` workers.

    ``seconds_milli`` is the call's wall time, a cross-check: far above
    ``busy_milli / workers`` means the dispatcher, not the games, set the
    pace. ``busy_milli`` sums the games' own times and ranks the rungs.
    ``outputs_digest`` covers the games' digests in order; ``row_bytes``
    sums their ledger bytes.
    """

    workers: int
    games: int
    seconds_milli: int
    outputs_digest: str
    busy_milli: int
    row_bytes: int
    indices: tuple[int, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "indices", tuple(self.indices))
        _count(self.workers, "trial.workers", 1)
        _count(self.games, "trial.games", 1)
        _count(self.seconds_milli, "trial.seconds_milli")
        _count(self.busy_milli, "trial.busy_milli")
        _count(self.row_bytes, "trial.row_bytes")
        if not _is_digest(self.outputs_digest):
            raise ValidationError('trial.outputs_digest: must be "sha256:" and 64 lowercase hex digits')
        if (
            len(self.indices) != self.games
            or any(type(index) is not int or not 0 <= index <= _MAX_INT for index in self.indices)
            or len(set(self.indices)) != self.games
        ):
            raise ValidationError("trial.indices: must be the trial's distinct schedule positions, one per game")

    @property
    def rate(self) -> Fraction:
        """Completed games per millisecond at this worker count: ``workers * games / busy_milli``, exactly."""
        return Fraction(self.workers * self.games, max(self.busy_milli, 1))

    def to_json(self) -> dict[str, Any]:
        return {
            "workers": self.workers,
            "games": self.games,
            "indices": list(self.indices),
            "seconds_milli": self.seconds_milli,
            "busy_milli": self.busy_milli,
            "row_bytes": self.row_bytes,
            "outputs_digest": self.outputs_digest,
        }

    @classmethod
    def from_json(cls, value: Any, context: str = "trial") -> Trial:
        _exact_keys(_object(value, context), _TRIAL_KEYS, context)
        if not isinstance(value["indices"], list):
            raise ValidationError(f"{context}.indices: must be a list")
        try:
            return cls(**{**value, "indices": tuple(value["indices"])})
        except ValidationError as exc:
            raise ValidationError(f"{context}: {exc}") from exc


@dataclass(frozen=True)
class MachinePlacement:
    """One machine a run considered: its disposition and why."""

    machine: str
    disposition: str
    reason: str


@dataclass(frozen=True)
class Placement:
    """Where a run plays and why (COMPUTE-POLICY.md item 1): each of ``PLACEMENT_MACHINES`` once, in that order,
    with a disposition from ``PLACEMENT_DISPOSITIONS`` and a reason; at least one machine is used."""

    entries: tuple[MachinePlacement, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "entries", tuple(self.entries))
        if (
            not all(isinstance(entry, MachinePlacement) for entry in self.entries)
            or tuple(entry.machine for entry in self.entries) != PLACEMENT_MACHINES
            or any(entry.disposition not in PLACEMENT_DISPOSITIONS for entry in self.entries)
            or any(type(entry.reason) is not str or not entry.reason.strip() for entry in self.entries)
            or not any(entry.disposition == "used" for entry in self.entries)
        ):
            raise ThroughputError(_PLACEMENT_FORM)

    @classmethod
    def parse(cls, text: str) -> Placement:
        """Read ``'main-pc=used: why; haleyspc=slower: why; runpod=not_authorized: why'`` (the ``--placement`` text)."""
        found: dict[str, MachinePlacement] = {}
        for item in text.split(";"):
            match = _PLACEMENT_ITEM.fullmatch(item)
            machine = match.group(1).lower() if match else ""
            if match is None or machine in found:
                raise ThroughputError(_PLACEMENT_FORM)
            found[machine] = MachinePlacement(machine, match.group(2), match.group(3))
        if set(found) != set(PLACEMENT_MACHINES):
            raise ThroughputError(_PLACEMENT_FORM)
        return cls(tuple(found[machine] for machine in PLACEMENT_MACHINES))

    def __str__(self) -> str:
        return "; ".join(f"{entry.machine}={entry.disposition}: {entry.reason}" for entry in self.entries)

    def to_json(self) -> dict[str, Any]:
        return {entry.machine: {"disposition": entry.disposition, "reason": entry.reason} for entry in self.entries}

    @classmethod
    def from_json(cls, value: Any, context: str = "placement") -> Placement:
        _exact_keys(_object(value, context), PLACEMENT_MACHINES, context)
        entries = []
        for machine in PLACEMENT_MACHINES:
            item = _object(value[machine], f"{context}.{machine}")
            _exact_keys(item, ("disposition", "reason"), f"{context}.{machine}")
            entries.append(MachinePlacement(machine, _text(item["disposition"], f"{context}.{machine}.disposition"),
                                            _text(item["reason"], f"{context}.{machine}.reason")))
        try:
            return cls(tuple(entries))
        except ThroughputError as exc:
            raise ValidationError(f"{context}: {exc}") from exc


@dataclass(frozen=True)
class MachineFacts:
    """The machine as the launch found it: total memory, NVIDIA GPUs, and free bytes per target volume.

    ``free_bytes`` pairs a role (``run_dir``, ``pin_root``), never a path,
    with its volume's free bytes, sorted by role.
    """

    memory_bytes: int | None
    gpus: tuple[str, ...]
    free_bytes: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "gpus", tuple(self.gpus))
        object.__setattr__(self, "free_bytes", tuple(tuple(pair) for pair in self.free_bytes))
        if self.memory_bytes is not None:
            _count(self.memory_bytes, "machine.memory_bytes", 1)
        for index, name in enumerate(self.gpus):
            _text(name, f"machine.gpus[{index}]")
        roles = [pair[0] if len(pair) == 2 else None for pair in self.free_bytes]
        if any(type(role) is not str or not _ROLE.fullmatch(role) for role in roles) or roles != sorted(set(roles)):
            raise ValidationError("machine.free_bytes: keys must be distinct roles such as run_dir, never paths")
        for role, free in self.free_bytes:
            _count(free, f"machine.free_bytes.{role}")

    def to_json(self) -> dict[str, Any]:
        return {"memory_bytes": self.memory_bytes, "gpus": list(self.gpus), "free_bytes": dict(self.free_bytes)}

    @classmethod
    def from_json(cls, value: Any, context: str = "machine") -> MachineFacts:
        _exact_keys(_object(value, context), ("memory_bytes", "gpus", "free_bytes"), context)
        if not isinstance(value["gpus"], list):
            raise ValidationError(f"{context}.gpus: must be a list")
        free = _object(value["free_bytes"], f"{context}.free_bytes")
        return cls(memory_bytes=value["memory_bytes"], gpus=tuple(value["gpus"]), free_bytes=tuple(sorted(free.items())))


@dataclass(frozen=True)
class Budget:
    """A run's declared bytes (ARTIFACT-LAW.md clause 1): its ledger rows projected from the probe plus
    ``pinned_bytes`` of pinned files, under ``cap_bytes``."""

    projected_bytes: int
    pinned_bytes: int
    cap_bytes: int

    def __post_init__(self) -> None:
        for name in ("projected_bytes", "pinned_bytes", "cap_bytes"):
            _count(getattr(self, name), f"budget.{name}")
        if not self.pinned_bytes <= self.projected_bytes <= self.cap_bytes:
            raise ValidationError("budget: the pinned bytes are part of the projection, which stays under the cap")

    def to_json(self) -> dict[str, Any]:
        return {"projected_bytes": self.projected_bytes, "pinned_bytes": self.pinned_bytes, "cap_bytes": self.cap_bytes}

    @classmethod
    def from_json(cls, value: Any, context: str = "budget") -> Budget:
        _exact_keys(_object(value, context), ("projected_bytes", "pinned_bytes", "cap_bytes"), context)
        return cls(**value)


@dataclass(frozen=True)
class Allocation:
    """How many games a run plays at once, and the evidence for it (the manifest's ``allocation`` block).

    ``kind`` is ``substantial`` (a scaling comparison chose the workers; the
    only measured kind), ``small`` (the schedule was too short to qualify,
    so it kept its resource-bounded workers unmeasured) or ``unmeasured``
    (no guard ran). ``label`` in the JSON spells this out. ``games_total``
    and ``projected_serial_seconds`` describe the schedule the allocation
    was planned for; ``qualification_seconds_milli`` is the wall time the
    measurement took; ``reused`` says an earlier launch measured it, so this
    run spent nothing on it. ``outputs_note`` explains outputs that differed
    between replays of identical games.
    """

    kind: str
    workers: int
    host: str
    cpu_count: int
    per_game_cores: int
    probe: Trial | None = None
    trials: tuple[Trial, ...] = ()
    projected_serial_seconds: int | None = None
    placement: Placement | None = None
    outputs_identical: bool | None = None
    qualification_seconds_milli: int | None = None
    workload: str | None = None
    reused: bool = False
    games_total: int | None = None
    outputs_note: str | None = None
    machine: MachineFacts | None = None
    budget: Budget | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "trials", tuple(self.trials))
        _check_allocation(self)

    @property
    def measured(self) -> bool:
        """Whether a scaling comparison measured this allocation (Decision 3: only such runs are rated)."""
        return self.kind == "substantial"

    @property
    def label(self) -> str:
        return ALLOCATION_LABELS[self.kind]

    @property
    def qualified_rate(self) -> float | None:
        """Games per second the chosen worker count sustained in qualification; None unless substantial."""
        if self.kind != "substantial":
            return None
        chosen = next(trial for trial in self.trials if trial.workers == self.workers)
        return float(chosen.rate * 1000)

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "label": self.label,
            "workers": self.workers,
            "host": self.host,
            "cpu_count": self.cpu_count,
            "per_game_cores": self.per_game_cores,
            "games_total": self.games_total,
            "probe": None if self.probe is None else self.probe.to_json(),
            "trials": [trial.to_json() for trial in self.trials],
            "projected_serial_seconds": self.projected_serial_seconds,
            "placement": None if self.placement is None else self.placement.to_json(),
            "outputs_identical": self.outputs_identical,
            "outputs_note": self.outputs_note,
            "qualification_seconds_milli": self.qualification_seconds_milli,
            "workload": self.workload,
            "reused": self.reused,
            "machine": None if self.machine is None else self.machine.to_json(),
            "budget": None if self.budget is None else self.budget.to_json(),
        }

    @classmethod
    def from_json(cls, value: Any, context: str = "allocation") -> Allocation:
        _exact_keys(_object(value, context), _ALLOCATION_KEYS, context)
        fields = dict(value)
        label = fields.pop("label")
        if fields["kind"] not in ALLOCATION_KINDS or label != ALLOCATION_LABELS[fields["kind"]]:
            raise ValidationError(f"{context}.label: must be the kind's label {ALLOCATION_LABELS}")
        if not isinstance(fields["trials"], list):
            raise ValidationError(f"{context}.trials: must be a list")
        parsers = {"probe": Trial.from_json, "placement": Placement.from_json, "machine": MachineFacts.from_json,
                   "budget": Budget.from_json}
        for name, parse in parsers.items():
            if fields[name] is not None:
                fields[name] = parse(fields[name], f"{context}.{name}")
        fields["trials"] = tuple(
            Trial.from_json(item, f"{context}.trials[{index}]") for index, item in enumerate(fields["trials"])
        )
        return cls(**fields)

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
    """Field types, then the evidence each kind carries, then that it follows from the rule."""
    if allocation.kind not in ALLOCATION_KINDS:
        raise ValidationError(f"allocation.kind: must be one of {list(ALLOCATION_KINDS)}")
    _count(allocation.workers, "allocation.workers", 1)
    _text(allocation.host, "allocation.host")
    _count(allocation.cpu_count, "allocation.cpu_count", 1)
    _count(allocation.per_game_cores, "allocation.per_game_cores", 1)
    for name, kind in (("probe", Trial), ("placement", Placement), ("machine", MachineFacts), ("budget", Budget)):
        if getattr(allocation, name) is not None and not isinstance(getattr(allocation, name), kind):
            raise ValidationError(f"allocation.{name}: must be a {kind.__name__} or null")
    if not all(isinstance(trial, Trial) for trial in allocation.trials):
        raise ValidationError("allocation.trials: must hold trials")
    for name, minimum in (("projected_serial_seconds", 0), ("qualification_seconds_milli", 0), ("games_total", 1)):
        if getattr(allocation, name) is not None:
            _count(getattr(allocation, name), f"allocation.{name}", minimum)
    if allocation.outputs_identical is not None and type(allocation.outputs_identical) is not bool:
        raise ValidationError("allocation.outputs_identical: must be a boolean or null")
    if allocation.outputs_note is not None:
        _text(allocation.outputs_note, "allocation.outputs_note")
    if allocation.workload is not None and not _is_digest(allocation.workload):
        raise ValidationError('allocation.workload: must be "sha256:" and 64 lowercase hex digits, or null')
    if type(allocation.reused) is not bool:
        raise ValidationError("allocation.reused: must be a boolean")
    evidence = (allocation.probe, allocation.projected_serial_seconds, allocation.outputs_identical, allocation.outputs_note,
                allocation.qualification_seconds_milli, allocation.games_total, allocation.machine, allocation.budget)
    if allocation.kind == "unmeasured":
        if allocation.trials or allocation.reused or any(item is not None for item in evidence):
            raise ValidationError("allocation: an unmeasured allocation carries no measurement")
        return
    probe, games_total, budget = allocation.probe, allocation.games_total, allocation.budget
    if probe is None or games_total is None or budget is None or allocation.projected_serial_seconds is None:
        raise ValidationError(f"allocation: a {allocation.kind} allocation needs its probe, schedule, projection and budget")
    if probe.workers != 1 or allocation.projected_serial_seconds != _projected_seconds(probe, games_total):
        raise ValidationError("allocation: the projection must follow from the 1-worker probe and games_total")
    if budget.projected_bytes != _projected_row_bytes(probe, games_total) + budget.pinned_bytes:
        raise ValidationError("allocation.budget: the projection must follow from the probe's rows and the pinned bytes")
    if allocation.kind == "small":
        if allocation.trials or allocation.outputs_identical is not None or allocation.outputs_note is not None:
            raise ValidationError("allocation: a small allocation has no scaling comparison")
        if _size_class(probe, games_total, allocation.workers) != "small":
            raise ValidationError("allocation: a schedule this long qualifies, so it cannot be small")
        return
    trials = allocation.trials
    top = max((trial.workers for trial in trials), default=1)
    if (
        not trials
        or trials[0] != probe
        or tuple(trial.workers for trial in trials) != worker_ladder(top)
        or any(trial.indices != probe.indices for trial in trials)
        or probe.games != QUALIFY_GAMES_PER_WORKER * top
        or _size_class(probe, games_total, top) != "substantial"
    ):
        raise ValidationError(
            "allocation: a substantial allocation compares 1, top // 2 and top workers on the probe's games, "
            "and its schedule must be long enough to qualify"
        )
    if allocation.placement is None:
        raise ValidationError("allocation: a substantial allocation needs its placement")
    if allocation.workers != _fastest(trials):
        raise ValidationError("allocation.workers: must be the rung with the most games per second of busy time")
    same = len({trial.outputs_digest for trial in trials}) == 1
    if allocation.outputs_identical is not same or (allocation.outputs_note is None) is not same:
        raise ValidationError(
            "allocation: outputs_identical says whether the trials' digests agree, and differing digests need a note"
        )


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


def resource_bound(cpu_count: int, per_game_cores: int) -> int:
    """Games that fit at once when each needs ``per_game_cores`` declared cores (spec 11.4); at least 1."""
    return max(1, cpu_count // max(1, per_game_cores))


def worker_ladder(cap: int) -> tuple[int, ...]:
    """The worker counts a substantial run compares: 1, ``cap // 2`` and ``cap``, without repeats."""
    return tuple(sorted({1, max(1, cap // 2), max(1, cap)}))


def sample_order(groups: Sequence[Sequence[int]]) -> tuple[int, ...]:
    """Schedule positions taking one game from each group in turn, for example each matchup's games in order."""
    columns = [list(group) for group in groups]
    order: list[int] = []
    for position in range(max((len(column) for column in columns), default=0)):
        order.extend(column[position] for column in columns if position < len(column))
    return tuple(order)


def workload_id(value: Any) -> str:
    """The identity a qualification is reused under.

    ``"sha256:"`` and the SHA-256 of the canonical JSON of what shapes the
    games: the config minus run-specific fields (such as ``tournament_dir``),
    the engine and bot files' SHA-256 values, and the arena version.
    """
    try:
        data = canonical_json_dumps(value)
    except ValidationError as exc:
        raise ThroughputError(f"a workload must be canonical JSON: {exc}") from exc
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _projected_seconds(probe: Trial, games_total: int) -> int:
    return -(-probe.seconds_milli * games_total // (1000 * probe.games))


def _projected_row_bytes(probe: Trial, games_total: int) -> int:
    return -(-probe.row_bytes * games_total // probe.games)


def _ladder_fits(games_total: int, bound: int) -> bool:
    """Whether the scaling comparison fits: ``QUALIFY_GAMES_PER_WORKER`` games per top-rung worker, costing at
    most ``QUALIFY_BUDGET_PERCENT`` percent of the serial schedule at ideal scaling (the time per game cancels)."""
    games = QUALIFY_GAMES_PER_WORKER * bound
    cost = games * sum(Fraction(1, workers) for workers in worker_ladder(bound))
    return games <= games_total and cost * 100 <= games_total * QUALIFY_BUDGET_PERCENT


def _size_class(probe: Trial, games_total: int, bound: int) -> str:
    long_enough = _projected_seconds(probe, games_total) > SMALL_RUN_SECONDS
    return "substantial" if long_enough and _ladder_fits(games_total, bound) else "small"


def _fastest(trials: Sequence[Trial]) -> int:
    return max(trials, key=lambda trial: (trial.rate, -trial.workers)).workers


def _usable_seconds(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _combined_digest(digests: Sequence[str]) -> str:
    return "sha256:" + hashlib.sha256("".join(digest + "\n" for digest in digests).encode("ascii")).hexdigest()


def _trial(
    play: Callable[[int, tuple[int, ...]], tuple[float, Sequence[PlayedGame]]], workers: int, indices: tuple[int, ...]
) -> tuple[Trial, tuple[str, ...]]:
    """Play the games once; returns the trial and the games' own digests."""
    context = f"playing {len(indices)} games with {workers} worker{'s' if workers != 1 else ''}"
    result = play(workers, indices)  # its own errors propagate unchanged
    try:
        wall, reported = result
        games = tuple(reported)
    except (TypeError, ValueError) as exc:
        raise ThroughputError(f"{context}: play must return (wall seconds, the played games): {exc}") from exc
    if not _usable_seconds(wall):
        raise ThroughputError(f"{context} reported no usable wall time: {wall!r}")
    if len(games) != len(indices) or any(
        not isinstance(game, PlayedGame) or game.index != index for game, index in zip(games, indices)
    ):
        raise ThroughputError(f"{context} did not report each requested game, in order")
    for game in games:
        if not _usable_seconds(game.seconds) or not _is_digest(game.digest):
            raise ThroughputError(f"{context}: game {game.index} needs a usable time and a sha256 digest")
        if type(game.row_bytes) is not int or game.row_bytes < 0:
            raise ThroughputError(f"{context}: game {game.index} needs its ledger bytes")
    digests = tuple(game.digest for game in games)
    try:
        trial = Trial(
            workers=workers, games=len(indices), seconds_milli=round(wall * 1000), outputs_digest=_combined_digest(digests),
            busy_milli=round(sum(game.seconds for game in games) * 1000), row_bytes=sum(game.row_bytes for game in games),
            indices=indices,
        )
    except ValidationError as exc:
        raise ThroughputError(f"{context}: {exc}") from exc
    return trial, digests


def _since(clock: Callable[[], float], started: float) -> int:
    return max(0, round((clock() - started) * 1000))


def _placement_needed(projected: int) -> str:
    return f"a substantial run (projected {projected} s serial) needs a placement note: {_PLACEMENT_FORM}"


def _placement(placement: Placement | str | None) -> Placement | None:
    if placement is None or isinstance(placement, Placement):
        return placement
    if isinstance(placement, str):
        return Placement.parse(placement) if placement.strip() else None
    raise ThroughputError("placement: must be a Placement, its text, or None")


def _sample(sample: Sequence[int] | None, games_total: int) -> tuple[int, ...]:
    if sample is None:
        return tuple(range(games_total))
    order = tuple(sample)
    if any(type(index) is not int for index in order) or sorted(order) != list(range(games_total)):
        raise ThroughputError(f"the sample must order every scheduled game once (positions 0 to {games_total - 1})")
    return order


def _budget(probe: Trial, games_total: int, pinned_bytes: int, cap_bytes: int | None) -> Budget:
    projected = _projected_row_bytes(probe, games_total) + pinned_bytes
    cap = 2 * projected if cap_bytes is None else cap_bytes
    if projected > cap:
        raise ThroughputError(f"the run projects {projected} bytes, over its {cap}-byte cap (ARTIFACT-LAW.md clause 1)")
    return Budget(projected_bytes=projected, pinned_bytes=pinned_bytes, cap_bytes=cap)


def check_reserve(machine: MachineFacts, projected_bytes: int) -> None:
    """Refuse when ``projected_bytes`` more would leave any target volume under ``RESERVE_BYTES`` free.

    Each volume is charged the whole projection, which is conservative when
    the rows and the pins land on different volumes.
    """
    for role, free in machine.free_bytes:
        if free - projected_bytes < RESERVE_BYTES:
            raise ThroughputError(
                f"{role} has {free / 2**30:.1f} GiB free; {projected_bytes} more bytes would leave less than the "
                f"{RESERVE_BYTES // 2**30} GiB reserve (ARTIFACT-LAW.md clause 1)"
            )


def _outputs(
    play: Callable[[int, tuple[int, ...]], tuple[float, Sequence[PlayedGame]]],
    indices: tuple[int, ...],
    trials: Sequence[Trial],
    first_digests: tuple[str, ...],
) -> tuple[bool, str | None]:
    """Whether the rungs' outputs agree; when they do not, replay the 1-worker rung to tell why."""
    if len({trial.outputs_digest for trial in trials}) == 1:
        return True, None
    _, again = _trial(play, 1, indices)
    changed = [str(index) for index, first, second in zip(indices, first_digests, again) if first != second]
    if not changed:
        raise ThroughputError("worker counts changed the results of identical games; refusing to parallelize")
    games = f"game{'s' if len(changed) > 1 else ''} {', '.join(changed)}"
    return False, (
        f"the 1-worker trial did not reproduce itself ({games} differed), so the outputs depend on something "
        "besides the worker count, such as a bot reading the clock (spec 11.4); the worker count was chosen on speed alone"
    )


# ---------------------------------------------------------------------------
# Evidence: a local, unhashed cache of measured allocations
# ---------------------------------------------------------------------------


def _read_evidence(path: Path) -> list[Allocation]:
    """The fresh (not reused) allocations in a local evidence file, oldest first.

    It is a cache: unreadable lines are skipped, and an unreadable file is an error.
    """
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
        if allocation is not None and allocation.kind != "unmeasured" and not allocation.reused:
            allocations.append(allocation)
    return allocations


def _ensure_writable(path: Path) -> None:
    """Open the evidence file for appending before any game plays, so a measurement is never lost to it."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "ab"):
            pass
    except OSError as exc:
        raise ThroughputError(f"cannot write the throughput evidence {path}: {exc}") from exc


def _record_evidence(path: Path, allocation: Allocation) -> None:
    line = canonical_json_dumps({"schema": EVIDENCE_SCHEMA, "allocation": allocation.to_json()}) + b"\n"
    try:
        with open(path, "ab") as handle:
            handle.write(line)
    except OSError as exc:
        raise ThroughputError(f"cannot record the throughput evidence in {path}: {exc}") from exc


def _worker_bound(allocation: Allocation) -> int:
    """The worker bound a measured allocation was planned under: its top rung, or a small run's workers."""
    return max(trial.workers for trial in allocation.trials) if allocation.trials else allocation.workers


def _hardware(machine: MachineFacts | None) -> tuple[int | None, tuple[str, ...]] | None:
    return None if machine is None else (machine.memory_bytes, machine.gpus)


def _prior_allocation(
    path: Path, *, host: str, cpu_count: int, per_game_cores: int, workload: str, bound: int, games_total: int,
    machine: MachineFacts | None,
) -> Allocation | None:
    """The newest recorded allocation for the same conditions, size class and scale (half to twice the games)."""
    key = (host, cpu_count, per_game_cores, workload, bound, _hardware(machine))

    def compatible(prior: Allocation) -> bool:
        assert prior.probe is not None and prior.games_total is not None
        return (
            (prior.host, prior.cpu_count, prior.per_game_cores, prior.workload, _worker_bound(prior),
             _hardware(prior.machine)) == key
            and prior.games_total <= 2 * games_total
            and games_total <= 2 * prior.games_total
            and prior.probe.games <= games_total
            and _size_class(prior.probe, games_total, bound) == prior.kind
        )

    matches = [prior for prior in _read_evidence(path) if compatible(prior)]
    return matches[-1] if matches else None


def _reused(
    prior: Allocation, *, games_total: int, placement: Placement | None, machine: MachineFacts | None,
    pinned_bytes: int, cap_bytes: int | None,
) -> Allocation:
    """``prior`` for this run: its measurement, with this schedule's projection, budget, machine and placement."""
    assert prior.probe is not None
    projected = _projected_seconds(prior.probe, games_total)
    if prior.kind == "substantial" and placement is None:
        raise ThroughputError(_placement_needed(projected))
    budget = _budget(prior.probe, games_total, pinned_bytes, cap_bytes)
    if machine is not None:
        check_reserve(machine, budget.projected_bytes)
    return replace(prior, games_total=games_total, projected_serial_seconds=projected, placement=placement,
                   machine=machine, budget=budget, reused=True)


def plan_allocation(
    *,
    games_total: int,
    cap: int,
    per_game_cores: int,
    play: Callable[[int, tuple[int, ...]], tuple[float, Sequence[PlayedGame]]],
    placement: Placement | str | None,
    cpu_count: int | None = None,
    host: str | None = None,
    sample: Sequence[int] | None = None,
    workload: str | None = None,
    evidence: Path | None = None,
    machine: MachineFacts | None = None,
    pinned_bytes: int = 0,
    cap_bytes: int | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> Allocation:
    """Choose how many games run at once (COMPUTE-POLICY.md items 2 to 5; ARTIFACT-LAW.md clause 1).

    ``play(workers, indices)`` plays the scheduled games at those positions
    with ``workers`` workers and returns ``(wall seconds, one PlayedGame per
    index, in order)``. Every call in one qualification uses the same
    throwaway secret, so the rungs play identical games; each game's digest
    covers exactly the ledger row the run would hash, and its time includes
    serialization and storage. ``sample`` orders every scheduled game
    (default: schedule order); qualification takes games from its front.
    ``placement`` is a :class:`Placement` or its text; a substantial run
    needs one. With ``evidence`` (a local file, never published) and
    ``workload`` (:func:`workload_id`), a compatible earlier measurement is
    reused, and a fresh one is appended. ``machine`` (:func:`machine_facts`)
    is recorded and every volume in it keeps ``RESERVE_BYTES`` free after
    the projected bytes: the probe's rows scaled to the schedule plus
    ``pinned_bytes``, under ``cap_bytes`` (default twice the projection).
    ``clock`` times the qualification. Every input is checked before the
    first game plays; an empty schedule is refused.
    """
    if type(games_total) is not int or games_total < 1:
        raise ThroughputError(f"the schedule has no games to qualify (games_total={games_total!r})")
    cpu = _cpu_count(cpu_count)
    for label, value in (("cap", cap), ("per_game_cores", per_game_cores), ("cpu_count", cpu)):
        if type(value) is not int or value < 1:
            raise ThroughputError(f"{label}: must be a positive integer, got {value!r}")
    machine_name = _host_name(host)
    if type(machine_name) is not str or not machine_name.strip():
        raise ThroughputError("host: must be a nonblank string")
    if workload is not None and not _is_digest(workload):
        raise ThroughputError('workload: must be "sha256:" and 64 lowercase hex digits (see workload_id)')
    if evidence is not None and workload is None:
        raise ThroughputError("reusing throughput evidence needs the workload it was measured on")
    for label, value in (("pinned_bytes", pinned_bytes), ("cap_bytes", 0 if cap_bytes is None else cap_bytes)):
        if type(value) is not int or value < 0:
            raise ThroughputError(f"{label}: must be a non-negative integer, got {value!r}")
    if machine is not None and not isinstance(machine, MachineFacts):
        raise ThroughputError("machine: must be MachineFacts (see machine_facts)")
    order = _sample(sample, games_total)
    note = _placement(placement)
    if machine is not None:
        check_reserve(machine, 0)
    # More workers than games is never useful (COMPUTE-POLICY.md item 2).
    bound = min(cap, resource_bound(cpu, per_game_cores), games_total)
    if evidence is not None:
        assert workload is not None
        evidence = Path(evidence)
        _ensure_writable(evidence)
        prior = _prior_allocation(evidence, host=machine_name, cpu_count=cpu, per_game_cores=per_game_cores,
                                  workload=workload, bound=bound, games_total=games_total, machine=machine)
        if prior is not None:
            return _reused(prior, games_total=games_total, placement=note, machine=machine, pinned_bytes=pinned_bytes,
                           cap_bytes=cap_bytes)
    started = clock()
    fits = _ladder_fits(games_total, bound)
    # When the comparison fits, the probe plays its games and is its 1-worker rung.
    indices = order[: QUALIFY_GAMES_PER_WORKER * bound if fits else min(PROBE_GAMES, games_total)]
    probe, probe_digests = _trial(play, 1, indices)
    projected = _projected_seconds(probe, games_total)
    budget = _budget(probe, games_total, pinned_bytes, cap_bytes)
    if machine is not None:
        check_reserve(machine, budget.projected_bytes)
    common: dict[str, Any] = dict(
        host=machine_name, cpu_count=cpu, per_game_cores=per_game_cores, games_total=games_total, probe=probe,
        projected_serial_seconds=projected, placement=note, workload=workload, machine=machine, budget=budget,
    )
    if not fits or projected <= SMALL_RUN_SECONDS:
        allocation = Allocation(kind="small", workers=bound, qualification_seconds_milli=_since(clock, started), **common)
    else:
        if note is None:
            raise ThroughputError(_placement_needed(projected))
        trials = [probe, *(_trial(play, workers, indices)[0] for workers in worker_ladder(bound)[1:])]
        identical, outputs_note = _outputs(play, indices, trials, probe_digests)
        allocation = Allocation(kind="substantial", workers=_fastest(trials), trials=tuple(trials), outputs_identical=identical,
                                outputs_note=outputs_note, qualification_seconds_milli=_since(clock, started), **common)
    if evidence is not None:
        _record_evidence(evidence, allocation)
    return allocation


# ---------------------------------------------------------------------------
# Machine facts and CPU sampling (standard library only)
# ---------------------------------------------------------------------------


def total_memory() -> int | None:
    """Total physical memory in bytes, or None when the platform does not say."""
    try:
        if os.name == "nt":
            import ctypes

            class _MemoryStatus(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                    (name, ctypes.c_ulonglong) for name in ("total_phys", "avail_phys", "total_page", "avail_page",
                                                            "total_virtual", "avail_virtual", "avail_extended")
                ]

            status = _MemoryStatus()
            status.length = ctypes.sizeof(status)
            total = int(status.total_phys) if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)) else 0
        else:
            total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, OSError, ValueError):
        return None
    return total if 0 < total <= _MAX_INT else None


def nvidia_gpus(*, timeout_s: float = 10.0) -> tuple[str, ...]:
    """The NVIDIA GPUs ``nvidia-smi`` lists, or none when it is absent or fails."""
    program = shutil.which("nvidia-smi")
    if program is None:
        return ()
    try:
        result = subprocess.run([program, "--query-gpu=name", "--format=csv,noheader"], stdin=subprocess.DEVNULL,
                                capture_output=True, timeout=timeout_s, check=False)
    except (OSError, subprocess.SubprocessError):
        return ()
    if result.returncode != 0:
        return ()
    return tuple(line.strip() for line in result.stdout.decode("utf-8", errors="replace").splitlines() if line.strip())


def free_bytes(path: Path) -> int:
    """Free bytes on the volume that holds ``path``, or its nearest existing parent."""
    candidate = Path(path).absolute()
    while not candidate.exists() and candidate.parent != candidate:
        candidate = candidate.parent
    try:
        return shutil.disk_usage(candidate).free
    except OSError as exc:
        raise ThroughputError(f"cannot read the free space for {path}: {exc}") from exc


def machine_facts(
    volumes: Mapping[str, Path],
    *,
    memory: Callable[[], int | None] = total_memory,
    gpus: Callable[[], Sequence[str]] = nvidia_gpus,
    disk_free: Callable[[Path], int] = free_bytes,
) -> MachineFacts:
    """This machine's memory, GPUs and the free bytes of each target volume, by role (``run_dir``, ``pin_root``)."""
    return MachineFacts(memory_bytes=memory(), gpus=tuple(gpus()),
                        free_bytes=tuple(sorted((role, disk_free(Path(path))) for role, path in volumes.items())))


def _system_times() -> tuple[int, int] | None:
    """Windows ``GetSystemTimes``: (idle, kernel + user) in 100 ns units since boot; kernel time includes idle."""
    try:
        import ctypes
        from ctypes import wintypes

        idle, kernel, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
        if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            return None
    except (AttributeError, ImportError, OSError):
        return None

    def ticks(value: Any) -> int:
        return (value.dwHighDateTime << 32) | value.dwLowDateTime

    return ticks(idle), ticks(kernel) + ticks(user)


def _load_share() -> float | None:
    """POSIX: the one-minute load average per logical CPU, capped at 1."""
    try:
        load = os.getloadavg()[0]
    except (AttributeError, OSError):
        return None
    return min(1.0, max(0.0, load / (os.cpu_count() or 1)))


class CpuSampler:
    """The machine's CPU busy share since the previous sample (COMPUTE-POLICY.md item 6).

    Windows reads ``GetSystemTimes`` through ctypes, and its first sample is
    None (nothing to compare with yet); POSIX reports the load average per
    CPU. ``counters`` replaces the Windows source with any function returning
    cumulative ``(idle, total)`` ticks.
    """

    def __init__(self, counters: Callable[[], tuple[int, int] | None] | None = None) -> None:
        self._counters = counters if counters is not None else (_system_times if os.name == "nt" else None)
        self._last: tuple[int, int] | None = None

    def sample(self) -> float | None:
        if self._counters is None:
            return _load_share()
        now = self._counters()
        last, self._last = self._last, now
        if now is None or last is None or now[1] <= last[1]:
            return None
        return min(1.0, max(0.0, 1.0 - (now[0] - last[0]) / (now[1] - last[1])))


# ---------------------------------------------------------------------------
# Monitoring while the run plays
# ---------------------------------------------------------------------------


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
    """Flags eligible capacity that stays unused while games wait (COMPUTE-POLICY.md item 6).

    Idle slots: a tick is idle when fewer than ``slots`` games run while
    games are queued. Only unbroken idle ticks spanning ``IDLE_WINDOWS``
    windows of ``window_s`` seconds warn (120 s by default: the policy's two
    consecutive 60-second windows); a busy tick, or one with nothing queued,
    ends the stretch. Tick on a timer (every few seconds) and after filling
    free slots, never only when a game finishes: a tick taken between a game
    ending and its slot's refill sees a free slot, so a monitor ticked only
    then would warn about a healthy run.

    Slow throughput: with ``qualified_rate`` (games per second, see
    :attr:`Allocation.qualified_rate`) and the run's finished game count
    (``completed``), each window that finishes fewer than
    ``RATE_FLOOR_PERCENT`` percent of the expected games while games stay
    queued is slow, and ``IDLE_WINDOWS`` slow windows in a row warn. A rate
    window lasts at least ``window_s`` and until it expects
    ``RATE_MIN_GAMES`` games, so long games are not judged in windows where
    none would finish.

    ``cpu`` (for example :meth:`CpuSampler.sample`) is sampled once a
    window; warnings quote its latest value. ``on_warning`` receives each
    warning as it happens (:func:`warning_sink` writes it to disk at once);
    ``tick`` also returns it.
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
