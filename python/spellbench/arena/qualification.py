"""Planning an allocation before a run's first game (COMPUTE-POLICY.md items 1 to 5; ARTIFACT-LAW.md clause 1).

- Qualification plays games sampled across the schedule (``sample``, for
  example one game of each matchup in turn: :func:`sample_order`), never
  repeats of one game. ``play(workers, indices)`` plays the given games with
  that many workers and reports each game's own time, digest and ledger
  bytes (``PlayedGame``).
- The current rules are this module's constants (:func:`current_rules`);
  each allocation records the rules it was planned under, and is checked
  against those, so tests that change a rule patch it here.
- A run is substantial when its projected serial time reaches
  ``SUBSTANTIAL_RUN_SECONDS`` and its scaling comparison fits the
  budget: every rung of 1, ``bound // 2`` and ``bound``
  workers plays the same ``QUALIFY_GAMES_PER_WORKER * bound`` games, at
  most ``QUALIFY_BUDGET_PERCENT`` percent of the serial schedule at ideal
  scaling, because qualification counts toward the time to a completed
  result. The probe plays those games with one worker and is the first
  rung. The fastest rung by busy time wins (``workers * games / summed game
  seconds``; on identical games the spread in game lengths cancels, where a
  batch's wall time is dominated by its slowest games), the fewer workers on
  a tie. A substantial run needs a ``Placement`` naming every machine with a
  disposition. Outputs that change with the worker count are refused, even
  beside games whose outputs change on every replay (bots that read the
  clock), which are recorded rather than refused.
- Every other run is small: after a short probe it keeps its configured
  workers (within the declared cores and the game count), and after the run
  one scheduled game is replayed serially (:func:`spot_check_game`,
  ``Allocation.with_spot_check``); only a passed spot check makes it
  ratable (Decision 3).
- With an evidence file, a qualification is recorded locally and reused by a
  later launch under the same rules on the same host, cores, cores per
  game, worker bound, hardware and workload whose probe would play the
  same games, for half to twice as many games in the same size class; a
  reuse never carries a spot check forward.
- The allocation carries the machine's facts and a byte budget: ledger rows
  projected from the probe plus the pinned files, under a cap. A launch that
  would leave less than ``RESERVE_BYTES`` free on the run or pin volume is
  refused, before the first game and again after the probe.
"""

from __future__ import annotations

import hashlib
import math
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ..errors import ProtocolError, ValidationError
from ..wire import canonical_json_dumps, strict_json_loads
from .allocation import (
    PLACEMENT_FORM, Allocation, Budget, MachineFacts, Placement, PlayedGame, QualificationRules, ThroughputError,
    Trial, exact_keys, fastest_workers, is_digest, projected_row_bytes, projected_seconds,
)
from .machine import RESERVE_BYTES, check_reserve, host_name, machine_facts, usable_cpus

# The current qualification rules (current_rules). Each allocation records the rules it was planned under and is
# checked against those, so changing one here never invalidates a published manifest; patch them here in tests.
# A run projected at this much serial time or more is substantial.
SUBSTANTIAL_RUN_SECONDS = 600
# The scaling comparison's cost at ideal scaling, as a share of the projected serial time.
QUALIFY_BUDGET_PERCENT = 12
# Games every rung plays, per worker of the top rung.
QUALIFY_GAMES_PER_WORKER = 2
# The probe of a schedule too small for a scaling comparison.
PROBE_GAMES = 2
# The worker ladder: 1 and cap // divisor for each divisor, so (2, 1) compares 1, cap // 2 and cap.
LADDER_DIVISORS = (2, 1)
# A small run spot-checks game games_total // SPOT_CHECK_DIVISOR: the middle one, played while every worker was busy.
SPOT_CHECK_DIVISOR = 2
EVIDENCE_SCHEMA = "spellbench-throughput-evidence/v1"

Play = Callable[[int, tuple[int, ...]], tuple[float, Sequence[PlayedGame]]]


def current_rules() -> QualificationRules:
    """The rules a launch plans under now, read from this module's constants at call time."""
    return QualificationRules(
        substantial_run_seconds=SUBSTANTIAL_RUN_SECONDS, budget_percent=QUALIFY_BUDGET_PERCENT,
        games_per_worker=QUALIFY_GAMES_PER_WORKER, probe_games=PROBE_GAMES, ladder_divisors=LADDER_DIVISORS,
        spot_check_divisor=SPOT_CHECK_DIVISOR,
    )


def resource_bound(cpu_count: int, per_game_cores: int) -> int:
    """Games that fit at once when each needs ``per_game_cores`` declared cores (spec 11.4); at least 1."""
    return max(1, cpu_count // max(1, per_game_cores))


def worker_ladder(cap: int) -> tuple[int, ...]:
    """The worker counts a substantial run compares under the current rules: 1, ``cap // 2`` and ``cap``."""
    return current_rules().ladder(cap)


def spot_check_game(games_total: int) -> int:
    """The scheduled game a small run planned now replays serially after it finishes (its allocation's rules
    name it too: ``Allocation.rules.spot_check_game``)."""
    return current_rules().spot_check_game(games_total)


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


def _probe_indices(rules: QualificationRules, order: tuple[int, ...], games_total: int, bound: int) -> tuple[int, ...]:
    """The games a schedule's probe plays under ``rules``, from the front of the sample."""
    return order[: rules.probe_size(games_total, bound)]


def _usable_seconds(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _combined_digest(digests: Sequence[str]) -> str:
    return "sha256:" + hashlib.sha256("".join(digest + "\n" for digest in digests).encode("ascii")).hexdigest()


def _trial(play: Play, workers: int, indices: tuple[int, ...]) -> tuple[Trial, tuple[str, ...]]:
    """Play the games once; returns the trial and the games' own digests, in order."""
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
        if not _usable_seconds(game.seconds) or not is_digest(game.digest):
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


def _games(indices: Sequence[int]) -> str:
    return f"game{'s' if len(indices) > 1 else ''} {', '.join(str(index) for index in indices)}"


def _outputs(
    play: Play, indices: tuple[int, ...], rung_digests: Sequence[tuple[str, ...]]
) -> tuple[bool, str | None]:
    """Whether the rungs' outputs agree, game by game; when they do not, replay the 1-worker rung.

    A game that differs between worker counts is tolerated only when the
    replay changes it too (its outputs change on every play, as when a bot
    reads the clock); any other difference means the worker count changed the
    results, and the run is refused.
    """
    first = rung_digests[0]
    changed = sorted({index for digests in rung_digests[1:] for index, one, other in zip(indices, first, digests)
                      if one != other})
    if not changed:
        return True, None
    _, again = _trial(play, 1, indices)
    unstable = {index for index, one, other in zip(indices, first, again) if one != other}
    stable = [index for index in changed if index not in unstable]
    if stable:
        raise ThroughputError(
            f"worker counts changed the results of identical games ({_games(stable)}) that one worker reproduces; "
            "refusing to parallelize"
        )
    return False, (
        f"{_games(changed)} differed between worker counts and changed again when one worker replayed them, so "
        "their outputs depend on something besides the worker count, such as a bot reading the clock (spec 11.4); "
        "the worker count was chosen on speed alone"
    )


def _since(clock: Callable[[], float], started: float) -> int:
    return max(0, round((clock() - started) * 1000))


def _placement_needed(projected: int) -> str:
    return f"a substantial run (projected {projected} s serial) needs a placement note: {PLACEMENT_FORM}"


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
    projected = projected_row_bytes(probe, games_total) + pinned_bytes
    cap = 2 * projected if cap_bytes is None else cap_bytes
    if projected > cap:
        raise ThroughputError(f"the run projects {projected} bytes, over its {cap}-byte cap (ARTIFACT-LAW.md clause 1)")
    return Budget(projected_bytes=projected, pinned_bytes=pinned_bytes, cap_bytes=cap)


# ---------------------------------------------------------------------------
# Evidence: a local, unhashed cache of measured allocations
# ---------------------------------------------------------------------------


def load_evidence(path: Path) -> list[Allocation]:
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
            exact_keys(record, ("schema", "allocation"), "evidence")
            allocation = Allocation.from_json(record["allocation"]) if record["schema"] == EVIDENCE_SCHEMA else None
        except ProtocolError:
            continue
        if allocation is not None and allocation.kind != "unmeasured" and not allocation.reused:
            allocations.append(allocation)
    return allocations


def record_evidence(path: Path, allocation: Allocation) -> None:
    """Append one allocation to a local evidence file."""
    line = canonical_json_dumps({"schema": EVIDENCE_SCHEMA, "allocation": allocation.to_json()}) + b"\n"
    try:
        with open(path, "ab") as handle:
            handle.write(line)
    except OSError as exc:
        raise ThroughputError(f"cannot record the throughput evidence in {path}: {exc}") from exc


def _ensure_writable(path: Path) -> None:
    """Open the evidence file for appending before any game plays, so a measurement is never lost to it."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "ab"):
            pass
    except OSError as exc:
        raise ThroughputError(f"cannot write the throughput evidence {path}: {exc}") from exc


def _worker_bound(allocation: Allocation) -> int:
    """The worker bound a measured allocation was planned under: its top rung, or a small run's workers."""
    return max(trial.workers for trial in allocation.trials) if allocation.trials else allocation.workers


def _hardware(machine: MachineFacts) -> tuple[int | None, tuple[str, ...]]:
    return machine.memory_bytes, machine.gpus


def _prior_allocation(
    path: Path, *, host: str, cpu_count: int, per_game_cores: int, workload: str, bound: int, games_total: int,
    machine: MachineFacts, probe_indices: tuple[int, ...], rules: QualificationRules,
) -> Allocation | None:
    """The newest recorded allocation this schedule may reuse.

    The same rules, host, cores, cores per game, workload, worker bound and
    hardware; a probe of exactly the games this schedule's own probe would
    play; half to twice as many games; and the size class this schedule
    gets from its own projection (that identical probe's pace, its own game
    count).
    """
    key = (rules, host, cpu_count, per_game_cores, workload, bound, _hardware(machine))

    def compatible(prior: Allocation) -> bool:
        assert prior.probe is not None and prior.games_total is not None and prior.machine is not None
        return (
            (prior.rules, prior.host, prior.cpu_count, prior.per_game_cores, prior.workload, _worker_bound(prior),
             _hardware(prior.machine)) == key
            and prior.probe.indices == probe_indices
            and prior.games_total <= 2 * games_total
            and games_total <= 2 * prior.games_total
            and rules.size_class(prior.probe, games_total, bound) == prior.kind
        )

    matches = [prior for prior in load_evidence(path) if compatible(prior)]
    return matches[-1] if matches else None


def _reused(
    prior: Allocation, *, games_total: int, placement: Placement | None, machine: MachineFacts, pinned_bytes: int,
    cap_bytes: int | None,
) -> Allocation:
    """``prior``'s measurement for this run (under the same rules): this schedule's projection, budget, machine
    and placement, and no spot check (a small run's spot check is its own)."""
    assert prior.probe is not None
    projected = projected_seconds(prior.probe, games_total)
    if prior.kind == "substantial" and placement is None:
        raise ThroughputError(_placement_needed(projected))
    budget = _budget(prior.probe, games_total, pinned_bytes, cap_bytes)
    check_reserve(machine, budget.projected_bytes)
    return replace(prior, games_total=games_total, projected_serial_seconds=projected, placement=placement,
                   machine=machine, budget=budget, spot_check=None, reused=True)


def plan_allocation(
    *,
    games_total: int,
    cap: int,
    per_game_cores: int,
    play: Play,
    placement: Placement | str | None,
    cpu_count: int | None = None,
    host: str | None = None,
    sample: Sequence[int] | None = None,
    workload: str | None = None,
    evidence: Path | None = None,
    machine: MachineFacts | None = None,
    volumes: Mapping[str, Path] | None = None,
    pinned_bytes: int = 0,
    cap_bytes: int | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> Allocation:
    """Choose how many games run at once, and record why.

    ``play(workers, indices)`` plays the scheduled games at those positions
    with ``workers`` workers and returns ``(wall seconds, one PlayedGame per
    index, in order)``. Every call in one qualification uses the same
    throwaway secret, so the rungs play identical games; each game's digest
    covers exactly the ledger row the run would hash, and its time includes
    serialization and storage. ``sample`` orders every scheduled game
    (default: schedule order); qualification takes games from its front.
    ``placement`` is a ``Placement`` or its text; a substantial run needs
    one. ``machine`` (``machine_facts``), or else ``volumes`` to measure,
    must cover the ``run_dir`` and ``pin_root`` volumes: each keeps
    ``RESERVE_BYTES`` free after the projected bytes (the probe's rows
    scaled to the schedule plus ``pinned_bytes``, under ``cap_bytes``,
    default twice the projection). With ``evidence`` (a local file, never
    published) and ``workload`` (:func:`workload_id`), a compatible earlier
    measurement is reused, and a fresh one is appended. ``clock`` times the
    qualification. Every input is checked before the first game plays; an
    empty schedule is refused.
    """
    if type(games_total) is not int or games_total < 1:
        raise ThroughputError(f"the schedule has no games to qualify (games_total={games_total!r})")
    cpu = usable_cpus(cpu_count)
    for label, value in (("cap", cap), ("per_game_cores", per_game_cores), ("cpu_count", cpu)):
        if type(value) is not int or value < 1:
            raise ThroughputError(f"{label}: must be a positive integer, got {value!r}")
    machine_name = host_name(host)
    if type(machine_name) is not str or not machine_name.strip():
        raise ThroughputError("host: must be a nonblank string")
    if workload is not None and not is_digest(workload):
        raise ThroughputError('workload: must be "sha256:" and 64 lowercase hex digits (see workload_id)')
    if evidence is not None and workload is None:
        raise ThroughputError("reusing throughput evidence needs the workload it was measured on")
    for label, value in (("pinned_bytes", pinned_bytes), ("cap_bytes", 0 if cap_bytes is None else cap_bytes)):
        if type(value) is not int or value < 0:
            raise ThroughputError(f"{label}: must be a non-negative integer, got {value!r}")
    order = _sample(sample, games_total)
    note = _placement(placement)
    rules = current_rules()
    if machine is None:
        if volumes is None:
            raise ThroughputError(f"the {RESERVE_BYTES // 2**30} GiB reserve check needs the run_dir and pin_root "
                                  "volumes, or their machine facts")
        machine = machine_facts(volumes)
    if not isinstance(machine, MachineFacts):
        raise ThroughputError("machine: must be MachineFacts (see machine_facts)")
    check_reserve(machine, 0)
    # More workers than games is never useful (COMPUTE-POLICY.md item 2).
    bound = min(cap, resource_bound(cpu, per_game_cores), games_total)
    indices = _probe_indices(rules, order, games_total, bound)
    if evidence is not None:
        assert workload is not None
        evidence = Path(evidence)
        _ensure_writable(evidence)
        prior = _prior_allocation(evidence, host=machine_name, cpu_count=cpu, per_game_cores=per_game_cores,
                                  workload=workload, bound=bound, games_total=games_total, machine=machine,
                                  probe_indices=indices, rules=rules)
        if prior is not None:
            return _reused(prior, games_total=games_total, placement=note, machine=machine, pinned_bytes=pinned_bytes,
                           cap_bytes=cap_bytes)
    started = clock()
    probe, probe_digests = _trial(play, 1, indices)
    projected = projected_seconds(probe, games_total)
    budget = _budget(probe, games_total, pinned_bytes, cap_bytes)
    check_reserve(machine, budget.projected_bytes)
    common: dict[str, Any] = dict(
        host=machine_name, cpu_count=cpu, per_game_cores=per_game_cores, games_total=games_total, probe=probe,
        projected_serial_seconds=projected, rules=rules, placement=note, workload=workload,
        machine=machine, budget=budget,
    )
    if rules.size_class(probe, games_total, bound) == "small":
        allocation = Allocation(kind="small", workers=bound, qualification_seconds_milli=_since(clock, started), **common)
    else:
        if note is None:
            raise ThroughputError(_placement_needed(projected))
        trials, rung_digests = [probe], [probe_digests]
        for workers in rules.ladder(bound)[1:]:
            trial, digests = _trial(play, workers, indices)
            trials.append(trial)
            rung_digests.append(digests)
        identical, outputs_note = _outputs(play, indices, rung_digests)
        allocation = Allocation(kind="substantial", workers=fastest_workers(trials), trials=tuple(trials),
                                outputs_identical=identical, outputs_note=outputs_note,
                                qualification_seconds_milli=_since(clock, started), **common)
    if evidence is not None:
        record_evidence(evidence, allocation)
    return allocation
