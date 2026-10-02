"""Run a benchmark: a committed run with its pushed proof, or an unrated local run; reveal and rerun.

The run lands in ``<benchmark_dir>/runs/<date>[-N]/``. Its recorded config
keeps the definition's ``${NAME}`` placeholders; processes start with the
values from the environment or ``benchmarks/local.json`` (the environment
wins). An unresolved placeholder stops the run before any process starts.

A committed run (``run=<name>``) plays the secret ``bench commit`` pushed a
commitment for: this invocation takes a lock beside the secret, checks the
secret against the commitment, the placement note recorded at commit time, and
:func:`~spellbench.bench.commit.pushed_commit`, then runs with the
:class:`~spellbench.arena.manifest.CommitmentProof`. A committed run that
fails before its manifest is revealed with a fixed reason category (spec
11.6). An unrated run uses a fresh secret and no proof.

Every run is planned by the launch guard (:func:`plan_for`): the throughput
qualification samples games across the matchups, reuses the benchmark's local
evidence file while its conditions hold, projects the byte budget, and keeps
the 60 GiB reserve on the run and pin volumes (COMPUTE-POLICY, ARTIFACT-LAW
clause 1). A committed run also pins the engine command's, the subprocess bot
commands' and the checkpoints' files under ``SPELLBENCH_PIN_ROOT`` and
registers each pin live at pinning and frozen at closure, and the run tree at
its close (ARTIFACT-LAW clauses 4 and 9, R3-7); a guard failure before the
first game is revealed with reason ``guard``. The manifest's ``engine_files``
list the engine command's files on every run.

:func:`rerun_games` replays games of a published run from its revealed secret
and reports every difference from the ledger; the replay is planned by the
guard like any other launch (R3-6).
"""

from __future__ import annotations

import datetime
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from ..arena import runner, store
from ..arena.executor import GameOutcome
from ..arena.ledger import LedgerRow, parse_ledger
from ..arena.manifest import CommitmentProof, EngineFile
from ..arena.schedule import preflight, schedule
from ..arena.throughput import (
    Allocation,
    Placement,
    PlayedGame,
    ThroughputError,
    plan_allocation,
    sample_order,
    workload_id,
)
from ..arena.validate import REVEAL_NAME, validate_tournament_dir
from ..run_secret import RunSecret
from . import definition
from .commit import (
    ARTIFACT_REGISTER_NAME,
    PIN_ROOT_NAME,
    CommitError,
    load_placement,
    load_run_secret,
    pushed_commit,
    reveal_run,
    secrets_dir,
)
from .pinning import PinningError, engine_files, pin_files, register_pins, register_tree

# The local, unhashed, git-ignored throughput evidence cache of a benchmark directory (R1-6).
EVIDENCE_NAME = "throughput-evidence.jsonl"
# The local values naming the pin-catalog owner and this machine's alias in the evidence key.
ARTIFACT_OWNER_NAME = "SPELLBENCH_ARTIFACT_OWNER"
HOST_ALIAS_NAME = "SPELLBENCH_HOST_ALIAS"


@dataclass(frozen=True)
class BenchmarkRun:
    run_dir: Path
    summary: runner.TournamentSummary
    failures: tuple[str, ...]  # validate failures; empty means OK


def _parse_placement(text: str) -> Placement:
    """The placement note through Task 5's structured form, or a BenchmarkError naming it."""
    try:
        return Placement.parse(text)
    except ThroughputError as exc:
        raise definition.BenchmarkError(f"the placement note does not parse: {exc}") from exc


def run_files(config: runner.TournamentConfig) -> tuple[EngineFile, ...]:
    """The files a launch pins (ARTIFACT-LAW clause 4, R3-7).

    The engine command's files, then each subprocess bot command's, then each
    bot's checkpoint (``registry.json`` cites checkpoint hashes through bot
    ids, so a checkpoint is pinned under its own hash, not the bot's).
    """
    groups = [engine_files(config.engine_command)]
    groups.extend(engine_files(spec.command) for spec in config.bots if spec.type == "subprocess")
    groups.extend(engine_files([spec.checkpoint]) for spec in config.bots if spec.checkpoint is not None)
    return tuple(file for group in groups for file in group)


def qualification_play(
    config: runner.TournamentConfig,
) -> Callable[[int, tuple[int, ...]], tuple[float, tuple[PlayedGame, ...]]]:
    """The ``play`` callback of a launch's throughput qualification (R3-6).

    One throwaway ``RunSecret.generate()`` and one preflight, so every call in
    one qualification plays identical games. ``play(workers, indices)`` plays
    the scheduled games at those positions with ``workers`` workers through
    :func:`runner.play_games <spellbench.arena.runner.play_games>` and returns
    the wall seconds and, per game, its own seconds (arrival to arrival, so
    serialization and storage count), the ``"sha256:"`` digest of its
    canonical ledger row, and that row's ledger bytes.
    """
    secret = RunSecret.generate()
    setup = preflight(config, secret)
    contexts = schedule(config, secret)
    entries = {entry.name: entry for entry in runner.registry_entries(config, config)}

    def play(workers: int, indices: tuple[int, ...]) -> tuple[float, tuple[PlayedGame, ...]]:
        chosen = [contexts[index] for index in indices]
        started = time.monotonic()
        last = started
        games: list[PlayedGame] = []

        def record(outcome: GameOutcome) -> None:
            nonlocal last
            now = time.monotonic()
            data = store.canonical_bytes(outcome.row.to_json())
            games.append(PlayedGame(outcome.row.game_index, now - last, f"sha256:{store.sha256_hex(data)}", len(data) + 1))
            last = now

        result = runner.play_games(
            config,
            setup,
            chosen,
            run_secret=secret,
            entries=entries,
            workers=workers,
            stop_on_violation=False,
            on_outcome=record,
        )
        wall = time.monotonic() - started
        if result.stopped == "aborted":
            assert result.error is not None
            raise result.error
        return wall, tuple(games)

    return play


def plan_for(
    config: runner.TournamentConfig,
    *,
    placement: str | Placement | None,
    evidence: Path,
    volumes: Mapping[str, Path],
    files: Sequence[EngineFile] = (),
    environ: Mapping[str, str] | None = None,
) -> Allocation:
    """Plan one launch through the throughput guard (R3-6, R3-7, ARTIFACT-LAW clause 1).

    ``config`` is the executed (resolved) config; ``files`` are what the run
    pins, charged to the budget and named in the workload the evidence is
    reused under. Qualification samples the schedule across the matchups: the
    first game of each matchup in schedule order, then each matchup's second
    game, and so on, so a pool that opens with builtin against builtin still
    measures the slow bots (R3-6). ``volumes`` names the directories whose
    volumes keep the 60 GiB reserve: ``run_dir`` and, for a rated run,
    ``pin_root``. A projection past the cap, or too little free space, is a
    ``ThroughputError`` before any game.
    """
    env = os.environ if environ is None else environ
    host = env.get(HOST_ALIAS_NAME) or "local"
    cpu_count = os.cpu_count() or 1
    contexts = schedule(config, RunSecret.generate())  # the throwaway secret changes no matchup or count
    groups = [
        [context.game_index for context in contexts if context.matchup_index == matchup]
        for matchup in dict.fromkeys(context.matchup_index for context in contexts)
    ]
    workload = workload_id(
        {
            "host": host,
            "cpu_count": cpu_count,
            "per_game_cores": config.per_game_cores(),
            "engine_files": [file.to_json() for file in files],
            "config": {key: value for key, value in config.to_json().items() if key != "tournament_dir"},
        }
    )
    return plan_allocation(
        games_total=len(contexts),
        cap=config.workers,
        per_game_cores=config.per_game_cores(),
        play=qualification_play(config),
        placement=placement,
        cpu_count=cpu_count,
        host=host,
        sample=sample_order(groups),
        workload=workload,
        evidence=Path(evidence),
        volumes=volumes,
        pinned_bytes=sum(file.bytes for file in files),
    )


def _pin_values(env: Mapping[str, str], local: Mapping[str, str]) -> tuple[Path, Path, str]:
    """The pin root, the artifact-register script and the owner a rated run needs (R3-14)."""
    pin_root = env.get(PIN_ROOT_NAME) or local.get(PIN_ROOT_NAME)
    if not pin_root:
        raise definition.BenchmarkError(
            f"{PIN_ROOT_NAME} is not set (the environment or benchmarks/{definition.LOCAL_VALUES_FILE})"
        )
    register = env.get(ARTIFACT_REGISTER_NAME) or local.get(ARTIFACT_REGISTER_NAME)
    if not register or not Path(register).is_file():
        raise definition.BenchmarkError(
            f"{ARTIFACT_REGISTER_NAME} must name an existing file (the environment or "
            f"benchmarks/{definition.LOCAL_VALUES_FILE})"
        )
    owner = env.get(ARTIFACT_OWNER_NAME) or local.get(ARTIFACT_OWNER_NAME) or "spellbench"
    return Path(pin_root), Path(register), owner


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

    ``run`` names a run committed with ``bench commit`` (its placement is the
    one recorded at commit time, and ``proof`` is the commit's third-party
    timestamp reference); ``unrated`` plays a fresh local run, dated ``date``
    (YYYY-MM-DD, default today) and placed by ``placement``. ``environ``
    defaults to ``os.environ``.
    """
    # Absolute, so "." has a folder name and the parent holds local.json.
    benchmark_dir = Path(benchmark_dir).resolve()
    benchmark = definition.load_benchmark(benchmark_dir)
    env = os.environ if environ is None else environ
    values = definition.placeholder_values(
        definition.placeholder_names(benchmark),
        definition.load_local_values(benchmark_dir.parent),
        env,
    )
    if run is None and not unrated:
        raise definition.BenchmarkError("pass run=<name> for a committed run, or unrated=True for a local run")
    if run is not None and unrated:
        raise definition.BenchmarkError("run and unrated are exclusive: a committed run, or a fresh unrated one")
    if run is not None and (date is not None or placement is not None):
        raise definition.BenchmarkError("a committed run takes its date and its placement from bench commit")
    if unrated and proof is not None:
        raise definition.BenchmarkError("an unrated run takes no commitment proof")
    if run is not None:
        return _run_committed(benchmark_dir, benchmark, values, run=run, proof=proof, environ=env)
    return _run_unrated(benchmark_dir, benchmark, values, date=date, placement=placement, environ=env)


def _run_unrated(
    benchmark_dir: Path,
    benchmark: definition.Benchmark,
    values: Mapping[str, str],
    *,
    date: str | None,
    placement: str | None,
    environ: Mapping[str, str],
) -> BenchmarkRun:
    """A fresh secret, no proof, the ``placement`` argument; the runner writes the commitment before the first game."""
    if placement is not None:
        _parse_placement(placement)
    if date is None:
        date = datetime.date.today().isoformat()
    name = definition.next_run_name(benchmark_dir, date)
    run_dir = benchmark_dir / definition.RUNS_DIR / name
    config = runner.TournamentConfig.from_json(benchmark.tournament_config(f"{definition.RUNS_DIR}/{name}"))
    resolve = lambda text: definition.substitute(text, values)  # noqa: E731
    executed = runner.executed_config(config, resolve)
    allocation = plan_for(
        executed,
        placement=placement,
        evidence=benchmark_dir / EVIDENCE_NAME,
        volumes={"run_dir": benchmark_dir, "pin_root": benchmark_dir},  # an unrated run pins nothing
        files=run_files(executed),
        environ=environ,
    )
    summary = runner.run_tournament(
        config,
        run_secret=RunSecret.generate(),
        allocation=allocation,
        benchmark_id=benchmark.id,
        run_label=name,
        resolve=resolve,
        output_dir=run_dir,
        engine_files=engine_files(executed.engine_command),
    )
    return BenchmarkRun(run_dir=run_dir, summary=summary, failures=tuple(validate_tournament_dir(run_dir)))


def _reveal_reason(exc: BaseException) -> str:
    """The reveal category of a committed run that died before its manifest (a category, never text, R3-28)."""
    if isinstance(exc, KeyboardInterrupt):
        return "interrupted"
    if isinstance(exc, (ThroughputError, PinningError, definition.BenchmarkError)):
        return "guard"  # the launch guards refuse before the first game (R3-6, R3-7)
    if isinstance(exc, runner.TournamentError):
        return "preflight"  # a TournamentError before any game; a later one publishes an aborted manifest
    return "error"


def _run_committed(
    benchmark_dir: Path,
    benchmark: definition.Benchmark,
    values: Mapping[str, str],
    *,
    run: str,
    proof: str | None,
    environ: Mapping[str, str],
) -> BenchmarkRun:
    """The run committed as ``run``: its pushed secret, its recorded placement, its proof (R3-14)."""
    run_dir = benchmark_dir / definition.RUNS_DIR / run
    if not run_dir.is_dir():
        raise CommitError(f"{run_dir} is not a committed run (bench commit writes only {store.COMMITMENT_NAME} there)")
    if sorted(entry.name for entry in run_dir.iterdir()) != [store.COMMITMENT_NAME]:
        raise CommitError(f"{run_dir} is already running or finished")
    if proof is None:
        raise CommitError("a committed run needs the commitment's third-party timestamp reference (proof)")
    secrets = secrets_dir(environ, definition.load_local_values(benchmark_dir.parent))
    lock = secrets / benchmark.id / f"{run}.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise CommitError(f"{run_dir} is already running or finished") from exc
    os.close(descriptor)
    try:
        secret = load_run_secret(run_dir, benchmark_id=benchmark.id, environ=environ)
        record = store.read_json(run_dir / store.COMMITMENT_NAME)
        if secret.commitment() != record.get("commitment"):
            raise CommitError(f"the run secret does not hash to the commitment in {store.COMMITMENT_NAME}")
        placement = _parse_placement(load_placement(run_dir, benchmark_id=benchmark.id, environ=environ))
        commit = pushed_commit(run_dir)
        config = runner.TournamentConfig.from_json(benchmark.tournament_config(f"{definition.RUNS_DIR}/{run}"))
        resolve = lambda text: definition.substitute(text, values)  # noqa: E731
        local = definition.load_local_values(benchmark_dir.parent)
        try:
            # The launch guards, all before the first game: the pin values, the files to
            # pin, the throughput allocation, the pins and their live catalog rows, so a
            # crash never leaves a pin uncatalogued (R3-6, R3-7, R3-14).
            pin_root, register, owner = _pin_values(environ, local)
            executed = runner.executed_config(config, resolve)
            engine = preflight(executed, secret).engine  # the identity the pins' regen line names
            files = run_files(executed)
            allocation = plan_for(
                executed,
                placement=placement,
                evidence=benchmark_dir / EVIDENCE_NAME,
                volumes={"run_dir": benchmark_dir, "pin_root": pin_root},
                files=files,
                environ=environ,
            )
            pinned = pin_files(files, pin_root)
            register_pins(
                register,
                pinned,
                owner=owner,
                status="live",
                purpose="pinned engine and bot files of spellbench runs",
                doc=str(run_dir / store.MANIFEST_NAME),
                regen=f"build {engine.name} {engine.version} at {engine.source_revision or 'unknown'}",
                cited_by=f"{benchmark.id} run {run}",
            )
        except BaseException as exc:
            # A guard failure stops the run before the first game; the commitment is already
            # public, so this invocation, which holds the lock, publishes the reveal (spec 11.6).
            reveal_run(run_dir, benchmark_id=benchmark.id, reason=_reveal_reason(exc), environ=environ)
            raise
        try:
            summary = runner.run_tournament(
                config,
                run_secret=secret,
                allocation=allocation,
                commitment_proof=CommitmentProof(commit=commit, timestamp=proof),
                benchmark_id=benchmark.id,
                run_label=run,
                resolve=resolve,
                output_dir=run_dir,
                engine_files=engine_files(executed.engine_command),
            )
        except BaseException as exc:
            # A committed run that fails before the runner publishes a manifest is
            # revealed, in this invocation, which holds its lock (spec 11.6, R3-14).
            if not store.is_published(run_dir):
                reveal_run(run_dir, benchmark_id=benchmark.id, reason=_reveal_reason(exc), environ=environ)
            raise
        cited_by = f"{benchmark.id} run {run}"
        try:
            register_pins(
                register,
                pinned,
                owner=owner,
                status="frozen",
                purpose="pinned engine and bot files of spellbench runs",
                doc=str(run_dir / store.MANIFEST_NAME),
                regen=f"build {engine.name} {engine.version} at {engine.source_revision or 'unknown'}",
                cited_by=cited_by,
            )
        except PinningError as exc:
            # The pins are already catalogued live; a failed freeze is a warning, not a failed run.
            print(f"warning: the pins of {cited_by} were not frozen: {exc}", file=sys.stderr)
        register_tree(
            register,
            run_dir,
            owner=owner,
            status="closed",
            purpose="published run trees of spellbench benchmarks",
            doc=str(run_dir / store.MANIFEST_NAME),
            regen=f"spellbench bench rerun {run_dir}",
        )
        return BenchmarkRun(run_dir=run_dir, summary=summary, failures=tuple(validate_tournament_dir(run_dir)))
    finally:
        lock.unlink(missing_ok=True)


def _revealed_secret(run_dir: Path) -> RunSecret:
    """The run's revealed secret: the manifest's for a published run, ``REVEAL.json``'s for an aborted one."""
    if store.is_published(run_dir):
        document = store.read_json(run_dir / store.MANIFEST_NAME)
        return RunSecret.from_hex(document["secrets"]["run_secret"])
    if (run_dir / REVEAL_NAME).is_file():
        return RunSecret.from_hex(store.read_json(run_dir / REVEAL_NAME)["run_secret"])
    raise definition.BenchmarkError(f"{run_dir} holds no revealed secret (no manifest.json, no {REVEAL_NAME})")


def rerun_games(run_dir: Path, *, games: Sequence[int] | None = None, environ: Mapping[str, str] | None = None) -> list[str]:
    """Replay games of a published run from its revealed secret; one line per difference from the ledger.

    Placeholders resolve as in :func:`run_benchmark`; the schedule is rebuilt
    from the revealed secret and the chosen games (all ledger games by
    default) replay through :func:`runner.play_games <spellbench.arena.runner.play_games>`.
    A game whose outcome, reason or ``game_digest`` differs from the ledger is
    reported.
    """
    run_dir = Path(run_dir).resolve()
    benchmark_dir = run_dir.parent.parent
    benchmark = definition.load_benchmark(benchmark_dir)
    env = os.environ if environ is None else environ
    values = definition.placeholder_values(
        definition.placeholder_names(benchmark),
        definition.load_local_values(benchmark_dir.parent),
        env,
    )
    secret = _revealed_secret(run_dir)
    config = runner.TournamentConfig.from_json(benchmark.tournament_config(f"{definition.RUNS_DIR}/{run_dir.name}"))
    executed = runner.executed_config(config, lambda text: definition.substitute(text, values))
    placement: Placement | None = None
    if store.is_published(run_dir):
        document = store.read_json(run_dir / store.MANIFEST_NAME)
        if document["secrets"].get("commitment_proof") is not None:
            placement = _parse_placement(load_placement(run_dir, benchmark_id=benchmark.id, environ=env))
        else:
            placement = Allocation.from_json(document["allocation"]).placement
    # A substantial rerun is a launch like any other: the guard plans it first (R3-6).
    allocation = plan_for(
        executed,
        placement=placement,
        evidence=benchmark_dir / EVIDENCE_NAME,
        volumes={"run_dir": benchmark_dir, "pin_root": benchmark_dir},  # a rerun pins nothing
        files=run_files(executed),
        environ=env,
    )
    setup = preflight(executed, secret)
    contexts = schedule(executed, secret)
    entries = {entry.name: entry for entry in runner.registry_entries(config, executed)}
    rows: list[LedgerRow] = []
    ledger_path = run_dir / store.LEDGER_NAME
    if ledger_path.is_file():
        rows = list(parse_ledger(store.read_jsonl(ledger_path, schema=store.LEDGER_SCHEMA)))
    by_index = {row.game_index: row for row in rows}
    indices = list(games) if games is not None else sorted(by_index)
    for index in indices:
        if not 0 <= index < len(contexts) or index not in by_index:
            raise definition.BenchmarkError(f"game {index} has no ledger row in {run_dir}")
    chosen = [contexts[index] for index in indices]
    result = runner.play_games(
        executed, setup, chosen, run_secret=secret, entries=entries, workers=allocation.workers, stop_on_violation=False
    )
    if result.stopped == "aborted":
        assert result.error is not None
        raise result.error
    replayed = {outcome.row.game_index: outcome.row for outcome in result.outcomes}
    mismatches: list[str] = []
    for index in indices:
        row, again = by_index[index], replayed.get(index)
        if again is None:
            mismatches.append(f"game {index}: was not replayed")
            continue
        for field in ("outcome", "reason", "game_digest"):
            if getattr(row, field) != getattr(again, field):
                mismatches.append(
                    f"game {index}: {field} differs: the ledger has {getattr(row, field)!r}, "
                    f"the rerun {getattr(again, field)!r}"
                )
    return mismatches
