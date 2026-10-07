"""Run a benchmark, committed or unrated, and rerun a published run's games (spec 11.1, 11.6; Decisions 3, 9, 10).

A run lands in ``<benchmark_dir>/runs/<date>[-N]/``. Its recorded config keeps the definition's ``${NAME}``
placeholders; processes start with the values from the environment or ``benchmarks/local.json`` (the
environment wins). An unresolved placeholder stops the run before any process starts.

A committed run (``run=NAME``, ``proof=REF``) plays under the commitment ``bench commit`` pushed
(:mod:`.commit`). Its directory must hold only ``COMMITMENT.json``, and this invocation owns it through the lock
beside its secret (R3-14). It is played once: a run whose tournament began before is refused. The secret must hash
to the commitment, the commitment must be on ``origin``'s default branch, unchanged since its first push (R3-8),
and the benchmark folder (its runs aside) must be the one the commitment commit holds, at ``HEAD`` and in the work
tree too, so a kept secret never chooses among definitions (spec 11.6). The run publishes
``CommitmentProof(commit, proof)``. When it stops before the runner publishes its manifest, this invocation reveals
it (``REVEAL.json``, reason ``preflight``, ``guard``, ``interrupted`` or ``error``), so every committed run is
published (spec 11.6). An unrated run (``unrated=True``) plays under a fresh secret and no proof; the runner writes
its commitment before the first game.

Every launch is guarded (Decision 10; COMPUTE-POLICY.md, ARTIFACT-LAW.md clauses 1, 4 and 9): :func:`plan_for`
measures the allocation on games sampled across the matchups, reusing compatible local evidence
(``EVIDENCE_NAME``, in the benchmark's folder, git-ignored), and refuses a run that would leave less than the 60 GiB
reserve free, before the first game. A committed run also pins its engine and bot files by SHA-256 under
``SPELLBENCH_PIN_ROOT`` and registers each pin, live, with ``SPELLBENCH_ARTIFACT_REGISTER`` before its first game;
once published, its pins are registered again as frozen and its run directory as closed. A guard's refusal of a
committed run reveals it with reason ``guard``, since its commitment is already public. :func:`rerun_games` plans
its replay the same way (R3-6).
"""

from __future__ import annotations

import contextlib
import datetime
import hashlib
import json
import json
import os
import sys
import time
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

from .. import __version__
from ..arena import machine, runner, store
from ..arena.config import TournamentConfig
from ..arena.machine import DEFAULT_HOST_ALIAS, HOST_ALIAS_ENV, usable_cpus
from ..arena.manifest import CommitmentProof, EngineFile, commitment_record, isolation_refusals
from ..arena.schedule import RunSetup, preflight, schedule
from ..arena.throughput import (
    Allocation, MachineFacts, Placement, PlayedGame, ThroughputError, check_reserve, plan_allocation, resource_bound,
    sample_order, workload_id, QualificationRules,
)
from ..arena.validate import validate_tournament_dir
from ..arena.job_storage import JobStorageGuard
from ..errors import ProtocolError, RemoteError, TransportError
from ..host.engine_process import EngineProcess
from ..messages import EngineIdentity
from ..run_secret import RunSecret
from ..llm.provider import ProviderError
from ..llm.run_budget import check_hosted_budgets
from ..wire import canonical_json_dumps
from . import commit, definition, pinning
from .commit import CommitError
from .definition import BenchmarkError
from .pinning import PinningError

# A rerun compares every field of a replayed game's ledger row: the ledger is a hashed data file, so it holds no
# wall-clock value (a game is deterministic given the run secret, spec 11.6, 11.8). A game decided by a clock, a
# timeout forfeit say, may replay differently, and is then reported like any other difference.
_SHOWN_LIMIT = 160

# The local, unhashed, git-ignored throughput evidence (R1-6): a cache of measured allocations, kept in the
# benchmark's folder (for spellbench run, beside the run directory), so an unchanged launch is not measured again.
# Pruning it only costs a requalification.
EVIDENCE_NAME = "throughput-evidence.jsonl"
# The artifact catalog's owner of a rated run's pins and run directory (a local value; ARTIFACT-LAW.md clause 9).
OWNER_NAME = "SPELLBENCH_ARTIFACT_OWNER"
DEFAULT_OWNER = "spellbench"
PINS_PURPOSE = "pinned engine and bot files of spellbench runs"
RUN_PURPOSE = "a published spellbench benchmark run"


class GuardError(BenchmarkError):
    """A rated run lacks a local value the launch guard needs (``SPELLBENCH_PIN_ROOT``,
    ``SPELLBENCH_ARTIFACT_REGISTER``; Decision 10): it stops before its first game."""


# The launch guard's refusals: a committed run they stop is revealed with reason "guard" (Decision 10).
_GUARD_ERRORS = (ThroughputError, PinningError, GuardError)

Play = Callable[[int, tuple[int, ...]], tuple[float, tuple[PlayedGame, ...]]]


@dataclass(frozen=True)
class QualificationPlay:
    """A measurement and its operator-only replay record, revealed after all games exit."""

    play: Play
    finish: Callable[[], None]

    def __call__(self, workers: int, positions: tuple[int, ...]):
        return self.play(workers, positions)


# ---------------------------------------------------------------------------
# The launch guard (Decision 10)
# ---------------------------------------------------------------------------


def qualification_play(config: TournamentConfig, *, games: Sequence[int] | None = None,
                       storage_dir: Path | None = None, files: Sequence[EngineFile] | None = None,
                       job_storage: JobStorageGuard | None = None) -> QualificationPlay:
    """The ``play`` a qualification calls (``throughput.plan_allocation``).

    ``play(workers, positions)`` plays the scheduled games at those positions of the schedule (of ``games``, the
    schedule indices a launch plays, when given) with ``workers`` workers through ``runner.play_games``, and
    returns the wall seconds and one ``PlayedGame`` per position: its own time (``runner.TimedOutcome``), the
    digest of its canonical ledger row and that row's bytes, newline included. Every call plays under one
    throwaway secret (``RunSecret.generate()``), so the rungs play identical games; the one preflight runs at the
    first call, so a reused measurement starts no process. The caller samples positions across the matchups
    (:func:`plan_for`, R3-6). ``config`` is the executed config. The caller must call ``finish`` after the last
    trial exits, including on failure. It reveals the replay secret only after confirmed normal cleanup, never
    during measured games. An aborted pool leaves an explicit suppression record without a secret.
    ``REPLAY.json`` and the per-trial diagnostics are operator artifacts, outside prompts and primary digests.
    A hard process kill can prevent this final reveal; it cannot recover secrets from older qualifications.
    """
    secret = RunSecret.generate()
    files = run_files(config) if files is None else tuple(files)
    contexts = schedule(config, secret)
    chosen = contexts if games is None else [contexts[index] for index in games]
    entries = {entry.name: entry for entry in runner.registry_entries(config, config)}
    setups: list[RunSetup] = []
    stored: list[Path] = []
    trial_number = 0
    qualification_completed = 0
    trials = []
    finished = False
    cleanup_confirmed = True
    harness = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
               for path in (Path(__file__), Path(runner.__file__))}

    def play(workers: int, positions: tuple[int, ...]) -> tuple[float, tuple[PlayedGame, ...]]:
        nonlocal trial_number, cleanup_confirmed
        if finished:
            raise ThroughputError("qualification replay secret already revealed; refusing more trials")
        if not cleanup_confirmed:
            raise ThroughputError("qualification abort cleanup unconfirmed; refusing more trials")
        _hosted_budget_guard(config)
        pinning.verify_files(files)
        if not setups:
            setups.append(preflight(config, secret))
        if not stored:
            parent = None if storage_dir is None else storage_dir / ".qualification-records"
            if parent is not None:
                parent.mkdir(parents=True, exist_ok=True)
            stored.append(Path(tempfile.mkdtemp(prefix="qualification-", dir=parent)))
        trial_number += 1
        trials.append({"workers": workers, "schedule_indices": [chosen[position].game_index for position in positions]})
        ledger = stored[0] / f"trial-{trial_number}-workers-{workers}.jsonl"
        write_seconds = {}

        def record(outcome):
            nonlocal qualification_completed
            started_write = time.perf_counter()
            store.append_ledger_row(ledger, outcome.row.to_json())
            if outcome.diagnostics:
                store.append_diagnostics(stored[0] / f"trial-{trial_number}-diagnostics.jsonl",
                                         outcome.row.game_id, outcome.diagnostics)
            write_seconds[outcome.row.game_index] = time.perf_counter() - started_write
            _hosted_budget_guard(config, allow_pending=True)
            if job_storage is not None:
                qualification_completed += 1
                job_storage.reconcile_game(len(chosen), qualification_games=max(0, 32 - qualification_completed))

        cpu = machine.CpuSampler() if os.name == "nt" else None
        if cpu is not None:
            cpu.sample()
        started = time.perf_counter()
        # Aborted pools do not wait for descendants. Do not publish the secret unless normal cleanup returns.
        cleanup_confirmed = False
        result = runner.play_games(config, setups[0], [chosen[position] for position in positions],
                                   run_secret=secret, entries=entries, workers=workers, stop_on_violation=False,
                                   timed=True, on_outcome=record, launch_files=files,
                                   guard=None if job_storage is None else job_storage.check)
        cleanup_confirmed = result.stopped != "aborted"
        pinning.verify_files(files)
        wall = time.perf_counter() - started
        counts = {name: sum(outcome.row.classification == name for outcome in result.outcomes)
                  for name in ("natural", "forfeit", "halted", "truncated")}
        summary = {"workers": workers, "elapsed_seconds": wall, "terminal_counts": counts,
                   "machine_cpu_busy_share": None if cpu is None else cpu.sample(),
                   "useful_completed": counts["natural"] + counts["forfeit"],
                   "requested_games": len(positions),
                   "game_timings": [{
                       "game_index": outcome.row.game_index,
                       "matchup_index": outcome.row.matchup_index,
                       "bots": [seat.name for seat in outcome.row.seats],
                       "decks": [deck.catalog_id for deck in outcome.row.decks],
                       "classification": outcome.row.classification,
                       "elapsed_seconds": outcome.seconds,
                       "ledger_write_seconds": write_seconds[outcome.row.game_index],
                   } for outcome in result.outcomes]}
        (stored[0] / f"trial-{trial_number}-summary.json").write_text(
            json.dumps(summary, sort_keys=True) + "\n", encoding="utf-8")
        if result.error is not None:
            raise result.error
        if counts["halted"] or counts["truncated"]:
            raise ThroughputError("qualification has halted or truncated games; retained elapsed time and usage, no qualified rate")
        played = []
        for position, outcome in zip(positions, result.outcomes):
            assert isinstance(outcome, runner.TimedOutcome)
            played.append(PlayedGame(index=position, seconds=outcome.seconds + write_seconds[outcome.row.game_index],
                                     digest=runner.row_digest(outcome.row),
                                     row_bytes=len(store.canonical_bytes(outcome.row.to_json())) + 1))
        return wall, tuple(played)

    def finish() -> None:
        nonlocal finished
        finished = True
        if not stored:
            return  # Cached allocations start no games and create no replay artifacts.
        if not cleanup_confirmed:
            store.write_json_atomic(stored[0] / "FINALIZATION.json", {
                "schema": "spellbench-qualification-finalization/v1", "secret_disclosed": False,
                "reason": "abort_cleanup_unconfirmed", "trials": trials,
            })
            return
        store.write_json_atomic(stored[0] / "REPLAY.json", {
            "schema": "spellbench-qualification-replay/v1", "run_secret": secret.hex(),
            "config": config.to_json(), "files": [file.to_json() for file in files],
            "harness_files": harness, "arena_version": __version__, "trials": trials,
        })
        if job_storage is not None:
            job_storage.check()

    return QualificationPlay(play, finish)


def _hosted_budget_guard(config: TournamentConfig, *, allow_pending: bool = False) -> None:
    try:
        check_hosted_budgets(config, allow_pending=allow_pending)
    except (ProviderError, ValueError, TypeError) as exc:
        raise ThroughputError("hosted inference budget is failed, expired or unresolved; refusing further evaluation") from exc


def _completed_game_guard(config, job_storage, games_total, completed):
    _hosted_budget_guard(config, allow_pending=True)
    if job_storage is not None:
        job_storage.reconcile_game(max(0, games_total - completed))


def _job_storage(config, benchmark, environ, paths):
    if benchmark.job_storage_budget is None:
        return None
    paths = list(paths)
    for bot in config.bots:
        for index, part in enumerate(bot.command):
            for flag in ("--log-dir", "--run-budget", "--run-budget-map"):
                if part == flag and index + 1 < len(bot.command):
                    paths.append(bot.command[index + 1])
                elif part.startswith(flag + "="):
                    paths.append(part.split("=", 1)[1])
    return JobStorageGuard(benchmark.job_storage_budget, environ=environ, paths=paths)


def _distinct(files: Sequence[EngineFile]) -> tuple[EngineFile, ...]:
    """Each file once (the same name and bytes, such as the interpreter of the engine and of a bot), in order."""
    seen: set[tuple[str, str]] = set()
    kept = []
    for file in files:
        if (file.file_name, file.sha256) not in seen:
            seen.add((file.file_name, file.sha256))
            kept.append(file)
    return tuple(kept)


def _launch_files(config: TournamentConfig) -> tuple[tuple[EngineFile, ...], tuple[EngineFile, ...]]:
    """The engine command's files (a manifest's ``engine_files``) and :func:`run_files`, each file hashed once, so
    the manifest records the very bytes that were pinned."""
    engine = pinning.engine_files(config.engine_command, extra=config.evaluation_engine_inputs)
    from ..arena.snapshot import files_identity
    if config.evaluation_engine_identity is not None and files_identity(engine) != config.evaluation_engine_identity:
        raise GuardError("engine inputs changed after bench prepare; prepare and commit a new evaluation")
    commands: list[EngineFile] = []
    checkpoints: list[EngineFile] = []
    for spec in config.bots:
        if spec.type != "subprocess":
            if spec.evaluation_identity is not None:
                from .panel import bot_files
                files = bot_files(spec)
                if files_identity(files) != spec.evaluation_identity:
                    raise GuardError(f"bot {spec.name!r} inputs changed after bench prepare; prepare a new evaluation")
                commands += list(files)
            continue
        files = pinning.engine_files(spec.command, extra=(() if spec.checkpoint is None else (spec.checkpoint,)) + spec.evaluation_inputs)
        if spec.evaluation_identity is not None and files_identity(files) != spec.evaluation_identity:
            raise GuardError(f"bot {spec.name!r} inputs changed after bench prepare; prepare and commit a new evaluation")
        commands += [file for file in files if file.index < len(spec.command)]
        checkpoints += [file for file in files if file.index >= len(spec.command)]
    return engine, _distinct((*engine, *commands, *checkpoints))


def run_files(config: TournamentConfig) -> tuple[EngineFile, ...]:
    """The files a run pins, each once: the engine command's (``pinning.engine_files``), then each subprocess bot
    command's, then each bot checkpoint (ARTIFACT-LAW.md clause 4: ``registry.json`` cites checkpoint hashes
    through bot ids, R3-7). ``config`` is the executed config, its placeholders resolved."""
    return _launch_files(config)[1]


def _machine_facts(volumes: Mapping[str, Path]) -> MachineFacts:
    """This machine's memory, GPUs and free space per volume role, read through :mod:`arena.machine` at call time."""
    return machine.machine_facts(volumes, memory=machine.total_memory, gpus=machine.nvidia_gpus,
                                 disk_free=machine.free_bytes)


def _free_space(volumes: Mapping[str, Path]) -> MachineFacts:
    """The free space of each volume role, read again now."""
    return machine.machine_facts(volumes, memory=lambda: None, gpus=tuple, disk_free=machine.free_bytes)


def plan_for(
    config: TournamentConfig,
    *,
    placement: str | None,
    evidence: Path,
    volumes: Mapping[str, Path],
    files: Sequence[EngineFile] = (),
    games: Sequence[int] | None = None,
    environ: Mapping[str, str] | None = None,
    rules: QualificationRules | None = None,
    sample: Sequence[int] = (),
    job_storage: JobStorageGuard | None = None,
) -> Allocation:
    """Plan a launch's allocation before its first game (Decision 10; COMPUTE-POLICY.md; ARTIFACT-LAW.md clause 1).

    ``config`` is the executed config. Unvetted subprocess entries are refused first, as the runner refuses them,
    before any process starts (spec 11.7, R3-9). ``throughput.plan_allocation`` then measures the schedule (or the
    scheduled ``games`` a rerun replays) with :func:`qualification_play`, its sample taking each matchup's first
    game in schedule order, then each matchup's second, and so on, so a pool that opens with builtins still
    measures the slow bots (R3-6). ``placement`` is the note a substantial run needs. ``evidence`` is the local
    evidence file: a measurement of the same workload (the config minus ``tournament_dir``, the ``files``'
    SHA-256 values, the rerun's games and the arena version) on the same host, cores and hardware is reused, and a
    fresh one is recorded. The host is the alias ``SPELLBENCH_HOST_ALIAS`` in ``environ`` (default
    ``os.environ``), else ``"local"``, never the machine's name (R3-28).

    ``volumes`` names the ``run_dir`` volume (where the run lands) and, when the launch pins ``files``, the
    ``pin_root`` volume: the pinned bytes then join the budget. A launch that pins nothing checks its run volume
    in both roles. Every volume must keep ``RESERVE_BYTES`` (60 GiB) free after the projected bytes: before the
    first qualification game, after the probe, and once more, read afresh, when the plan is done. A projection
    past the cap or a breached reserve is a ``ThroughputError`` before the run's first game.
    """
    refusals = isolation_refusals(config)
    if refusals:
        raise runner.TournamentError("; ".join(refusals))
    if "run_dir" not in volumes:
        raise ThroughputError("the launch guard needs the run_dir volume (ARTIFACT-LAW.md clause 1)")
    roles = {name: Path(path) for name, path in volumes.items()}
    pinned_bytes = sum(file.bytes for file in files) if "pin_root" in roles else 0
    roles.setdefault("pin_root", roles["run_dir"])
    contexts = schedule(config, RunSecret.generate())  # the schedule's shape: its games' matchups, no process
    positions = list(range(len(contexts))) if games is None else list(games)
    matchups: dict[int, list[int]] = {}
    for position, index in enumerate(positions):
        matchups.setdefault(contexts[index].matchup_index, []).append(position)
    if any(type(index) is not int or index not in positions for index in sample) or len(set(sample)) != len(sample):
        raise ThroughputError("qualification sample must name distinct scheduled games")
    preferred = [positions.index(index) for index in sample]
    ordinary = sample_order(list(matchups.values()))
    ordered_sample = tuple(preferred + [index for index in ordinary if index not in preferred])
    environ = os.environ if environ is None else environ
    host = environ.get(HOST_ALIAS_ENV, "").strip() or DEFAULT_HOST_ALIAS
    from ..llm.run_budget import qualification_config
    shape = {key: value for key, value in qualification_config(config).items() if key != "tournament_dir"}
    identity = {"arena": __version__, "config": shape, "files": [file.to_json() for file in files],
                "games": None if games is None else positions}
    if sample:
        identity["qualification_sample"] = list(sample)
    if job_storage is not None:
        job_storage.check()
        identity["job_storage_budget"] = job_storage.settings
    workload = workload_id(identity)
    _hosted_budget_guard(config)
    measured = qualification_play(config, games=None if games is None else positions, storage_dir=roles["run_dir"],
                                  files=files, job_storage=job_storage)
    try:
        allocation = plan_allocation(
            games_total=len(positions), cap=config.workers, per_game_cores=config.per_game_cores(),
            play=measured,
            placement=placement, host=host, sample=ordered_sample, workload=workload,
            evidence=Path(evidence), machine=_machine_facts(roles), pinned_bytes=pinned_bytes,
            rules=rules,
        )
    except BaseException as failure:
        try:
            measured.finish()
        except BaseException as finalization_error:
            # Python prints notes alongside the original traceback in the operator's controller log.
            failure.add_note(f"qualification finalization failed: {type(finalization_error).__name__}: {finalization_error}")
        raise
    else:
        measured.finish()
    assert allocation.budget is not None
    # The disk may have filled while the qualification played: the reserve holds now, just before the first game.
    check_reserve(_free_space(roles), allocation.budget.projected_bytes)
    _hosted_budget_guard(config)
    if job_storage is not None:
        job_storage.check()
    return allocation


@dataclass(frozen=True)
class _Catalog:
    """Where a rated run's pins go and how the artifact catalog lists them (ARTIFACT-LAW.md clauses 4 and 9)."""

    pin_root: Path
    register: Path
    owner: str


def _catalog(environ: Mapping[str, str], local: Mapping[str, str]) -> _Catalog:
    """The rated run's local values, from the environment, then ``benchmarks/local.json`` (Decision 10); a missing
    one is a :class:`GuardError`."""
    def value(name: str) -> str | None:
        return environ.get(name) or local.get(name) or None

    where = "set it in the environment or in benchmarks/local.json"
    pin_root, register = value(commit.PIN_ROOT_NAME), value(commit.REGISTER_NAME)
    if not pin_root:
        raise GuardError(f"{commit.PIN_ROOT_NAME} is not set: a rated run pins its engine and bot files under it "
                         f"before its first game (Decision 10); {where}")
    if not register:
        raise GuardError(f"{commit.REGISTER_NAME} is not set: a rated run registers its pinned files with that "
                         f"script (ARTIFACT-LAW.md clause 9); {where}")
    if not Path(register).expanduser().is_file():
        raise GuardError(f"{commit.REGISTER_NAME} names {register}, which is not a file; {where}")
    return _Catalog(pin_root=Path(pin_root).expanduser().resolve(), register=Path(register).expanduser(),
                    owner=value(OWNER_NAME) or DEFAULT_OWNER)


def _engine_identity(config: TournamentConfig) -> EngineIdentity:
    """The identity the engine reports in ``hello`` (name, version, source revision), for its pins' catalog rows."""
    try:
        with EngineProcess(list(config.engine_command), timeout_s=config.time_control.startup_ms / 1000) as engine:
            return engine.hello().engine
    except (TransportError, ProtocolError, RemoteError) as exc:
        raise runner.TournamentError(f"the engine did not start and answer hello: {exc}") from exc


def _warn(text: str) -> None:
    print(f"warning: {text}", file=sys.stderr)


def _close_run(run_dir: Path, pins: Sequence[Path], catalog: _Catalog, *, cited_by: str, regen: str,
               failing: bool) -> None:
    """A published run's closure (ARTIFACT-LAW.md clause 9): its pins frozen, citing this run, then the run
    directory registered, closed and kept in full. A pin that stays live is a warning, since the pins are
    catalogued already; an unregistered run directory is an error, unless the run is failing already (the run's
    own exception follows). A run revealed without its manifest has no closure here."""
    if not store.is_published(run_dir):
        return
    doc = str(run_dir / store.MANIFEST_NAME)
    with runner.deferred_interrupts():
        try:
            pinning.register_pins(catalog.register, pins, owner=catalog.owner, purpose=PINS_PURPOSE, doc=doc,
                                  regen=regen, cited_by=cited_by, status=pinning.CLOSURE_STATUS)
        except PinningError as exc:
            _warn(f"the pins of {cited_by} stay catalogued as live, not {pinning.CLOSURE_STATUS}: {exc}")
        try:
            pinning.register_tree(catalog.register, run_dir, owner=catalog.owner, status="closed",
                                  purpose=RUN_PURPOSE, doc=doc, regen=f"spellbench bench rerun {run_dir}")
        except PinningError as exc:
            if not failing:
                raise
            _warn(f"the run directory of {cited_by} is not registered: {exc}")


@dataclass(frozen=True)
class BenchmarkRun:
    run_dir: Path
    summary: runner.TournamentSummary
    failures: tuple[str, ...]  # validate failures; empty means OK


def run_benchmark(
    benchmark_dir: Path,
    *,
    run: str | None = None,
    proof: str | None = None,
    unrated: bool = False,
    date: str | None = None,
    placement: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> BenchmarkRun:
    """Play one run of the benchmark in ``benchmark_dir`` and validate it.

    Either ``run`` (the name ``bench commit`` gave the run) with ``proof`` (the third-party timestamp of its pushed
    commitment), or ``unrated``, with ``date`` (YYYY-MM-DD, default today) and an optional ``placement`` note; a
    committed run uses the placement recorded at ``bench commit``. ``environ`` defaults to ``os.environ``.
    """
    if (run is not None) == bool(unrated):
        raise BenchmarkError("a benchmark run is committed (run and proof, after bench commit) or unrated")
    if run is not None:
        if date is not None or placement is not None:
            raise BenchmarkError("a committed run takes its date from its name and its placement from bench commit")
        if type(proof) is not str or not proof.strip():
            raise BenchmarkError("a committed run needs the third-party timestamp of its pushed commitment as its "
                                 "proof (spec 11.6)")
        definition.run_sort_key(run)  # a run name, never a path
    elif proof is not None:
        raise BenchmarkError("an unrated run has no commitment to prove")
    environ = os.environ if environ is None else environ
    # Absolute, so "." has a folder name and the parent holds local.json.
    benchmark_dir = Path(benchmark_dir).resolve()
    benchmark = definition.load_benchmark(benchmark_dir)
    if benchmark.opponent_panel:
        from ..arena.snapshot import contract
        config = _config(benchmark, "check")
        contract(config)
        if not config.matchups:
            raise BenchmarkError("no missing panel evaluations; use spellbench bench compose instead")
    values = definition.placeholder_values(
        definition.placeholder_names(benchmark), definition.load_local_values(benchmark_dir.parent), environ
    )

    def resolve(text: str) -> str:
        return definition.substitute(text, values)

    if run is None:
        return _unrated_run(benchmark, benchmark_dir, date=date, placement=placement, resolve=resolve,
                            environ=environ)
    return _committed_run(benchmark, benchmark_dir, run, proof=proof, environ=environ)


def _config(benchmark: definition.Benchmark, name: str) -> TournamentConfig:
    return TournamentConfig.from_json(benchmark.tournament_config(f"{definition.RUNS_DIR}/{name}"))


def _unrated_run(
    benchmark: definition.Benchmark,
    benchmark_dir: Path,
    *,
    date: str | None,
    placement: str | None,
    resolve: Callable[[str], str],
    environ: Mapping[str, str],
) -> BenchmarkRun:
    name = definition.next_run_name(benchmark_dir, datetime.date.today().isoformat() if date is None else date)
    if placement is not None:
        try:
            Placement.parse(placement)  # the launch guard plans with it (Decision 10)
        except ThroughputError as exc:
            raise BenchmarkError(f"the placement note: {exc}") from None
    config = _config(benchmark, name)
    run_dir = benchmark_dir / definition.RUNS_DIR / name
    executed = runner.executed_config(config, resolve)
    engine, files = _launch_files(executed)
    job_storage = _job_storage(executed, benchmark, environ, (benchmark_dir,))
    # Nothing is pinned: the run's volume keeps the reserve, and the files' hashes key the evidence (R1-6).
    allocation = plan_for(executed, placement=placement, evidence=benchmark_dir / EVIDENCE_NAME,
                          volumes={"run_dir": benchmark_dir}, files=files, environ=environ,
                          rules=benchmark.qualification_rules(), sample=benchmark.qualification_sample,
                          job_storage=job_storage)
    summary = runner.run_tournament(
        config, run_secret=RunSecret.generate(), allocation=allocation, run_label=name, benchmark_id=benchmark.id,
        engine_files=engine, resolve=resolve, output_dir=run_dir,
        launch_files=files,
        on_game=lambda row: _completed_game_guard(executed, job_storage, allocation.games_total, row.game_index + 1),
        guard=None if job_storage is None else job_storage.check,
    )
    return BenchmarkRun(run_dir=run_dir, summary=summary, failures=tuple(validate_tournament_dir(run_dir)))


def _holds_only_the_commitment(run_dir: Path, benchmark_id: str) -> None:
    """A committed run not yet started: its directory holds ``COMMITMENT.json`` and nothing else (R3-14)."""
    try:
        names = sorted(path.name for path in run_dir.iterdir())
    except FileNotFoundError:
        names = []
    except OSError as exc:
        raise CommitError(f"cannot read the run directory {run_dir}: {exc.strerror or exc}") from exc
    if store.COMMITMENT_NAME not in names:
        raise CommitError(f"{benchmark_id} run {run_dir.name} has no {store.COMMITMENT_NAME}: publish its commitment "
                          "with spellbench bench commit first (spec 11.6)")
    if names != [store.COMMITMENT_NAME]:
        raise CommitError(f"{benchmark_id} run {run_dir.name} is already running or finished: {run_dir} holds more "
                          f"than its {store.COMMITMENT_NAME}")


def _committed_run(
    benchmark: definition.Benchmark,
    benchmark_dir: Path,
    name: str,
    *,
    proof: str,
    environ: Mapping[str, str],
) -> BenchmarkRun:
    run_dir = benchmark_dir / definition.RUNS_DIR / name
    _holds_only_the_commitment(run_dir, benchmark.id)
    with commit.run_lock(run_dir, benchmark_id=benchmark.id, environ=environ):
        _holds_only_the_commitment(run_dir, benchmark.id)  # again, now that no other invocation can start it
        commit.check_not_started(run_dir, benchmark_id=benchmark.id, environ=environ)  # played once (spec 11.6)
        secret = commit.load_run_secret(run_dir, benchmark_id=benchmark.id, environ=environ)
        placement = commit.load_placement(run_dir, benchmark_id=benchmark.id, environ=environ)  # recorded (R3-14)
        pushed = commit.pushed_commit(run_dir)
        # The commitment fixed the benchmark (spec 11.6): the definition is read again once checked, and the run
        # plays that one.
        commit.check_definition(benchmark_dir, pushed)
        checked = definition.load_benchmark(benchmark_dir)
        local = definition.load_local_values(benchmark_dir.parent)
        values = definition.placeholder_values(definition.placeholder_names(checked), local, environ)
        config = _config(checked, name)

        def resolve(text: str) -> str:
            return definition.substitute(text, values)

        commit.mark_started(run_dir, benchmark_id=benchmark.id, environ=environ)
        # From here every ending publishes the run: a guard's refusal reveals it with reason "guard" (Decision 10).
        with _revealed_on_failure(run_dir, benchmark_id=benchmark.id, environ=environ):
            catalog = _catalog(environ, local)
            executed = runner.executed_config(config, resolve)
            engine, files = _launch_files(executed)
            job_storage = _job_storage(executed, checked, environ, (benchmark_dir, catalog.pin_root))
            # Planned before pinning, so the pins' volume keeps its reserve too (ARTIFACT-LAW.md clause 1).
            allocation = plan_for(executed, placement=placement, evidence=benchmark_dir / EVIDENCE_NAME,
                                  volumes={"run_dir": benchmark_dir, "pin_root": catalog.pin_root}, files=files,
                                  environ=environ, rules=checked.qualification_rules(), sample=checked.qualification_sample,
                                  job_storage=job_storage)
            pinning.verify_files(files)
            identity = _engine_identity(executed)
            cited_by = f"{checked.id} run {name}"
            regen = f"build {identity.name} {identity.version} at {identity.source_revision or 'unknown'}"
            # Each pin is catalogued, live, before its copy lands, so a crash never leaves a pin uncatalogued (R3-7).
            pins = pinning.pin_and_register(files, catalog.pin_root, catalog.register, owner=catalog.owner,
                                            purpose=PINS_PURPOSE, doc=str(run_dir / store.MANIFEST_NAME),
                                            regen=regen, cited_by=cited_by)
            if job_storage is not None:
                job_storage.rebase()  # the pins are setup, not the first game's growth
            try:
                summary = runner.run_tournament(
                    config, run_secret=secret, allocation=allocation,
                    commitment_proof=CommitmentProof(commit=pushed, timestamp=proof), run_label=name,
                    benchmark_id=checked.id, engine_files=engine, resolve=resolve, output_dir=run_dir,
                    launch_files=files,
                    on_game=lambda row: _completed_game_guard(executed, job_storage, allocation.games_total, row.game_index + 1),
                    guard=None if job_storage is None else job_storage.check,
                )
            except BaseException:
                _close_run(run_dir, pins, catalog, cited_by=cited_by, regen=regen, failing=True)
                raise
            _close_run(run_dir, pins, catalog, cited_by=cited_by, regen=regen, failing=False)
    return BenchmarkRun(run_dir=run_dir, summary=summary, failures=tuple(validate_tournament_dir(run_dir)))


@contextlib.contextmanager
def _revealed_on_failure(run_dir: Path, *, benchmark_id: str, environ: Mapping[str, str]) -> Iterator[None]:
    """Every committed run is published (spec 11.6): when the body stops without the runner's manifest, the run is
    revealed with its reason category (R3-28), a Ctrl+C held while ``REVEAL.json`` is written (R3-31), and the
    exception raised again. A run whose manifest was published reveals its secret there."""
    try:
        yield
    except BaseException as exc:
        if not store.is_published(run_dir):
            with runner.deferred_interrupts():
                commit.reveal_run(run_dir, benchmark_id=benchmark_id, reason=_reveal_reason(exc, run_dir),
                                  environ=environ)
        raise


def _reveal_reason(exc: BaseException, run_dir: Path) -> str:
    """The reveal's category, never the exception's text: ``interrupted`` for a Ctrl+C, ``guard`` for a launch
    guard's refusal (Decision 10), ``preflight`` for a tournament error before any game was recorded (a config
    error, spec 11.1), ``error`` otherwise."""
    if isinstance(exc, KeyboardInterrupt):
        return "interrupted"
    if isinstance(exc, _GUARD_ERRORS):
        return "guard"
    ledger = run_dir / store.LEDGER_NAME
    if isinstance(exc, runner.TournamentError) and not (ledger.is_file() and ledger.stat().st_size):
        return "preflight"
    return "error"


# ---------------------------------------------------------------------------
# bench rerun
# ---------------------------------------------------------------------------


def _placeholders(config: TournamentConfig) -> list[str]:
    """The ``${NAME}`` placeholders of a recorded config's engine and bot commands and checkpoints."""
    texts = [*config.engine_command, *config.evaluation_engine_inputs]
    for spec in config.bots:
        texts += [*spec.command, *([spec.checkpoint] if spec.checkpoint is not None else [])]
        texts += list(spec.evaluation_inputs)
    return sorted({name for text in texts for name in definition.PLACEHOLDER_PATTERN.findall(text)})


def _revealed_secret(run_dir: Path, manifest: dict[str, Any]) -> RunSecret:
    """The run secret the manifest reveals; it must hash to the manifest's commitment and be the one committed in
    ``COMMITMENT.json``, for this run (spec 11.6)."""
    secrets = manifest.get("secrets")
    try:
        secret = RunSecret.from_hex(secrets.get("run_secret") if isinstance(secrets, dict) else None)
    except ValueError:
        raise BenchmarkError(f"{store.MANIFEST_NAME} reveals no run secret (spec 11.6)") from None
    if secret.commitment() != secrets.get("commitment"):
        raise BenchmarkError(f"the run secret in {store.MANIFEST_NAME} does not hash to its commitment (spec 11.6)")
    names = manifest.get("run") if isinstance(manifest.get("run"), dict) else {}
    expected = commitment_record(run_secret=secret, benchmark_id=names.get("benchmark_id"),
                                 run_label=names.get("label"))
    try:
        committed = store.read_json(run_dir / store.COMMITMENT_NAME)
    except store.StoreError as exc:
        raise BenchmarkError(f"no readable commitment for this run: {exc}") from None
    if canonical_json_dumps(committed) != canonical_json_dumps(expected):
        raise BenchmarkError(f"the run secret in {store.MANIFEST_NAME} is not the one committed in "
                             f"{store.COMMITMENT_NAME} for this run (spec 11.6)")
    return secret


def _ledger_by_index(run_dir: Path) -> dict[int, dict[str, Any]]:
    ledger: dict[int, dict[str, Any]] = {}
    for number, row in enumerate(store.read_jsonl(run_dir / store.LEDGER_NAME), 1):
        index = row.get("game_index")
        if type(index) is not int or index in ledger:
            raise BenchmarkError(f"{store.LEDGER_NAME} line {number} has no game_index of its own: validate the run")
        ledger[index] = row
    return ledger


def _shown(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=True)
    return text if len(text) <= _SHOWN_LIMIT else text[: _SHOWN_LIMIT - 3] + "..."


def _differences(recorded: dict[str, Any], replayed: dict[str, Any]) -> list[str]:
    """Each field of a ledger row whose value differs between the ledger and the rerun (JSON values compared as
    canonical JSON, so ``true`` is not ``1``); a field only one side has differs too."""
    missing = object()
    differ = []
    for field in sorted(set(recorded) | set(replayed)):
        old, new = recorded.get(field, missing), replayed.get(field, missing)
        if old is missing or new is missing or canonical_json_dumps(old) != canonical_json_dumps(new):
            differ.append(f"{field} {'missing' if old is missing else _shown(old)} in the ledger, "
                          f"{'missing' if new is missing else _shown(new)} in the rerun")
    return differ


def _recorded_placement(run_dir: Path, manifest: dict[str, Any], environ: Mapping[str, str]) -> str | None:
    """The placement note ``bench commit`` recorded for a committed run, when this machine keeps it; else None."""
    secrets, names = manifest.get("secrets"), manifest.get("run")
    if not isinstance(secrets, dict) or secrets.get("commitment_proof") is None or not isinstance(names, dict):
        return None
    try:
        return commit.load_placement(run_dir, benchmark_id=names.get("benchmark_id"), environ=environ)
    except CommitError:
        return None


def rerun_games(
    run_dir: Path,
    *,
    games: Sequence[int] | None = None,
    placement: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> list[str]:
    """Replay games of the published run in ``run_dir`` from its revealed secret; one line per replayed game whose
    ledger row differs from the ledger's in any field (empty means every one matches).

    ``games`` are game indices (default: every game of the ledger). Placeholders resolve as in
    :func:`run_benchmark`; the schedule is rebuilt from the secret. The replay is a launch like any other
    (R3-6): :func:`plan_for` plans it, with ``placement`` or else the placement a committed run recorded at
    ``bench commit``, its evidence in the benchmark's folder. Then, after a preflight, every chosen game plays to
    its end through ``runner.play_games`` with the planned workers.
    """
    environ = os.environ if environ is None else environ
    run_dir = Path(run_dir).resolve()
    manifest = store.read_json(run_dir / store.MANIFEST_NAME)
    config = TournamentConfig.from_json(store.read_json(run_dir / store.CONFIG_NAME))
    secret = _revealed_secret(run_dir, manifest)
    ledger = _ledger_by_index(run_dir)
    chosen = list(ledger) if games is None else list(games)
    values = definition.placeholder_values(
        _placeholders(config), definition.load_local_values(run_dir.parent.parent.parent), environ
    )
    executed = runner.executed_config(config, lambda text: definition.substitute(text, values))
    contexts = schedule(executed, secret)
    for index in chosen:
        if type(index) is not int or index not in ledger or not 0 <= index < len(contexts):
            raise BenchmarkError(f"game {index!r} is not a game of the ledger of {run_dir}")
    if len(set(chosen)) != len(chosen):
        raise BenchmarkError("each game is rerun once")
    if not chosen:
        return []
    files = run_files(executed)
    allocation = plan_for(
        executed, placement=_recorded_placement(run_dir, manifest, environ) if placement is None else placement,
        evidence=run_dir.parent.parent / EVIDENCE_NAME, volumes={"run_dir": run_dir}, files=files,
        games=chosen, environ=environ,
    )
    pinning.verify_files(files)
    setup = preflight(executed, secret)
    entries = {entry.name: entry for entry in runner.registry_entries(config, executed)}
    workers = min(allocation.workers, resource_bound(usable_cpus(), config.per_game_cores()))
    result = runner.play_games(executed, setup, [contexts[index] for index in chosen], run_secret=secret,
                               entries=entries, workers=workers, stop_on_violation=False, launch_files=files)
    pinning.verify_files(files)
    if result.error is not None:
        raise result.error
    mismatches = []
    for outcome in result.outcomes:
        differ = _differences(ledger[outcome.row.game_index], outcome.row.to_json())
        if differ:
            mismatches.append(f"game {outcome.row.game_index} ({outcome.row.game_id}): {'; '.join(differ)}")
    return mismatches
