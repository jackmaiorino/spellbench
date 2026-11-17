"""Export blocks: a ladder's second set of evaluation conditions, for the blocks of the bots it lists.

A board with export blocks has two forms. Its published blocks stay selected under the base form, byte for byte;
the blocks of the listed bots are played in runs of the export form; a run is one form; a snapshot that holds both
records each form's contract and engine facts; and nothing lets a block of one form stand in for the other.
"""

from __future__ import annotations

import copy
import json
import shutil
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from arena_helpers import FAKE_ENGINE, TEST_RUN_SECRET, builtin
from spellbench.arena import snapshot, store
from spellbench.arena.config import BASE_FORM, EXPORT_FORM, TournamentConfig, TournamentError
from spellbench.arena.schedule import preflight, schedule
from spellbench.arena.validate import validate_tournament_dir
from spellbench.bench import definition, panel, run as bench_run
from spellbench.human import match
from spellbench.site import render
from spellbench.site.build import build_site
from test_arena_validity import UNIT
from test_ladder import completed, copied  # noqa: F401 - completed is a fixture
from test_panel import play, value, write_definition
from test_site_render import BENCH

REPO = Path(__file__).resolve().parents[2]
ENTRANT, EXPORT_VERSION = "cached-llm", "fixture-v1-export"
HEX = "0123456789abcdef" * 4


def _export_engine(folder: Path) -> list[str]:
    """The fake engine under another file name: the same play, another engine identity."""
    folder.mkdir(parents=True, exist_ok=True)
    for path in FAKE_ENGINE.parent.glob("fake_v2_*.py"):
        shutil.copyfile(path, folder / path.name)
    shutil.copyfile(FAKE_ENGINE, folder / "fake_export_engine.py")
    return [sys.executable, str(folder / "fake_export_engine.py")]


def _with_export_blocks(directory: Path, tmp_path: Path, *, stale_schedule: bool = False,
                        **changes: Any) -> dict[str, Any]:
    """Give the played fixture ladder export blocks for its entrant. The fixture's file still holds the schedule
    of its first run, all three blocks; ``stale_schedule`` keeps it, as a hand edit of a prepared file would."""
    raw = json.loads((directory / "benchmark.json").read_bytes())
    raw["export_blocks"] = {"evaluation_version": EXPORT_VERSION, "bots": [ENTRANT],
                            "engine": {"command": _export_engine(tmp_path / "export-engine")}, "extensions": [],
                            **changes}
    if not stale_schedule:
        del raw["evaluation_matchups"], raw["evaluation_targets"]
    write_definition(directory, raw)
    return raw


# ---------------- the config: one board, two forms; a run is one form ----------------


def test_a_board_config_resolves_to_one_form_at_a_time(completed, tmp_path: Path) -> None:  # noqa: F811
    directory = copied(completed, tmp_path)
    before = panel.full_config(definition.load_benchmark(directory))
    assert before.forms() == (BASE_FORM,) and before.as_form(BASE_FORM) is before
    _with_export_blocks(directory, tmp_path, evaluation_engine_identity=HEX)
    board = panel.full_config(definition.load_benchmark(directory))
    assert board.forms() == (BASE_FORM, EXPORT_FORM)
    assert board.form_of((ENTRANT, "heuristic")) == EXPORT_FORM and board.form_of(("first", "uniform")) == BASE_FORM
    assert TournamentConfig.from_json(board.to_json()) == board  # the whole board round-trips with its export blocks
    # A form is its own blocks under its own conditions. The base form is the board as it was before it named
    # export blocks, to the byte, less the entrant's block; the export form holds that block alone.
    base, export = board.as_form(BASE_FORM), board.as_form(EXPORT_FORM)
    assert base.matchups == tuple(pair for pair in before.matchups if ENTRANT not in pair)
    assert export.matchups == tuple(pair for pair in before.matchups if ENTRANT in pair) != ()
    assert store.canonical_bytes({**base.to_json(), "matchups": before.to_json()["matchups"]}) == store.canonical_bytes(
        before.to_json())
    assert export.export_blocks is None and export.evaluation_version == EXPORT_VERSION
    assert export.engine_command[-1].endswith("fake_export_engine.py") and export.evaluation_engine_identity == HEX
    contracts = snapshot.form_contracts(board)
    assert contracts[BASE_FORM] == snapshot.contract(before) and contracts[EXPORT_FORM] != contracts[BASE_FORM]
    assert contracts[EXPORT_FORM]["evaluation_version"] == EXPORT_VERSION
    with pytest.raises(snapshot.SnapshotError, match="one contract for each form"):
        snapshot.contract(board)
    # The whole board is two engines, so nothing schedules or starts it: a caller takes one form first.
    for play_it in (lambda: schedule(board, TEST_RUN_SECRET), lambda: preflight(board, TEST_RUN_SECRET)):
        with pytest.raises(TournamentError, match="a board with export blocks is not one run"):
            play_it()
    # Scheduling a form plays that form's blocks only: no export block under the base engine, and the reverse.
    def blocks(config: TournamentConfig) -> set[tuple[str, ...]]:
        return {tuple(sorted(spec.name for _, spec in game.seat_specs)) for game in schedule(config, TEST_RUN_SECRET)}

    assert blocks(base) == {("first", "uniform"), ("heuristic", "uniform")}
    assert blocks(export) == {(ENTRANT, "heuristic")}
    assert len(schedule(base, TEST_RUN_SECRET)) + len(schedule(export, TEST_RUN_SECRET)) == len(
        schedule(before, TEST_RUN_SECRET))
    # A roster without the export bots is one form again.
    assert snapshot.without_entrants(board, (ENTRANT,)).export_blocks is None
    two = TournamentConfig.from_json({**board.to_json(), "export_blocks": {
        **board.export_blocks.to_json(), "bots": [ENTRANT, "first"]}})
    assert snapshot.without_entrants(two, (ENTRANT,)).export_blocks.bots == ("first",)


def test_the_export_form_keeps_the_boards_extensions() -> None:
    board = json.loads((REPO / "benchmarks/pauper-ladder-v3/snapshots/2026-11-15/config.json").read_bytes())
    export = {"evaluation_version": "pauper-ladder-v3.1.0", "bots": ["chains-a-c4-u1048576"],
              "engine": {"command": ["engine"]}, "extensions": [*board["extensions"], "x_kernel_infoset_v1"]}
    assert TournamentConfig.from_json({**board, "export_blocks": export}).export_blocks.extensions[-1] == "x_kernel_infoset_v1"
    export["extensions"] = ["x_kernel_infoset_v1", board["extensions"][0]]  # drops one the other blocks have
    with pytest.raises(TournamentError, match="must keep every extension of the board"):
        TournamentConfig.from_json({**board, "export_blocks": export})


def test_human_play_takes_the_boards_own_engine(completed, tmp_path: Path) -> None:  # noqa: F811
    """A match against a person is built from the whole board; it plays the board's engine, without the panel
    fields and without the export blocks."""
    directory = copied(completed, tmp_path)
    _with_export_blocks(directory, tmp_path)
    whole = replace(definition.load_benchmark(directory), evaluation_targets=None, evaluation_matchups=None)
    source = whole.tournament_config(str(tmp_path / "run"))
    assert source["export_blocks"]["bots"] == [ENTRANT]
    doc, _ = match.match_config(source, players=("uniform", "first"), bank_ms=600_000, run_dir=tmp_path / "run")
    assert "export_blocks" not in doc and doc["engine"]["command"][-1] == str(FAKE_ENGINE)
    # The export form's files need no local value for a match: its placeholders are dropped before any is resolved.
    raw = json.loads((directory / "benchmark.json").read_bytes())
    raw["export_blocks"]["engine"]["command"] = [sys.executable, "${AN_EXPORT_ENGINE_WITH_NO_LOCAL_VALUE}"]
    write_definition(directory, raw)
    resolved = match.benchmark_source(directory, {}, tmp_path / "run")
    assert "export_blocks" not in resolved and resolved["engine"]["command"][-1] == str(FAKE_ENGINE)
    # The same for a config file given as the source (--config), with local values to resolve.
    whole = replace(definition.load_benchmark(directory), evaluation_targets=None, evaluation_matchups=None)
    path = tmp_path / "source-config.json"
    path.write_text(json.dumps(whole.tournament_config(str(tmp_path / "run"))), encoding="utf-8")
    assert "export_blocks" in json.loads(path.read_text(encoding="utf-8"))
    for local in ({}, {"SOME_OTHER_VALUE": "x"}):
        from_file = match.config_source(path, local)
        assert "export_blocks" not in from_file and from_file["engine"]["command"][-1] == str(FAKE_ENGINE)


@pytest.mark.parametrize("change, message", [
    ({"bots": ["uniform"]}, "the rating anchor plays the base form"),
    ({"bots": ["nobody"]}, "must list distinct configured bots"),
    ({"bots": [ENTRANT, ENTRANT]}, "must list distinct configured bots"),
    ({"bots": []}, "must list distinct configured bots"),
    ({"evaluation_version": "fixture-v1"}, "must differ from"),
    ({"engine": {"command": []}}, "must be a nonempty list of strings"),
    ({"extensions": ["not an extension"]}, "must be a list of distinct extension names"),
    ({"evaluation_engine_identity": "abc"}, "needs 64 lowercase hex characters"),
    ({"surprise": 1}, "must be an object with evaluation_version, bots, engine and extensions"),
])
def test_export_blocks_are_checked(completed, tmp_path: Path, change: dict[str, Any], message: str) -> None:  # noqa: F811
    directory = copied(completed, tmp_path)
    _with_export_blocks(directory, tmp_path, **change)
    with pytest.raises((definition.BenchmarkError, TournamentError), match=message):
        panel.full_config(definition.load_benchmark(directory))


def test_export_blocks_need_a_ladder_and_a_block_without_them(tmp_path: Path) -> None:
    directory = tmp_path / "fixture"
    raw = value(directory)  # a reference panel, no ladder
    raw["export_blocks"] = {"evaluation_version": EXPORT_VERSION, "bots": [ENTRANT],
                            "engine": {"command": [sys.executable, str(FAKE_ENGINE)]}, "extensions": []}
    write_definition(directory, raw)
    with pytest.raises(definition.BenchmarkError, match="export_blocks: needs a ladder"):
        definition.load_benchmark(directory)
    raw.update(opponent_panel=["uniform", "heuristic"], ladder={"band": 1, "entrants": {ENTRANT: ["heuristic"]}})
    raw["export_blocks"]["bots"] = ["heuristic", ENTRANT]  # every block has an export bot
    write_definition(directory, raw)
    with pytest.raises((definition.BenchmarkError, TournamentError), match="every block would use it"):
        panel.full_config(definition.load_benchmark(directory))


# ---------------- end to end: the published blocks stay, the export block is played once, both compose ----------------


def test_the_published_blocks_stay_and_only_the_export_block_is_played(completed, tmp_path: Path) -> None:  # noqa: F811
    directory = copied(completed, tmp_path)
    earlier = directory / "snapshots" / "2026-10-01"
    old_manifest = store.read_json(earlier / "manifest.json")
    old_bytes = {path.name: path.read_bytes() for path in earlier.iterdir()}
    base_identity = json.loads((directory / "benchmark.json").read_bytes())["evaluation_engine_identity"]
    _with_export_blocks(directory, tmp_path)

    # Prepare fingerprints the export engine and schedules the one block that needs it. The base blocks are found
    # again under an unchanged contract; the entrant's earlier block was played without the export, so it does not
    # count for the export form.
    assert panel.prepare_benchmark(directory) == (ENTRANT, "heuristic")
    prepared = definition.load_benchmark(directory)
    assert prepared.evaluation_matchups == ((ENTRANT, "heuristic"),)
    assert prepared.evaluation_engine_identity == base_identity
    export_identity = prepared.export_blocks.evaluation_engine_identity
    assert export_identity and export_identity != base_identity
    assert panel.check_prepared(directory) == []
    board = panel.full_config(prepared)
    found = panel.sources(directory)
    selected = snapshot.select_blocks(board, found)
    assert set(selected) == {("first", "uniform"), ("heuristic", "uniform")}
    assert snapshot.contract(found[0].config) == snapshot.form_contracts(board)[BASE_FORM]

    # Before the export run exists the board composes as before it named export blocks: schema v1, the entrant
    # pending, the same contract.
    pending = panel.compose_benchmark(directory, date="2026-10-02")
    manifest = store.read_json(pending / "manifest.json")
    assert manifest["schema"] == snapshot.SCHEMA and "export_blocks" not in manifest
    assert manifest["pending"] == [ENTRANT] and manifest["contract"] == old_manifest["contract"]
    assert validate_tournament_dir(pending) == []
    shutil.rmtree(pending)

    # The run of the export block is an ordinary run of one form: the export conditions stand at the top level.
    config = TournamentConfig.from_json(prepared.tournament_config("runs/2026-10-03"))
    assert config.export_blocks is None and config.evaluation_version == EXPORT_VERSION
    assert config.evaluation_engine_identity == export_identity
    assert config.engine_command[-1].endswith("fake_export_engine.py")
    assert snapshot.contract(config) == snapshot.form_contracts(board)[EXPORT_FORM]
    result = play(directory, "2026-10-03")
    assert result.rated and validate_tournament_dir(result.tournament_dir) == []
    assert panel.prepare_benchmark(directory) == ()  # nothing is left to play

    # The snapshot holds both forms: the top level is the base form's, byte for byte; one object carries the
    # export form's contract, engine facts and matchups.
    composed = panel.compose_benchmark(directory, date="2026-10-03")
    assert validate_tournament_dir(composed) == []
    manifest = store.read_json(composed / "manifest.json")
    assert manifest["schema"] == snapshot.SCHEMA_TWO_FORMS
    for key in ("contract", "protocol", "engine", "engine_profile", "information_rules", "engine_files",
                "resolved_decks"):
        assert manifest[key] == old_manifest[key], key
    export = manifest["export_blocks"]
    assert set(export) == {"contract", "engine", "engine_profile", "information_rules", "engine_files", "matchups"}
    assert export["matchups"] == [[ENTRANT, "heuristic"]]
    assert export["contract"]["evaluation_version"] == EXPORT_VERSION
    assert export["contract"]["evaluation_engine_identity"] == export_identity
    assert [file["file_name"] for file in export["engine_files"]] != [
        file["file_name"] for file in manifest["engine_files"]]
    assert [(source["run"], source["matchups"]) for source in manifest["sources"]] == [
        ("2026-10-01", [["first", "uniform"], ["heuristic", "uniform"]]), ("2026-10-03", [[ENTRANT, "heuristic"]])]
    leaderboard = store.read_json(composed / "leaderboard.json")
    assert leaderboard["evaluation"]["version"] == "fixture-v1"
    assert leaderboard["evaluation"]["export_blocks"] == {"version": EXPORT_VERSION, "bots": [ENTRANT],
                                                           "extensions": [], "matchups": 1}
    assert ("Evaluation versions by block: fixture-v1-export (extensions: none) for the 1 block of cached-llm; "
            "fixture-v1 (extensions: none) for the other 2 blocks.") in leaderboard["notes"]
    assert {row["name"] for row in leaderboard["rows"]} == {"first", "uniform", "heuristic", ENTRANT}

    # The site builds from it, and the board page says which block was played under which version.
    shutil.copytree(directory, tmp_path / "benchmarks" / directory.name)
    build_site(tmp_path / "benchmarks", tmp_path / "site")
    page = (tmp_path / "site" / "b" / directory.name / "index.html").read_text(encoding="utf-8")
    assert ('<p class="export-blocks">Evaluation versions by block: fixture-v1-export (extensions: none) for the '
            "1 block of cached-llm; fixture-v1 for every other block.</p>") in page

    # A tampered export object does not recompute, and the earlier snapshot still validates byte for byte.
    body = json.loads((composed / "manifest.json").read_bytes())
    body["export_blocks"]["matchups"] = []
    (composed / "manifest.json").write_bytes(store.canonical_bytes(body) + b"\n")
    assert validate_tournament_dir(composed) == ["manifest.json does not recompute from the source runs"]
    assert {path.name: path.read_bytes() for path in earlier.iterdir()} == old_bytes
    assert validate_tournament_dir(earlier) == []


def test_a_block_of_one_form_never_stands_in_for_the_other(completed, tmp_path: Path) -> None:  # noqa: F811
    directory = copied(completed, tmp_path)
    raw = _with_export_blocks(directory, tmp_path)
    panel.prepare_benchmark(directory)
    play(directory, "2026-10-03")
    board = panel.full_config(definition.load_benchmark(directory))
    by_run = {source.path.name: source for source in panel.sources(directory)}
    selected = snapshot.select_blocks(board, list(by_run.values()))
    # The entrant's block comes from the export-form run although the base-form run holds one too.
    assert by_run["2026-10-01"].blocks().keys() >= {(ENTRANT, "heuristic")}
    assert selected[(ENTRANT, "heuristic")].path.name == "2026-10-03"
    wrong = dict(selected)
    wrong[(ENTRANT, "heuristic")] = by_run["2026-10-01"]
    with pytest.raises(snapshot.SnapshotError, match="source 2026-10-01 has incompatible evaluation conditions"):
        snapshot.materialize(board, wrong, benchmark_id=directory.name, label="2026-10-04")
    # Without export blocks the board is one form again, and the export-form run supplies nothing.
    plain = json.loads((directory / "benchmark.json").read_bytes())
    del plain["export_blocks"]
    write_definition(directory, plain)
    plain_board = panel.full_config(definition.load_benchmark(directory))
    again = snapshot.select_blocks(plain_board, list(by_run.values()))
    assert {pair: source.path.name for pair, source in again.items()} == {
        ("first", "uniform"): "2026-10-01", ("heuristic", "uniform"): "2026-10-01", (ENTRANT, "heuristic"): "2026-10-01"}
    wrong = dict(again)
    wrong[(ENTRANT, "heuristic")] = by_run["2026-10-03"]
    with pytest.raises(snapshot.SnapshotError, match="source 2026-10-03 has incompatible evaluation conditions"):
        snapshot.materialize(plain_board, wrong, benchmark_id=directory.name, label="2026-10-04")
    assert raw["export_blocks"]["bots"] == [ENTRANT]


def test_prepare_replaces_a_stale_schedule_that_mixes_the_forms(completed, tmp_path: Path) -> None:  # noqa: F811
    directory = copied(completed, tmp_path)
    _with_export_blocks(directory, tmp_path, stale_schedule=True)
    # The schedule of the first run named all three blocks; with export blocks that is a mix, and the file is
    # refused wherever it is loaded (bench commit and bench run load it first).
    with pytest.raises(definition.BenchmarkError, match="mixes blocks of the export form"):
        definition.load_benchmark(directory)
    # The definition's excluded runs still count while its schedule is stale: with the only run excluded, every
    # block is missing, which is a mix, and prepare says so and does not take the excluded run as played.
    stale = json.loads((directory / "benchmark.json").read_bytes())
    write_definition(directory, {**stale, "excluded_runs": [{"run": "2026-10-01", "reason": "left out for the test"}]})
    with pytest.raises(definition.BenchmarkError, match="the missing blocks mix the export form and the base form"):
        panel.prepare_benchmark(directory)
    write_definition(directory, stale)
    assert panel.prepare_benchmark(directory) == (ENTRANT, "heuristic")
    assert definition.load_benchmark(directory).evaluation_matchups == ((ENTRANT, "heuristic"),)


# ---------------- a run is one form: a mixed schedule is refused before any commitment ----------------


def test_a_schedule_that_mixes_the_forms_is_refused_at_prepare_and_before_a_commitment(completed,  # noqa: F811
                                                                                     tmp_path: Path) -> None:
    directory = copied(completed, tmp_path)
    raw = _with_export_blocks(directory, tmp_path)
    raw["bots"][0]["seed"] = 101  # uniform changes: its two base blocks are missing too
    write_definition(directory, raw)
    before = (directory / "benchmark.json").read_bytes()
    with pytest.raises(definition.BenchmarkError, match="the missing blocks mix the export form and the base form"):
        panel.prepare_benchmark(directory)
    assert (directory / "benchmark.json").read_bytes() == before  # nothing is written
    # A hand-written mixed schedule is refused where the run's config is built, which bench commit does first.
    mixed = copy.deepcopy(raw)
    mixed["evaluation_matchups"] = [["first", "uniform"], [ENTRANT, "heuristic"]]
    mixed["evaluation_targets"] = ["first", "uniform", ENTRANT, "heuristic"]
    write_definition(directory, mixed)
    with pytest.raises(definition.BenchmarkError, match="mixes blocks of the export form"):
        definition.load_benchmark(directory)  # which is where bench commit and bench run start
    unscheduled = definition.parse_benchmark({key: item for key, item in mixed.items() if key != "evaluation_matchups"})
    with pytest.raises(definition.BenchmarkError, match="mixes blocks of the export form"):
        replace(unscheduled, evaluation_matchups=tuple(map(tuple, mixed["evaluation_matchups"]))).tournament_config("check")
    # Deferring the export entrant leaves a base-form schedule, which records the base version.
    raw["deferred_entrants"] = [ENTRANT]
    write_definition(directory, raw)
    assert panel.prepare_benchmark(directory) == ("first", "heuristic", "uniform")
    base_run = TournamentConfig.from_json(definition.load_benchmark(directory).tournament_config("runs/2026-10-05"))
    assert base_run.evaluation_version == "fixture-v1" and base_run.export_blocks is None
    assert base_run.engine_command[-1] == str(FAKE_ENGINE)
    # The whole board is not a run: a definition that schedules no blocks of one form is not played.
    whole = json.loads((directory / "benchmark.json").read_bytes())
    del whole["evaluation_matchups"], whole["deferred_entrants"]
    whole["evaluation_targets"] = [bot["name"] for bot in whole["bots"]]
    write_definition(directory, whole)
    with pytest.raises(definition.BenchmarkError, match="schedules no blocks of one form"):
        bench_run._config(definition.load_benchmark(directory), "2026-10-05")


# ---------------- a failed block stays barred in its own form ----------------


def test_a_base_block_that_failed_stays_barred_when_the_board_gains_export_blocks(tmp_path: Path) -> None:
    directory = tmp_path / "fixture"
    raw = value(directory)
    first = builtin("first")
    first["display"] = {"label": "first", "author": "fixture", "description": "local test bot", "url": None}
    raw["bots"] = [raw["bots"][0], raw["bots"][1], first]
    raw.update(deck_pool=["Burn", "Halt"], pairs_per_deck=2, validity=UNIT,  # the second deck halts every game
               opponent_panel=["uniform", "heuristic"], ladder={"band": 1, "entrants": {"first": ["heuristic"]}})
    write_definition(directory, raw)
    panel.prepare_benchmark(directory)
    failed = play(directory, "2026-10-01")
    assert store.read_json(failed.tournament_dir / "manifest.json")["validity"]["verdict"] == "fail"
    both = {("heuristic", "uniform"): "2026-10-01", ("first", "heuristic"): "2026-10-01"}
    assert panel.failed_attempts(directory, panel.full_config(definition.load_benchmark(directory))) == both
    # The board gains export blocks for the entrant. The base block that failed keeps its contract, so it stays
    # barred: the new version is no way to play it again. The entrant's block is a new evaluation (another
    # version and engine), which the definition's review decided.
    raw = json.loads((directory / "benchmark.json").read_bytes())
    raw["export_blocks"] = {"evaluation_version": EXPORT_VERSION, "bots": ["first"],
                            "engine": {"command": _export_engine(tmp_path / "export-engine")}, "extensions": []}
    raw.pop("evaluation_matchups", None)
    write_definition(directory, raw)
    board = panel.full_config(definition.load_benchmark(directory))
    assert panel.failed_attempts(directory, board) == {("heuristic", "uniform"): "2026-10-01"}
    with pytest.raises(definition.BenchmarkError, match=r"heuristic vs uniform \(run 2026-10-01\); a failed "
                                                        "evaluation is not replayed or topped up"):
        panel.prepare_benchmark(directory)
    # A failed export-form run bars its own block the same way.
    raw["deferred_entrants"] = ["first"]
    raw["evaluation_version"] = "fixture-v2"  # a reviewed new base evaluation, so the base block may be scheduled
    write_definition(directory, raw)
    assert set(panel.prepare_benchmark(directory)) == {"heuristic", "uniform"}
    raw = json.loads((directory / "benchmark.json").read_bytes())
    del raw["deferred_entrants"]
    raw["evaluation_matchups"], raw["evaluation_targets"] = [["first", "heuristic"]], ["first", "heuristic"]
    write_definition(directory, raw)
    export_failed = play(directory, "2026-10-02")
    assert store.read_json(export_failed.tournament_dir / "manifest.json")["validity"]["verdict"] == "fail"
    board = panel.full_config(definition.load_benchmark(directory))
    assert panel.failed_attempts(directory, board) == {("first", "heuristic"): "2026-10-02"}
    with pytest.raises(definition.BenchmarkError, match=r"first vs heuristic \(run 2026-10-02\)"):
        panel.refuse_replay(directory, definition.load_benchmark(directory))


# ---------------- the page ----------------


def test_the_board_page_says_which_blocks_used_which_evaluation_version() -> None:
    evaluation = {"mode": "ladder", "version": "board-1.0.0", "opponents": ["uniform"], "sources": ["2026-10-01"],
                  "caveat": "A caveat.", "band": 1,
                  "export_blocks": {"version": "board-1.1.0", "bots": ["searcher"], "extensions": ["x_a_v1", "x_b_v1"],
                                    "matchups": 3}}
    page = render.render_benchmark({**BENCH, "evaluation": evaluation})
    assert ('<p class="export-blocks">Evaluation versions by block: board-1.1.0 (extensions: x_a_v1, x_b_v1) for '
            "the 3 blocks of searcher; board-1.0.0 for every other block.</p>") in page
    plain = {key: item for key, item in evaluation.items() if key != "export_blocks"}
    assert "export-blocks" not in render.render_benchmark({**BENCH, "evaluation": plain})
