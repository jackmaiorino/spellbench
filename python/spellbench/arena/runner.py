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
4. prepare the run directory, which may already hold this run's commitment,
   and check that a ``COMMITMENT.json`` present names this run's commitment,
   benchmark and run label (spec 11.6, R3-30);
5. enter the committed phase (below) and write ``COMMITMENT.json`` unless
   present;
6. write ``config.json``, ``registry.json`` and an empty ``matches.jsonl``;
7. play the schedule through :func:`play_games` (``executor.execute``:
   results in schedule order, and a live-validation violation ends the run
   at that game, Decision 6), checking each game's engine identity against
   the preflight pin before its row is appended (R3-5). With more than one
   worker the idle monitor watches the pool (COMPUTE-POLICY.md item 6, R3-6):
   each warning is appended to the run's unhashed ``throughput.jsonl`` and
   written to stderr as it happens, and no manifest lists that file;
8. spot-check a small allocation (Decision 3, Task 5): a complete run that
   could otherwise be rated replays one scheduled game serially, and the
   allocation records whether its ledger row came back byte for byte;
9. publish the leaderboard, then ``manifest.json`` last, and leave the
   committed phase. The status, the validator verdict and the rated rule
   come from the rows actually appended (R3-13).

Each game (:func:`play_one`) starts its own engine process and seat drivers
and plays through ``host.game.play_game``, which routes, validates, keeps the
clocks and adjudicates forfeits, halts, caps and stalling (spec 11.2 to 11.5).
An engine that cannot start or answer ``hello`` halts only its game (spec
11.5, R3-23); an engine whose identity drifted from preflight aborts the run
(R3-5).

Every committed run is published (spec 11.6). One SIGINT handler covers the
committed phase, from before ``COMMITMENT.json`` is written (a commitment
already present is checked against this run first) until ``manifest.json``
is written (R3-31):

- while games play, a Ctrl+C switches the handler to holding and then raises
  ``KeyboardInterrupt``, which stops the games;
- everywhere else in the phase (the commitment and data files, recording a
  game, winding down and publishing) a Ctrl+C is held. One held while a file
  or a game's row is written stops the run as soon as that write is done;
  one held after the games stopped is delivered once, to the handler the run
  found, after the manifest is written.

So any number of Ctrl+C landing anywhere in the phase, or an exception that
stops the games (the caller's ``on_game``, an engine that changed identity),
still publishes the run with the games recorded so far and the revealed run
secret, as ``aborted`` unless every game was recorded (R3-13); the interrupt
or error is raised again after the manifest. Only a run killed outright
(SIGKILL or SIGTERM, say) or unable to write its files misses its manifest,
and ``bench`` reveals such a committed run (Decision 9).

The handler is installed only in the main thread and only over a SIGINT
handler set from Python that does not ignore the signal: a process that
ignores SIGINT keeps ignoring it, and on another thread, where no handler
can be installed, the run takes no interrupt at all (Python raises
``KeyboardInterrupt`` in the main thread), so it publishes unless the
process exits first.

Worker processes are spawned, so a script calling :func:`run_tournament` with
more than one worker must do so under ``if __name__ == "__main__":``.
"""

from __future__ import annotations

import contextlib
import dataclasses
import functools
import hashlib
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence

from .. import wire
from ..digests import GameDigest
from ..file_pins import PinningError, verify_files
from ..errors import PeerTimeoutError, ProtocolError, RemoteError, TransportError, ValidationError
from ..host.engine_process import EngineProcess
from ..host.game import GameResult, play_game
from ..host.setup import GameSetup
from ..messages import EngineIdentity, ResetRequest
from ..run_secret import RunSecret
from . import engine_records, leaderboard, registry, store
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
from .throughput import Allocation, CpuSampler, IdleMonitor, resource_bound, warning_sink
from .validate import THROUGHPUT_NAME

__all__ = [
    "BotSpec",
    "TournamentConfig",
    "TournamentError",
    "TimedOutcome",
    "TournamentSummary",
    "deferred_interrupts",
    "executed_config",
    "play_games",
    "play_one",
    "registry_entries",
    "row_digest",
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


class _Interrupts:
    """The one SIGINT handler of a run's committed phase (spec 11.6, R3-31); a context manager.

    Entered, it replaces the SIGINT handler it finds and holds: a SIGINT is
    recorded, never raised. Inside :meth:`interruptible` (games playing), a
    SIGINT switches the handler back to holding and only then raises
    ``KeyboardInterrupt``, so a second Ctrl+C that lands while the games stop
    and the run publishes is held too; entering it raises at once for a
    SIGINT held until then, and :meth:`holding` suspends it around a write.
    On exit the handler found is restored and a SIGINT held meanwhile is
    delivered to it once, whether the body completed or raised: Python's
    default handler then raises ``KeyboardInterrupt``.

    Nothing is installed off the main thread (handlers cannot be set there),
    when the handler in place was not set from Python (it could not be put
    back), or when SIGINT is ignored: a process that ignores it keeps
    ignoring it. Every method then only tracks the mode.
    """

    def __init__(self) -> None:
        self._found: Any = None  # the handler replaced while ours is installed, else None
        self._interruptible = False
        self._held = False

    def __enter__(self) -> _Interrupts:
        found = signal.getsignal(signal.SIGINT)
        if found is not None and found != signal.SIG_IGN:
            try:
                self._found = signal.signal(signal.SIGINT, self._on_sigint)
            except ValueError:  # not the main thread of the main interpreter, where alone handlers can be set
                pass
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._interruptible = False
        found, self._found = self._found, None
        if found is None:
            return
        signal.signal(signal.SIGINT, found)
        if self._held:  # delivered once, now that the body (the publish) is done (R3-31)
            self._held = False
            signal.raise_signal(signal.SIGINT)

    def _on_sigint(self, signum: int, frame: Any) -> None:
        if self._interruptible:
            self._interruptible = False  # hold from here: the run stops, and still publishes (spec 11.6)
            raise KeyboardInterrupt
        self._held = True

    def _resume(self) -> None:
        """Games again: a SIGINT raises, and one held until now raises at once."""
        self._interruptible = True
        if self._held:
            self._held = False
            self._interruptible = False
            raise KeyboardInterrupt

    @contextlib.contextmanager
    def interruptible(self) -> Iterator[None]:
        """While the body plays games, a SIGINT raises ``KeyboardInterrupt``; after it, SIGINT is held again."""
        self._resume()
        try:
            yield
        finally:
            self._interruptible = False

    @contextlib.contextmanager
    def holding(self) -> Iterator[None]:
        """Hold SIGINT while the body writes, even inside :meth:`interruptible`, which resumes after it (so a
        SIGINT held meanwhile raises then)."""
        resume, self._interruptible = self._interruptible, False
        try:
            yield
        finally:
            if resume:
                self._resume()


@contextlib.contextmanager
def deferred_interrupts() -> Iterator[None]:
    """Hold back Ctrl+C (SIGINT) while the body runs, then deliver it once (R3-31).

    The holding half of the run's committed-phase handler: a SIGINT that
    arrives while the body runs is recorded, and on exit, once the previous
    handler is restored, delivered to it once, whether the body completed or
    raised (Python's default handler raises ``KeyboardInterrupt``). A process
    that ignores SIGINT keeps ignoring it; off the main thread, or over a
    handler not set from Python, this changes nothing.
    """
    with _Interrupts():
        yield


def executed_config(config: TournamentConfig, resolve: Callable[[str], str]) -> TournamentConfig:
    """``config`` with every command part and checkpoint path passed through ``resolve``.

    Processes start from the executed config; every published artifact records ``config`` as written.
    """
    bots = tuple(
        dataclasses.replace(
            spec,
            command=tuple(resolve(part) for part in spec.command),
            checkpoint=None if spec.checkpoint is None else resolve(spec.checkpoint),
            evaluation_inputs=tuple(resolve(path) for path in spec.evaluation_inputs),
        )
        for spec in config.bots
    )
    return dataclasses.replace(config, engine_command=tuple(resolve(part) for part in config.engine_command), bots=bots,
                               evaluation_engine_inputs=tuple(resolve(path) for path in config.evaluation_engine_inputs))


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
    launch_files: Sequence[EngineFile] = (),
    recording: dict | None = None,
) -> GameOutcome:
    """Play one scheduled game in its own engine process and seat drivers; returns its ledger row.

    Top level and picklable, so worker processes can run it. It pins nothing:
    the outcome carries the identity this game's engine reported, which the
    caller checks against the run's pin (R3-5). The engine gets ``startup_ms``
    to start and answer ``hello``; one that does not halts this game only
    (spec 11.5, R3-23). A host fault from ``play_game`` propagates, and every
    process is closed whatever happens.
    """
    verify_files(launch_files)
    engine_records.assert_current(recording)
    game = game_setup(config, setup, context, RunSecret.from_hex(run_secret_hex))
    with contextlib.ExitStack() as stack:
        capture = None if recording is None else engine_records.EngineRecord(recording, context)
        if capture is not None:
            stack.callback(capture.close)
        try:
            command = list(config.engine_command)
            if capture is None:
                engine = EngineProcess(command, timeout_s=config.time_control.startup_ms / 1000)
            else:
                command = engine_records.work_command(command, capture.directory / "engine-work")
                peer = wire.SubprocessPeer(command, timeout_s=config.time_control.startup_ms / 1000)
                engine = EngineProcess(peer=engine_records.RecordPeer(peer, capture))
        except TransportError as exc:
            return _unstarted(config, setup, context, entries, game, exc)
        stack.callback(engine.close)
        try:
            hello = engine.hello()
        except (TransportError, ProtocolError, RemoteError) as exc:
            return _unstarted(config, setup, context, entries, game, exc)
        seats = {}
        for seat, spec in context.seat_specs:
            if capture is not None and spec.command:
                spec = dataclasses.replace(spec, command=tuple(engine_records.work_command(
                    spec.command, capture.directory / f"agent-work-{seat}")))
            driver = make_driver(spec, config.time_control, launch_files=launch_files)
            stack.callback(driver.close)
            seats[seat] = driver
        result = play_game(game, engine=engine, seats=seats)
    if result.classification == "halted" and result.reason.startswith("engine_contract_failure:"):
        # Read only after cleanup drains the bounded stderr reader. Peer text stays outside the hashed row.
        diagnostic = engine.stderr_text()
        if diagnostic:
            result = dataclasses.replace(result, diagnostics=(*result.diagnostics, diagnostic))
    verify_files(launch_files)
    outcome = _outcome(config, setup, context, entries, result, hello.engine)
    if capture is not None:
        fields = {field.name: getattr(outcome, field.name) for field in dataclasses.fields(outcome)}
        return RecordedOutcome(**fields, record_directory=capture.seal(outcome.row))
    return outcome


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


@dataclass(frozen=True)
class RecordedOutcome(GameOutcome):
    record_directory: str | None = dataclasses.field(default=None, kw_only=True)


@dataclass(frozen=True)
class TimedOutcome(RecordedOutcome):
    """A played game and its own time in seconds, measured in the process that played it: from the game's start
    (its engine and seat processes starting) to its result. Qualification ranks worker counts by these times
    (Task 5: ``PlayedGame.seconds``)."""

    seconds: float


def _timed(play: Callable[[GameContext], GameOutcome], context: GameContext) -> TimedOutcome:
    """``play(context)`` with the game's own time; top level, so worker processes can run it."""
    started = time.perf_counter()
    outcome = play(context)
    fields = {field.name: getattr(outcome, field.name) for field in dataclasses.fields(outcome)}
    return TimedOutcome(**fields, seconds=time.perf_counter() - started)


def row_digest(row: LedgerRow) -> str:
    """``"sha256:"`` and the hex SHA-256 of a game's canonical ledger row, the bytes the run hashes: a
    qualification game's digest and a spot check's (Task 5)."""
    return "sha256:" + hashlib.sha256(store.canonical_bytes(row.to_json())).hexdigest()


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
    timed: bool = False,
    guard: Callable[[], None] | None = None,
    launch_files: Sequence[EngineFile] = (),
    recording: dict | None = engine_records.FROM_ENV,
) -> ExecutionResult:
    """Play ``contexts`` (a run's schedule, or any of its games: a qualification sample, a rerun) with ``workers``
    workers through ``executor.execute``: outcomes in the order given, the rest stopped at a violation when
    ``stop_on_violation`` (Decision 6), and any exception reported in the result's ``error`` (spec 11.3). With
    ``timed``, each outcome is a :class:`TimedOutcome`."""
    recording = engine_records.settings() if recording is engine_records.FROM_ENV else recording
    play = functools.partial(play_one, config, setup, run_secret_hex=run_secret.hex(), entries=entries,
                             launch_files=launch_files, recording=recording)
    if timed:
        play = functools.partial(_timed, play)
    return execute(contexts, play, workers=workers, stop_on_violation=stop_on_violation, on_outcome=on_outcome,
                   monitor=monitor, on_warning=on_warning, guard=guard,
                   submission_window=None if recording is None else workers)


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


def _commitment_present(directory: Path, record: dict[str, Any]) -> bool:
    """Whether ``COMMITMENT.json`` is already there for this run; one made for another run is refused (spec 11.6,
    R3-30).

    A commitment published before the run (``bench commit``) is kept byte for byte; it must name this run's
    commitment, benchmark id and run label, and otherwise the run stops before writing anything else. The run
    writes an absent one itself, inside its committed phase.
    """
    path = directory / store.COMMITMENT_NAME
    if not path.exists():
        return False
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
    return True


def _spot_check_game(
    allocation: Allocation,
    *,
    scheduled: int,
    recorded: int,
    violations: int,
    commitment_proof: CommitmentProof | None,
    engine_files: Sequence[EngineFile],
) -> int | None:
    """The game a small run replays before its manifest, or None when no replay is due.

    Only a small allocation planned for this schedule and not spot-checked yet needs one (Task 5), and only a
    complete run that Decision 3 could otherwise rate (a commitment proof and pinned engine files) is worth the
    extra game: an unrated run stays unrated whatever its spot check says (COMPUTE-POLICY.md).
    """
    if (
        allocation.kind != "small" or allocation.spot_check is not None or allocation.rules is None
        or allocation.games_total != scheduled or recorded != scheduled or violations
        or commitment_proof is None or not engine_files
    ):
        return None
    return allocation.rules.spot_check_game(scheduled)


def _spot_checked(
    allocation: Allocation,
    index: int,
    *,
    config: TournamentConfig,
    setup: RunSetup,
    context: GameContext,
    row: LedgerRow,
    run_secret: RunSecret,
    entries: dict[str, RegistryEntry],
    launch_files: Sequence[EngineFile] = (),
    recording: dict | None = None,
    guard: Callable[[], None] | None = None,
) -> tuple[Allocation, BaseException | None]:
    """Replay scheduled game ``index`` serially and record whether its ledger row matches the recorded one
    (``Allocation.with_spot_check``). A replay that raises leaves the allocation unchecked, so the run publishes
    as unrated; the exception is returned for the caller to note, or to raise after the manifest."""
    result = play_games(config, setup, [context], run_secret=run_secret, entries=entries, workers=1,
                        stop_on_violation=False, launch_files=launch_files, recording=recording, guard=guard,
                        on_outcome=lambda outcome: engine_records.collect(
                            getattr(outcome, "record_directory", None), outcome.row, guard=guard))
    if result.error is not None or len(result.outcomes) != 1:
        return allocation, result.error
    replayed = result.outcomes[0].row
    return allocation.with_spot_check(index, recorded_digest=row_digest(row), replayed_digest=row_digest(replayed)), None


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
    guard: Callable[[], None] | None = None,
    launch_files: Sequence[EngineFile] = (),
    recording: dict | None = engine_records.FROM_ENV,
) -> TournamentSummary:
    """Run the full schedule and publish the tournament (the module docstring gives the order).

    ``resolve`` maps each engine and bot command part and checkpoint path to the string that starts the process
    or locates the file; every published artifact records ``config`` as written. ``output_dir`` publishes into
    that directory instead of ``config.tournament_dir``. ``on_game`` sees each row once it is appended. A run is
    rated only under Decision 3 (``manifest.is_rated``): complete, a passing verdict, ``commitment_proof``, a
    measured ``allocation`` (a small one once its spot check passed) and pinned ``engine_files``.
    """
    refusals = isolation_refusals(config)
    recording = engine_records.settings() if recording is engine_records.FROM_ENV else recording
    engine_records.assert_current(recording)
    if refusals:
        raise TournamentError("; ".join(refusals))
    executed = config if resolve is None else executed_config(config, resolve)
    entries_list = registry_entries(config, executed)
    entries = {entry.name: entry for entry in entries_list}
    allocation = _run_allocation(allocation, config)
    pin = EnginePin()
    verify_files(launch_files)
    setup = preflight(executed, run_secret, pin=pin)
    contexts = schedule(executed, run_secret)
    directory = Path(config.tournament_dir if output_dir is None else output_dir)
    store.prepare_tournament_dir(directory, allowed=(store.COMMITMENT_NAME,))
    commitment = commitment_record(run_secret=run_secret, benchmark_id=benchmark_id, run_label=run_label)
    committed = _commitment_present(directory, commitment)

    ledger_path = directory / store.LEDGER_NAME
    rows: list[LedgerRow] = []
    violations: list[dict[str, Any]] = []
    interrupts = _Interrupts()

    def record(outcome: GameOutcome) -> None:
        identity = EngineIdentity.from_json(outcome.engine)
        try:
            pin.check(identity)
        except TournamentError:
            raise TournamentError(
                f"the engine identity changed during the run: game {outcome.row.game_index}'s engine reported "
                f"{_identity_text(identity)}; preflight pinned {_identity_text(pin.identity)} (R3-5)"
            ) from None
        with interrupts.holding():  # the file, the rows and the violations stay in step (R3-13)
            store.append_ledger_row(ledger_path, outcome.row.to_json())
            rows.append(outcome.row)
            if outcome.violation is not None:
                violations.append(outcome.violation)
            if outcome.diagnostics:
                store.append_diagnostics(directory / store.DIAGNOSTICS_NAME, outcome.row.game_id, outcome.diagnostics)
        engine_records.collect(getattr(outcome, "record_directory", None), outcome.row, guard=guard)
        if on_game is not None:
            on_game(outcome.row)

    # With more than one worker, the idle monitor reports unused capacity and throughput below the qualified rate
    # as it happens: each warning goes to the run's unhashed throughput.jsonl, flushed, and to stderr, and never
    # into a manifest (COMPUTE-POLICY.md item 6, R3-6).
    monitor: IdleMonitor | None = None
    on_warning: Callable[[str], None] | None = None
    if allocation.workers > 1:
        monitor = IdleMonitor(allocation.workers, qualified_rate=allocation.qualified_rate, cpu=CpuSampler().sample)
        on_warning = warning_sink(directory / THROUGHPUT_NAME, stream=sys.stderr)

    error: BaseException | None = None
    try:
        # The committed phase: one SIGINT handler from before the commitment is written until the manifest is.
        # Leaving it delivers a Ctrl+C held since the games stopped, once (spec 11.6, R3-31).
        with interrupts:
            if not committed:
                store.write_json_atomic(directory / store.COMMITMENT_NAME, commitment)
            # Committed: every ending from here publishes the run.
            try:
                store.write_json_atomic(directory / store.CONFIG_NAME, config.to_json())
                registry.write_registry(directory / store.REGISTRY_NAME, entries_list)
                ledger_path.write_bytes(b"")  # truncate/create the ledger before the first game
                with interrupts.interruptible():  # only here does a Ctrl+C raise, and it stops the games
                    result = play_games(executed, setup, contexts, run_secret=run_secret, entries=entries,
                                        workers=allocation.workers, on_outcome=record, monitor=monitor,
                                        on_warning=on_warning, launch_files=launch_files, guard=guard, recording=recording)
                error = result.error
                game = None if error is not None else _spot_check_game(
                    allocation, scheduled=len(contexts), recorded=len(rows), violations=len(violations),
                    commitment_proof=commitment_proof, engine_files=engine_files,
                )
                if game is not None:
                    with interrupts.interruptible():  # a Ctrl+C stops the replay; the run still publishes
                        allocation, failure = _spot_checked(
                            allocation, game, config=executed, setup=setup, context=contexts[game], row=rows[game],
                            run_secret=run_secret, entries=entries,
                            launch_files=launch_files,
                            recording=recording, guard=guard,
                        )
                    if isinstance(failure, Exception):  # noted, never fatal: the run publishes as not spot-checked
                        with interrupts.holding():
                            store.append_diagnostics(directory / store.DIAGNOSTICS_NAME, contexts[game].game_id,
                                                     (f"spot check replay: {type(failure).__name__}: {failure}",))
                    elif failure is not None:
                        error = failure  # a Ctrl+C: raised again after the manifest
                verify_files(launch_files)
            except BaseException as exc:  # noqa: BLE001 - published as aborted below, then raised again
                error = exc
            summary = _publish(
                directory, config=config, entries=entries_list, setup=setup, rows=rows, violations=violations,
                scheduled=len(contexts), run_secret=run_secret, commitment_proof=commitment_proof,
                allocation=allocation, engine_files=() if isinstance(error, PinningError) else engine_files,
                benchmark_id=benchmark_id, run_label=run_label,
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
