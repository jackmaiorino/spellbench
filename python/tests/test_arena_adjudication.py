"""Host adjudication in tournaments: forfeits, halts, truncation, stalling, attribution (spec 11.4, 11.5)."""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

import pytest

from spellbench.arena import runner
from spellbench.arena.validate import validate_tournament_dir

from arena_helpers import BOT_HOSTILE, builtin, hostile_bot, ledger_rows, leaderboard, make_config, row_by_name, run, subprocess_bot

FAST = {"startup_ms": 30000, "game_start_ms": 30000, "bank_ms": 600000, "increment_ms": 0, "max_decision_ms": 500, "engine_step_ms": 30000}
TIGHT = {"max_decisions": 10000, "max_steps": 100000, "max_seat_decisions_per_turn": 20,
         "max_seat_decisions_per_game": 4999, "max_seat_steps_per_game": 49999}


def _duel(directory: Path, second: dict, **extra) -> runner.TournamentSummary:
    return run(make_config(directory, [builtin("heuristic"), second], pairs=1, include_self_play=False, **extra))


@pytest.mark.parametrize(
    ("mode", "cause"),
    [("out-of-range", "invalid_selection"), ("wrong-echo-semantic", "invalid_selection"), ("hang", "timeout"),
     ("garbage", "malformed_response"), ("nested", "malformed_response"), ("flood", "malformed_response"),
     ("bigint", "malformed_response"), ("surrogate-error", "malformed_response"), ("error-response", "agent_error"),
     ("crash", "transport_error")],
)
def test_a_bad_bot_forfeits_rated_losses_and_the_run_still_publishes(tmp_path: Path, mode: str, cause: str) -> None:
    directory = tmp_path / "t"
    summary = _duel(directory, hostile_bot(mode), time_control=FAST)
    assert (summary.status, summary.games_total, summary.games_forfeit, summary.games_rated) == ("complete", 2, 2, 2)
    assert {row["reason"] for row in ledger_rows(directory)} == {f"forfeit:{cause}"}
    offender = row_by_name(leaderboard(directory), "hostile")
    assert offender["forfeit_losses"] == 2 and offender["forfeits_by_cause"] == {cause: 2}
    assert validate_tournament_dir(directory) == []


@pytest.mark.parametrize(("mode", "reason"), [("stdout-noise", "hostile"), ("wrong-name", "hostile"), ("badname", "hello"),
                                              ("slow-hello", "hostile"), ("requires-poison", "poison")])
def test_a_bot_that_cannot_introduce_itself_stops_the_tournament_up_front(tmp_path: Path, mode: str, reason: str) -> None:
    directory = tmp_path / "t"
    with pytest.raises(runner.TournamentError, match=reason) as caught:
        _duel(directory, hostile_bot(mode), time_control={**FAST, "startup_ms": 2000})
    assert "Loading" not in str(caught.value)            # nothing the bot printed is quoted
    assert not directory.exists()


@pytest.mark.parametrize(
    ("deck", "classification", "reason", "counter"),
    [("Crash", "halted", "host_engine_fault:transport", "halts_attributed"),
     ("Halt", "halted", "engine_contract_failure:test_hook", "halts_attributed")],
)
def test_engine_endings_are_unrated_and_attributed(tmp_path: Path, deck, classification, reason, counter) -> None:
    directory = tmp_path / "t"
    summary = run(make_config(directory, [builtin("heuristic"), builtin("first")], decks=(deck, deck), pairs=1, include_self_play=False))
    rows = ledger_rows(directory)
    assert {(row["classification"], row["reason"]) for row in rows} == {(classification, reason)}
    assert all(row["last_selection"]["seat"] == "p0" for row in rows) and summary.games_rated == 0
    assert sum(entry[counter] for entry in leaderboard(directory)["rows"]) == 2


def test_an_engine_truncation_below_the_caps_is_a_violation_that_stops_the_run(tmp_path: Path) -> None:
    # Spec 9.2 as hardened: the validator accepts a truncated terminal only at a reached cap, and the
    # per-seat caps (each below half the game cap, spec 11.1) always rule first, so the Truncate hook's
    # first-step truncation halts as host_validator:V3 and the run stops on the violation (R3-13).
    directory = tmp_path / "t"
    summary = run(make_config(directory, [builtin("heuristic"), builtin("first")], decks=("Truncate", "Truncate"),
                              pairs=1, include_self_play=False))
    (row,) = ledger_rows(directory)
    assert (row["classification"], row["reason"], row["last_selection"]["seat"]) == ("halted", "host_validator:V3", "p0")
    assert (summary.status, summary.games_total, summary.games_rated) == ("invalid", 1, 0)
    assert sum(entry["halts_attributed"] for entry in leaderboard(directory)["rows"]) == 1


def test_stalling_and_mandatory_loops_are_adjudicated_at_the_caps(tmp_path: Path) -> None:
    loop = tmp_path / "loop"
    run(make_config(loop, [builtin("first"), builtin("heuristic")], decks=("Loop", "Loop"), pairs=1, include_self_play=False, limits=TIGHT))
    assert {row["reason"] for row in ledger_rows(loop)} == {"mandatory_loop"}
    stall = tmp_path / "stall"
    run(make_config(stall, [builtin("first"), builtin("heuristic")], decks=("Stall", "Stall"), pairs=1, include_self_play=False, limits=TIGHT))
    assert sorted(row["reason"] for row in ledger_rows(stall)) == ["forfeit:stalling", "stall_ended"]
    assert row_by_name(leaderboard(stall), "heuristic")["forfeits_by_cause"] == {"stalling": 1}


def test_adjudicated_rows_are_byte_identical_across_reruns(tmp_path: Path) -> None:
    for name in ("a", "b"):
        _duel(tmp_path / name, hostile_bot("crash"))     # the crashing bot prints its PID to stderr; none of it reaches the ledger
    assert (tmp_path / "a" / "matches.jsonl").read_bytes() == (tmp_path / "b" / "matches.jsonl").read_bytes()


def test_a_hung_bot_behind_a_wrapper_process_is_killed(tmp_path: Path) -> None:
    if os.name == "nt":
        wrapper = tmp_path / "wrap.bat"
        wrapper.write_text(f'@"{sys.executable}" "{BOT_HOSTILE}" hang\n', encoding="ascii")
        command = ["cmd", "/c", str(wrapper)]
    else:
        wrapper = tmp_path / "wrap.sh"
        wrapper.write_text(f'"{sys.executable}" "{BOT_HOSTILE}" hang\n', encoding="ascii")
        command = ["sh", str(wrapper)]
    directory = tmp_path / "t"
    outcome: list[BaseException | None] = []

    def play() -> None:
        try:
            _duel(directory, subprocess_bot("hostile", command), time_control=FAST)
            outcome.append(None)
        except BaseException as exc:
            outcome.append(exc)

    worker = threading.Thread(target=play, daemon=True)
    worker.start()
    worker.join(timeout=60)
    assert outcome == [None], "the host is still blocked on the hung bot's pipes"
    assert {row["reason"] for row in ledger_rows(directory)} == {"forfeit:timeout"}
