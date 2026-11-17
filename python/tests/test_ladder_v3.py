"""pauper-ladder-v3: every ordered deck pairing on the ladder, the search entrant's export blocks, deferred
entrants, no per-deck ratings, and a definition that ``bench prepare`` reproduces."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from arena_helpers import TEST_RUN_SECRET, builtin, leaderboard, make_config, roomy_machine, run
from spellbench.arena import cli, snapshot, store
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
    # The plain adapter: the information-set exporter halts on a token in a hand, which off-mirror games reach.
    assert benchmark.extensions == ("x_kernel_flat_v4", "x_public_history_v1")
    assert benchmark.engine_command[1] == "${MTG_KERNEL_V2_ENGINE}"
    assert len(benchmark.deck_pool) == 8 and benchmark.evaluation_version == "pauper-ladder-v3.0.0"
    board = panel.full_config(benchmark)
    # Fifteen rung blocks (seven rungs, band 3) and three for each of the two entrants: 21 blocks of 64 pairs.
    played = {frozenset(pair) for pair in board.matchups}
    rungs = {frozenset((a, RUNGS[j])) for i, a in enumerate(RUNGS) for j in range(i + 1, min(len(RUNGS), i + 4))}
    assert len(rungs) == 15 and rungs <= played and len(played) == 21  # each rung against the three above it
    assert played - rungs == {frozenset((entrant, rung)) for entrant in ("chains-a-c4-u1048576", SEARCH_ENTRANT)
                              for rung in RUNGS[-3:]}
    # Each form schedules its own blocks only: 18 without the export (the published ones), 3 with it.
    base, export = board.as_form("base"), board.as_form("export")
    assert {frozenset(pair) for pair in export.matchups} == {frozenset((SEARCH_ENTRANT, rung)) for rung in RUNGS[-3:]}
    assert {frozenset(pair) for pair in base.matchups} == played - {frozenset(pair) for pair in export.matchups}
    # Each form's roster is its own: the base form does not hold the search entrant, which needs the export.
    assert [bot.name for bot in base.bots] == [*RUNGS, "chains-a-c4-u1048576"]
    assert [bot.name for bot in export.bots] == [*RUNGS, SEARCH_ENTRANT]
    assert set(base.ladder.entrants) == {"chains-a-c4-u1048576"} and set(export.ladder.entrants) == {SEARCH_ENTRANT}
    assert base.engine_command[1] == "${MTG_KERNEL_V2_ENGINE}" and "x_kernel_infoset_v1" not in base.extensions
    assert export.engine_command[1] == "${MTG_KERNEL_V2_INFOSET_ENGINE}" and "x_kernel_infoset_v1" in export.extensions
    for config, blocks in ((base, 18), (export, 3)):
        games = schedule(config, TEST_RUN_SECRET)
        assert len(games) == blocks * 128
        # The search entrant sits in every game of the export form and in none of the base form.
        assert {SEARCH_ENTRANT in {spec.name for _, spec in game.seat_specs} for game in games} == {config is export}
        for matchup in range(blocks):
            block = [game for game in games if game.matchup_index == matchup]
            pairings = Counter((game.decks[0].catalog_id, game.decks[1].catalog_id) for game in block)
            assert len(pairings) == 64 and set(pairings.values()) == {2}  # one seat-swapped pair per ordered pairing
            seats = Counter((spec.name, seat, game.decks[int(seat[1])].catalog_id,
                             game.decks[1 - int(seat[1])].catalog_id) for game in block for seat, spec in game.seat_specs)
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


def test_the_search_entrants_blocks_are_export_blocks_and_the_published_blocks_keep_their_contract() -> None:
    raw = json.loads((BOARD / "benchmark.json").read_bytes())
    benchmark = definition.load_benchmark(BOARD)
    export = benchmark.export_blocks
    assert benchmark.deferred_entrants == () and export.bots == (SEARCH_ENTRANT,)
    # Each form carries its own version: the published blocks stay 3.0.0, the export blocks are 3.1.0.
    assert (benchmark.evaluation_version, export.evaluation_version) == ("pauper-ladder-v3.0.0",
                                                                         "pauper-ladder-v3.1.0")
    assert export.engine_command[1] == "${MTG_KERNEL_V2_INFOSET_ENGINE}"
    assert export.engine_command[3] == "${MTG_KERNEL_V2_EXPORT_BRIDGE}" != benchmark.engine_command[3]
    assert export.extensions == (*benchmark.extensions, "x_kernel_infoset_v1")
    assert export.evaluation_engine_identity and export.evaluation_engine_identity != benchmark.evaluation_engine_identity
    assert all("evaluation_identity" in bot for bot in raw["bots"])
    # The definition schedules the entrant's three blocks and nothing else: one run, one form.
    assert sorted(map(sorted, raw["evaluation_matchups"])) == [sorted((rung, SEARCH_ENTRANT)) for rung in RUNGS[-3:]]
    run = TournamentConfig.from_json(benchmark.tournament_config("runs/check"))
    assert run.export_blocks is None and run.evaluation_version == "pauper-ladder-v3.1.0"
    assert run.extensions == export.extensions and run.evaluation_engine_identity == export.evaluation_engine_identity
    assert len(schedule(run, TEST_RUN_SECRET)) == 3 * 128
    # The published run is still a source of the base form: its contract is the board's base contract, unchanged.
    board = panel.full_config(benchmark)
    contracts = snapshot.form_contracts(board)
    published = TournamentConfig.from_json(store.read_json(BOARD / "runs" / "2026-11-15" / "config.json"))
    assert snapshot.contract(published) == contracts["base"]
    assert store.read_json(BOARD / "snapshots" / "2026-11-15" / "manifest.json")["contract"] == contracts["base"]
    assert snapshot.contract(run) == contracts["export"] != contracts["base"]
    assert all(board.form_of(pair) == ("export" if SEARCH_ENTRANT in pair else "base") for pair in board.matchups)


def test_the_board_text_follows_the_wording_rules() -> None:
    raw = json.loads((BOARD / "benchmark.json").read_bytes())
    receipt = (BOARD / "ENGINE-AUDITS.json").read_text(encoding="utf-8")
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    about_v3 = readme[readme.index("`pauper-ladder-v3` plays"):readme.index("`pauper-grid-v1` plays")]
    assert "never\ncompare a v3 number with a v2 or grid number" in about_v3 and "mirror-only records" in about_v3
    assert "no per-deck bot ratings" in about_v3 and "narrower" not in about_v3
    assert "mulligan_mode" not in json.dumps(raw) and "Terror" not in raw["deck_pool"]
    assert json.loads(receipt)["engine_bytes"]["evaluation_engine_identity"] == raw["evaluation_engine_identity"]
    text = json.dumps(raw, ensure_ascii=False) + receipt + about_v3
    assert chr(0x2014) not in text and chr(0x2013) not in text and "cancels exactly" not in text and "cancel exactly" not in text
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


def test_the_page_says_why_a_board_has_no_deck_tables() -> None:
    page = render.render_benchmark({**BENCH, "deck_tables": [], "deck_pairing": "all_pairs", "deck_slices": False})
    assert "This board publishes no per-deck bot ratings" in page
    for view in ({**BENCH, "deck_tables": []}, {**BENCH, "deck_tables": [], "deck_pairing": "all_pairs"}):
        assert "This benchmark uses one deck pairing" in render.render_benchmark(view)


def test_a_snapshot_of_such_a_board_publishes_no_per_deck_ratings_either(tmp_path: Path) -> None:
    directory = tmp_path / "fixture"
    raw = ladder_value(directory)
    raw["bots"] = [bot for bot in raw["bots"] if bot["name"] != "cached-llm"]
    raw.update(deck_pool=["Burn", "Elves"], pairs_per_deck=2, ladder={"band": 1, "entrants": {}})
    for slices in (True, False):
        folder = tmp_path / str(slices) / "fixture"
        write_definition(folder, {**raw, "id": "fixture", **({} if slices else {"deck_slices": False})})
        panel.prepare_benchmark(folder)
        play(folder, "2026-10-01")
        board = store.read_json(panel.compose_benchmark(folder, date="2026-10-01") / "leaderboard.json")
        assert len(board["slices"]["deck"]) == (2 if slices else 0)
        assert (NO_DECK_SLICES_NOTE in board["notes"]) is not slices


@pytest.mark.skipif(not (os.environ.get("SPELLBENCH_PINNED_LOCAL") and os.environ.get("SPELLBENCH_PINNED_PYTHON")),
                    reason="needs the board's pinned binaries: set SPELLBENCH_PINNED_LOCAL to the local values file "
                           "and SPELLBENCH_PINNED_PYTHON to the pinned interpreter")
def test_the_committed_board_reproduces_under_the_pinned_assets(tmp_path: Path) -> None:
    """The board's rule (integrations/mtg_kernel/README.md): prepared again from a clean copy, by the pinned
    interpreter and with every placeholder from the local values, the committed definition comes out byte for
    byte. The check runs in the pinned interpreter as a child process, as an operator runs it."""
    folder = tmp_path / "benchmarks" / BOARD.name
    folder.mkdir(parents=True)
    shutil.copyfile(BOARD / "benchmark.json", folder / "benchmark.json")
    # The published run is part of what prepare reads: its blocks are the ones the schedule leaves out.
    shutil.copytree(BOARD / "runs", folder / "runs")
    shutil.copyfile(os.environ["SPELLBENCH_PINNED_LOCAL"], folder.parent / "local.json")
    names = definition.placeholder_names(definition.load_benchmark(folder))
    environ = {key: value for key, value in os.environ.items()
               if key not in names and key != "MTG_KERNEL_V2_SOURCE"}
    environ.update(PYTHONPATH=str(REPO / "python"), PYTHONUTF8="1")
    command = [os.environ["SPELLBENCH_PINNED_PYTHON"], "-B", "-c",
               "import sys; from spellbench.arena.cli import main; sys.exit(main())",
               "bench", "prepare", str(folder), "--check"]
    done = subprocess.run(command, env=environ, capture_output=True, text=True, cwd=tmp_path)
    assert done.returncode == 0 and "prepare check: OK" in done.stdout, done.stdout + done.stderr
    assert (folder / "benchmark.json").read_bytes() == (BOARD / "benchmark.json").read_bytes()


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
