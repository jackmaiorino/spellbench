"""pauper-ladder-v3: every ordered deck pairing on the ladder, a deferred entrant, no per-deck ratings, and a
definition that ``bench prepare`` reproduces."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from arena_helpers import TEST_RUN_SECRET, builtin, leaderboard, make_config, roomy_machine, run
from spellbench.arena import cli, store
from spellbench.arena.config import TournamentConfig, TournamentError
from spellbench.arena.leaderboard import NO_DECK_SLICES_NOTE
from spellbench.arena.schedule import schedule
from spellbench.arena.validate import validate_tournament_dir
from spellbench.bench import definition, panel
from spellbench.site import render
from test_ladder import completed, copied, ladder_value  # noqa: F401 - completed is a fixture
from test_panel import play, write_definition
from test_site_render import BENCH

REPO = Path(__file__).resolve().parents[2]
BOARD = REPO / "benchmarks" / "pauper-ladder-v3"
SEARCH_ENTRANT = "oh2-r2s1-b512-s4a-16k-k4"
RUNGS = ["uniform", "heuristic", "c12", "gorge-ar8", "g115", "oh2-r2s1-b512", "oh2-r2s1-b512-argmax"]


# ---------------- the committed board ----------------


def test_the_board_plays_every_ordered_pairing_in_every_block() -> None:
    benchmark = definition.load_benchmark(BOARD)
    assert benchmark.pairing == "all_pairs" and list(benchmark.opponent_panel) == RUNGS
    assert len(benchmark.deck_pool) == 8 and benchmark.evaluation_version == "pauper-ladder-v3.0.0"
    config = TournamentConfig.from_json(benchmark.tournament_config("runs/check"))
    games = schedule(config, TEST_RUN_SECRET)
    # Fifteen rung blocks (seven rungs, band 3) and Basilisk 2's three: 18 blocks of 64 pairs, 2,304 games.
    assert (len(config.matchups), config.pairs_per_matchup, len(games)) == (18, 64, 2304)
    assert SEARCH_ENTRANT not in {bot.name for bot in config.bots}
    for matchup in range(len(config.matchups)):
        block = [game for game in games if game.matchup_index == matchup]
        pairings = Counter((game.decks[0].catalog_id, game.decks[1].catalog_id) for game in block)
        assert len(pairings) == 64 and set(pairings.values()) == {2}  # one seat-swapped pair per ordered pairing
        seats = Counter((spec.name, seat, game.decks[int(seat[1])].catalog_id, game.decks[1 - int(seat[1])].catalog_id)
                        for game in block for seat, spec in game.seat_specs)
        # Each bot holds every deck against every deck once on the play and once on the draw.
        assert len(seats) == 2 * 2 * 64 and set(seats.values()) == {1}


def test_the_board_names_its_validity_unit_and_publishes_no_deck_ratings() -> None:
    benchmark = definition.load_benchmark(BOARD)
    config = TournamentConfig.from_json(benchmark.tournament_config("runs/check"))
    assert config.to_json()["validity"] == {
        "unit": "spellbench-validity/v1", "block_natural_permille": 970, "block_complete_pairs_permille": 970,
        "rung_natural_permille": 970, "pairing_natural_permille": 900}
    assert config.to_json()["deck_slices"] is False
    assert benchmark.excluded_runs == ()


def test_the_search_entrant_is_listed_and_not_scheduled() -> None:
    raw = json.loads((BOARD / "benchmark.json").read_bytes())
    benchmark = definition.load_benchmark(BOARD)
    assert benchmark.deferred_entrants == (SEARCH_ENTRANT,) and benchmark.bot(SEARCH_ENTRANT) is not None
    assert SEARCH_ENTRANT in benchmark.ladder.entrants
    assert all(SEARCH_ENTRANT not in pair for pair in raw["evaluation_matchups"])
    assert SEARCH_ENTRANT not in raw["evaluation_targets"] and len(raw["evaluation_matchups"]) == 18
    assert all("evaluation_identity" in bot for bot in raw["bots"])  # prepared, the deferred entrant included


def test_the_board_text_follows_the_wording_rules() -> None:
    raw = json.loads((BOARD / "benchmark.json").read_bytes())
    receipt = (BOARD / "ENGINE-AUDITS.json").read_text(encoding="utf-8")
    text = json.dumps(raw, ensure_ascii=False) + receipt
    assert "—" not in text and "cancels exactly" not in text and "cancel exactly" not in text
    assert "not comparable with pauper-ladder-v2" in raw["summary"]
    assert "per-deck ratings are not published" in raw["summary"]


# ---------------- deck_slices ----------------


def test_a_board_can_publish_no_per_deck_ratings(tmp_path: Path, monkeypatch: Any) -> None:
    roomy_machine(monkeypatch)
    bots = [builtin("uniform", seed=3), builtin("first"), builtin("heuristic")]
    settings = {"deck_pool": ("Burn", "Elves", "Faeries"), "pairs": 9, "deck_pairing": "all_pairs",
                "include_self_play": False}
    plain = make_config(tmp_path / "plain", bots, **settings)
    quiet = make_config(tmp_path / "quiet", bots, deck_slices=False, **settings)
    assert "deck_slices" not in TournamentConfig.from_json(plain).to_json()  # the default keeps its bytes
    assert TournamentConfig.from_json(quiet).to_json()["deck_slices"] is False
    run(plain, rated=True)
    run(quiet, rated=True)
    with_slices, without = leaderboard(tmp_path / "plain"), leaderboard(tmp_path / "quiet")
    assert len(with_slices["slices"]["deck"]) == 3 and without["slices"] == {"deck": []}
    assert without["deck_grid"] == with_slices["deck_grid"] and without["rows"] == with_slices["rows"]
    assert NO_DECK_SLICES_NOTE in without["notes"] and NO_DECK_SLICES_NOTE not in with_slices["notes"]
    assert not any(note.startswith("deck slices ") for note in without["notes"])
    markdown = (tmp_path / "quiet" / "LEADERBOARD.md").read_text(encoding="utf-8")
    assert "## By deck" not in markdown and "## Deck grid" in markdown
    assert validate_tournament_dir(tmp_path / "quiet") == [] and validate_tournament_dir(tmp_path / "plain") == []
    with pytest.raises(TournamentError, match="deck_slices"):
        TournamentConfig.from_json({**quiet, "deck_slices": "no"})


def test_the_page_says_why_a_grid_board_has_no_deck_tables() -> None:
    page = render.render_benchmark({**BENCH, "deck_tables": [], "deck_pairing": "all_pairs"})
    assert "This board publishes no per-deck ratings" in page
    assert "This benchmark uses one deck pairing" in render.render_benchmark({**BENCH, "deck_tables": []})


# ---------------- deferred entrants ----------------


def test_a_deferred_entrant_is_pending_and_never_scheduled(completed, tmp_path: Path) -> None:  # noqa: F811
    directory = copied(completed, tmp_path)
    raw = json.loads((directory / "benchmark.json").read_bytes())
    raw["bots"][0]["seed"] = 101  # uniform changes, so its two blocks are missing
    raw["bots"][-1]["command"].append("--changed")  # and the entrant's block with them
    raw["deferred_entrants"] = ["cached-llm"]
    write_definition(directory, raw)
    assert panel.prepare_benchmark(directory) == ("first", "heuristic", "uniform")
    prepared = definition.load_benchmark(directory)
    assert {tuple(sorted(pair)) for pair in prepared.evaluation_matchups} == {("first", "uniform"),
                                                                             ("heuristic", "uniform")}
    config = TournamentConfig.from_json(prepared.tournament_config("runs/2026-10-02"))
    assert "cached-llm" not in {bot.name for bot in config.bots} and config.ladder.entrants == {}
    play(directory, "2026-10-02")
    assert panel.prepare_benchmark(directory) == ()  # nothing left to play while the entrant is deferred
    composed = panel.compose_benchmark(directory, date="2026-10-02")
    assert validate_tournament_dir(composed) == []
    board = store.read_json(composed / "leaderboard.json")
    assert board["evaluation"]["pending"] == ["cached-llm"]
    assert "cached-llm" not in {row["name"] for row in board["rows"]}
    # Taken off the list, only its own block is scheduled.
    raw = json.loads((directory / "benchmark.json").read_bytes())
    del raw["deferred_entrants"]
    write_definition(directory, raw)
    assert panel.prepare_benchmark(directory) == ("cached-llm", "heuristic")
    assert definition.load_benchmark(directory).evaluation_matchups == (("cached-llm", "heuristic"),)


@pytest.mark.parametrize("deferred", [["uniform"], ["nobody"], [], ["cached-llm", "cached-llm"], "cached-llm"])
def test_deferred_entrants_are_ladder_entrants(tmp_path: Path, deferred: Any) -> None:
    raw = ladder_value(tmp_path / "fixture")
    assert definition.parse_benchmark({**raw, "deferred_entrants": ["cached-llm"]}).deferred_entrants == ("cached-llm",)
    with pytest.raises(definition.BenchmarkError, match="deferred_entrants"):
        definition.parse_benchmark({**raw, "deferred_entrants": deferred})
    del raw["ladder"]
    with pytest.raises(definition.BenchmarkError, match="deferred_entrants"):
        definition.parse_benchmark({**raw, "deferred_entrants": ["cached-llm"]})


# ---------------- bench prepare --check ----------------


def test_the_committed_definition_is_the_one_bench_prepare_writes(completed, tmp_path: Path,  # noqa: F811
                                                                  capsys: pytest.CaptureFixture[str]) -> None:
    directory = copied(completed, tmp_path)
    assert panel.prepare_benchmark(directory) == ()
    committed = (directory / "benchmark.json").read_bytes()
    assert panel.check_prepared(directory) == []
    assert cli.main(["bench", "prepare", str(directory), "--check"]) == 0
    assert "prepare check: OK" in capsys.readouterr().out
    assert (directory / "benchmark.json").read_bytes() == committed  # the check writes nothing
    # A hand edit of an identity, or of the schedule, is reported and nothing is written.
    raw = json.loads(committed)
    raw["bots"][0]["evaluation_identity"] = "0" * 64
    raw["evaluation_targets"] = ["first"]
    write_definition(directory, raw)
    edited = (directory / "benchmark.json").read_bytes()
    problems = panel.check_prepared(directory)
    assert any(problem.startswith("bots: uniform: the committed entry differs") for problem in problems)
    assert "evaluation_targets: the committed value differs from the prepared one" in problems
    assert cli.main(["bench", "prepare", str(directory), "--check"]) == 1
    assert "FAIL bots: uniform" in capsys.readouterr().err
    assert (directory / "benchmark.json").read_bytes() == edited
    # The same content in another layout is not the file bench prepare writes.
    (directory / "benchmark.json").write_text(json.dumps(json.loads(committed)), encoding="utf-8")
    assert panel.check_prepared(directory) == ["the committed bytes differ from the prepared ones in formatting only: "
                                               "commit the file bench prepare writes"]


def test_the_check_refuses_a_placeholder_set_in_the_environment(tmp_path: Path) -> None:
    directory = tmp_path / "benchmarks" / "fixture"
    raw = ladder_value(directory)
    raw["engine"]["command"] = ["${PY}", "${FAKE_ENGINE}"]
    write_definition(directory, raw)
    values = {"PY": ladder_value(directory)["engine"]["command"][0],
              "FAKE_ENGINE": ladder_value(directory)["engine"]["command"][1]}
    (directory.parent / "local.json").write_text(json.dumps(values), encoding="utf-8")
    panel.prepare_benchmark(directory, environ={})
    assert panel.check_prepared(directory, environ={}) == []
    assert panel.check_prepared(directory, environ={"FAKE_ENGINE": values["FAKE_ENGINE"], "UNRELATED": "1"}) == [
        "set in the process environment: FAKE_ENGINE; a set variable wins over benchmarks/local.json, so unset them "
        "and check again"]
