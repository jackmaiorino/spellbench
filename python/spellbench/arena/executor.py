"""Playing a run's games, serially or in a spawned worker pool (Decision 6, R3-6, R3-31).

``execute`` consumes game results in schedule order whatever the worker count,
so the recorded ledger is always a contiguous prefix of the schedule: the same
games, seeds and results in the same order. A game's live-validation violation
ends the run at that game (spec 11.3, Decision 6): queued games are cancelled,
running ones finish, and their later results are dropped. Any exception (a
worker's, or one raised in the parent, a ``KeyboardInterrupt`` from Ctrl+C or
from ``on_outcome`` included) aborts the run with the prefix recorded so far
and the exception in the result's ``error``.

While games play, the idle monitor (``throughput.IdleMonitor``, Task 5) is
ticked before waiting on each future and again after every 5-second wait, with
the games recorded so far as ``completed``. Each warning goes to ``on_warning``
at once (the runner's sink writes and flushes it, so a long run reports idle
capacity while it happens, R3-6) and is collected in the result's ``warnings``.

On an abort the worker processes are terminated and the pool is shut down
without waiting, so Ctrl+C never waits minutes for running games (R3-31).
Workers are spawned, so a caller using ``workers > 1`` must run under
``if __name__ == "__main__":``.
"""

from __future__ import annotations

import multiprocessing
from collections import deque
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from itertools import islice
from typing import Callable, Sequence, TypeVar

from .ledger import LedgerRow
from .throughput import IdleMonitor

# The per-game context a runner hands to ``play_one`` (one scheduled game).
C = TypeVar("C")

# A future wait lasts at most this long before the monitor is ticked again.
WAIT_SLICE_S = 5.0


@dataclass(frozen=True)
class GameOutcome:
    """One played game.

    ``violation`` is ``{"game_index", "game_id", "rule", "detail"}`` when live
    validation halted the game (spec 11.3), else None; ``engine`` is the
    identity the game's engine process reported.
    """

    row: LedgerRow
    diagnostics: tuple[str, ...]
    violation: dict | None
    engine: dict


@dataclass(frozen=True)
class ExecutionResult:
    """The games recorded, always a contiguous prefix of the schedule.

    ``stopped`` is None when every game played out, ``"violation"`` when a
    game's violation ended the run there, or ``"aborted"`` when an exception
    did, with that exception in ``error``.
    """

    outcomes: tuple[GameOutcome, ...]
    stopped: str | None
    error: BaseException | None
    warnings: tuple[str, ...]


def _terminate_workers(pool: ProcessPoolExecutor) -> None:
    """Kill the pool's worker processes at once, without their atexit handlers.

    This runs before shutdown, which drops the pool's reference to the
    processes. ``terminate_workers`` exists on Python 3.14 and later; before
    that, terminate each process of the pool's ``_processes`` ourselves. A
    failure here never hides the abort it serves.
    """
    terminate = getattr(pool, "terminate_workers", None)
    if terminate is not None:
        try:
            terminate()
        except Exception:
            pass
        return
    for process in list((pool._processes or {}).values()):
        try:
            process.terminate()
        except Exception:
            pass


def execute(
    contexts: Sequence[C],
    play_one: Callable[[C], GameOutcome],
    *,
    workers: int,
    stop_on_violation: bool = True,
    on_outcome: Callable[[GameOutcome], None] | None = None,
    monitor: IdleMonitor | None = None,
    on_warning: Callable[[str], None] | None = None,
    guard: Callable[[], None] | None = None,
    submission_window: int | None = None,
) -> ExecutionResult:
    """Play each context through ``play_one``, recording outcomes in schedule order.

    ``workers == 1`` plays serially; more plays in a spawn-context pool. With
    ``submission_window``, at most that many tasks remain submitted but not
    collected. Replenishment waits for ``on_outcome`` and ``guard`` to return,
    so a collection acknowledgment can bound retained worker artifacts.
    ``None`` keeps the existing eager submission. See the module docstring
    for the prefix, violation and abort rules.
    """
    if submission_window is not None and (
        type(submission_window) is not int or not 1 <= submission_window <= workers
    ):
        raise ValueError("submission_window must be an integer from 1 through workers")
    outcomes: list[GameOutcome] = []
    warnings: list[str] = []
    stopped: str | None = None
    error: BaseException | None = None

    def record(outcome: GameOutcome) -> bool:
        """Record one outcome, then report it; True when its violation stops the run.

        The outcome is recorded before ``on_outcome`` runs, so an interrupt
        raised inside the callback still keeps the game.
        """
        outcomes.append(outcome)
        if on_outcome is not None:
            on_outcome(outcome)
        if guard is not None:
            guard()
        return stop_on_violation and outcome.violation is not None

    def tick() -> None:
        """One monitor observation; a warning goes to ``on_warning`` at once (R3-6)."""
        if guard is not None:
            guard()
        if monitor is None:
            return
        remaining = len(contexts) - len(outcomes)
        warning = monitor.tick(
            running=min(workers, remaining), queued=max(remaining - workers, 0), completed=len(outcomes)
        )
        if warning:
            warnings.append(warning)
            if on_warning is not None:
                on_warning(warning)

    if workers == 1 and guard is None:
        try:
            for context in contexts:
                if record(play_one(context)):
                    stopped = "violation"
                    break
        except BaseException as exc:
            stopped, error = "aborted", exc
        return ExecutionResult(tuple(outcomes), stopped, error, tuple(warnings))

    pool: ProcessPoolExecutor | None = None
    try:
        if guard is not None:
            guard()
        pool = ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn"))
        pending = iter(contexts)
        window = len(contexts) if submission_window is None else submission_window
        futures = deque(pool.submit(play_one, context) for context in islice(pending, window))
        while futures:  # schedule order, whatever the completion order
            future = futures.popleft()
            tick()
            while True:
                try:
                    outcome = future.result(timeout=WAIT_SLICE_S)
                    break
                except TimeoutError:
                    tick()
            if record(outcome):
                stopped = "violation"
                break
            if submission_window is not None:
                try:
                    context = next(pending)
                except StopIteration:
                    pass
                else:
                    futures.append(pool.submit(play_one, context))
    except BaseException as exc:
        stopped, error = "aborted", exc
    finally:
        if pool is not None:
            if stopped == "aborted":
                _terminate_workers(pool)
            # A violation cancels the queued games and lets the running ones
            # finish (their results are dropped); an abort does not wait (R3-31).
            pool.shutdown(wait=stopped != "aborted", cancel_futures=True)
    return ExecutionResult(tuple(outcomes), stopped, error, tuple(warnings))
