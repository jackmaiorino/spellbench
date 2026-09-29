"""Run a benchmark, committed or unrated, and rerun a published run's games (spec 11.1, 11.6; Decisions 3, 9).

A run lands in ``<benchmark_dir>/runs/<date>[-N]/``. Its recorded config keeps the definition's ``${NAME}``
placeholders; processes start with the values from the environment or ``benchmarks/local.json`` (the
environment wins). An unresolved placeholder stops the run before any process starts.

A committed run (``run=NAME``, ``proof=REF``) plays under the commitment ``bench commit`` pushed
(:mod:`.commit`). Its directory must hold only ``COMMITMENT.json``, and this invocation owns it through the lock
beside its secret (R3-14). The secret must hash to the commitment, the commitment must be in a pushed commit,
unchanged since its first push (R3-8), and the run publishes ``CommitmentProof(commit, proof)``. When it stops
before the runner publishes its manifest, this invocation reveals it (``REVEAL.json``, reason ``preflight``,
``interrupted`` or ``error``), so every committed run is published (spec 11.6). An unrated run
(``unrated=True``) plays under a fresh secret and no proof; the runner writes its commitment before the first
game.

The allocation is unmeasured until the launch guard plans it (Decision 10), so every run publishes as unrated
for now (Decision 3).
"""

from __future__ import annotations

import contextlib
import datetime
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

from ..arena import runner, store
from ..arena.config import TournamentConfig
from ..arena.machine import usable_cpus
from ..arena.manifest import CommitmentProof
from ..arena.schedule import preflight, schedule
from ..arena.throughput import Allocation, Placement, ThroughputError, resource_bound
from ..arena.validate import validate_tournament_dir
from ..run_secret import RunSecret
from . import commit, definition
from .commit import CommitError
from .definition import BenchmarkError

# The ledger fields a rerun compares with the replayed game (spec 11.8: the digest chains the whole game).
RERUN_FIELDS = ("outcome", "winner", "reason", "game_digest")


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
    values = definition.placeholder_values(
        definition.placeholder_names(benchmark), definition.load_local_values(benchmark_dir.parent), environ
    )

    def resolve(text: str) -> str:
        return definition.substitute(text, values)

    if run is None:
        return _unrated_run(benchmark, benchmark_dir, date=date, placement=placement, resolve=resolve)
    return _committed_run(benchmark, benchmark_dir, run, proof=proof, resolve=resolve, environ=environ)


def _config(benchmark: definition.Benchmark, name: str) -> TournamentConfig:
    return TournamentConfig.from_json(benchmark.tournament_config(f"{definition.RUNS_DIR}/{name}"))


def _allocation(config: TournamentConfig) -> Allocation:
    """Unmeasured until the launch guard plans the run (Decision 10); it records the cores each game declares,
    which cap the workers the runner starts (spec 11.4)."""
    return Allocation.unmeasured(config.workers, per_game_cores=config.per_game_cores())


def _unrated_run(
    benchmark: definition.Benchmark,
    benchmark_dir: Path,
    *,
    date: str | None,
    placement: str | None,
    resolve: Callable[[str], str],
) -> BenchmarkRun:
    name = definition.next_run_name(benchmark_dir, datetime.date.today().isoformat() if date is None else date)
    if placement is not None:
        try:
            Placement.parse(placement)  # the launch guard plans with it (Decision 10)
        except ThroughputError as exc:
            raise BenchmarkError(f"the placement note: {exc}") from None
    config = _config(benchmark, name)
    run_dir = benchmark_dir / definition.RUNS_DIR / name
    summary = runner.run_tournament(
        config, run_secret=RunSecret.generate(), allocation=_allocation(config), run_label=name,
        benchmark_id=benchmark.id, resolve=resolve, output_dir=run_dir,
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
    resolve: Callable[[str], str],
    environ: Mapping[str, str],
) -> BenchmarkRun:
    run_dir = benchmark_dir / definition.RUNS_DIR / name
    _holds_only_the_commitment(run_dir, benchmark.id)
    with commit.run_lock(run_dir, benchmark_id=benchmark.id, environ=environ):
        _holds_only_the_commitment(run_dir, benchmark.id)  # again, now that no other invocation can start it
        secret = commit.load_run_secret(run_dir, benchmark_id=benchmark.id, environ=environ)
        commit.load_placement(run_dir, benchmark_id=benchmark.id, environ=environ)  # the guard plans with it
        commitment_proof = CommitmentProof(commit=commit.pushed_commit(run_dir), timestamp=proof)
        config = _config(benchmark, name)
        with _revealed_on_failure(run_dir, benchmark_id=benchmark.id, environ=environ):
            summary = runner.run_tournament(
                config, run_secret=secret, allocation=_allocation(config), commitment_proof=commitment_proof,
                run_label=name, benchmark_id=benchmark.id, resolve=resolve, output_dir=run_dir,
            )
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
    """The reveal's category, never the exception's text: ``interrupted`` for a Ctrl+C, ``preflight`` for a
    tournament error before any game was recorded (a config error, spec 11.1), ``error`` otherwise."""
    if isinstance(exc, KeyboardInterrupt):
        return "interrupted"
    ledger = run_dir / store.LEDGER_NAME
    if isinstance(exc, runner.TournamentError) and not (ledger.is_file() and ledger.stat().st_size):
        return "preflight"
    return "error"


# ---------------------------------------------------------------------------
# bench rerun
# ---------------------------------------------------------------------------


def _placeholders(config: TournamentConfig) -> list[str]:
    """The ``${NAME}`` placeholders of a recorded config's engine and bot commands and checkpoints."""
    texts = [*config.engine_command]
    for spec in config.bots:
        texts += [*spec.command, *([spec.checkpoint] if spec.checkpoint is not None else [])]
    return sorted({name for text in texts for name in definition.PLACEHOLDER_PATTERN.findall(text)})


def _revealed_secret(manifest: dict[str, Any]) -> RunSecret:
    secrets = manifest.get("secrets")
    try:
        secret = RunSecret.from_hex(secrets.get("run_secret") if isinstance(secrets, dict) else None)
    except ValueError:
        raise BenchmarkError(f"{store.MANIFEST_NAME} reveals no run secret (spec 11.6)") from None
    if secret.commitment() != secrets.get("commitment"):
        raise BenchmarkError(f"the run secret in {store.MANIFEST_NAME} does not hash to its commitment (spec 11.6)")
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
    return json.dumps(value, ensure_ascii=True)


def rerun_games(
    run_dir: Path, *, games: Sequence[int] | None = None, environ: Mapping[str, str] | None = None
) -> list[str]:
    """Replay games of the published run in ``run_dir`` from its revealed secret; one line per replayed game whose
    outcome, winner, reason or ``game_digest`` differs from the ledger (empty means every one matches).

    ``games`` are game indices (default: every game of the ledger). Placeholders resolve as in
    :func:`run_benchmark`; the schedule is rebuilt from the secret, and after a preflight every chosen game plays
    to its end through ``runner.play_games``.
    """
    environ = os.environ if environ is None else environ
    run_dir = Path(run_dir).resolve()
    manifest = store.read_json(run_dir / store.MANIFEST_NAME)
    config = TournamentConfig.from_json(store.read_json(run_dir / store.CONFIG_NAME))
    secret = _revealed_secret(manifest)
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
    setup = preflight(executed, secret)
    entries = {entry.name: entry for entry in runner.registry_entries(config, executed)}
    workers = min(config.workers, resource_bound(usable_cpus(), config.per_game_cores()))
    result = runner.play_games(executed, setup, [contexts[index] for index in chosen], run_secret=secret,
                               entries=entries, workers=workers, stop_on_violation=False)
    if result.error is not None:
        raise result.error
    mismatches = []
    for outcome in result.outcomes:
        replayed, recorded = outcome.row.to_json(), ledger[outcome.row.game_index]
        differ = [
            f"{field} {_shown(recorded.get(field))} in the ledger, {_shown(replayed[field])} in the rerun"
            for field in RERUN_FIELDS
            if recorded.get(field) != replayed[field]
        ]
        if differ:
            mismatches.append(f"game {outcome.row.game_index} ({outcome.row.game_id}): {'; '.join(differ)}")
    return mismatches
