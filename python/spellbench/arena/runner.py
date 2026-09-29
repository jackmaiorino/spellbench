"""Tournament runner, protocol v2: one run's commitment, preflight, schedule, games and publish (spec 11).

A run plays the round robin of ``schedule.schedule`` under one run secret
(spec 11.6): ``game_index`` is a game's position in the schedule, its
``game_id`` is the opaque id derived from the secret, and so are its game
secret and both agent seeds. The two games of a seat-swapped pair get
independent secrets; there is no v1 seed schedule any more. The manifest
reveals the run secret when the run ends, whatever its status, so anyone can
recompute every id, secret and seed and rerun the schedule.

``run_tournament`` works in this order (spec 11.1, 11.6; Decisions 3, 6, 9):

1. refuse unvetted subprocess entries (``manifest.isolation_refusals``, spec
   11.7, R3-9) before any process starts or anything is written;
2. resolve the executed config and the registry entries (a checkpoint is
   hashed at its resolved path), and fix the worker count: the allocation's,
   capped by the games the declared cores allow at once (spec 11.4, R3-24);
3. preflight (``schedule.preflight``) with a fresh ``EnginePin``: a config
   error stops the run with nothing written;
4. prepare the run directory, which may already hold this run's commitment;
5. write ``COMMITMENT.json``, or check that the one present names this run's
   commitment, benchmark and run label (spec 11.6, R3-30);
6. write ``config.json``, ``registry.json`` and an empty ``matches.jsonl``;
7. play the schedule through :func:`play_games` (``executor.execute``:
   results in schedule order, and a live-validation violation ends the run
   at that game, Decision 6), checking each game's engine identity against
   the preflight pin before its row is appended (R3-5);
8. publish the leaderboard, then ``manifest.json`` last. The status, the
   validator verdict and the rated rule come from the rows actually appended
   (R3-13).

Each game (:func:`play_one`) starts its own engine process and seat drivers
and plays through ``host.game.play_game``, which routes, validates, keeps the
clocks and adjudicates forfeits, halts, caps and stalling (spec 11.2 to 11.5).
An engine that cannot start or answer ``hello`` halts only its game (spec
11.5, R3-23); an engine whose identity drifted from preflight aborts the run
(R3-5).

Once the commitment is written, an interrupt or an error (Ctrl+C included)
still publishes the run, with the games recorded so far and the revealed run
secret, as ``aborted`` unless every game was recorded (R3-13), and is then
raised again (spec 11.6: every committed run is published). Writing the data files, recording a game and publishing
run inside :func:`deferred_interrupts`, so a Ctrl+C there waits until those
files, that row or the manifest are written (R3-31).

Worker processes are spawned, so a script calling :func:`run_tournament` with
more than one worker must do so under ``if __name__ == "__main__":``.
"""

from __future__ import annotations

import contextlib
import dataclasses
import functools
import signal
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence

from ..digests import GameDigest
from ..errors import PeerTimeoutError, ProtocolError, RemoteError, TransportError, ValidationError
from ..host.engine_process import EngineProcess
from ..host.game import GameResult, play_game
from ..host.setup import GameSetup
from ..messages import EngineIdentity, ResetRequest
from ..run_secret import RunSecret
from . import leaderboard, registry, store
from .config import BotSpec, TournamentConfig, TournamentError  # re-exported
from .drivers import make_driver
from .executor import ExecutionResult, GameOutcome, execute
from .ledger import Adjudication, LastSelection, LedgerRow, LedgerSeat
from .machine import usable_cpus
from .manifest import (
    CommitmentProof,
    EngineFile,
    commitment_record,
    information_rules,
    isolation_refusals,
    manifest_body,
    run_status,
)
from .registry import RegistryEntry
from .schedule import EnginePin, GameContext, RunSetup, game_setup, preflight, schedule
from .throughput import Allocation, IdleMonitor, resource_bound

__all__ = [
    "BotSpec",
    "TournamentConfig",
    "TournamentError",
    "TournamentSummary",
    "deferred_interrupts",
    "executed_config",
    "play_games",
    "play_one",
    "registry_entries",
    "run_tournament",
]

# A key one of two documents lacks.
_ABSENT = object()


@dataclass(frozen=True)
class TournamentSummary:
    tournament_dir: Path
    games_total: int
    games_rated: int
    games_truncated: int
    games_halted: int
    games_forfeit: int
    leaderboard_status: str
    status: str
    rated: bool
    manifest: dict


@contextlib.contextmanager
def deferred_interrupts() -> Iterator[None]:
    """Hold back Ctrl+C (SIGINT) while the body runs, then deliver it (R3-31).

    While a run records a game or publishes its manifest, an interrupt would
    leave the ledger and the manifest disagreeing, or the run without a
    manifest. The handler installed here only records the signal. On exit the
    previous handler is restored and, if a signal arrived meanwhile and the
    body completed, the signal is delivered to it once: Python's default
    handler raises ``KeyboardInterrupt``, and a process that ignores SIGINT
    keeps ignoring it. A body's own exception propagates unchanged. Signal
    handlers belong to the main thread, so elsewhere this changes nothing, as
    it does when the handler in place was not set from Python.
    """
    if threading.current_thread() is not threading.main_thread() or signal.getsignal(signal.SIGINT) is None:
        yield
        return
    received: list[int] = []

    def hold(signum: int, frame: Any) -> None:
        received.append(signum)

    previous = signal.signal(signal.SIGINT, hold)
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, previous)
    if received:
        signal.raise_signal(signal.SIGINT)


def executed_config(config: TournamentConfig, resolve: Callable[[str], str]) -> TournamentConfig:
    """``config`` with every command part and checkpoint path passed through ``resolve``.

    Processes start from the executed config; every published artifact records ``config`` as written.
    """
    bots = tuple(
        dataclasses.replace(
            spec,
            command=tuple(resolve(part) for part in spec.command),
            checkpoint=None if spec.checkpoint is None else resolve(spec.checkpoint),
        )
        for spec in config.bots
    )
    return dataclasses.replace(config, engine_command=tuple(resolve(part) for part in config.engine_command), bots=bots)


def registry_entries(config: TournamentConfig, executed: TournamentConfig) -> list[RegistryEntry]:
    """Each bot's registry entry in config order: the descriptor as written, a checkpoint hashed where it resolves."""
    return [
        spec.registry_entry(checkpoint_path=run_spec.checkpoint) for spec, run_spec in zip(config.bots, executed.bots)
    ]


# ---------------------------------------------------------------------------
# One game
# ---------------------------------------------------------------------------


def play_one(
    config: TournamentConfig,
    setup: RunSetup,
    context: GameContext,
    run_secret_hex: str,
    entries: dict[str, RegistryEntry],
) -> GameOutcome:
    """Play one scheduled game in its own engine process and seat drivers; returns its ledger row.

    Top level and picklable, so worker processes can run it. It pins nothing:
    the outcome carries the identity this game's engine reported, which the
    caller checks against the run's pin (R3-5). The engine gets ``startup_ms``
    to start and answer ``hello``; one that does not halts this game only
    (spec 11.5, R3-23). A host fault from ``play_game`` propagates, and every
    process is closed whatever happens.
    """
    game = game_setup(config, setup, context, RunSecret.from_hex(run_secret_hex))
    with contextlib.ExitStack() as stack:
        try:
            engine = EngineProcess(list(config.engine_command), timeout_s=config.time_control.startup_ms / 1000)
        except TransportError as exc:
            return _unstarted(config, setup, context, entries, game, exc)
        stack.callback(engine.close)
        try:
            hello = engine.hello()
        except (TransportError, ProtocolError, RemoteError) as exc:
            return _unstarted(config, setup, context, entries, game, exc)
        seats = {}
        for seat, spec in context.seat_specs:
            driver = make_driver(spec, config.time_control)
            stack.callback(driver.close)
            seats[seat] = driver
        result = play_game(game, engine=engine, seats=seats)
    return _outcome(config, setup, context, entries, result, hello.engine)


def _unstarted(
    config: TournamentConfig,
    setup: RunSetup,
    context: GameContext,
    entries: dict[str, RegistryEntry],
    game: GameSetup,
    exc: BaseException,
) -> GameOutcome:
    """The halted game of an engine that could not start or answer ``hello`` (spec 11.5: a halt, not an aborted run).

    ``host_engine_fault:timeout`` when ``hello`` ran out of ``startup_ms``, else ``transport``; no selection was
    made and nothing was counted. The digest chains the reset request this game would have sent, then the halt
    record (spec 11.8), which is what the game loop chains for an engine that dies before answering its reset.
    The preflight identity stands as the engine's, since this process named none. The exception's text, which
    may quote the engine's stderr, goes to the diagnostics only.
    """
    if isinstance(exc, PeerTimeoutError):
        fault, detail = "timeout", f"the engine did not answer hello within {config.time_control.startup_ms} ms"
    else:
        fault, detail = "transport", "the engine process could not start or answer hello"
    reason = f"host_engine_fault:{fault}"
    digest = GameDigest(_reset_request(game).to_json())
    digest.add_adjudication(classification="halted", outcome="halted", reason=reason, winner=None)
    result = GameResult(
        outcome="halted", classification="halted", winner=None, reason=reason,
        adjudication={"kind": "halt", "detail": detail}, step_count=0, decision_count=0, decisions_checked=0,
        last_selection_seat=None, game_digest=digest.value(), violation=None,
        diagnostics=(f"engine start: {type(exc).__name__}: {exc}",),
    )
    return _outcome(config, setup, context, entries, result, setup.engine)


def _reset_request(game: GameSetup) -> ResetRequest:
    """The ``reset`` a game sends (spec 9.2), as ``host.game`` builds it. The digest leaves the request id out
    (spec 11.8); ``h-2`` is the one the engine client would give it, right after ``hello``."""
    return ResetRequest(request_id="h-2", game_id=game.game_id, format=game.format, seats=game.wire_decks,
                        rules=game.rules, game_secret=game.game_secret_hex, max_decisions=game.limits.max_decisions,
                        max_steps=game.limits.max_steps)


def _outcome(
    config: TournamentConfig,
    setup: RunSetup,
    context: GameContext,
    entries: dict[str, RegistryEntry],
    result: GameResult,
    identity: EngineIdentity,
) -> GameOutcome:
    """The game's ledger row, its live-validation violation (spec 11.3) and the identity its engine reported."""
    seats = tuple(
        LedgerSeat(seat=seat, bot_id=entries[spec.name].bot_id, name=entries[spec.name].name,
                   version=entries[spec.name].version)
        for seat, spec in context.seat_specs
    )
    bot_ids = {entry.seat: entry.bot_id for entry in seats}
    last = result.last_selection_seat
    row = LedgerRow(
        game_index=context.game_index,
        game_id=context.game_id,
        matchup_index=context.matchup_index,
        pair_index=context.pair_index,
        pair_slot=context.pair_slot,
        format=config.format,
        seats=seats,
        decks=tuple(setup.decks[spec].ledger() for spec in context.decks),
        outcome=result.outcome,
        classification=result.classification,
        winner=result.winner,
        winner_bot_id=None if result.winner is None else bot_ids[result.winner],
        reason=result.reason,
        adjudication=None if result.adjudication is None else Adjudication.from_json(result.adjudication),
        step_count=result.step_count,
        decision_count=result.decision_count,
        decisions_checked=result.decisions_checked,
        last_selection=None if last is None else LastSelection(seat=last, bot_id=bot_ids[last]),
        game_digest=result.game_digest,
        engine=identity.provenance().to_json(),
    )
    violation = None
    if result.violation is not None:
        violation = {"game_index": context.game_index, "game_id": context.game_id, **result.violation}
    return GameOutcome(row=row, diagnostics=result.diagnostics, violation=violation, engine=identity.to_json())


def play_games(
    config: TournamentConfig,
    setup: RunSetup,
    contexts: Sequence[GameContext],
    *,
    run_secret: RunSecret,
    entries: dict[str, RegistryEntry],
    workers: int,
    stop_on_violation: bool = True,
    on_outcome: Callable[[GameOutcome], None] | None = None,
    monitor: IdleMonitor | None = None,
    on_warning: Callable[[str], None] | None = None,
) -> ExecutionResult:
    """Play ``contexts`` (a run's schedule, or any of its games: a qualification sample, a rerun) with ``workers``
    workers through ``executor.execute``: outcomes in the order given, the rest stopped at a violation when
    ``stop_on_violation`` (Decision 6), and any exception reported in the result's ``error`` (spec 11.3)."""
    play = functools.partial(play_one, config, setup, run_secret_hex=run_secret.hex(), entries=entries)
    return execute(contexts, play, workers=workers, stop_on_violation=stop_on_violation, on_outcome=on_outcome,
                   monitor=monitor, on_warning=on_warning)


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


def _identity_text(identity: EngineIdentity) -> str:
    return ", ".join(f"{name} {value!r}" for name, value in identity.to_json().items())


def _run_allocation(allocation: Allocation, config: TournamentConfig) -> Allocation:
    """The allocation with the workers the run plays: its own, capped by the games whose declared cores fit at once
    (spec 11.4), whatever a library caller passes; the manifest records that number (R3-24). An allocation whose
    evidence cannot hold that count (a measured one needs its fastest rung) is refused before anything starts."""
    workers = min(allocation.workers, resource_bound(usable_cpus(), config.per_game_cores()))
    try:
        return dataclasses.replace(allocation, workers=workers)
    except ValidationError as exc:
        raise TournamentError(
            f"the allocation's {allocation.workers} workers cannot run here: the declared cores fit {workers} "
            f"games at once (spec 11.4), and its record then fails: {exc}"
        ) from exc


def _publish_commitment(directory: Path, record: dict[str, Any]) -> None:
    """Write ``COMMITMENT.json``, or refuse a present one made for another run (spec 11.6, R3-30).

    A commitment published before the run (``bench commit``) is kept byte for byte; it must name this run's
    commitment, benchmark id and run label, and otherwise the run stops before writing anything else.
    """
    path = directory / store.COMMITMENT_NAME
    if not path.exists():
        store.write_json_atomic(path, record)
        return
    try:
        present = store.read_json(path)
    except store.StoreError as exc:
        raise TournamentError(f"{store.COMMITMENT_NAME} cannot be read: {exc}") from exc
    keys = sorted(set(record) | set(present))
    differing = [key for key in keys if present.get(key, _ABSENT) != record.get(key, _ABSENT)]
    if differing:
        verb = "differs" if len(differing) == 1 else "differ"
        raise TournamentError(
            f"{store.COMMITMENT_NAME} in {directory} was made for another run: its {', '.join(differing)} {verb} "
            "from this run's (spec 11.6)"
        )


def run_tournament(
    config: TournamentConfig,
    *,
    run_secret: RunSecret,
    allocation: Allocation,
    commitment_proof: CommitmentProof | None = None,
    run_label: str | None = None,
    benchmark_id: str | None = None,
    engine_files: Sequence[EngineFile] = (),
    resolve: Callable[[str], str] | None = None,
    output_dir: str | Path | None = None,
    on_game: Callable[[LedgerRow], None] | None = None,
) -> TournamentSummary:
    """Run the full schedule and publish the tournament (the module docstring gives the order).

    ``resolve`` maps each engine and bot command part and checkpoint path to the string that starts the process
    or locates the file; every published artifact records ``config`` as written. ``output_dir`` publishes into
    that directory instead of ``config.tournament_dir``. ``on_game`` sees each row once it is appended. A run is
    rated only under Decision 3 (``manifest.is_rated``): complete, a passing verdict, ``commitment_proof``, a
    measured ``allocation`` and pinned ``engine_files``.
    """
    refusals = isolation_refusals(config)
    if refusals:
        raise TournamentError("; ".join(refusals))
    executed = config if resolve is None else executed_config(config, resolve)
    entries_list = registry_entries(config, executed)
    entries = {entry.name: entry for entry in entries_list}
    allocation = _run_allocation(allocation, config)
    pin = EnginePin()
    setup = preflight(executed, run_secret, pin=pin)
    contexts = schedule(executed, run_secret)
    directory = Path(config.tournament_dir if output_dir is None else output_dir)
    store.prepare_tournament_dir(directory, allowed=(store.COMMITMENT_NAME,))
    commitment = commitment_record(run_secret=run_secret, benchmark_id=benchmark_id, run_label=run_label)
    _publish_commitment(directory, commitment)

    ledger_path = directory / store.LEDGER_NAME
    rows: list[LedgerRow] = []
    violations: list[dict[str, Any]] = []

    def record(outcome: GameOutcome) -> None:
        identity = EngineIdentity.from_json(outcome.engine)
        try:
            pin.check(identity)
        except TournamentError:
            raise TournamentError(
                f"the engine identity changed during the run: game {outcome.row.game_index}'s engine reported "
                f"{_identity_text(identity)}; preflight pinned {_identity_text(pin.identity)} (R3-5)"
            ) from None
        with deferred_interrupts():  # the file, the rows and the violations stay in step (R3-13)
            store.append_ledger_row(ledger_path, outcome.row.to_json())
            rows.append(outcome.row)
            if outcome.violation is not None:
                violations.append(outcome.violation)
            if outcome.diagnostics:
                store.append_diagnostics(directory / store.DIAGNOSTICS_NAME, outcome.row.game_id, outcome.diagnostics)
        if on_game is not None:
            on_game(outcome.row)

    # With the commitment written, every ending from here publishes the run (spec 11.6).
    error: BaseException | None = None
    try:
        with deferred_interrupts():  # the data files exist before a Ctrl+C can stop the run
            store.write_json_atomic(directory / store.CONFIG_NAME, config.to_json())
            registry.write_registry(directory / store.REGISTRY_NAME, entries_list)
            ledger_path.write_bytes(b"")  # truncate/create the ledger before the first game
        result = play_games(executed, setup, contexts, run_secret=run_secret, entries=entries,
                            workers=allocation.workers, on_outcome=record)
        error = result.error
    except BaseException as exc:  # noqa: BLE001 - published as aborted below, then raised again
        error = exc
    try:
        with deferred_interrupts():  # a Ctrl+C now waits for the manifest (R3-31)
            summary = _publish(
                directory, config=config, entries=entries_list, setup=setup, rows=rows, violations=violations,
                scheduled=len(contexts), run_secret=run_secret, commitment_proof=commitment_proof,
                allocation=allocation, engine_files=engine_files, benchmark_id=benchmark_id, run_label=run_label,
            )
    finally:
        if error is not None:
            raise error  # after the manifest: an aborting error, KeyboardInterrupt included
    return summary


def _publish(
    directory: Path,
    *,
    config: TournamentConfig,
    entries: list[RegistryEntry],
    setup: RunSetup,
    rows: Sequence[LedgerRow],
    violations: Sequence[dict[str, Any]],
    scheduled: int,
    run_secret: RunSecret,
    commitment_proof: CommitmentProof | None,
    allocation: Allocation,
    engine_files: Sequence[EngineFile],
    benchmark_id: str | None,
    run_label: str | None,
) -> TournamentSummary:
    """The leaderboard and the manifest of the rows appended, the manifest last; the status comes from those rows
    (R3-13), and the run secret is revealed whatever it is (spec 11.6)."""
    status = run_status(scheduled=scheduled, rows=len(rows), violations=len(violations))
    anchor_bot_id = next(entry.bot_id for entry in entries if entry.name == config.rating_anchor)
    document, markdown = leaderboard.build_leaderboard(
        rows, entries, anchor_bot_id=anchor_bot_id, base_seed=config.stats_seed,
        bootstrap_replicates=config.bootstrap_replicates, format=config.format,
        schema=leaderboard.LEADERBOARD_SCHEMA_V2,
    )
    store.write_json_atomic(directory / store.LEADERBOARD_JSON_NAME, document)
    store.write_bytes_atomic(directory / store.LEADERBOARD_MD_NAME, markdown.encode("utf-8"))
    body = manifest_body(
        config=config, entries=entries, anchor_bot_id=anchor_bot_id, engine=setup.engine, profile=setup.profile,
        protocol_minor=setup.hello.protocol_minor,
        info_rules=information_rules(setup.rules, setup.profile, setup.native_id_extensions), rows=rows,
        violations=violations, scheduled=scheduled, leaderboard_status=document["status"], status=status,
        benchmark_id=benchmark_id, run_label=run_label, run_secret=run_secret, commitment_proof=commitment_proof,
        allocation=allocation, engine_files=engine_files,
    )
    names = (store.COMMITMENT_NAME, *store.DATA_FILE_NAMES)  # the commitment first
    body["files"] = [store.file_entry(directory / name, name) for name in names]
    store.publish_manifest(directory, body)
    games = body["games"]
    return TournamentSummary(
        tournament_dir=directory,
        games_total=games["total"],
        games_rated=games["natural"] + games["forfeit"],
        games_truncated=games["truncated"],
        games_halted=games["halted"],
        games_forfeit=games["forfeit"],
        leaderboard_status=document["status"],
        status=status,
        rated=body["run"]["rated"],
        manifest=body,
    )
