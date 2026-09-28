"""Schedule-order execution: the same prefix whatever the worker count (Decision 6)."""

from __future__ import annotations

import time

import pytest

from spellbench.arena.executor import GameOutcome, execute
from spellbench.arena.ledger import parse_ledger

from test_ledger import VALID, row


def play_one(index: int) -> GameOutcome:
    """Top-level so spawned workers can import it: game 3 breaks a validator rule, game 9 raises."""
    if index == 9:
        raise RuntimeError("the engine binary vanished")
    value = row(game_index=index) if index != 3 else {**VALID["validator halt"], "game_index": 3}
    violation = {"game_index": 3, "game_id": value["game_id"], "rule": "V4", "detail": "stale"} if index == 3 else None
    (parsed,) = parse_ledger([value])
    return GameOutcome(row=parsed, diagnostics=(), violation=violation, engine={"name": "fake"})


def slow_or_failing(index: int) -> GameOutcome:
    """Game 0 fails at once; every other game would run for 30 s."""
    if index == 0:
        raise RuntimeError("the engine binary vanished")
    time.sleep(30)
    return play_one(index)


@pytest.mark.parametrize("workers", [1, 3])
def test_a_violation_ends_the_prefix_at_that_game(workers: int) -> None:
    result = execute(list(range(8)), play_one, workers=workers)
    assert result.stopped == "violation" and [o.row.game_index for o in result.outcomes] == [0, 1, 2, 3]


@pytest.mark.parametrize("workers", [1, 2])
def test_all_games_in_schedule_order(workers: int) -> None:
    seen = []
    result = execute([0, 1, 2, 4, 5], play_one, workers=workers, on_outcome=lambda outcome: seen.append(outcome.row.game_index))
    assert result.stopped is None and seen == [0, 1, 2, 4, 5]


@pytest.mark.parametrize("workers", [1, 2])
def test_an_error_aborts_with_the_prefix(workers: int) -> None:
    result = execute([0, 1, 9, 2], play_one, workers=workers)
    assert result.stopped == "aborted" and [o.row.game_index for o in result.outcomes] == [0, 1]
    assert "vanished" in str(result.error)


def test_an_interrupt_in_the_parent_aborts_and_keeps_what_was_recorded() -> None:
    def interrupt(outcome):
        if outcome.row.game_index == 1:
            raise KeyboardInterrupt

    result = execute([0, 1, 2], play_one, workers=1, on_outcome=interrupt)
    assert result.stopped == "aborted" and isinstance(result.error, KeyboardInterrupt)
    assert [o.row.game_index for o in result.outcomes] == [0, 1]


def test_an_abort_does_not_wait_for_running_games() -> None:
    started = time.monotonic()
    result = execute([0, 1, 2], slow_or_failing, workers=3)
    assert result.stopped == "aborted" and result.outcomes == ()
    assert time.monotonic() - started < 20                     # the two 30 s games were terminated (R3-31)


def test_warnings_reach_the_callback_as_they_happen() -> None:
    class Monitor:
        def tick(self, *, running: int, queued: int, completed: int) -> str:
            return f"tick after {completed} games"

    seen: list[str] = []
    result = execute([0, 1, 2], play_one, workers=2, monitor=Monitor(), on_warning=seen.append)
    assert seen and seen == list(result.warnings)                # R3-6
