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
11.6). An unrated run uses a fresh secret and no proof. Either way the
allocation is :meth:`Allocation.unmeasured` until Task 43 wires the throughput
guard, so every run publishes as unrated until then.

:func:`rerun_games` replays games of a published run from its revealed secret
and reports every difference from the ledger.
"""

from __future__ import annotations

import datetime
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from ..arena import runner, store
from ..arena.ledger import LedgerRow, parse_ledger
from ..arena.manifest import CommitmentProof
from ..arena.schedule import preflight, schedule
from ..arena.throughput import Allocation, Placement, ThroughputError
from ..arena.validate import REVEAL_NAME, validate_tournament_dir
from ..run_secret import RunSecret
from . import definition
from .commit import CommitError, load_placement, load_run_secret, pushed_commit, reveal_run, secrets_dir


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
    return _run_unrated(benchmark_dir, benchmark, values, date=date, placement=placement)


def _run_unrated(
    benchmark_dir: Path,
    benchmark: definition.Benchmark,
    values: Mapping[str, str],
    *,
    date: str | None,
    placement: str | None,
) -> BenchmarkRun:
    """A fresh secret, no proof, the ``placement`` argument; the runner writes the commitment before the first game."""
    if placement is not None:
        _parse_placement(placement)
    if date is None:
        date = datetime.date.today().isoformat()
    name = definition.next_run_name(benchmark_dir, date)
    run_dir = benchmark_dir / definition.RUNS_DIR / name
    config = runner.TournamentConfig.from_json(benchmark.tournament_config(f"{definition.RUNS_DIR}/{name}"))
    summary = runner.run_tournament(
        config,
        run_secret=RunSecret.generate(),
        allocation=Allocation.unmeasured(benchmark.workers),
        benchmark_id=benchmark.id,
        run_label=name,
        resolve=lambda text: definition.substitute(text, values),
        output_dir=run_dir,
    )
    return BenchmarkRun(run_dir=run_dir, summary=summary, failures=tuple(validate_tournament_dir(run_dir)))


def _reveal_reason(exc: BaseException) -> str:
    """The reveal category of a committed run that died before its manifest (a category, never text, R3-28)."""
    if isinstance(exc, KeyboardInterrupt):
        return "interrupted"
    if isinstance(exc, runner.TournamentError):
        return "preflight"  # a TournamentError before any game; a later one publishes an aborted manifest
    return "error"  # Task 43 adds "guard"


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
        _parse_placement(load_placement(run_dir, benchmark_id=benchmark.id, environ=environ))
        commit = pushed_commit(run_dir)
        config = runner.TournamentConfig.from_json(benchmark.tournament_config(f"{definition.RUNS_DIR}/{run}"))
        try:
            summary = runner.run_tournament(
                config,
                run_secret=secret,
                allocation=Allocation.unmeasured(benchmark.workers),
                commitment_proof=CommitmentProof(commit=commit, timestamp=proof),
                benchmark_id=benchmark.id,
                run_label=run,
                resolve=lambda text: definition.substitute(text, values),
                output_dir=run_dir,
            )
        except BaseException as exc:
            # A committed run that fails before the runner publishes a manifest is
            # revealed, in this invocation, which holds its lock (spec 11.6, R3-14).
            if not store.is_published(run_dir):
                reveal_run(run_dir, benchmark_id=benchmark.id, reason=_reveal_reason(exc), environ=environ)
            raise
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
        executed, setup, chosen, run_secret=secret, entries=entries, workers=config.workers, stop_on_violation=False
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
