"""The validity unit: thresholds on scheduled games, the manifest record, and what a failing run publishes."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest

from arena_helpers import TEST_ENGINE_FILES, TEST_PROOF, TEST_RUN_SECRET, builtin, make_config, small_allocation
from spellbench.arena import cli, leaderboard, registry, snapshot, store, validity
from spellbench.arena.config import TournamentConfig, TournamentError, ValidityUnit
from spellbench.arena.ledger import parse_ledger
from spellbench.arena.manifest import is_rated
from spellbench.arena.schedule import schedule
from spellbench.arena.validate import validate_tournament_dir
from spellbench.bench import definition, panel
from spellbench.run_secret import RunSecret
from spellbench.site.build import board_run_dir, build_site
from test_panel import play, value, write_definition

REPO = Path(__file__).resolve().parents[2]
# The thresholds proposed for pauper-ladder-v3: 97% of a block natural and in complete pairs, 97% per bot, 90% per
# ordered deck pairing.
UNIT = {"unit": "spellbench-validity/v1", "block_natural_permille": 970, "block_complete_pairs_permille": 970,
        "rung_natural_permille": 970, "pairing_natural_permille": 900}
POOL = ("Burn", "Elves", "Faeries", "Affinity", "Rally", "Spy", "Wildfire", "CawGates")
RUNGS = ("uniform", "heuristic", "first", "r3", "r4", "r5", "r6")


@dataclass(frozen=True)
class _Row:
    """What ``validity.evaluate`` reads of a ledger row."""

    game_index: int
    classification: str = "natural"

    @property
    def rated(self) -> bool:
        return self.classification in ("natural", "forfeit")


def _board(tmp_path: Path, unit: dict[str, Any] | None = UNIT) -> TournamentConfig:
    """The shape of the ladder: seven rungs within a band of three (15 blocks) and one entrant on three rungs,
    64 pairs a block, one pair per ordered pairing of eight decks: 18 blocks, 2,304 games."""
    names = [*RUNGS, "entrant"]
    bots = [builtin(name) if name in ("uniform", "heuristic", "first") else
            {"name": name, "version": "1.0.0", "type": "subprocess", "command": ["bot"], "owner": "spellbench"}
            for name in names]
    matchups = [[a, RUNGS[j]] for i, a in enumerate(RUNGS) for j in range(i + 1, min(len(RUNGS), i + 4))]
    matchups += [["entrant", rung] for rung in RUNGS[-3:]]
    extra = {} if unit is None else {"validity": unit}
    return TournamentConfig.from_json(make_config(
        tmp_path / "t", bots, deck_pool=POOL, pairs=64, deck_pairing="all_pairs", include_self_play=False,
        matchups=matchups, **extra))


def _record(config: TournamentConfig, bad: dict[int, str] | None = None, *, played: int | None = None):
    """The validity record of a run whose games ended natural except ``bad`` (game index to classification); only
    the first ``played`` scheduled games have rows."""
    contexts = schedule(config, TEST_RUN_SECRET)
    rows = [_Row(context.game_index, (bad or {}).get(context.game_index, "natural"))
            for context in contexts[:played]]
    return contexts, validity.evaluate(config, contexts, rows, run_label="2026-11-15")


def _games(contexts, *, block: int | None = None, decks: tuple[str, str] | None = None):
    return [context.game_index for context in contexts
            if (block is None or context.matchup_index == block)
            and (decks is None or (context.decks[0].catalog_id, context.decks[1].catalog_id) == decks)]


# ---------------- the unit ----------------


def test_thresholds_round_up_on_scheduled_counts() -> None:
    assert validity.at_least(128, 970) == 125  # 124.16 games
    assert validity.at_least(64, 970) == 63  # 62.08 pairs: 126 of 128 games in complete pairs
    assert validity.at_least(384, 970) == 373
    # An ordered pairing may lose its rounded share, and always one game.
    assert [validity.pairing_minimum(scheduled, 900) for scheduled in (36, 30, 6, 2)] == [33, 27, 5, 1]
    assert validity.pairing_minimum(36, 1000) == 35


@pytest.mark.parametrize("change, message", [
    ({"unit": "spellbench-validity/v0"}, "validity.unit"),
    ({"block_natural_permille": True}, "block_natural_permille"),
    ({"block_natural_permille": 0}, "block_natural_permille"),
    ({"pairing_natural_permille": 1001}, "pairing_natural_permille"),
    ({"rung_natural_permille": 97.0}, "rung_natural_permille"),
    ({"extra": 1}, "fields mismatch"),
])
def test_the_unit_is_strict(tmp_path: Path, change: dict[str, Any], message: str) -> None:
    with pytest.raises(TournamentError, match=message):
        _board(tmp_path, {**UNIT, **change})
    with pytest.raises(TournamentError, match="fields mismatch"):
        ValidityUnit.from_json({key: item for key, item in UNIT.items() if key != "rung_natural_permille"})


def test_the_unit_is_part_of_the_config_only_when_named(tmp_path: Path) -> None:
    named, plain = _board(tmp_path), _board(tmp_path, None)
    assert named.to_json()["validity"] == UNIT and TournamentConfig.from_json(named.to_json()) == named
    assert "validity" not in plain.to_json()  # earlier configs keep their bytes
    contexts = schedule(plain, TEST_RUN_SECRET)
    assert validity.evaluate(plain, contexts, [], run_label=None) is None


# ---------------- the verdict ----------------


def test_a_clean_run_passes_with_scheduled_denominators(tmp_path: Path) -> None:
    contexts, record = _record(_board(tmp_path))
    assert len(contexts) == 2304 and record["verdict"] == "pass" and record["failures"] == []
    assert record["exclusion"] is None and record["unit"] == UNIT
    assert len(record["blocks"]) == 18
    assert all((block["scheduled"], block["natural"], block["natural_min"], block["pairs_scheduled"],
                block["complete_pairs"], block["complete_pairs_min"], block["missing"], block["pass"])
               == (128, 128, 125, 64, 64, 63, 0, True) for block in record["blocks"])
    assert len(record["pairings"]) == 64  # every ordered pairing of the eight decks
    assert all((pairing["scheduled"], pairing["natural_min"], pairing["not_natural"]) == (36, 33, [])
               for pairing in record["pairings"])
    by_name = {rung["name"]: rung for rung in record["rungs"]}
    assert [rung["name"] for rung in record["rungs"]] == [*RUNGS, "entrant"]  # config order
    assert (by_name["uniform"]["scheduled"], by_name["r3"]["scheduled"], by_name["entrant"]["scheduled"]) == (
        3 * 128, 6 * 128, 3 * 128)
    assert by_name["entrant"]["natural_min"] == 373


def test_a_block_at_125_natural_with_122_rated_games_fails(tmp_path: Path) -> None:
    config = _board(tmp_path)
    contexts = schedule(config, TEST_RUN_SECRET)
    block = _games(contexts, block=13)
    # Three halts in three different pairs: 125 natural games, but each takes its pair partner out of the fit.
    halted = {block[0]: "halted", block[2]: "halted", block[4]: "halted"}
    _, record = _record(config, halted)
    row = record["blocks"][13]
    assert (row["natural"], row["natural_min"], row["complete_pairs"], row["complete_pairs_min"]) == (125, 125, 61, 63)
    assert 2 * row["complete_pairs"] == 122 and row["pass"] is False
    assert record["verdict"] == "fail"
    assert record["failures"] == [f"block 13 ({row['bots'][0]} vs {row['bots'][1]}): 61 of 64 scheduled pairs are "
                                  "complete, needs 63"]
    assert record["exclusion"] == {"run": "2026-11-15", "reason":
                                   "failed the board's validity unit (spellbench-validity/v1): " + record["failures"][0]}
    # Two halts in one pair break one pair: 126 natural, 63 complete pairs, a pass.
    _, record = _record(config, {block[0]: "halted", block[1]: "halted"})
    assert (record["blocks"][13]["natural"], record["blocks"][13]["complete_pairs"]) == (126, 63)
    assert record["verdict"] == "pass"
    # A fourth game that is not natural fails the natural count too.
    _, record = _record(config, {**halted, block[5]: "truncated"})
    assert len(record["failures"]) == 2 and "124 of 128 scheduled games ended natural, needs 125" in record["failures"][0]


def test_a_forfeit_is_not_natural_but_keeps_its_pair(tmp_path: Path) -> None:
    config = _board(tmp_path)
    block = _games(schedule(config, TEST_RUN_SECRET), block=0)
    _, record = _record(config, {block[index]: "forfeit" for index in (0, 2, 4, 6)})
    row = record["blocks"][0]
    assert (row["natural"], row["forfeit"], row["complete_pairs"]) == (124, 4, 64)
    assert record["failures"] == [f"block 0 ({row['bots'][0]} vs {row['bots'][1]}): 124 of 128 scheduled games ended "
                                  "natural, needs 125"]


def test_a_dead_deck_pairing_fails_a_run_whose_blocks_all_pass(tmp_path: Path) -> None:
    config = _board(tmp_path)
    contexts = schedule(config, TEST_RUN_SECRET)
    dead = _games(contexts, decks=("Faeries", "Rally"))
    assert len(dead) == 36  # one pair in each of the 18 blocks
    _, record = _record(config, {index: "halted" for index in dead})
    assert all(block["pass"] and (block["natural"], block["complete_pairs"]) == (126, 63)
               for block in record["blocks"])
    assert all(rung["pass"] for rung in record["rungs"])
    assert record["verdict"] == "fail"
    assert record["failures"] == ["deck pairing Faeries (p0) vs Rally (p1): 0 of 36 scheduled games ended natural, "
                                  "needs 33"]
    cell = next(pairing for pairing in record["pairings"] if pairing["decks"] == ["Faeries", "Rally"])
    assert cell["not_natural"] == dead and cell["pass"] is False
    # The pairing may lose three of its 36 games (the share of the grid's worst published cell, 27 of 30).
    _, record = _record(config, {index: "halted" for index in dead[:6:2]})
    assert record["verdict"] == "pass"
    _, record = _record(config, {index: "halted" for index in dead[:8:2]})
    assert record["failures"] == ["deck pairing Faeries (p0) vs Rally (p1): 32 of 36 scheduled games ended natural, "
                                  "needs 33"]


def test_a_game_that_was_not_played_counts_against_the_run(tmp_path: Path) -> None:
    config = _board(tmp_path)
    _, record = _record(config, played=2300)
    last = record["blocks"][-1]
    assert (last["scheduled"], last["played"], last["missing"], last["natural"], last["complete_pairs"]) == (
        128, 124, 4, 124, 62)
    assert record["verdict"] == "fail" and len(record["failures"]) == 2  # the natural count and the pairs
    assert all(block["scheduled"] == 128 for block in record["blocks"])


def test_the_share_per_bot_is_its_own_threshold(tmp_path: Path) -> None:
    config = _board(tmp_path, {**UNIT, "block_natural_permille": 900, "block_complete_pairs_permille": 900,
                               "rung_natural_permille": 990})
    contexts = schedule(config, TEST_RUN_SECRET)
    halted = {}
    for block in (15, 16):  # two of the entrant's three blocks, two broken pairs each
        games = _games(contexts, block=block)
        halted.update({games[0]: "halted", games[2]: "halted"})
    _, record = _record(config, halted)
    assert all(block["pass"] for block in record["blocks"])
    assert record["failures"] == ["bot entrant: 380 of 384 scheduled games ended natural, needs 381"]


def test_small_runs_that_each_pass_can_fail_together(tmp_path: Path) -> None:
    """Three one-block runs, each losing one game of the same ordered pairing: every run passes, the rating
    composed from them does not."""
    config = _board(tmp_path)
    contexts = schedule(config, TEST_RUN_SECRET)
    parts = []
    for label, block in (("2026-11-01", 15), ("2026-11-02", 16), ("2026-11-03", 17)):
        games = [context for context in contexts if context.matchup_index == block]
        lost = next(context.game_index for context in games
                    if (context.decks[0].catalog_id, context.decks[1].catalog_id) == ("Faeries", "Rally"))
        rows = [_Row(context.game_index, "halted" if context.game_index == lost else "natural") for context in games]
        alone = validity.evaluate_composition(config, [(label, games, rows)])
        assert alone["verdict"] == "pass"  # 1 of 2 games of the pairing: one game is always allowed
        parts.append((label, games, rows))
    record = validity.evaluate_composition(config, parts)
    assert record["verdict"] == "fail" and "exclusion" not in record
    assert record["failures"] == ["deck pairing Faeries (p0) vs Rally (p1): 3 of 6 scheduled games ended natural, "
                                  "needs 5"]
    assert [(block["run"], block["matchup_index"], block["natural"], block["complete_pairs"])
            for block in record["blocks"]] == [("2026-11-01", 15, 127, 63), ("2026-11-02", 16, 127, 63),
                                               ("2026-11-03", 17, 127, 63)]
    cell = next(pairing for pairing in record["pairings"] if pairing["decks"] == ["Faeries", "Rally"])
    assert [run for run, _ in cell["not_natural"]] == ["2026-11-01", "2026-11-02", "2026-11-03"]
    # With the 18-block run beside them the pairing has 42 scheduled games and may lose four.
    whole = [("2026-11-04", list(contexts), [_Row(context.game_index) for context in contexts])]
    assert validity.evaluate_composition(config, parts + whole)["verdict"] == "pass"
    assert validity.evaluate_composition(_board(tmp_path, None), parts) is None


def test_a_long_list_of_failures_is_cut_in_the_reason() -> None:
    reason = validity.exclusion_reason([f"line {index}" for index in range(12)])
    assert reason.endswith("line 7; and 4 more") and "line 8" not in reason


def test_a_failing_verdict_keeps_a_run_unrated() -> None:
    facts = {"status": "complete", "verdict": "pass", "commitment_proof": TEST_PROOF,
             "allocation": small_allocation(), "engine_files": TEST_ENGINE_FILES}
    assert is_rated(**facts) and is_rated(**facts, validity_verdict="pass")
    assert not is_rated(**facts, validity_verdict="fail")


# ---------------- the published ledgers under the proposed unit ----------------


def _published(benchmark: str, run: str):
    run_dir = REPO / "benchmarks" / benchmark / "runs" / run
    config = TournamentConfig.from_json(store.read_json(run_dir / store.CONFIG_NAME))
    manifest = store.read_json(run_dir / store.MANIFEST_NAME)
    rows = parse_ledger(store.read_jsonl(run_dir / store.LEDGER_NAME))
    contexts = schedule(config, RunSecret.from_hex(manifest["secrets"]["run_secret"]))
    record = validity.evaluate(replace(config, validity=ValidityUnit.from_json(UNIT)), contexts, rows, run_label=run)
    return manifest, record


def test_the_published_runs_carry_no_record_and_show_the_threshold_arithmetic() -> None:
    """The arithmetic behind the proposed thresholds, on the published ledgers. Their own manifests name no unit,
    so nothing published changes; the unit is applied here only to read what it would have said."""
    manifest, record = _published("pauper-ladder-v2", "2026-11-08")
    assert "validity" not in manifest and manifest["run"]["rated"] is True
    worst = record["blocks"][13]  # the published block with 125 natural games and 122 games in complete pairs
    assert (worst["natural"], worst["complete_pairs"]) == (125, 61)
    assert record["failures"] == [f"block 13 ({worst['bots'][0]} vs {worst['bots'][1]}): 61 of 64 scheduled pairs "
                                  "are complete, needs 63"]
    assert sorted(block["complete_pairs"] for block in record["blocks"])[:3] == [61, 63, 63]
    # The entrant run: one halt, one broken pair, a pass.
    manifest, record = _published("pauper-ladder-v2", "2026-11-09")
    assert "validity" not in manifest and record["verdict"] == "pass"
    assert sorted((block["natural"], block["complete_pairs"]) for block in record["blocks"])[0] == (127, 63)
    # The excluded run: block 0 misses the natural count and the pairs, one rung falls under 97%, and the Faeries
    # mirror keeps 43 of its 48 games (89.6%).
    manifest, record = _published("pauper-ladder-v2", "2026-11-14")
    assert "validity" not in manifest
    assert (record["blocks"][0]["natural"], record["blocks"][0]["complete_pairs"]) == (124, 61)
    faeries = next(pairing for pairing in record["pairings"] if pairing["decks"] == ["Faeries", "Faeries"])
    assert (faeries["natural"], faeries["scheduled"], faeries["natural_min"], faeries["pass"]) == (43, 48, 44, False)
    assert len(record["failures"]) == 4
    # The grid: one block with two broken pairs, and its worst cell keeps exactly the 90% the unit asks for.
    manifest, record = _published("pauper-grid-v1", "2026-11-08")
    assert "validity" not in manifest
    assert [block["complete_pairs"] for block in record["blocks"] if block["complete_pairs"] < 64] == [63, 63, 62, 63, 63]
    cells = {tuple(pairing["decks"]): pairing for pairing in record["pairings"] if pairing["not_natural"]}
    assert {decks: (cell["natural"], cell["scheduled"], cell["natural_min"]) for decks, cell in cells.items()} == {
        ("Faeries", "Rally"): (27, 30, 27), ("Rally", "Faeries"): (28, 30, 27), ("Faeries", "CawGates"): (29, 30, 27)}
    assert len(record["failures"]) == 1 and "62 of 64 scheduled pairs are complete" in record["failures"][0]


def test_a_published_leaderboard_rebuilds_byte_for_byte() -> None:
    run_dir = REPO / "benchmarks" / "pauper-grid-v1" / "runs" / "2026-11-08"
    config = TournamentConfig.from_json(store.read_json(run_dir / store.CONFIG_NAME))
    assert config.validity is None
    entries = {entry.name: entry for entry in registry.read_registry(run_dir / store.REGISTRY_NAME)}
    rows = parse_ledger(store.read_jsonl(run_dir / store.LEDGER_NAME))
    document, markdown = leaderboard.build_leaderboard(
        rows, [entries[spec.name] for spec in config.bots], anchor_bot_id=entries[config.rating_anchor].bot_id,
        base_seed=config.stats_seed, bootstrap_replicates=config.bootstrap_replicates, format=config.format,
        schema=leaderboard.LEADERBOARD_SCHEMA_V2)
    assert store.canonical_bytes(document) + b"\n" == (run_dir / store.LEADERBOARD_JSON_NAME).read_bytes()
    assert markdown.encode("utf-8") == (run_dir / store.LEADERBOARD_MD_NAME).read_bytes()


# ---------------- a run, its manifest, and what is published from it ----------------


def _definition(directory: Path, pool: list[str]) -> dict[str, Any]:
    raw = value(directory)
    raw["bots"] = raw["bots"][:2]  # uniform and heuristic, both rungs
    raw.update(deck_pool=pool, pairs_per_deck=2, validity=UNIT)
    return raw


@pytest.fixture(scope="module")
def failing(tmp_path_factory):
    """A committed run on a board whose second deck halts every game: half of each block is not natural."""
    directory = tmp_path_factory.mktemp("validity") / "fixture"
    write_definition(directory, _definition(directory, ["Burn", "Halt"]))
    panel.prepare_benchmark(directory)
    return directory, play(directory, "2026-10-01")


@pytest.fixture(scope="module")
def passing(tmp_path_factory):
    directory = tmp_path_factory.mktemp("validity") / "fixture"
    write_definition(directory, _definition(directory, ["Burn", "Elves"]))
    panel.prepare_benchmark(directory)
    return directory, play(directory, "2026-10-01")


def test_a_failing_run_is_published_in_full_and_not_rated(failing) -> None:
    directory, summary = failing
    run_dir = summary.tournament_dir
    assert (summary.status, summary.games_total, summary.games_halted, summary.rated) == ("complete", 8, 4, False)
    manifest = store.read_json(run_dir / store.MANIFEST_NAME)
    record = manifest["validity"]
    assert record["verdict"] == "fail" and manifest["run"] == {
        "benchmark_id": "fixture", "label": "2026-10-01", "status": "complete", "rated": False}
    assert (record["blocks"][0]["natural"], record["blocks"][0]["natural_min"], record["blocks"][0]["complete_pairs"],
            record["blocks"][0]["complete_pairs_min"]) == (4, 8, 2, 4)
    assert [(pairing["decks"], pairing["natural"], pairing["scheduled"]) for pairing in record["pairings"]] == [
        (["Burn", "Burn"], 4, 4), (["Halt", "Halt"], 0, 4)]
    assert record["exclusion"]["run"] == "2026-10-01"
    assert record["exclusion"]["reason"].startswith("failed the board's validity unit (spellbench-validity/v1): ")
    assert manifest["secrets"]["run_secret"]  # revealed like every run
    assert validate_tournament_dir(run_dir) == []  # the record and the withheld leaderboard recompute


def test_a_failing_run_publishes_no_rating(failing) -> None:
    _, summary = failing
    board = store.read_json(summary.tournament_dir / store.LEADERBOARD_JSON_NAME)
    assert board["status"] == "withheld" and summary.leaderboard_status == "withheld"
    assert board["withheld"]["reason"].startswith("failed the board's validity unit")
    assert all((row["rated"], row["rank"], row["elo_milli"], row["rating_log_units_e6"], row["ci95_elo_milli"])
               == (False, None, None, None, None) for row in board["rows"])
    assert {row["name"]: row["games"] for row in board["rows"]} == {"uniform": 4, "heuristic": 4}  # what was played
    assert board["subratings"] == [] and board["slices"] == {"deck": []} and "deck_grid" not in board
    assert board["bt"]["rating_bootstrap"]["status"] == "not_applicable"
    assert "no rating is published from this run" in board["notes"][-1]
    text = (summary.tournament_dir / store.LEADERBOARD_MD_NAME).read_text(encoding="utf-8")
    assert "- Status: withheld (no rating is published from this run: it failed the board's validity unit" in text
    assert "| - | uniform 2.0.0 | - | - | - |" in text


def test_the_validator_recomputes_the_record(failing, tmp_path: Path) -> None:
    directory, summary = failing
    run_dir = tmp_path / "2026-10-01"
    shutil.copytree(summary.tournament_dir, run_dir)
    manifest = json.loads((run_dir / "manifest.json").read_bytes())
    manifest["validity"]["verdict"] = "pass"
    manifest["validity"]["exclusion"] = None
    manifest["run"]["rated"] = True
    (run_dir / "manifest.json").write_bytes(store.canonical_bytes(manifest) + b"\n")
    failures = validate_tournament_dir(run_dir)
    assert any("manifest validity.verdict is \"pass\"; recomputed: \"fail\"" in failure for failure in failures)
    assert any("manifest run.rated is true; recomputed: false" in failure
               and "the run fails its board's validity unit" in failure for failure in failures)
    del manifest["validity"]
    (run_dir / "manifest.json").write_bytes(store.canonical_bytes(manifest) + b"\n")
    assert any("manifest validity is missing, but config.json names a validity unit" in failure
               for failure in validate_tournament_dir(run_dir))


def test_a_record_without_a_unit_fails_validation(tmp_path: Path) -> None:
    directory = tmp_path / "fixture"
    raw = _definition(directory, ["Burn", "Elves"])
    del raw["validity"]
    write_definition(directory, raw)
    panel.prepare_benchmark(directory)
    run_dir = play(directory, "2026-10-01").tournament_dir
    manifest = json.loads((run_dir / "manifest.json").read_bytes())
    manifest["validity"] = {"verdict": "pass"}
    (run_dir / "manifest.json").write_bytes(store.canonical_bytes(manifest) + b"\n")
    assert any("manifest validity is present, but config.json names no validity unit" in failure
               for failure in validate_tournament_dir(run_dir))


def test_a_failing_run_is_excluded_by_its_own_record(failing, tmp_path: Path) -> None:
    directory, summary = failing
    benchmark = definition.load_benchmark(directory)
    assert benchmark.excluded_runs == ()  # nothing typed by hand
    excluded = definition.excluded_runs(directory)
    assert [run for run, _ in excluded] == ["2026-10-01"]
    assert excluded[0][1] == store.read_json(summary.tournament_dir / "manifest.json")["validity"]["exclusion"]["reason"]
    assert definition.excluded_run_names(directory) == {"2026-10-01"}
    assert panel.sources(directory) == []
    refusal = r"no rating is composed for heuristic vs uniform \(run 2026-10-01\): that run failed"
    with pytest.raises(snapshot.SnapshotError, match=refusal):
        panel.compose_benchmark(directory, date="2026-10-01")
    with pytest.raises(snapshot.SnapshotError, match=refusal):
        panel.compose_benchmark(directory, unrated=True, date="2026-10-01")  # not as an unrated preview either
    assert not (directory / "snapshots").exists()
    assert board_run_dir(directory) is None
    root = tmp_path / "benchmarks"
    shutil.copytree(directory, root / directory.name)
    warnings = build_site(root, tmp_path / "site")
    assert any("runs/2026-10-01: excluded from measurement: failed the board's validity unit" in warning
               for warning in warnings)
    assert not (tmp_path / "site" / "b" / directory.name).exists()


def test_a_failed_evaluation_is_not_replayed_under_the_same_conditions(failing, tmp_path: Path) -> None:
    directory, _ = failing
    target = tmp_path / directory.name
    shutil.copytree(directory, target)
    before = (target / "benchmark.json").read_bytes()
    assert panel.failed_attempts(target, panel.full_config(definition.load_benchmark(target))) == {
        ("heuristic", "uniform"): "2026-10-01"}
    with pytest.raises(definition.BenchmarkError, match=r"heuristic vs uniform \(run 2026-10-01\); a failed "
                                                        "evaluation is not replayed or topped up"):
        panel.prepare_benchmark(target)
    assert (target / "benchmark.json").read_bytes() == before
    # A changed evaluation is a new definition: everything is scheduled again, and the failed run stays a record.
    raw = json.loads(before)
    raw["evaluation_version"] = "fixture-v2"
    write_definition(target, raw)
    assert set(panel.prepare_benchmark(target)) == {"uniform", "heuristic"}
    assert (target / "runs" / "2026-10-01" / "manifest.json").is_file()


def test_a_failed_evaluation_is_not_committed_or_run_again(failing, tmp_path: Path,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    """The unchanged definition still schedules the failed matchup: neither bench commit nor a committed bench run
    plays it, whether or not bench prepare was run again."""
    from spellbench.bench import commit as bench_commit, run as bench_run
    directory, _ = failing
    benchmark = definition.load_benchmark(directory)
    assert benchmark.evaluation_matchups is None and benchmark.evaluation_targets == ("heuristic", "uniform")
    with pytest.raises(definition.BenchmarkError, match="a failed evaluation is not replayed or topped up"):
        panel.refuse_replay(directory, benchmark)
    with pytest.raises(bench_commit.CommitError, match=r"heuristic vs uniform \(run 2026-10-01\)"):
        bench_commit.commit_run(directory, placement="main-pc=used: test")
    # A committed run that reaches play is refused inside the reveal guard, so its commitment is still published.
    revealed = []
    run_dir = directory / "runs" / "2026-10-02"
    monkeypatch.setattr(bench_run, "_holds_only_the_commitment", lambda *args: None)
    monkeypatch.setattr(bench_run.commit, "run_lock", lambda *args, **kwargs: __import__("contextlib").nullcontext())
    for name in ("check_not_started", "load_run_secret", "load_placement", "pushed_commit", "check_definition",
                 "mark_started"):
        monkeypatch.setattr(bench_run.commit, name, lambda *args, **kwargs: None)
    monkeypatch.setattr(bench_run.commit, "reveal_run", lambda run, **kwargs: revealed.append(kwargs["reason"]))
    with pytest.raises(bench_run.GuardError, match="a failed evaluation is not replayed or topped up"):
        bench_run._committed_run(benchmark, directory, "2026-10-02", proof="test", environ={})
    assert revealed == ["guard"] and not run_dir.exists()
    # An unrated run binds nothing, and a board without a unit is never refused.
    panel.refuse_replay(directory, replace(benchmark, validity=None))


def test_a_run_that_lists_no_matchups_still_binds_its_round_robin(failing, tmp_path: Path) -> None:
    directory, _ = failing
    target = tmp_path / directory.name
    shutil.copytree(directory, target)
    config_path = target / "runs" / "2026-10-01" / "config.json"
    config = json.loads(config_path.read_bytes())
    del config["matchups"]  # a panel config may leave its schedule to the round robin
    config_path.write_bytes(store.canonical_bytes(config) + b"\n")
    assert panel.failed_attempts(target, panel.full_config(definition.load_benchmark(target))) == {
        ("heuristic", "uniform"): "2026-10-01"}


def test_a_later_run_never_stands_in_for_a_failed_one(passing) -> None:
    directory, summary = passing
    source = snapshot.read_source(summary.tournament_dir)
    config = panel.full_config(definition.load_benchmark(directory))
    pair = ("heuristic", "uniform")
    assert snapshot.select_blocks(config, [source]) == {pair: source}
    # The matchup failed in an earlier committed run of this evaluation: this later block is never selected.
    assert snapshot.select_blocks(config, [source], barred={pair: "2026-09-30"}) == {}
    assert snapshot.select_blocks(config, [source], barred={pair: "2026-10-01"}) == {pair: source}
    # A block played before the failed attempt keeps its place.
    assert snapshot.select_blocks(config, [source], barred={pair: "2026-10-02"}) == {pair: source}


# A unit loose enough per block that one lost game passes a one-block run of eight games.
LOOSE = {"unit": "spellbench-validity/v1", "block_natural_permille": 800, "block_complete_pairs_permille": 700,
         "rung_natural_permille": 800, "pairing_natural_permille": 900}


def test_three_real_runs_that_each_pass_do_not_compose(tmp_path: Path) -> None:
    """Three one-block runs of a ladder, played for real. With one game of the Burn mirror lost in each, every run
    still passes the unit (3 of 4 games of the pairing, one always allowed) and the rating composed from the three
    does not (9 of 12, 11 needed): the composition is judged from the sources' own schedules."""
    directory = tmp_path / "fixture"
    raw = value(directory)
    first = builtin("first")
    first["display"] = {"label": "first", "author": "fixture", "description": "local test bot", "url": None}
    raw["bots"] = [raw["bots"][0], raw["bots"][1], first]
    raw.update(deck_pool=["Burn", "Elves"], pairs_per_deck=2, validity=LOOSE,
               opponent_panel=["uniform", "heuristic", "first"], ladder={"band": 2, "entrants": {}})
    write_definition(directory, raw)
    panel.prepare_benchmark(directory)
    prepared = json.loads((directory / "benchmark.json").read_bytes())
    matchups = prepared["evaluation_matchups"]
    assert len(matchups) == 3
    for day, pair in zip(("2026-10-01", "2026-10-02", "2026-10-03"), matchups):
        write_definition(directory, {**prepared, "evaluation_matchups": [pair]})
        summary = play(directory, day)
        assert summary.rated and summary.games_total == 8
    write_definition(directory, prepared)
    config = panel.full_config(definition.load_benchmark(directory))
    found = panel.sources(directory)
    selected = snapshot.select_blocks(config, found)
    assert sorted(source.path.name for source in selected.values()) == ["2026-10-01", "2026-10-02", "2026-10-03"]
    manifest = snapshot.materialize(config, selected, benchmark_id="fixture", label="2026-10-04")[0]
    assert manifest["validity"]["verdict"] == "pass"
    assert sorted((block["run"], block["scheduled"], block["natural"]) for block in manifest["validity"]["blocks"]) == [
        ("2026-10-01", 8, 8), ("2026-10-02", 8, 8), ("2026-10-03", 8, 8)]
    assert [(pairing["decks"], pairing["scheduled"]) for pairing in manifest["validity"]["pairings"]] == [
        (["Burn", "Burn"], 12), (["Elves", "Elves"], 12)]

    def losing_one(source: snapshot.Source) -> snapshot.Source:
        """The same run with its first Burn mirror game halted, as an engine halt records it."""
        lost = next(row for row in source.rows if row.decks[0].catalog_id == "Burn")
        halted = replace(lost, classification="halted", outcome="halted", winner=None, winner_bot_id=None,
                         reason="engine_contract_failure:test")
        return replace(source, rows=tuple(halted if row is lost else row for row in source.rows))

    thin = {pair: losing_one(source) for pair, source in selected.items()}
    for source in thin.values():  # each run alone still passes the unit
        contexts = schedule(source.config, RunSecret.from_hex(source.manifest["secrets"]["run_secret"]))
        alone = validity.evaluate(source.config, contexts, source.rows, run_label=source.path.name)
        assert alone["verdict"] == "pass" and alone["blocks"][0]["natural"] == 7
    with pytest.raises(snapshot.SnapshotError, match="the composed results fail the board's validity unit: deck "
                                                     r"pairing Burn \(p0\) vs Burn \(p1\): 9 of 12 scheduled games "
                                                     "ended natural, needs 11"):
        snapshot.materialize(config, thin, benchmark_id="fixture", label="2026-10-04")
    with pytest.raises(snapshot.SnapshotError, match="the composed results fail"):
        snapshot.materialize(config, thin, benchmark_id="fixture", label="2026-10-04", rated_only=False)


def test_a_hand_typed_exclusion_keeps_its_reason(failing, tmp_path: Path) -> None:
    directory, _ = failing
    target = tmp_path / directory.name
    shutil.copytree(directory, target)
    raw = json.loads((target / "benchmark.json").read_bytes())
    raw["excluded_runs"] = [{"run": "2026-10-01", "reason": "typed by hand"}]
    write_definition(target, raw)
    assert definition.excluded_runs(target) == (("2026-10-01", "typed by hand"),)


def test_an_unreadable_manifest_excludes_nothing(tmp_path: Path) -> None:
    run_dir = tmp_path / "2026-10-01"
    run_dir.mkdir()
    assert validity.run_exclusion(run_dir) is None
    (run_dir / "manifest.json").write_bytes(b"[1,2]\n")
    assert validity.run_exclusion(run_dir) is None


def test_a_snapshot_never_cites_a_failing_run(failing) -> None:
    directory, summary = failing
    source = snapshot.read_source(summary.tournament_dir)
    config = panel.full_config(definition.load_benchmark(directory))
    assert snapshot.select_blocks(config, [source], rated_only=False) == {}
    with pytest.raises(snapshot.SnapshotError, match="failed its board's validity unit"):
        snapshot.materialize(config, {("heuristic", "uniform"): source}, benchmark_id="fixture", label="2026-10-01",
                             rated_only=False)


def test_a_passing_run_is_rated_and_composes(passing, tmp_path: Path) -> None:
    directory, summary = passing
    manifest = store.read_json(summary.tournament_dir / store.MANIFEST_NAME)
    assert summary.rated and manifest["validity"]["verdict"] == "pass" and manifest["validity"]["exclusion"] is None
    assert validate_tournament_dir(summary.tournament_dir) == []
    assert store.read_json(summary.tournament_dir / store.LEADERBOARD_JSON_NAME)["status"] == "ok"
    assert definition.excluded_runs(directory) == ()
    target = tmp_path / directory.name
    shutil.copytree(directory, target)
    composed = panel.compose_benchmark(target, date="2026-10-01")
    assert validate_tournament_dir(composed) == []
    published = store.read_json(composed / store.MANIFEST_NAME)
    assert published["contract"]["validity"] == UNIT
    # The snapshot carries the unit applied to the blocks it combines, with their scheduled denominators.
    assert published["validity"]["verdict"] == "pass" and "exclusion" not in published["validity"]
    assert [(block["run"], block["scheduled"], block["natural"]) for block in published["validity"]["blocks"]] == [
        ("2026-10-01", 8, 8)]
    # A composed sample that fails the unit is not published, rated or as an unrated preview.
    failed = {**published["validity"], "verdict": "fail", "failures": ["deck pairing Burn (p0) vs Elves (p1): thin"]}
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(validity, "evaluate_composition", lambda config, parts: failed)
        for unrated in (False, True):
            with pytest.raises(snapshot.SnapshotError, match="the composed results fail the board's validity unit: "
                                                             "deck pairing Burn"):
                panel.compose_benchmark(target, unrated=unrated, date="2026-10-02")
        assert validate_tournament_dir(composed) != []  # and a published one would not validate
    assert not (target / "snapshots" / "2026-10-02").exists()
    # The unit is part of the evaluation: another unit matches no played block.
    raw = json.loads((target / "benchmark.json").read_bytes())
    raw["validity"] = {**UNIT, "pairing_natural_permille": 950}
    write_definition(target, raw)
    assert set(panel.prepare_benchmark(target)) == {"uniform", "heuristic"}


def test_a_board_without_a_unit_has_no_record(tmp_path: Path) -> None:
    directory = tmp_path / "fixture"
    raw = _definition(directory, ["Burn", "Halt"])
    del raw["validity"]
    write_definition(directory, raw)
    panel.prepare_benchmark(directory)
    summary = play(directory, "2026-10-01")
    manifest = store.read_json(summary.tournament_dir / store.MANIFEST_NAME)
    assert "validity" not in manifest and summary.rated  # as before: nothing judges the halts
    assert "validity" not in store.read_json(summary.tournament_dir / store.CONFIG_NAME)
    assert validate_tournament_dir(summary.tournament_dir) == []


def test_the_definition_checks_the_unit(tmp_path: Path) -> None:
    raw = _definition(tmp_path / "fixture", ["Burn"])
    assert definition.parse_benchmark(raw).validity == ValidityUnit.from_json(UNIT)
    with pytest.raises(definition.BenchmarkError, match="benchmark.validity.block_natural_permille"):
        definition.parse_benchmark({**raw, "validity": {**UNIT, "block_natural_permille": 1200}})


def test_bench_run_reports_the_verdict(failing, passing, monkeypatch: pytest.MonkeyPatch,
                                       capsys: pytest.CaptureFixture[str]) -> None:
    from spellbench.bench import run as bench_run
    for (directory, summary), code in ((passing, 0), (failing, 1)):
        result = bench_run.BenchmarkRun(run_dir=summary.tournament_dir, summary=summary, failures=())
        monkeypatch.setattr(bench_run, "run_benchmark", lambda *args, result=result, **kwargs: result)
        monkeypatch.setattr(panel, "compose_benchmark", lambda *args, **kwargs: summary.tournament_dir)
        assert cli.main(["bench", "run", str(directory), "--unrated"]) == code
        out, err = capsys.readouterr()
        assert f"validity: {'pass' if code == 0 else 'fail'} (spellbench-validity/v1)" in out
        if code:
            assert "validity: block 0 (uniform vs heuristic): 4 of 8 scheduled games ended natural, needs 8" in err
            assert "the run stays published and is excluded from measurement" in err
            assert "snapshot published" not in out
