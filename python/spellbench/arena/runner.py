"""Tournament runner on protocol v2: the schedule, secrets and commitment, parallel games, the publish.

The schedule is the v1 round robin (``arena.schedule``): matchups in
``itertools.combinations_with_replacement`` order over the config's bots
(mirrors unless ``include_self_play`` is false), each matchup
``pairs_per_matchup`` seat-swapped pairs, ``game_index`` counting from 0 in
schedule order and every game's id, secret and agent seeds derived from the
run secret (spec 11.6: opaque ids; there is no v1 seed schedule).
``COMMITMENT.json`` names the run secret's commitment — plus the run's
benchmark and label — and is written, or checked against a commitment already
made for the run, before any game, so the secret a run publishes was fixed
before the first game (spec 11.6, Decision 9).

Games play through the executor's prefix rule (Decision 6): outcomes are
recorded in schedule order whatever the worker count, so the ledger is always
a contiguous prefix of the schedule; a live-validation violation ends the run
at its game (spec 11.3); any exception aborts it. Adjudication lives in
``host.game`` (forfeits, halts and the mandatory-loop draw), and the ledger
row the runner builds only repeats what the game loop ruled. An engine whose
identity drifts from the preflight's (rebuilt mid-run) aborts the tournament
(R3-5); an engine that cannot start or answer ``hello`` halts that game
instead (spec 11.5: an engine fault is a halt, not an aborted run; R3-23).

Games are independent (their own engine process, fresh seat drivers, secrets
fixed by the schedule), so ``workers`` games run concurrently in spawned
worker processes (``arena.executor``); budget ``workers`` to the host's free
cores, since the clocks of spec 11.4 are wall-clock time. Worker processes
are spawned, so a script that calls :func:`run_tournament` with ``workers >
1`` must do so under ``if __name__ == "__main__":``.

While the runner writes an aborted run's manifest, a second Ctrl+C is held
back by :func:`deferred_interrupts` and raised as ``KeyboardInterrupt`` once
the manifest is written (R3-31). ``bench/definition.py`` reads v1 names this
module no longer holds at import, so it fails with an ``AttributeError``
until Task 37 ports it; every test importing ``spellbench.bench`` is skipped
at module level meanwhile (R3-25).

With more than one worker, an :class:`~spellbench.arena.throughput.IdleMonitor`
watches the run as it plays (a substantial allocation's qualified rate, the
machine's CPU); each warning is appended to the run's unhashed
``throughput.jsonl`` and echoed to stderr as it happens, never into the
manifest's files (R3-6). After a complete run, a small allocation's
spot-check game is replayed serially and its digest compared with the
ledger's, so only a reproduced game makes the run ratable (Decision 3).
"""

from __future__ import annotations

import contextlib
import functools
import os
import signal
import sys
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, ContextManager, Iterator, Sequence

from ..digests import GameDigest
from ..errors import PeerTimeoutError, ProtocolError, RemoteError, TransportError
from ..host.engine_process import EngineProcess
from ..host.game import GameResult, play_game
from ..host.setup import GameSetup
from ..messages import PROTOCOL_MINOR, EngineIdentity, ResetRequest
from ..run_secret import RunSecret
from . import leaderboard, registry, store
from .config import BotSpec, TournamentConfig, TournamentError  # re-exported
from .drivers import make_driver
from .executor import ExecutionResult, GameOutcome, execute
from .ledger import Adjudication, LastSelection, LedgerRow, LedgerSeat
from .manifest import (
    CommitmentProof,
    EngineFile,
    commitment_record,
    information_rules,
    isolation_refusals,
    manifest_body,
    run_status,
)
from .schedule import EnginePin, GameContext, RunSetup, game_setup, preflight, schedule
from .throughput import Allocation, CpuSampler, IdleMonitor, resource_bound, warning_sink

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

# The idle monitor's warning log: local, unhashed and git-ignored, never in the manifest's files (R3-6).
THROUGHPUT_LOG_NAME = "throughput.jsonl"


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
    manifest: dict[str, Any]


def deferred_interrupts() -> ContextManager[None]:
    """Hold a second Ctrl+C back while an aborted run's manifest is written (R3-31).

    Inside the context a SIGINT is only recorded, in the main thread (elsewhere the
    context changes nothing); the previous handler is restored on exit, and a recorded
    signal is then raised as ``KeyboardInterrupt``.
    """

    @contextlib.contextmanager
    def hold() -> Iterator[None]:
        if threading.current_thread() is not threading.main_thread():
            yield
            return
        arrived: list[int] = []
        previous = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, lambda signum, frame: arrived.append(signum))
        try:
            yield
        finally:
            signal.signal(signal.SIGINT, previous)
        if arrived:
            raise KeyboardInterrupt

    return hold()


# ---------------------------------------------------------------------------
# The executed config and the registry (checkpoints hashed before any process starts)
# ---------------------------------------------------------------------------


def executed_config(config: TournamentConfig, resolve: Callable[[str], str]) -> TournamentConfig:
    """``config`` with every command part and checkpoint path passed through ``resolve``."""
    bots = tuple(
        replace(
            spec,
            command=tuple(resolve(part) for part in spec.command),
            checkpoint=None if spec.checkpoint is None else resolve(spec.checkpoint),
        )
        for spec in config.bots
    )
    return replace(config, engine_command=tuple(resolve(part) for part in config.engine_command), bots=bots)


def registry_entries(config: TournamentConfig, executed: TournamentConfig) -> list[registry.RegistryEntry]:
    """One registry entry per configured bot, in config order.

    The descriptor records the command as written; the checkpoint bytes are read at the
    executed (resolved) path, so a config error stops the run before any process starts.
    """
    return [
        spec.registry_entry(checkpoint_path=run_spec.checkpoint)
        for spec, run_spec in zip(config.bots, executed.bots)
    ]


# ---------------------------------------------------------------------------
# One game (spec 11.5; R3-23)
# ---------------------------------------------------------------------------


def _ledger_seats(
    context: GameContext, entries: dict[str, registry.RegistryEntry]
) -> tuple[LedgerSeat, LedgerSeat]:
    seats = tuple(
        LedgerSeat(seat=seat, bot_id=entries[spec.name].bot_id, name=spec.name, version=spec.version)
        for seat, spec in context.seat_specs
    )
    return (seats[0], seats[1])


def _row(
    config: TournamentConfig,
    setup: RunSetup,
    context: GameContext,
    entries: dict[str, registry.RegistryEntry],
    *,
    outcome: str,
    classification: str,
    winner: str | None,
    reason: str,
    adjudication: Adjudication | None,
    step_count: int,
    decision_count: int,
    decisions_checked: int,
    last_selection: LastSelection | None,
    game_digest: str,
    engine: EngineIdentity,
) -> LedgerRow:
    seat_specs = dict(context.seat_specs)
    winner_bot_id = None if winner is None else entries[seat_specs[winner].name].bot_id
    return LedgerRow(
        game_index=context.game_index,
        game_id=context.game_id,
        matchup_index=context.matchup_index,
        pair_index=context.pair_index,
        pair_slot=context.pair_slot,
        format=config.format,
        seats=_ledger_seats(context, entries),
        decks=(setup.decks[context.decks[0]].ledger(), setup.decks[context.decks[1]].ledger()),
        outcome=outcome,
        classification=classification,
        winner=winner,
        winner_bot_id=winner_bot_id,
        reason=reason,
        adjudication=adjudication,
        step_count=step_count,
        decision_count=decision_count,
        decisions_checked=decisions_checked,
        last_selection=last_selection,
        game_digest=game_digest,
        engine=engine.provenance().to_json(),
    )


def _engine_fault_outcome(
    config: TournamentConfig,
    setup: RunSetup,
    context: GameContext,
    bindings: GameSetup,
    entries: dict[str, registry.RegistryEntry],
    exc: BaseException,
    phase: str,
) -> GameOutcome:
    """The halted row of a game whose engine could not start or answer ``hello`` (spec 11.5, R3-23).

    The digest chains only the reset request and the halt record (no exchange was
    answered, spec 11.8); ``last_selection`` is null, the counts are 0, and the row's
    ``engine`` is the preflight identity.
    """
    if isinstance(exc, PeerTimeoutError):
        fault = "timeout"
        detail = f"the engine did not answer {phase} within {config.time_control.startup_ms} ms"
    else:
        fault = "transport"
        if isinstance(exc, RemoteError):
            detail = f"the engine answered {phase} with error {exc.code}"
        elif isinstance(exc, ProtocolError):
            detail = f"the engine's answer to {phase} was not a valid protocol message"
        elif phase == "start":
            detail = "the engine process could not be started"
        else:
            detail = f"the engine process failed at {phase}"
    reason = f"host_engine_fault:{fault}"
    reset = ResetRequest(
        request_id="h-1",
        game_id=bindings.game_id,
        format=bindings.format,
        seats=bindings.wire_decks,
        rules=bindings.rules,
        game_secret=bindings.game_secret_hex,
        max_decisions=bindings.limits.max_decisions,
        max_steps=bindings.limits.max_steps,
    )
    digest = GameDigest(reset.to_json())
    digest.add_adjudication(classification="halted", outcome="halted", reason=reason, winner=None)
    row = _row(
        config,
        setup,
        context,
        entries,
        outcome="halted",
        classification="halted",
        winner=None,
        reason=reason,
        adjudication=Adjudication(kind="halt", detail=detail),
        step_count=0,
        decision_count=0,
        decisions_checked=0,
        last_selection=None,
        game_digest=digest.value(),
        engine=setup.engine,
    )
    return GameOutcome(
        row=row, diagnostics=(f"{type(exc).__name__}: {exc}",), violation=None, engine=setup.engine.to_json()
    )


def play_one(
    config: TournamentConfig,
    setup: RunSetup,
    context: GameContext,
    run_secret_hex: str,
    entries: dict[str, registry.RegistryEntry],
) -> GameOutcome:
    """Play one scheduled game end to end and build its ledger row.

    Top level and picklable, so the executor can run it in a spawned worker. The
    engine starts bounded by ``startup_ms``; nothing is pinned here — the identity
    the engine reported comes back in the outcome for the parent to check.
    """
    run_secret = RunSecret.from_hex(run_secret_hex)
    bindings = game_setup(config, setup, context, run_secret)
    try:
        engine = EngineProcess(list(config.engine_command), timeout_s=config.time_control.startup_ms / 1000)
    except TransportError as exc:
        return _engine_fault_outcome(config, setup, context, bindings, entries, exc, "start")
    try:
        try:
            hello = engine.hello()
        except (TransportError, RemoteError, ProtocolError) as exc:
            return _engine_fault_outcome(config, setup, context, bindings, entries, exc, "hello")
        seats = {seat: make_driver(spec, config.time_control) for seat, spec in context.seat_specs}
        try:
            result = play_game(bindings, engine=engine, seats=seats)
        finally:
            for driver in seats.values():
                driver.close()
        return _game_outcome(config, setup, context, entries, result, hello.engine)
    finally:
        engine.close()


def _game_outcome(
    config: TournamentConfig,
    setup: RunSetup,
    context: GameContext,
    entries: dict[str, registry.RegistryEntry],
    result: GameResult,
    identity: EngineIdentity,
) -> GameOutcome:
    seat_specs = dict(context.seat_specs)
    last_selection = None
    if result.last_selection_seat is not None:
        seat = result.last_selection_seat
        last_selection = LastSelection(seat=seat, bot_id=entries[seat_specs[seat].name].bot_id)
    row = _row(
        config,
        setup,
        context,
        entries,
        outcome=result.outcome,
        classification=result.classification,
        winner=result.winner,
        reason=result.reason,
        adjudication=None if result.adjudication is None else Adjudication.from_json(result.adjudication),
        step_count=result.step_count,
        decision_count=result.decision_count,
        decisions_checked=result.decisions_checked,
        last_selection=last_selection,
        game_digest=result.game_digest,
        engine=identity,
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
    entries: dict[str, registry.RegistryEntry],
    workers: int,
    stop_on_violation: bool = True,
    on_outcome: Callable[[GameOutcome], None] | None = None,
    monitor: IdleMonitor | None = None,
    on_warning: Callable[[str], None] | None = None,
) -> ExecutionResult:
    """Play every context through :func:`play_one` (see ``arena.executor`` for the prefix rules)."""
    play = functools.partial(play_one, config, setup, run_secret_hex=run_secret.hex(), entries=entries)
    return execute(
        contexts,
        play,
        workers=workers,
        stop_on_violation=stop_on_violation,
        on_outcome=on_outcome,
        monitor=monitor,
        on_warning=on_warning,
    )


# ---------------------------------------------------------------------------
# The tournament (spec 11.1, 11.6; Decisions 3 and 6)
# ---------------------------------------------------------------------------


def _write_commitment(
    directory: Path, *, run_secret: RunSecret, benchmark_id: str | None, run_label: str | None
) -> None:
    """Write ``COMMITMENT.json``, or refuse one already made for a different run (spec 11.6, R3-30)."""
    record = commitment_record(run_secret=run_secret, benchmark_id=benchmark_id, run_label=run_label)
    path = directory / store.COMMITMENT_NAME
    if path.exists():
        present = store.read_json(path)
        for key in ("commitment", "benchmark_id", "run_label"):
            if present.get(key) != record[key]:
                raise TournamentError(
                    f"{store.COMMITMENT_NAME} was made for another run: its {key} is "
                    f"{present.get(key)!r}, this run's is {record[key]!r}"
                )
    else:
        store.write_json_atomic(path, record)


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
    """Run the full schedule and publish the tournament artifacts.

    ``resolve`` maps each engine and bot command part and checkpoint path to the
    string that starts the process or locates the file; every published artifact
    records ``config`` as written. ``output_dir`` publishes into that directory
    instead of ``config.tournament_dir``. A run stopped by a violation is
    published ``invalid``; one stopped by an exception (a ``KeyboardInterrupt``
    included) is published ``aborted`` and the exception re-raised once the
    manifest is written.
    """
    # An unvetted subprocess bot is refused before any process starts or anything is
    # written (R3-9); then checkpoints are hashed (registry entries) and the preflight
    # tries the engine and every subprocess bot, so a config error also writes nothing.
    refusals = isolation_refusals(config)
    if refusals:
        raise TournamentError("the tournament cannot start:\n" + "\n".join(refusals))
    executed = config if resolve is None else executed_config(config, resolve)
    entries_list = registry_entries(config, executed)
    entries = {entry.name: entry for entry in entries_list}
    anchor_bot_id = entries[config.rating_anchor].bot_id
    pin = EnginePin()
    setup = preflight(executed, run_secret, pin=pin)
    directory = Path(config.tournament_dir if output_dir is None else output_dir)
    store.prepare_tournament_dir(directory, allowed=(store.COMMITMENT_NAME,))
    _write_commitment(directory, run_secret=run_secret, benchmark_id=benchmark_id, run_label=run_label)

    store.write_json_atomic(directory / store.CONFIG_NAME, config.to_json())
    registry.write_registry(directory / store.REGISTRY_NAME, entries_list)
    ledger_path = directory / store.LEDGER_NAME
    ledger_path.write_bytes(b"")  # truncate/create the ledger before the first game

    rows: list[LedgerRow] = []
    violations: list[dict[str, Any]] = []

    def record(outcome: GameOutcome) -> None:
        # An engine whose identity drifted from the preflight's stops the run as aborted
        # (R3-5); otherwise the row (and its diagnostics) are appended as they arrive.
        identity = EngineIdentity.from_json(outcome.engine)
        try:
            pin.check(identity)
        except TournamentError as exc:
            raise TournamentError(
                f"the engine identity changed during the run: {identity} != {pin.identity}"
            ) from exc
        rows.append(outcome.row)
        if outcome.violation is not None:
            violations.append(outcome.violation)
        store.append_ledger_row(ledger_path, outcome.row.to_json())
        if outcome.diagnostics:
            store.append_diagnostics(directory / store.DIAGNOSTICS_NAME, outcome.row.game_id, outcome.diagnostics)
        if on_game is not None:
            on_game(outcome.row)

    contexts = schedule(executed, run_secret)
    # Games run in parallel only while their declared cores are free, whatever
    # allocation a library caller passes (spec 11.4); that number is published (R3-24).
    workers = min(allocation.workers, resource_bound(os.cpu_count() or 1, config.per_game_cores()))
    monitor: IdleMonitor | None = None
    on_warning: Callable[[str], None] | None = None
    if workers > 1:
        # The idle monitor watches the run as it plays; each warning lands in the run's
        # unhashed throughput log at once, and on stderr, never in the manifest's files (R3-6).
        monitor = IdleMonitor(workers, qualified_rate=allocation.qualified_rate, cpu=CpuSampler().sample)
        on_warning = warning_sink(directory / THROUGHPUT_LOG_NAME, stream=sys.stderr)
    allocation = replace(allocation, workers=workers)
    result = play_games(
        executed,
        setup,
        contexts,
        run_secret=run_secret,
        entries=entries,
        workers=workers,
        on_outcome=record,
        monitor=monitor,
        on_warning=on_warning,
    )

    status = run_status(scheduled=len(contexts), rows=len(rows), violations=len(violations))
    if (
        allocation.kind == "small"
        and allocation.spot_check is None
        and allocation.games_total == len(contexts)
        and status == "complete"
    ):
        # A small run replays the game its rules name, serially, after the run; only a
        # passed spot check makes the allocation measured, hence ratable (Decision 3).
        assert allocation.rules is not None
        game = allocation.rules.spot_check_game(len(contexts))
        replay = play_games(
            executed, setup, [contexts[game]], run_secret=run_secret, entries=entries, workers=1,
            stop_on_violation=False,
        )
        if replay.stopped == "aborted":
            assert replay.error is not None
            raise replay.error
        allocation = allocation.with_spot_check(
            game, recorded_digest=rows[game].game_digest, replayed_digest=replay.outcomes[0].row.game_digest
        )
    document, markdown = leaderboard.build_leaderboard(
        rows,
        entries_list,
        anchor_bot_id=anchor_bot_id,
        base_seed=config.stats_seed,
        bootstrap_replicates=config.bootstrap_replicates,
        format=config.format,
        schema=leaderboard.LEADERBOARD_SCHEMA_V2,
    )
    store.write_json_atomic(directory / store.LEADERBOARD_JSON_NAME, document)
    store.write_bytes_atomic(directory / store.LEADERBOARD_MD_NAME, markdown.encode("utf-8"))

    body = manifest_body(
        config=config,
        entries=entries_list,
        anchor_bot_id=anchor_bot_id,
        engine=setup.engine,
        profile=setup.profile,
        protocol_minor=PROTOCOL_MINOR,
        info_rules=information_rules(setup.rules, setup.profile, setup.native_id_extensions),
        rows=rows,
        violations=violations,
        scheduled=len(contexts),
        leaderboard_status=document["status"],
        status=status,
        benchmark_id=benchmark_id,
        run_label=run_label,
        run_secret=run_secret,
        commitment_proof=commitment_proof,
        allocation=allocation,
        engine_files=engine_files,
    )
    body["files"] = [store.file_entry(directory / store.COMMITMENT_NAME, store.COMMITMENT_NAME)] + [
        store.file_entry(directory / name, name) for name in store.DATA_FILE_NAMES
    ]
    if result.stopped == "aborted":
        # A second Ctrl+C is held back until the manifest is written, then the
        # aborting error (a KeyboardInterrupt included) is re-raised (R3-31).
        with deferred_interrupts():
            store.publish_manifest(directory, body)
        assert result.error is not None
        raise result.error
    store.publish_manifest(directory, body)
    counts = body["games"]
    return TournamentSummary(
        tournament_dir=directory,
        games_total=len(rows),
        games_rated=counts["natural"] + counts["forfeit"],
        games_truncated=counts["truncated"],
        games_halted=counts["halted"],
        games_forfeit=counts["forfeit"],
        leaderboard_status=document["status"],
        status=status,
        rated=body["run"]["rated"],
        manifest=body,
    )
