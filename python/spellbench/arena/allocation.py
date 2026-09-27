"""The allocation record: how many games a run plays at once, and the evidence for it.

:meth:`Allocation.to_json` is the manifest's ``allocation`` block. Every
record validates on construction, so :meth:`Allocation.from_json` and direct
construction share one rule set: an allocation cannot claim a kind, a worker
count, a projection or a verdict that its own evidence does not support. The
rules it is checked against live here too (the worker ladder, the
comparison's budget, the ranking by busy time, the spot-check game);
:mod:`.qualification` plans allocations under them.

Trials, machine facts and spot checks are wall-clock evidence: they live only
in the manifest's ``allocation`` block and the local evidence file, never in
hashed data files.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from fractions import Fraction
from typing import Any, Sequence

from ..errors import ValidationError

# Games every rung plays, per worker of the top rung.
QUALIFY_GAMES_PER_WORKER = 2
# The scaling comparison's cost at ideal scaling, as a share of the projected serial time.
QUALIFY_BUDGET_PERCENT = 12
ALLOCATION_KINDS = ("small", "substantial", "unmeasured")
# The placements COMPUTE-POLICY.md item 1 names: the operator's main PC, HaleysPC and RunPod.
PLACEMENT_MACHINES = ("main-pc", "haleyspc", "runpod")
PLACEMENT_DISPOSITIONS = ("used", "unavailable", "slower", "not_authorized")
# The target volumes whose free space a run records and keeps above the reserve (ARTIFACT-LAW.md clause 1).
VOLUME_ROLES = ("pin_root", "run_dir")

_MAX_INT = (1 << 53) - 1
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_ROLE = re.compile(r"[a-z][a-z0-9_]*")
_PLACEMENT_ITEM = re.compile(r"\s*([A-Za-z][A-Za-z0-9-]*)\s*=\s*([a-z_]+)\s*:\s*(.*\S)\s*")
PLACEMENT_FORM = (
    "a placement names each of main-pc, haleyspc and runpod once, as '<machine>=<disposition>: <reason>' "
    f"separated by ';', each disposition one of {', '.join(PLACEMENT_DISPOSITIONS)} and at least one used, for "
    "example 'main-pc=used: fastest measured; haleyspc=slower: half the speed per game; runpod=not_authorized: "
    "no spending authority' (COMPUTE-POLICY.md item 1)"
)
_TRIAL_KEYS = ("workers", "games", "indices", "seconds_milli", "busy_milli", "row_bytes", "outputs_digest")
_SPOT_CHECK_KEYS = ("game_index", "recorded_digest", "replayed_digest", "passed")
_ALLOCATION_KEYS = (
    "kind", "label", "workers", "host", "cpu_count", "per_game_cores", "games_total", "substantial_run_seconds",
    "probe", "trials", "projected_serial_seconds", "placement", "outputs_identical", "outputs_note", "spot_check",
    "qualification_seconds_milli", "workload", "reused", "machine", "budget",
)


class ThroughputError(Exception):
    """The launch guard refuses the run before its first game."""


def exact_keys(value: dict[str, Any], keys: Sequence[str], context: str) -> None:
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


def is_digest(value: Any) -> bool:
    """Whether ``value`` is ``"sha256:"`` and 64 lowercase hex digits."""
    return type(value) is str and _DIGEST.fullmatch(value) is not None


# ---------------------------------------------------------------------------
# The rules an allocation follows
# ---------------------------------------------------------------------------


def resource_bound(cpu_count: int, per_game_cores: int) -> int:
    """Games that fit at once when each needs ``per_game_cores`` declared cores (spec 11.4); at least 1."""
    return max(1, cpu_count // max(1, per_game_cores))


def worker_ladder(cap: int) -> tuple[int, ...]:
    """The worker counts a substantial run compares: 1, ``cap // 2`` and ``cap``, without repeats."""
    return tuple(sorted({1, max(1, cap // 2), max(1, cap)}))


def ladder_fits(games_total: int, bound: int) -> bool:
    """Whether the scaling comparison fits: ``QUALIFY_GAMES_PER_WORKER`` games per top-rung worker on every rung,
    costing at most ``QUALIFY_BUDGET_PERCENT`` percent of the serial schedule at ideal scaling (the time per game
    cancels, so this depends on the counts alone)."""
    games = QUALIFY_GAMES_PER_WORKER * bound
    cost = games * sum(Fraction(1, workers) for workers in worker_ladder(bound))
    return games <= games_total and cost * 100 <= games_total * QUALIFY_BUDGET_PERCENT


def projected_seconds(probe: Trial, games_total: int) -> int:
    """The serial time of ``games_total`` games at the 1-worker probe's pace, in whole seconds, rounded up."""
    return -(-probe.seconds_milli * games_total // (1000 * probe.games))


def projected_row_bytes(probe: Trial, games_total: int) -> int:
    return -(-probe.row_bytes * games_total // probe.games)


def size_class(probe: Trial, games_total: int, bound: int, substantial_run_seconds: int) -> str:
    """``substantial`` when the projection reaches ``substantial_run_seconds`` and the comparison fits, else ``small``."""
    long_enough = projected_seconds(probe, games_total) >= substantial_run_seconds
    return "substantial" if long_enough and ladder_fits(games_total, bound) else "small"


def fastest_workers(trials: Sequence[Trial]) -> int:
    """The rung with the most games per second of busy time; the fewer workers on a tie."""
    return max(trials, key=lambda trial: (trial.rate, -trial.workers)).workers


def spot_check_game(games_total: int) -> int:
    """The scheduled game a small run replays serially after it finishes: the middle one, played while every
    worker was busy."""
    return games_total // 2


# ---------------------------------------------------------------------------
# Records
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
        if not is_digest(self.outputs_digest):
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
        exact_keys(_object(value, context), _TRIAL_KEYS, context)
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
            raise ThroughputError(PLACEMENT_FORM)

    @classmethod
    def parse(cls, text: str) -> Placement:
        """Read ``'main-pc=used: why; haleyspc=slower: why; runpod=not_authorized: why'`` (the ``--placement`` text)."""
        found: dict[str, MachinePlacement] = {}
        for item in text.split(";"):
            match = _PLACEMENT_ITEM.fullmatch(item)
            machine = match.group(1).lower() if match else ""
            if match is None or machine in found:
                raise ThroughputError(PLACEMENT_FORM)
            found[machine] = MachinePlacement(machine, match.group(2), match.group(3))
        if set(found) != set(PLACEMENT_MACHINES):
            raise ThroughputError(PLACEMENT_FORM)
        return cls(tuple(found[machine] for machine in PLACEMENT_MACHINES))

    def __str__(self) -> str:
        return "; ".join(f"{entry.machine}={entry.disposition}: {entry.reason}" for entry in self.entries)

    def to_json(self) -> dict[str, Any]:
        return {entry.machine: {"disposition": entry.disposition, "reason": entry.reason} for entry in self.entries}

    @classmethod
    def from_json(cls, value: Any, context: str = "placement") -> Placement:
        exact_keys(_object(value, context), PLACEMENT_MACHINES, context)
        entries = []
        for machine in PLACEMENT_MACHINES:
            item = _object(value[machine], f"{context}.{machine}")
            exact_keys(item, ("disposition", "reason"), f"{context}.{machine}")
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

    @property
    def missing_roles(self) -> tuple[str, ...]:
        """The target volumes of ``VOLUME_ROLES`` these facts do not cover."""
        return tuple(role for role in VOLUME_ROLES if role not in dict(self.free_bytes))

    def to_json(self) -> dict[str, Any]:
        return {"memory_bytes": self.memory_bytes, "gpus": list(self.gpus), "free_bytes": dict(self.free_bytes)}

    @classmethod
    def from_json(cls, value: Any, context: str = "machine") -> MachineFacts:
        exact_keys(_object(value, context), ("memory_bytes", "gpus", "free_bytes"), context)
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
        exact_keys(_object(value, context), ("projected_bytes", "pinned_bytes", "cap_bytes"), context)
        return cls(**value)


@dataclass(frozen=True)
class SpotCheck:
    """A small run's output-identity check: one scheduled game (:func:`spot_check_game`) replayed serially after
    the run, its game digest compared with the one the run recorded."""

    game_index: int
    recorded_digest: str
    replayed_digest: str

    def __post_init__(self) -> None:
        _count(self.game_index, "spot_check.game_index")
        if not is_digest(self.recorded_digest) or not is_digest(self.replayed_digest):
            raise ValidationError('spot_check: both digests must be "sha256:" and 64 lowercase hex digits')

    @property
    def passed(self) -> bool:
        return self.recorded_digest == self.replayed_digest

    def to_json(self) -> dict[str, Any]:
        return {"game_index": self.game_index, "recorded_digest": self.recorded_digest,
                "replayed_digest": self.replayed_digest, "passed": self.passed}

    @classmethod
    def from_json(cls, value: Any, context: str = "spot_check") -> SpotCheck:
        exact_keys(_object(value, context), _SPOT_CHECK_KEYS, context)
        check = cls(game_index=value["game_index"], recorded_digest=value["recorded_digest"],
                    replayed_digest=value["replayed_digest"])
        if value["passed"] is not check.passed:
            raise ValidationError(f"{context}.passed: must say whether the two digests agree")
        return check


@dataclass(frozen=True)
class Allocation:
    """How many games a run plays at once, and the evidence for it (the manifest's ``allocation`` block).

    ``kind`` is ``substantial`` (a scaling comparison chose the workers),
    ``small`` (the schedule projected under ``substantial_run_seconds`` of
    serial time, or had too few games for the comparison, so it kept its
    configured workers and is checked by replaying one game after the run:
    ``spot_check``) or ``unmeasured`` (no guard ran). ``label`` in the JSON
    spells this out. ``games_total`` and ``projected_serial_seconds``
    describe the schedule the allocation was planned for;
    ``qualification_seconds_milli`` is the wall time the measurement took;
    ``reused`` says an earlier launch measured it, so this run spent nothing
    on it. ``outputs_note`` names games whose outputs changed between
    replays.
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
    substantial_run_seconds: int | None = None
    spot_check: SpotCheck | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "trials", tuple(self.trials))
        _check_allocation(self)

    @property
    def measured(self) -> bool:
        """Whether Decision 3 may rate a run with this allocation: a scaling comparison measured it, or it is a
        small run whose spot check passed."""
        if self.kind == "substantial":
            return True
        return self.kind == "small" and self.spot_check is not None and self.spot_check.passed

    @property
    def label(self) -> str:
        if self.kind != "small":
            return {"substantial": "substantial run, measured", "unmeasured": "unmeasured"}[self.kind]
        if self.spot_check is None:
            return "small run, not spot-checked"
        return "small run, spot-checked" if self.spot_check.passed else "small run, spot check failed"

    @property
    def qualified_rate(self) -> float | None:
        """Games per second the chosen worker count sustained in qualification; None unless substantial."""
        if self.kind != "substantial":
            return None
        chosen = next(trial for trial in self.trials if trial.workers == self.workers)
        return float(chosen.rate * 1000)

    def with_spot_check(self, game_index: int, *, recorded_digest: str, replayed_digest: str) -> Allocation:
        """This small allocation with the result of its spot check (the game at :func:`spot_check_game`)."""
        if self.kind != "small" or self.games_total is None:
            raise ThroughputError(f"only a small allocation is spot-checked; this one is {self.kind}")
        expected = spot_check_game(self.games_total)
        if game_index != expected:
            raise ThroughputError(f"a {self.games_total}-game run spot-checks game {expected}, not {game_index}")
        check = SpotCheck(game_index=game_index, recorded_digest=recorded_digest, replayed_digest=replayed_digest)
        return replace(self, spot_check=check)

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "label": self.label,
            "workers": self.workers,
            "host": self.host,
            "cpu_count": self.cpu_count,
            "per_game_cores": self.per_game_cores,
            "games_total": self.games_total,
            "substantial_run_seconds": self.substantial_run_seconds,
            "probe": None if self.probe is None else self.probe.to_json(),
            "trials": [trial.to_json() for trial in self.trials],
            "projected_serial_seconds": self.projected_serial_seconds,
            "placement": None if self.placement is None else self.placement.to_json(),
            "outputs_identical": self.outputs_identical,
            "outputs_note": self.outputs_note,
            "spot_check": None if self.spot_check is None else self.spot_check.to_json(),
            "qualification_seconds_milli": self.qualification_seconds_milli,
            "workload": self.workload,
            "reused": self.reused,
            "machine": None if self.machine is None else self.machine.to_json(),
            "budget": None if self.budget is None else self.budget.to_json(),
        }

    @classmethod
    def from_json(cls, value: Any, context: str = "allocation") -> Allocation:
        exact_keys(_object(value, context), _ALLOCATION_KEYS, context)
        fields = dict(value)
        label = fields.pop("label")
        if not isinstance(fields["trials"], list):
            raise ValidationError(f"{context}.trials: must be a list")
        parsers = {"probe": Trial.from_json, "placement": Placement.from_json, "machine": MachineFacts.from_json,
                   "budget": Budget.from_json, "spot_check": SpotCheck.from_json}
        for name, parse in parsers.items():
            if fields[name] is not None:
                fields[name] = parse(fields[name], f"{context}.{name}")
        fields["trials"] = tuple(
            Trial.from_json(item, f"{context}.trials[{index}]") for index, item in enumerate(fields["trials"])
        )
        allocation = cls(**fields)
        if label != allocation.label:
            raise ValidationError(f"{context}.label: must be {allocation.label!r}")
        return allocation

    @classmethod
    def unmeasured(
        cls, workers: int, *, cpu_count: int | None = None, per_game_cores: int = 1, host: str | None = None
    ) -> Allocation:
        """An allocation no guard measured (the library default): the run publishes as unrated."""
        from .machine import host_name, usable_cpus  # machine.py builds on this module's records

        return cls(kind="unmeasured", workers=workers, host=host_name(host), cpu_count=usable_cpus(cpu_count),
                   per_game_cores=per_game_cores)


def _check_allocation(allocation: Allocation) -> None:
    """Field types, then the evidence each kind carries, then that it follows from the rules."""
    if allocation.kind not in ALLOCATION_KINDS:
        raise ValidationError(f"allocation.kind: must be one of {list(ALLOCATION_KINDS)}")
    _count(allocation.workers, "allocation.workers", 1)
    _text(allocation.host, "allocation.host")
    _count(allocation.cpu_count, "allocation.cpu_count", 1)
    _count(allocation.per_game_cores, "allocation.per_game_cores", 1)
    records = (("probe", Trial), ("placement", Placement), ("machine", MachineFacts), ("budget", Budget),
               ("spot_check", SpotCheck))
    for name, kind in records:
        if getattr(allocation, name) is not None and not isinstance(getattr(allocation, name), kind):
            raise ValidationError(f"allocation.{name}: must be a {kind.__name__} or null")
    if not all(isinstance(trial, Trial) for trial in allocation.trials):
        raise ValidationError("allocation.trials: must hold trials")
    counts = (("projected_serial_seconds", 0), ("qualification_seconds_milli", 0), ("games_total", 1),
              ("substantial_run_seconds", 0))
    for name, minimum in counts:
        if getattr(allocation, name) is not None:
            _count(getattr(allocation, name), f"allocation.{name}", minimum)
    if allocation.outputs_identical is not None and type(allocation.outputs_identical) is not bool:
        raise ValidationError("allocation.outputs_identical: must be a boolean or null")
    if allocation.outputs_note is not None:
        _text(allocation.outputs_note, "allocation.outputs_note")
    if allocation.workload is not None and not is_digest(allocation.workload):
        raise ValidationError('allocation.workload: must be "sha256:" and 64 lowercase hex digits, or null')
    if type(allocation.reused) is not bool:
        raise ValidationError("allocation.reused: must be a boolean")
    evidence = (allocation.probe, allocation.projected_serial_seconds, allocation.outputs_identical,
                allocation.outputs_note, allocation.qualification_seconds_milli, allocation.games_total,
                allocation.machine, allocation.budget, allocation.substantial_run_seconds, allocation.spot_check)
    if allocation.kind == "unmeasured":
        if allocation.trials or allocation.reused or any(item is not None for item in evidence):
            raise ValidationError("allocation: an unmeasured allocation carries no measurement")
        return
    probe, games_total, budget, machine = allocation.probe, allocation.games_total, allocation.budget, allocation.machine
    threshold = allocation.substantial_run_seconds
    if None in (probe, games_total, budget, machine, threshold, allocation.projected_serial_seconds):
        raise ValidationError(f"allocation: a {allocation.kind} allocation needs its probe, schedule, threshold, "
                              "projection, machine and budget")
    assert probe is not None and games_total is not None and budget is not None and machine is not None
    assert threshold is not None
    if machine.missing_roles:
        raise ValidationError(f"allocation.machine: needs the free space of {', '.join(VOLUME_ROLES)}")
    if probe.workers != 1 or allocation.projected_serial_seconds != projected_seconds(probe, games_total):
        raise ValidationError("allocation: the projection must follow from the 1-worker probe and games_total")
    if budget.projected_bytes != projected_row_bytes(probe, games_total) + budget.pinned_bytes:
        raise ValidationError("allocation.budget: the projection must follow from the probe's rows and the pinned bytes")
    if allocation.kind == "small":
        if allocation.trials or allocation.outputs_identical is not None or allocation.outputs_note is not None:
            raise ValidationError("allocation: a small allocation has no scaling comparison")
        if size_class(probe, games_total, allocation.workers, threshold) != "small":
            raise ValidationError("allocation: a schedule this long qualifies, so it cannot be small")
        if allocation.spot_check is not None and allocation.spot_check.game_index != spot_check_game(games_total):
            raise ValidationError(f"allocation.spot_check: must replay game {spot_check_game(games_total)}")
        return
    trials = allocation.trials
    top = max((trial.workers for trial in trials), default=1)
    if (
        not trials
        or trials[0] != probe
        or tuple(trial.workers for trial in trials) != worker_ladder(top)
        or any(trial.indices != probe.indices for trial in trials)
        or probe.games != QUALIFY_GAMES_PER_WORKER * top
        or size_class(probe, games_total, top, threshold) != "substantial"
    ):
        raise ValidationError(
            "allocation: a substantial allocation compares 1, top // 2 and top workers on the probe's games, "
            "and its schedule must be long enough to qualify"
        )
    if allocation.placement is None or allocation.spot_check is not None:
        raise ValidationError("allocation: a substantial allocation needs its placement and has no spot check")
    if allocation.workers != fastest_workers(trials):
        raise ValidationError("allocation.workers: must be the rung with the most games per second of busy time")
    same = len({trial.outputs_digest for trial in trials}) == 1
    if allocation.outputs_identical is not same or (allocation.outputs_note is None) is not same:
        raise ValidationError(
            "allocation: outputs_identical says whether the trials' digests agree, and differing digests need a note"
        )
