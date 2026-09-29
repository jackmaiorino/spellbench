"""Host adjudication in tournaments: forfeits, halts, truncation, stalling, attribution (spec 11.4, 11.5).

Each run is two bots without self-play, one seat-swapped pair: pair slot 0 seats the first bot at p0, slot 1 the
second. p0 starts every game (``host_assigned``), so it answers step 0 of the fake engine's games.

Truncation: an engine may end a game ``truncated`` (winner ``null``, spec 9.5) only at a reached ``max_steps`` or
``max_decisions`` (spec 9.2), and every per-seat cap is below half of its game cap, the host ruling as soon as a seat
reaches one (spec 11.4). No valid v2 game is truncated: a truncated terminal below the caps is a V3 violation.
"""

from __future__ import annotations

import math
import os
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

from spellbench.arena import runner
from spellbench.arena.validate import validate_tournament_dir

from arena_helpers import (
    BOT_HOSTILE,
    builtin,
    hostile_bot,
    ledger_rows,
    leaderboard,
    make_config,
    manifest,
    row_by_name,
    run,
    subprocess_bot,
)

# Room for a slow Windows runner: an answer that arrives past its budget is a timeout whatever it holds (spec 11.4),
# so only a bot that never answers gets the short decision budget. game_start_ms also bounds each game_over ack.
ROOMY = {"startup_ms": 30000, "game_start_ms": 3000, "bank_ms": 600000, "increment_ms": 0, "max_decision_ms": 10000,
         "engine_step_ms": 30000}
HANG = {**ROOMY, "max_decision_ms": 500}
TIGHT = {"max_decisions": 10000, "max_steps": 100000, "max_seat_decisions_per_turn": 20,
         "max_seat_decisions_per_game": 4999, "max_seat_steps_per_game": 49999}
# The smallest caps a config accepts around a game cap of 5; the scoring game needs 4 answers to finish.
SMALL = {"max_decisions": 5, "max_steps": 5, "max_seat_decisions_per_turn": 2, "max_seat_decisions_per_game": 2,
         "max_seat_steps_per_game": 2}
NOT_A_MESSAGE = "the answer to choose was not a valid protocol message"
NOT_A_HELLO = "the answer to hello was not a valid protocol message"
# Each bot_v2_hostile mode that forfeits in a game: its cause and the adjudication's detail (spec 11.5).
FORFEITS: dict[str, tuple[str, str]] = {
    "out-of-range": ("invalid_selection", "candidate_id 999 is outside the 2 candidates"),
    "wrong-echo-semantic": ("invalid_selection", "semantic_echo does not match the chosen candidate"),
    "hang": ("timeout", "no answer to choose within 500 ms"),
    "garbage": ("malformed_response", NOT_A_MESSAGE),
    "nested": ("malformed_response", NOT_A_MESSAGE),
    "deep65": ("malformed_response", NOT_A_MESSAGE),
    # The host stops reading a line past the cap, so it waits out game_start_ms for this bot's game_over ack.
    "flood": ("malformed_response", NOT_A_MESSAGE),
    "bigint": ("malformed_response", NOT_A_MESSAGE),
    "string-id": ("malformed_response", NOT_A_MESSAGE),
    "surrogate-error": ("malformed_response", NOT_A_MESSAGE),
    "error-response": ("agent_error", "choose was answered with an error (internal_error)"),
    "crash": ("transport_error", "the bot process failed during choose"),
}
# Each mode preflight refuses: the startup_ms it runs under and the whole refusal.
REFUSALS: dict[str, tuple[int, str]] = {
    # A library banner on stdout before hello_ok (Review Focus 1): the bot is named, nothing it printed quoted.
    "stdout-noise": (30000, f"preflight: bot 'hostile': malformed_response: {NOT_A_HELLO}"),
    "wrong-name": (30000, "preflight: bot 'hostile': answered hello as 'impostor' '1.0.0'"),
    "badname": (30000, f"preflight: bot 'hostile': malformed_response: {NOT_A_HELLO}"),
    # startup_ms also bounds the engine's hello, hence room above a slow runner's process start.
    "slow-hello": (5000, "preflight: bot 'hostile': timeout: no answer to hello within 5000 ms"),
    "requires-poison": (30000, "preflight: bot 'hostile': requires the observation flag 'poison', which the engine "
                               "does not declare"),
}
# Each fake engine hook that ends a game at its first step: the reason and the host's adjudication.
ENGINE_ENDINGS: dict[str, tuple[str, dict[str, str] | None]] = {
    "Crash": ("host_engine_fault:transport", {"kind": "halt", "detail": "the engine process failed at step 0"}),
    # The engine's own halted terminal: its answer records it, so the host adds no adjudication (spec 11.5).
    "Halt": ("engine_contract_failure:test_hook", None),
}
# The fake engine's Truncate hook ends the game at its first step.
TRUNCATED_BELOW_CAPS = ("a truncated terminal after 1 answered decisions and 1 completed groups, below max_steps "
                        "100000 and max_decisions 10000")


def _duel(directory: Path, second: dict[str, Any], **extra: Any) -> runner.TournamentSummary:
    """heuristic against ``second``: slot 0 seats heuristic at p0, slot 1 seats ``second`` there."""
    return run(make_config(directory, [builtin("heuristic"), second], pairs=1, include_self_play=False, **extra))


def _endings(directory: Path) -> list[tuple[Any, ...]]:
    """Each row's pair slot, outcome, classification, winner, reason, adjudication, step count, last selection seat."""
    return [(row["pair_slot"], row["outcome"], row["classification"], row["winner"], row["reason"], row["adjudication"],
             row["step_count"], row["last_selection"] and row["last_selection"]["seat"])
            for row in ledger_rows(directory)]


def _forfeit(slot: int, loser: str, cause: str, detail: str, steps: int) -> tuple[Any, ...]:
    """The ending of a forfeit by ``loser`` (spec 11.5)."""
    winner = "p1" if loser == "p0" else "p0"
    adjudication = {"kind": "forfeit", "cause": cause, "loser_seat": loser, "detail": detail}
    return (slot, f"{winner}_win", "forfeit", winner, f"forfeit:{cause}", adjudication, steps, None)


@pytest.mark.parametrize("mode", list(FORFEITS))
def test_a_bad_bot_forfeits_rated_losses_and_the_run_still_publishes(tmp_path: Path, mode: str) -> None:
    cause, detail = FORFEITS[mode]
    directory = tmp_path / "t"
    summary = _duel(directory, hostile_bot(mode), time_control=HANG if mode == "hang" else ROOMY)
    assert (summary.status, summary.games_total, summary.games_forfeit, summary.games_rated) == ("complete", 2, 2, 2)
    # The bad bot answers at step 1 as p1 (slot 0) and at step 0 as p0 (slot 1): every forfeit is its own.
    assert _endings(directory) == [_forfeit(0, "p1", cause, detail, 1), _forfeit(1, "p0", cause, detail, 0)]
    document = leaderboard(directory)
    offender = row_by_name(document, "hostile")
    assert (offender["games"], offender["wins"], offender["draws"], offender["losses"]) == (2, 0, 0, 2)
    assert (offender["forfeit_losses"], offender["forfeits_by_cause"]) == (2, {cause: 2})
    # A forfeit is a rated loss (spec 11.5), or a losing bot could erase its losses by misbehaving:
    # heuristic 2-0 plus one virtual draw is 2.5 to 0.5, ln(5) apart.
    assert offender["rating_log_units_e6"] == round(-math.log(5) * 1_000_000)
    assert row_by_name(document, "heuristic")["forfeit_losses"] == 0
    assert validate_tournament_dir(directory) == []


@pytest.mark.parametrize("mode", list(REFUSALS))
def test_a_bot_that_cannot_introduce_itself_stops_the_tournament_up_front(tmp_path: Path, mode: str) -> None:
    # A bot that fails hello is a config problem: preflight refuses the tournament before its directory exists.
    startup_ms, message = REFUSALS[mode]
    directory = tmp_path / "t"
    with pytest.raises(runner.TournamentError) as caught:
        _duel(directory, hostile_bot(mode), time_control={**ROOMY, "startup_ms": startup_ms})
    assert str(caught.value) == message
    assert not directory.exists()


def test_a_bot_that_logs_to_stdout_after_preflight_forfeits_each_game(tmp_path: Path) -> None:
    # Review Focus 1, mid-run: the launcher serves preflight's hello well (crlf is tolerated, spec 2), then prints a
    # library banner before every later hello_ok.
    launcher = tmp_path / "launch.py"
    launcher.write_text("import os, runpy, sys\n"
                        "marker, bot = sys.argv[1], sys.argv[2]\n"
                        "mode = 'stdout-noise' if os.path.exists(marker) else 'crlf'\n"
                        "open(marker, 'a').close()\n"
                        "sys.argv = [bot, mode]\n"
                        "runpy.run_path(bot, run_name='__main__')\n", encoding="utf-8", newline="\n")
    directory = tmp_path / "t"
    command = [sys.executable, str(launcher), str(tmp_path / "preflight-done"), str(BOT_HOSTILE)]
    summary = _duel(directory, subprocess_bot("hostile", command), time_control=ROOMY)
    assert (summary.status, summary.games_forfeit, summary.games_rated) == ("complete", 2, 2)
    assert _endings(directory) == [_forfeit(0, "p1", "malformed_response", NOT_A_HELLO, 0),
                                   _forfeit(1, "p0", "malformed_response", NOT_A_HELLO, 0)]
    assert validate_tournament_dir(directory) == []


@pytest.mark.parametrize("deck", list(ENGINE_ENDINGS))
def test_engine_endings_are_unrated_and_attributed(tmp_path: Path, deck: str) -> None:
    reason, adjudication = ENGINE_ENDINGS[deck]
    directory = tmp_path / "t"
    summary = run(make_config(directory, [builtin("heuristic"), builtin("first")], decks=(deck, deck), pairs=1,
                              include_self_play=False))
    assert (summary.status, summary.games_total, summary.games_halted, summary.games_rated) == ("complete", 2, 2, 0)
    # Each game ends at its first step, after p0's selection, which the halt is attributed to (spec 11.5).
    assert _endings(directory) == [(slot, "halted", "halted", None, reason, adjudication, 1, "p0") for slot in (0, 1)]
    document = leaderboard(directory)
    assert document["status"] == "no_rated_games"
    assert {row["name"]: (row["halts_attributed"], row["truncations_attributed"]) for row in document["rows"]} == {
        "heuristic": (1, 0), "first": (1, 0)}
    assert validate_tournament_dir(directory) == []


def test_an_engine_truncation_below_the_caps_is_a_validator_halt_that_stops_the_run(tmp_path: Path) -> None:
    # An engine truncates only at a reached game cap (spec 9.2) and the host rules at the seat caps first (spec 11.4),
    # so this truncation at the first step is a V3 violation (spec 11.3): the game halts, the halt is attributed to
    # the selection before it (spec 11.5), and the run stops invalid at that game (Decision 6).
    directory = tmp_path / "t"
    summary = run(make_config(directory, [builtin("heuristic"), builtin("first")], decks=("Truncate", "Truncate"),
                              pairs=1, include_self_play=False))
    counts = (summary.games_total, summary.games_truncated, summary.games_halted, summary.games_rated)
    assert (summary.status, counts) == ("invalid", (1, 0, 1, 0))
    [row] = ledger_rows(directory)
    assert _endings(directory) == [(0, "halted", "halted", None, "host_validator:V3",
                                    {"kind": "halt", "detail": TRUNCATED_BELOW_CAPS}, 1, "p0")]
    assert {entry["name"]: (entry["halts_attributed"], entry["truncations_attributed"])
            for entry in leaderboard(directory)["rows"]} == {"heuristic": (1, 0), "first": (0, 0)}
    assert manifest(directory)["validator"]["violations"] == [
        {"game_index": 0, "game_id": row["game_id"], "rule": "V3", "detail": TRUNCATED_BELOW_CAPS}]
    assert validate_tournament_dir(directory) == []


def test_a_game_that_reaches_small_caps_is_adjudicated_never_truncated(tmp_path: Path) -> None:
    # v1 truncated every game at max_steps 2. In v2 the host rules when a seat reaches its cap (spec 11.4): p0 reaches
    # 2 decisions at the third answer, and the seat with more real choices in the window, heuristic playing its
    # lands against first's passes, forfeits as stalling.
    directory = tmp_path / "t"
    summary = run(make_config(directory, [builtin("heuristic"), builtin("first")], pairs=1, include_self_play=False,
                              limits=SMALL))
    assert (summary.games_total, summary.games_truncated, summary.games_forfeit, summary.games_rated) == (2, 0, 2, 2)
    capped = "p0 reached max_seat_decisions_per_game (2); real choices in the last 250 decisions: "
    assert _endings(directory) == [_forfeit(0, "p0", "stalling", capped + "p0 2, p1 0", 3),
                                   _forfeit(1, "p1", "stalling", capped + "p0 0, p1 1", 3)]
    assert validate_tournament_dir(directory) == []


def test_stalling_and_mandatory_loops_are_adjudicated_at_the_caps(tmp_path: Path) -> None:
    loop, stall = tmp_path / "loop", tmp_path / "stall"
    for directory, deck in ((loop, "Loop"), (stall, "Stall")):
        run(make_config(directory, [builtin("first"), builtin("heuristic")], decks=(deck, deck), pairs=1,
                        include_self_play=False, limits=TIGHT))
        assert validate_tournament_dir(directory) == []
    # Loop offers only [pass], so p0's 20th answer in the turn is a mandatory-loop draw (CR 104.4b).
    loop_detail = "p0 reached max_seat_decisions_per_turn (20); no real choice in the last 250 decisions"
    assert _endings(loop) == [(slot, "draw", "natural", None, "mandatory_loop",
                               {"kind": "mandatory_loop", "detail": loop_detail}, 39, None) for slot in (0, 1)]
    # Stall: first passes at once, the engine's own draw; heuristic activates its Relic until its cap, and forfeits.
    stall_detail = "p0 reached max_seat_decisions_per_turn (20); real choices in the last 250 decisions: p0 20, p1 0"
    assert _endings(stall) == [(0, "draw", "natural", None, "stall_ended", None, 1, None),
                               _forfeit(1, "p0", "stalling", stall_detail, 39)]
    assert row_by_name(leaderboard(stall), "heuristic")["forfeits_by_cause"] == {"stalling": 1}


def test_adjudicated_rows_are_byte_identical_across_reruns(tmp_path: Path) -> None:
    # The crashing bot prints its pid to stderr: nothing peer-controlled may reach the ledger, or identical configs
    # stop reproducing.
    for name in ("a", "b"):
        _duel(tmp_path / name, hostile_bot("crash"), time_control=ROOMY)
    assert {row["reason"] for row in ledger_rows(tmp_path / "a")} == {"forfeit:transport_error"}
    assert (tmp_path / "a" / "matches.jsonl").read_bytes() == (tmp_path / "b" / "matches.jsonl").read_bytes()


def test_a_hung_bot_behind_a_wrapper_process_is_killed(tmp_path: Path) -> None:
    # A wrapper (a .bat, sh without exec, conda run) keeps the real bot as a grandchild that holds the pipes; closing
    # must kill the whole tree instead of waiting on a pipe that never closes.
    line = f'"{sys.executable}" "{BOT_HOSTILE}" hang\n'
    if os.name == "nt":
        wrapper, line = tmp_path / "wrap.bat", "@" + line
        command = ["cmd", "/c", str(wrapper)]
    else:
        wrapper = tmp_path / "wrap.sh"
        command = ["sh", str(wrapper)]
    wrapper.write_text(line, encoding="ascii", newline="\n")
    directory = tmp_path / "t"
    outcome: list[BaseException | None] = []

    def play() -> None:
        try:
            _duel(directory, subprocess_bot("hostile", command), time_control=HANG)
            outcome.append(None)
        except BaseException as exc:
            outcome.append(exc)

    worker = threading.Thread(target=play, daemon=True)
    worker.start()
    worker.join(timeout=60)
    assert outcome, "the host is still blocked on the hung bot's pipes"
    assert outcome == [None]
    cause, detail = FORFEITS["hang"]
    assert _endings(directory) == [_forfeit(0, "p1", cause, detail, 1), _forfeit(1, "p0", cause, detail, 0)]
