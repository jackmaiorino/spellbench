"""End-to-end arena tournaments against the fake engines, plus the CLI."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

import spellbench
from spellbench.arena import store
from spellbench.arena.cli import main as cli_main
from spellbench.arena.cli import validate_tournament_dir

from arena_helpers import (
    FAKE_ENGINE,
    TEST_RUN_SECRET,
    builtin,
    cli_bot,
    ledger_rows,
    leaderboard,
    make_config,
    matchup_by_names,
    row_by_name,
    roomy_machine,
    run,
    subprocess_bot,
)

ALL_BUILTINS = [builtin("uniform", seed=11), builtin("heuristic"), builtin("first")]
REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _roomy_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    """``spellbench run`` is a guarded launch (Decision 10): the tests fake the disk it checks."""
    roomy_machine(monkeypatch)


def test_the_package_version_is_the_project_version() -> None:
    # Runs record spellbench.__version__, and validate compares it with the running arena's.
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["version"] == spellbench.__version__


def test_round_robin_with_every_builtin_bot(tmp_path: Path) -> None:
    # The fake engine's P0Wins hook always ends in a natural p0 win, so every
    # seat-swapped pair splits 1-1: each bot finishes 4-0-4 over 8 seat-games
    # (a decisive mirror game is one win and one loss) and all ratings tie at
    # the anchor.
    directory = tmp_path / "t"
    summary = run(make_config(directory, ALL_BUILTINS, engine=FAKE_ENGINE, decks=("P0Wins", "P0Wins"), pairs=1))
    assert (summary.games_total, summary.games_rated) == (12, 12)
    rows = ledger_rows(directory)
    assert [row["game_id"] for row in rows] == [TEST_RUN_SECRET.game_id(index) for index in range(12)]
    assert {row["outcome"] for row in rows} == {"p0_win"}
    document = leaderboard(directory)
    assert document["status"] == "ok"
    for name in ("uniform", "heuristic", "first"):
        row = row_by_name(document, name)
        assert (row["games"], row["wins"], row["draws"], row["losses"]) == (8, 4, 0, 4)
        assert row["rating_log_units_e6"] == 0
        assert row["elo_milli"] == 1_000_000


def test_outcomes_follow_the_bots_choices(tmp_path: Path) -> None:
    # The fake engine's scoring game: heuristic always plays its land (2
    # points), first always passes (0 points), so heuristic wins every cross
    # game and both mirrors draw. One virtual draw per rated matchup keeps the
    # 4-0 record finite: heuristic 4.5 vs first 0.5, a rating gap of ln(9).
    directory = tmp_path / "t"
    run(make_config(directory, [builtin("heuristic"), builtin("first")], pairs=2))
    document = leaderboard(directory)
    heuristic = row_by_name(document, "heuristic")
    first = row_by_name(document, "first")
    assert (heuristic["games"], heuristic["wins"], heuristic["draws"], heuristic["losses"]) == (12, 4, 8, 0)
    assert (first["games"], first["wins"], first["draws"], first["losses"]) == (12, 0, 8, 4)
    assert document["status"] == "ok"
    assert heuristic["rating_log_units_e6"] == 0
    assert first["rating_log_units_e6"] == round(-math.log(9) * 1_000_000)
    assert [row["name"] for row in document["rows"]] == ["heuristic", "first"]
    cross = matchup_by_names(document, "heuristic", "first")
    assert cross["games"] == 4 and cross["draws"] == 0
    assert {cross["a_wins"], cross["b_wins"]} == {4, 0}


def test_mirror_matchups_carry_no_paired_statistics(tmp_path: Path) -> None:
    # A bot holding both seats cannot beat itself: no score CI or sign test.
    directory = tmp_path / "t"
    run(make_config(directory, [builtin("heuristic"), builtin("first")], pairs=2))
    for name in ("heuristic", "first"):
        mirror = matchup_by_names(leaderboard(directory), name, name)
        assert mirror["games"] == 4
        assert mirror["a_score"]["num"] * 2 == mirror["a_score"]["den"]
        assert mirror["a_score_ci95"] is None
        assert mirror["sign_test"] is None


def test_training_style_subratings_refit_only_games_inside_the_tag(tmp_path: Path) -> None:
    # "rl" holds heuristic and first: their slice keeps heuristic-vs-first
    # games (4-0, so ln(9) apart under the prior) and drops every uniform
    # game. "baseline" holds only uniform, so it cannot be rated.
    directory = tmp_path / "t"
    bots = [
        builtin("uniform", seed=11, training_style_tags=["baseline"]),
        builtin("heuristic", training_style_tags=["rl"]),
        builtin("first", training_style_tags=["rl"]),
    ]
    run(make_config(directory, bots, pairs=2))
    subratings = {sub["tag"]: sub for sub in leaderboard(directory)["subratings"]}
    assert (subratings["baseline"]["status"], subratings["baseline"]["reason"]) == ("skipped", "fewer_than_two_bots")
    rl = subratings["rl"]
    assert rl["status"] == "ok"
    rows = {row["name"]: row for row in rl["rows"]}
    assert set(rows) == {"heuristic", "first"}
    assert (rows["heuristic"]["games"], rows["heuristic"]["wins"], rows["heuristic"]["losses"]) == (12, 4, 0)
    gap = rows["heuristic"]["rating_log_units_e6"] - rows["first"]["rating_log_units_e6"]
    assert abs(gap - math.log(9) * 1_000_000) <= 1


def test_rerun_of_an_identical_config_is_byte_identical(tmp_path: Path) -> None:
    first_dir, second_dir = tmp_path / "a", tmp_path / "b"
    run(make_config(first_dir, ALL_BUILTINS, pairs=2))
    run(make_config(second_dir, ALL_BUILTINS, pairs=2))
    for name in ("matches.jsonl", "registry.json", "leaderboard.json", "LEADERBOARD.md"):
        assert (first_dir / name).read_bytes() == (second_dir / name).read_bytes(), name
    # Non-vacuous: uniform's seeded choices must vary the results (a draw
    # needs uniform to play both lands; a heuristic win needs it to pass).
    versus_heuristic = [
        row["outcome"]
        for row in ledger_rows(first_dir)
        if {seat["name"] for seat in row["seats"]} == {"uniform", "heuristic"}
    ]
    assert "draw" in versus_heuristic
    assert any(outcome != "draw" for outcome in versus_heuristic)


def _flip_first_cross_game(directory: Path) -> None:
    """Rewrite one heuristic-vs-first win as a first win (a consistent row)."""
    rows = ledger_rows(directory)
    for row in rows:
        names = {seat["seat"]: seat for seat in row["seats"]}
        if {seat["name"] for seat in row["seats"]} == {"heuristic", "first"}:
            loser_seat = "p1" if row["winner"] == "p0" else "p0"
            row["outcome"] = f"{loser_seat}_win"
            row["winner"] = loser_seat
            row["winner_bot_id"] = names[loser_seat]["bot_id"]
            break
    else:
        raise AssertionError("no heuristic-vs-first game in the ledger")
    data = b"".join(store.canonical_bytes(row) + b"\n" for row in rows)
    (directory / "matches.jsonl").write_bytes(data)


def test_validate_rederives_ratings_and_catches_tampering(tmp_path: Path) -> None:
    directory = tmp_path / "t"
    run(make_config(directory, ALL_BUILTINS, pairs=1))
    assert validate_tournament_dir(directory) == []

    _flip_first_cross_game(directory)
    failures = validate_tournament_dir(directory)
    assert "digest mismatch: matches.jsonl" in failures

    # A forger who also refreshes the manifest digest is still caught: the
    # published leaderboard no longer matches a recomputation from the ledger.
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        if entry["path"] == "matches.jsonl":
            entry.update(store.file_entry(directory / "matches.jsonl", "matches.jsonl"))
    manifest_path.write_bytes(store.canonical_bytes(manifest) + b"\n")
    failures = validate_tournament_dir(directory)
    assert "leaderboard.json does not match a recomputation from matches.jsonl" in failures
    assert not any(failure.startswith("digest mismatch") for failure in failures)


def test_cli_run_validate_and_leaderboard(tmp_path: Path, capsys) -> None:
    directory = tmp_path / "t"
    config_path = tmp_path / "config.json"
    config_path.write_bytes(
        store.canonical_bytes(make_config(directory, [builtin("heuristic"), builtin("first")], pairs=1))
    )
    assert cli_main(["run", str(config_path)]) == 0
    assert cli_main(["validate", str(directory)]) == 0
    capsys.readouterr()
    assert cli_main(["leaderboard", str(directory)]) == 0
    printed = capsys.readouterr().out
    assert "| 1 | heuristic 2.0.0 |" in printed
    assert cli_main(["validate", str(tmp_path / "missing")]) == 1
    assert cli_main(["run", str(config_path)]) == 1  # refuses to overwrite a published run
    assert cli_main([]) == 2


def test_builtin_bot_served_over_stdio_plays_like_the_in_process_bot(tmp_path: Path) -> None:
    in_process = tmp_path / "in-process"
    over_stdio = tmp_path / "over-stdio"
    run(make_config(in_process, [builtin("heuristic"), builtin("uniform", seed=11)], pairs=2))
    run(
        make_config(
            over_stdio,
            [
                subprocess_bot("heuristic", cli_bot("heuristic"), version="2.0.0"),
                subprocess_bot("uniform", cli_bot("uniform", "--seed", "11"), version="2.0.0"),
            ],
            pairs=2,
        )
    )
    expected = [(row["game_id"], row["outcome"]) for row in ledger_rows(in_process)]
    assert [(row["game_id"], row["outcome"]) for row in ledger_rows(over_stdio)] == expected


def test_the_cli_module_leaves_the_benchmark_and_site_code_unloaded() -> None:
    # `spellbench bot` starts once per seat per game and needs neither.
    code = (
        "import sys, spellbench.arena.cli; "
        "print(sorted(name for name in sys.modules if name.startswith(('spellbench.bench', 'spellbench.site'))))"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "[]"


def _refresh_manifest(directory: Path, edit=None) -> None:
    """Re-sign every data file in the manifest (what a careful forger does)."""
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"] = [store.file_entry(directory / entry["path"], entry["path"]) for entry in manifest["files"]]
    if edit is not None:
        edit(manifest)
    manifest_path.write_bytes(store.canonical_bytes(manifest) + b"\n")


def test_validate_needs_nothing_outside_the_tournament_directory(tmp_path: Path) -> None:
    # The anchor's checkpoint is hashed into its bot_id at registration; a
    # published tournament must validate after the checkpoint moves.
    checkpoint = tmp_path / "weights.bin"
    checkpoint.write_bytes(b"weights")
    bots = [
        subprocess_bot("heuristic", cli_bot("heuristic"), version="2.0.0", checkpoint=str(checkpoint)),
        builtin("first"),
    ]
    directory = tmp_path / "t"
    run(make_config(directory, bots, pairs=1))
    checkpoint.unlink()
    assert validate_tournament_dir(directory) == []


def test_validate_requires_every_data_file_in_the_manifest(tmp_path: Path) -> None:
    directory = tmp_path / "t"
    run(make_config(directory, [builtin("heuristic"), builtin("first")], pairs=1, include_self_play=False))
    _refresh_manifest(directory, edit=lambda manifest: manifest.update(files=[]))
    assert any("manifest" in failure for failure in validate_tournament_dir(directory))


def test_validate_checks_the_ledger_against_the_schedule(tmp_path: Path) -> None:
    # A row moved off its scheduled game id changes no rating, so only a
    # schedule check can catch it.
    directory = tmp_path / "t"
    run(make_config(directory, [builtin("heuristic"), builtin("first")], pairs=1, include_self_play=False))
    rows = ledger_rows(directory)
    rows[0]["game_id"] = TEST_RUN_SECRET.game_id(len(rows))  # another game id of this run, scheduled for no game
    (directory / "matches.jsonl").write_bytes(b"".join(store.canonical_bytes(row) + b"\n" for row in rows))
    _refresh_manifest(directory)
    assert any("schedule" in failure for failure in validate_tournament_dir(directory))


def test_validate_checks_the_manifest_game_counts(tmp_path: Path) -> None:
    directory = tmp_path / "t"
    run(make_config(directory, [builtin("heuristic"), builtin("first")], pairs=1, include_self_play=False))
    _refresh_manifest(directory, edit=lambda manifest: manifest["games"].update(natural=0))
    assert any("games" in failure for failure in validate_tournament_dir(directory))


def _as_published_by_arena_0_1_0(directory: Path) -> None:
    """Rewrite a run the way arena 0.1.0 published it: no "slices" in leaderboard.json."""
    document = leaderboard(directory)
    del document["slices"]
    (directory / "leaderboard.json").write_bytes(store.canonical_bytes(document) + b"\n")
    _refresh_manifest(directory, edit=lambda manifest: manifest["tournament"].update(arena_version="0.1.0"))


def test_a_run_made_by_another_arena_version_fails_with_one_clear_message(tmp_path: Path, capsys) -> None:
    # Leaderboard output changes between versions, so recomputing an older
    # run would only report mismatches that read like tampering.
    directory = tmp_path / "t"
    run(make_config(directory, [builtin("heuristic"), builtin("first")], pairs=1, include_self_play=False))
    _as_published_by_arena_0_1_0(directory)
    message = (
        f"this run was made by spellbench arena 0.1.0; this is {spellbench.__version__}: "
        "rerun the benchmark, or validate with arena 0.1.0"
    )
    assert validate_tournament_dir(directory) == [message]
    capsys.readouterr()
    assert cli_main(["validate", str(directory)]) == 1
    assert capsys.readouterr().err.splitlines() == [f"FAIL {message}"]


def test_an_unprintable_recorded_version_is_quoted(tmp_path: Path) -> None:
    # The message reaches terminals and CI logs, where a line starting "::" is a workflow command.
    directory = tmp_path / "t"
    run(make_config(directory, [builtin("heuristic"), builtin("first")], pairs=1, include_self_play=False))
    forged = "0.1.0\n::error::forged"
    _refresh_manifest(directory, edit=lambda manifest: manifest["tournament"].update(arena_version=forged))
    assert validate_tournament_dir(directory) == [
        f"this run was made by spellbench arena '0.1.0\\n::error::forged'; this is {spellbench.__version__}: "
        "rerun the benchmark, or validate with arena '0.1.0\\n::error::forged'"
    ]


_VERSION = json.dumps(spellbench.__version__)  # the running version as a failure line quotes it


@pytest.mark.parametrize(
    ("edit", "expected"),
    [
        (
            lambda manifest: manifest["tournament"].pop("arena_version"),
            f"manifest tournament.arena_version is missing; recomputed: {_VERSION}",
        ),
        (
            lambda manifest: manifest["tournament"].update(arena_version=["0.1.0"]),
            f"manifest tournament.arena_version is a list of 1 items; recomputed: {_VERSION}",
        ),
        (
            lambda manifest: manifest.update(tournament=[]),
            "manifest tournament is a list of 0 items; recomputed: an object",
        ),
    ],
    ids=["missing", "not-a-string", "tournament-not-an-object"],
)
def test_a_manifest_without_a_version_string_is_a_failure_not_a_crash(tmp_path: Path, edit, expected: str) -> None:
    # The version gate reads only a version string; anything else fails the comparison with the rebuilt manifest.
    directory = tmp_path / "t"
    run(make_config(directory, [builtin("heuristic"), builtin("first")], pairs=1, include_self_play=False))
    _refresh_manifest(directory, edit=edit)
    assert validate_tournament_dir(directory) == [expected]


def test_the_two_games_of_a_pair_have_independent_secrets(tmp_path: Path) -> None:
    directory = tmp_path / "t"
    run(make_config(directory, [builtin("uniform", seed=11), builtin("first")], decks=("Echo", "Echo"), pairs=1,
                    include_self_play=False))
    first, second = ledger_rows(directory)
    assert (first["pair_index"], second["pair_index"]) == (0, 0)
    received = [row["reason"] for row in (first, second)]              # the Echo hook reports a hash of the secret it got
    assert received == ["secret:" + hashlib.sha256(TEST_RUN_SECRET.game_secret(index)).hexdigest()[:8] for index in (0, 1)]
    assert received[0] != received[1]                                  # what each engine received differs (R3-16)
