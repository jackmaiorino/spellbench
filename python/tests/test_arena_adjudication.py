"""Host adjudication: forfeits, engine failures, and truncation.

The schedule over two bots is m0 = (A, A), m1 = (A, B), m2 = (B, B), one
seat-swapped pair each: m1 g0 seats A at p0, m1 g1 seats B at p0. In
fake_arena_engine p0 acts at even steps and p1 at odd steps.
"""

from __future__ import annotations

import math
import os
import sys
import threading
from pathlib import Path

import pytest

from spellbench.arena.cli import validate_tournament_dir

from arena_helpers import (
    BOT_HANG,
    BOT_INVALID_CHOICE,
    builtin,
    cli_bot,
    hostile_bot,
    ledger_rows,
    leaderboard,
    make_config,
    row_by_name,
    run,
    subprocess_bot,
)


def _forfeits(directory: Path) -> list[tuple[str, str, str, str, int]]:
    return [
        (
            row["game_id"],
            row["outcome"],
            row["adjudication"]["cause"],
            row["adjudication"]["loser_seat"],
            row["step_count"],
        )
        for row in ledger_rows(directory)
        if row["classification"] == "forfeit"
    ]


def test_invalid_selection_is_a_forfeit_loss_for_the_acting_bot(tmp_path: Path) -> None:
    directory = tmp_path / "t"
    bad = subprocess_bot("bad-invalid", [sys.executable, str(BOT_INVALID_CHOICE)])
    summary = run(make_config(directory, [builtin("heuristic"), bad], pairs=1))
    # A forfeit is a rated loss: otherwise a losing bot could erase its
    # losses by hanging or answering garbage.
    assert (summary.games_total, summary.games_rated, summary.games_forfeit) == (6, 6, 4)
    assert _forfeits(directory) == [
        ("m0001p0000g0", "p0_win", "invalid_selection", "p1", 1),
        ("m0001p0000g1", "p1_win", "invalid_selection", "p0", 0),
        ("m0002p0000g0", "p1_win", "invalid_selection", "p0", 0),
        ("m0002p0000g1", "p1_win", "invalid_selection", "p0", 0),
    ]
    document = leaderboard(directory)
    offender = row_by_name(document, "bad-invalid")
    # 2 cross games lost, plus 2 mirror games (each a win and a loss for the
    # bot holding both seats).
    assert offender["forfeit_losses"] == 4
    assert (offender["games"], offender["wins"], offender["draws"], offender["losses"]) == (6, 2, 0, 4)
    assert row_by_name(document, "heuristic")["forfeit_losses"] == 0
    assert document["games"]["forfeit"] == 4
    # heuristic 2-0 plus one virtual draw: 2.5 to 0.5, ln(5) apart.
    assert offender["rating_log_units_e6"] == round(-math.log(5) * 1_000_000)


def test_choose_timeout_is_a_forfeit_loss(tmp_path: Path) -> None:
    directory = tmp_path / "t"
    hang = subprocess_bot("bad-hang", [sys.executable, str(BOT_HANG)])
    run(make_config(directory, [builtin("heuristic"), hang], pairs=1, choose_timeout_ms=300))
    assert [(game_id, cause, loser) for game_id, _, cause, loser, _ in _forfeits(directory)] == [
        ("m0001p0000g0", "timeout", "p1"),
        ("m0001p0000g1", "timeout", "p0"),
        ("m0002p0000g0", "timeout", "p0"),
        ("m0002p0000g1", "timeout", "p0"),
    ]


def test_bot_identity_mismatch_at_hello_is_a_forfeit(tmp_path: Path) -> None:
    # The process answers hello as "first", but the config registered it as
    # "impostor": the host refuses to seat it.
    directory = tmp_path / "t"
    impostor = subprocess_bot("impostor", cli_bot("first"))
    run(make_config(directory, [builtin("heuristic"), impostor], pairs=1))
    assert _forfeits(directory) == [
        ("m0001p0000g0", "p0_win", "malformed_response", "p1", 0),
        ("m0001p0000g1", "p1_win", "malformed_response", "p0", 0),
        ("m0002p0000g0", "p1_win", "malformed_response", "p0", 0),
        ("m0002p0000g1", "p1_win", "malformed_response", "p0", 0),
    ]


def test_engine_crash_mid_game_is_halted_and_unrated(tmp_path: Path) -> None:
    directory = tmp_path / "t"
    summary = run(
        make_config(directory, [builtin("heuristic"), builtin("first")], decks=("Crash", "Burn"), pairs=1)
    )
    assert (summary.games_total, summary.games_halted, summary.games_rated) == (6, 6, 0)
    for row in ledger_rows(directory):
        assert (row["outcome"], row["winner"], row["reason"]) == ("halted", None, "engine error mid-game")
        assert row["adjudication"]["kind"] == "engine_halt"
    assert leaderboard(directory)["status"] == "no_rated_games"


def test_engine_reported_halt_is_recorded_without_adjudication(tmp_path: Path) -> None:
    directory = tmp_path / "t"
    run(make_config(directory, [builtin("heuristic"), builtin("first")], decks=("Halt", "Burn"), pairs=1))
    rows = ledger_rows(directory)
    assert {(row["classification"], row["reason"]) for row in rows} == {("halted", "engine_contract_failure")}
    assert all(row["adjudication"] is None for row in rows)


def test_truncated_games_are_recorded_and_unrated(tmp_path: Path) -> None:
    directory = tmp_path / "t"
    summary = run(make_config(directory, [builtin("heuristic"), builtin("first")], pairs=1, max_steps=2))
    assert (summary.games_total, summary.games_truncated, summary.games_rated) == (6, 6, 0)
    assert {(row["outcome"], row["step_count"]) for row in ledger_rows(directory)} == {("truncated", 2)}
    assert leaderboard(directory)["status"] == "no_rated_games"


@pytest.mark.parametrize(
    ("mode", "cause"),
    [
        ("nested", "malformed_response"),
        ("surrogate", "malformed_response"),
        ("badname", "malformed_response"),
        ("garbage", "malformed_response"),
        ("crash", "transport_error"),
        ("flood", "malformed_response"),
    ],
)
def test_a_hostile_bot_forfeits_and_the_tournament_still_publishes(
    tmp_path: Path, mode: str, cause: str
) -> None:
    directory = tmp_path / "t"
    summary = run(make_config(directory, [builtin("heuristic"), hostile_bot(mode)], pairs=1))
    assert summary.games_forfeit == 4
    assert {row[2] for row in _forfeits(directory)} == {cause}
    assert validate_tournament_dir(directory) == []


def test_adjudicated_rows_are_byte_identical_across_reruns(tmp_path: Path) -> None:
    # The crashing bot prints its PID to stderr: nothing peer-controlled may
    # reach the ledger, or identical configs stop reproducing.
    first, second = tmp_path / "a", tmp_path / "b"
    for directory in (first, second):
        run(make_config(directory, [builtin("heuristic"), hostile_bot("crash")], pairs=1))
    assert (first / "matches.jsonl").read_bytes() == (second / "matches.jsonl").read_bytes()


def test_a_truncated_game_may_name_a_winner_and_stays_unrated(tmp_path: Path) -> None:
    directory = tmp_path / "t"
    summary = run(
        make_config(
            directory,
            [builtin("heuristic"), builtin("first")],
            decks=("CapWinner", "Burn"),
            pairs=1,
            max_steps=2,
        )
    )
    assert (summary.games_truncated, summary.games_rated) == (6, 0)
    assert {(row["outcome"], row["winner"]) for row in ledger_rows(directory)} == {("truncated", "p0")}


def test_a_hung_bot_behind_a_wrapper_process_is_killed(tmp_path: Path) -> None:
    # A wrapper (a .bat, sh without exec, conda run) keeps the real bot as a
    # grandchild that holds the pipes; closing must kill the whole tree
    # instead of waiting on a pipe that never closes.
    if os.name == "nt":
        wrapper = tmp_path / "wrap.bat"
        wrapper.write_text(f'@"{sys.executable}" "{BOT_HANG}" 60\n', encoding="ascii")
        command = ["cmd", "/c", str(wrapper)]
    else:
        wrapper = tmp_path / "wrap.sh"
        wrapper.write_text(f'"{sys.executable}" "{BOT_HANG}" 60\n', encoding="ascii")
        command = ["sh", str(wrapper)]
    directory = tmp_path / "t"
    config = make_config(
        directory,
        [builtin("heuristic"), subprocess_bot("bad-hang", command)],
        pairs=1,
        choose_timeout_ms=300,
    )
    outcome: list[BaseException | None] = []

    def play() -> None:
        try:
            run(config)
            outcome.append(None)
        except BaseException as exc:
            outcome.append(exc)

    worker = threading.Thread(target=play, daemon=True)
    worker.start()
    worker.join(timeout=45)
    assert outcome, "the host is still blocked on the hung bot's pipes"
    assert outcome[0] is None
    assert {row[2] for row in _forfeits(directory)} == {"timeout"}
