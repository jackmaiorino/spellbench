"""Reference-panel delivery: a new entrant never starts an unchanged inference bot."""
from __future__ import annotations

import json
import shutil
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from spellbench.arena import cli, runner, snapshot, store
from spellbench.arena.config import TournamentConfig, TournamentError
from spellbench.arena.validate import validate_tournament_dir
from spellbench.bench import definition, panel
from spellbench.bench.run import _launch_files, run_benchmark, GuardError
from spellbench.run_secret import RunSecret
from spellbench.site.build import build_site

from arena_helpers import FAKE_ENGINE, TEST_PROOF, small_allocation, builtin, subprocess_bot, roomy_machine

BOT = Path(__file__).with_name("panel_bot.py")


def write_definition(directory, value):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "benchmark.json").write_text(json.dumps(value), encoding="utf-8")


def value(directory):
    marker = directory.parent / "calls.txt"
    bots = [builtin("uniform", seed=100), builtin("heuristic"),
        subprocess_bot("cached-llm", [sys.executable, str(BOT), "cached-llm", f"--marker={marker}"],
                       evaluation_inputs=[str(BOT.with_name("bot_one_land.py"))])]
    for bot in bots:
        bot["display"] = {"label": bot["name"], "author": "fixture", "description": "local test bot", "url": None}
    return {"schema": "spellbench-benchmark/v2", "id": directory.name, "title": "Panel fixture",
        "summary": "Offline reference-panel fixture.", "format": "pauper-bo1",
        "engine": {"name": "fake-v2-engine", "command": [sys.executable, str(FAKE_ENGINE)]},
        "deck_pool": ["Burn"], "pairs_per_deck": 2, "stats_seed": 7, "bootstrap_replicates": 1000,
        "opponent_panel": ["uniform", "heuristic"], "evaluation_version": "fixture-v1", "bots": bots}


def play(directory, label, *, rated=True, secret=None):
    config = TournamentConfig.from_json(definition.load_benchmark(directory).tournament_config(f"runs/{label}"))
    engine, files = _launch_files(config)
    return runner.run_tournament(config, run_secret=secret or RunSecret(bytes(range(32))),
        allocation=small_allocation(), engine_files=engine, launch_files=files,
        commitment_proof=TEST_PROOF if rated else None, output_dir=directory / "runs" / label,
        benchmark_id=directory.name, run_label=label)


@pytest.fixture(scope="module")
def completed(tmp_path_factory):
    root = tmp_path_factory.mktemp("panel")
    directory = root / "fixture"
    raw = value(directory)
    write_definition(directory, raw)
    assert set(panel.prepare_benchmark(directory)) == {"uniform", "heuristic", "cached-llm"}
    first = play(directory, "2026-10-01")
    assert first.rated and validate_tournament_dir(first.tournament_dir) == []
    marker = root / "calls.txt"
    before = marker.read_bytes()
    original = {path.name: path.read_bytes() for path in first.tournament_dir.iterdir() if path.is_file()}
    raw = json.loads((directory / "benchmark.json").read_bytes())
    added = builtin("first")
    added["display"] = {"label": "new local bot", "author": "fixture", "description": "new local reference test bot", "url": None}
    raw["bots"].append(added)
    write_definition(directory, raw)
    assert panel.prepare_benchmark(directory) == ("first",)
    config = TournamentConfig.from_json(definition.load_benchmark(directory).tournament_config("runs/2026-10-02"))
    assert {bot.name for bot in config.bots} == {"uniform", "heuristic", "first"}
    assert {tuple(sorted(pair)) for pair in config.matchups} == {("first", "uniform"), ("first", "heuristic")}
    second = play(directory, "2026-10-02", secret=RunSecret(bytes(reversed(range(32)))))
    assert second.games_total == 8 and second.rated
    assert marker.read_bytes() == before, "unchanged LLM was started or called"
    assert original == {name: (first.tournament_dir / name).read_bytes() for name in original}
    composed = panel.compose_benchmark(directory, date="2026-10-02")
    assert validate_tournament_dir(composed) == []
    return directory, composed


def copied(completed, tmp_path):
    directory, _ = completed
    target = tmp_path / directory.name
    shutil.copytree(directory, target)
    return target


def test_new_entrant_uses_old_llm_results_without_launching_it(completed):
    directory, composed = completed
    board = store.read_json(composed / "leaderboard.json")
    assert board["games"]["total"] == 20
    assert len(board["rows"]) == 4
    assert board["evaluation"]["sources"] == ["2026-10-01", "2026-10-02"]
    assert all({m["a_name"], m["b_name"]} != {"first", "cached-llm"} for m in board["matchups"])
    assert len(board["matchups"]) == 5
    assert all(m["complete_pairs"] == 2 for m in board["matchups"])
    assert "Unplayed head-to-head" in (composed / "LEADERBOARD.md").read_text()


def test_no_change_needs_no_games_and_recomposition_is_deterministic(completed, tmp_path):
    directory = copied(completed, tmp_path)
    assert panel.prepare_benchmark(directory) == ()
    first = panel.compose_benchmark(directory, date="2026-10-03")
    second = panel.compose_benchmark(directory, date="2026-10-03")
    assert (first / "leaderboard.json").read_bytes() == (second / "leaderboard.json").read_bytes()
    with pytest.raises(definition.BenchmarkError, match="no missing"):
        run_benchmark(directory, unrated=True, date="2026-10-03")


@pytest.mark.parametrize("change", ["version", "seed", "clock", "epoch", "references", "engine"])
def test_changed_conditions_invalidate_the_affected_measurements(completed, tmp_path, change):
    directory = copied(completed, tmp_path)
    raw = json.loads((directory / "benchmark.json").read_bytes())
    if change == "version":
        raw["bots"][2]["version"] = "1.0.1"
    elif change == "seed":
        raw["bots"][2]["seed"] = 1
    elif change == "clock":
        raw["time_control"] = replace(definition.DEFAULT_TIME_CONTROL, bank_ms=700000).to_json()
    elif change == "epoch":
        raw["evaluation_version"] = "fixture-v2"
    elif change == "references":
        raw["bots"][0]["seed"] = 101
    elif change == "engine":
        raw["engine"]["command"].append("--test-another-setting")
    write_definition(directory, raw)
    pending = set(panel.prepare_benchmark(directory))
    assert "cached-llm" in pending
    if change in {"version", "seed"}:
        assert pending == {"cached-llm"}
    else:
        assert pending == {"uniform", "heuristic", "first", "cached-llm"}


def test_declared_policy_input_bytes_are_fingerprinted(completed, tmp_path):
    directory = copied(completed, tmp_path)
    raw = json.loads((directory / "benchmark.json").read_bytes())
    policy = tmp_path / "policy.json"
    policy.write_text('{"model":"snapshot-a"}', encoding="utf-8")
    raw["bots"][2]["evaluation_inputs"].append(str(policy))
    write_definition(directory, raw)
    assert panel.prepare_benchmark(directory) == ("cached-llm",)
    config = panel.full_config(definition.load_benchmark(directory))
    identity = config.bots[2].evaluation_identity
    policy.write_text('{"model":"snapshot-b"}', encoding="utf-8")
    with pytest.raises(GuardError, match="inputs changed"):
        _launch_files(config)
    panel.prepare_benchmark(directory)
    assert panel.full_config(definition.load_benchmark(directory)).bots[2].evaluation_identity != identity


def test_source_tampering_invalidates_the_snapshot(completed, tmp_path):
    directory = copied(completed, tmp_path)
    path = directory / "runs" / "2026-10-01" / "matches.jsonl"
    path.write_bytes(path.read_bytes() + b"\n")
    failures = validate_tournament_dir(directory / "snapshots" / "2026-10-02")
    assert failures and "digest mismatch" in " ".join(failures)


def test_snapshot_refuses_duplicate_blocks_and_path_escape(completed, tmp_path):
    directory = copied(completed, tmp_path)
    composed = directory / "snapshots" / "2026-10-02"
    manifest = store.read_json(composed / "manifest.json")
    manifest["sources"][0]["matchups"].append(manifest["sources"][0]["matchups"][0])
    store.write_json_atomic(composed / "manifest.json", manifest)
    assert "duplicate" in " ".join(validate_tournament_dir(composed))
    manifest["sources"][0]["run"] = "../../elsewhere"
    store.write_json_atomic(composed / "manifest.json", manifest)
    assert "dated run names" in " ".join(validate_tournament_dir(composed))


def test_unrated_sources_need_an_explicit_preview_and_do_not_enter_the_site(completed, tmp_path):
    directory = copied(completed, tmp_path)
    raw = json.loads((directory / "benchmark.json").read_bytes())
    raw["bots"][-1]["seed"] = 9
    write_definition(directory, raw)
    assert panel.prepare_benchmark(directory) == ("first",)
    play(directory, "2026-10-03", rated=False, secret=RunSecret(b"x" * 32))
    with pytest.raises(snapshot.SnapshotError, match="missing compatible"):
        panel.compose_benchmark(directory, date="2026-10-03")
    preview = panel.compose_benchmark(directory, date="2026-10-03", unrated=True)
    assert not store.read_json(preview / "manifest.json")["run"]["rated"]
    assert validate_tournament_dir(preview) == []
    site = tmp_path / "site"
    build_site(tmp_path, site)
    assert "2026-10-03" not in (site / "b" / directory.name / "index.html").read_text().split("Evaluation runs:")[1].split("</p>")[0]


def test_site_labels_indirect_ratings_and_exports_validated_sources(completed, tmp_path):
    directory = copied(completed, tmp_path)
    site = tmp_path / "site"
    build_site(tmp_path, site)
    page = (site / "b" / directory.name / "index.html").read_text(encoding="utf-8")
    assert "reference-panel" in page and "Unplayed head-to-head" in page
    assert "snapshots/2026-10-02" in page
    assert "<summary>Source run 2026-10-01" in page
    assert 'href="run/sources/2026-10-01/manifest.json"' in page
    assert "reference panel" in (site / "index.html").read_text(encoding="utf-8")
    assert "reference panel" in (site / "models.html").read_text(encoding="utf-8")
    assert validate_tournament_dir(site / "b" / directory.name / "run") == []


def test_cli_uses_the_guarded_launcher_and_composes_an_unrated_preview(completed, tmp_path, monkeypatch, capsys):
    directory = copied(completed, tmp_path)
    raw = json.loads((directory / "benchmark.json").read_bytes())
    raw["bots"][-1]["seed"] = 17
    write_definition(directory, raw)
    marker = completed[0].parent / "calls.txt"
    before = marker.read_bytes()
    assert cli.main(["bench", "prepare", str(directory), "--unrated"]) == 0
    roomy_machine(monkeypatch)
    assert cli.main(["bench", "run", str(directory), "--unrated", "--date", "2026-10-03"]) == 0
    assert marker.read_bytes() == before
    assert "snapshot published" in capsys.readouterr().out
    snapshot_dir = panel.published_snapshots(directory)[-1]
    assert not store.read_json(snapshot_dir / "manifest.json")["run"]["rated"]
    assert validate_tournament_dir(snapshot_dir) == []


def test_preparation_preserves_a_pending_committed_definition(completed, tmp_path):
    directory = copied(completed, tmp_path)
    pending = directory / "runs" / "2026-10-04"
    pending.mkdir()
    store.write_json_atomic(pending / "COMMITMENT.json", {"fixture": "pending"})
    before = (directory / "benchmark.json").read_bytes()
    with pytest.raises(definition.BenchmarkError, match="freeze the definition"):
        panel.prepare_benchmark(directory)
    assert (directory / "benchmark.json").read_bytes() == before


def test_whole_blocks_keep_halts_and_exclude_their_incomplete_pairs(completed):
    directory, _ = completed
    config = panel.full_config(definition.load_benchmark(directory))
    sources = panel.sources(directory)
    selected = snapshot.select_blocks(config, sources)
    source = sources[0]
    row = source.blocks()[("cached-llm", "heuristic")][0]
    halted = replace(row, classification="halted", outcome="halted", winner=None, winner_bot_id=None,
                     reason="fixture_engine_halt", adjudication=None)
    changed = replace(source, rows=tuple(halted if old is row else old for old in source.rows))
    selected[("cached-llm", "heuristic")] = changed
    _, _, board, _ = snapshot.materialize(config, selected, benchmark_id=directory.name, label="2026-10-05")
    assert board["games"]["total"] == 20 and board["games"]["halted"] == 1
    matchup = next(m for m in board["matchups"] if {m["a_name"], m["b_name"]} == {"cached-llm", "heuristic"})
    assert matchup["complete_pairs"] == 1 and matchup["incomplete_pairs"] == 1


def test_source_engine_facts_must_agree_before_combining_results(completed):
    directory, _ = completed
    config = panel.full_config(definition.load_benchmark(directory))
    selected = snapshot.select_blocks(config, panel.sources(directory))
    pair = ("first", "uniform")
    source = selected[pair]
    manifest = {**source.manifest, "engine": {**source.manifest["engine"], "version": "changed-engine"}}
    selected[pair] = replace(source, manifest=manifest)
    with pytest.raises(snapshot.SnapshotError, match="disagree on engine"):
        snapshot.materialize(config, selected, benchmark_id=directory.name, label="2026-10-05")


def test_engine_side_inputs_are_fingerprinted_and_guarded(completed, tmp_path):
    directory = copied(completed, tmp_path)
    raw = json.loads((directory / "benchmark.json").read_bytes())
    data = tmp_path / "engine-data.json"
    data.write_text('{"rules":"a"}', encoding="utf-8")
    raw["evaluation_engine_inputs"] = [str(data)]
    write_definition(directory, raw)
    assert set(panel.prepare_benchmark(directory)) == {"uniform", "heuristic", "first", "cached-llm"}
    config = panel.full_config(definition.load_benchmark(directory))
    data.write_text('{"rules":"b"}', encoding="utf-8")
    with pytest.raises(GuardError, match="engine inputs changed"):
        _launch_files(config)


@pytest.mark.parametrize("pairs", [[["uniform", "unknown"]], [["uniform", "uniform"]],
                                  [["uniform", "heuristic"], ["heuristic", "uniform"]], "invalid"])
def test_explicit_matchups_are_checked_before_launch(completed, pairs):
    directory, _ = completed
    config = panel.full_config(definition.load_benchmark(directory)).to_json()
    config["matchups"] = pairs
    with pytest.raises(TournamentError, match="matchups"):
        TournamentConfig.from_json(config)


@pytest.mark.parametrize("change", ["command", "placeholder", "targets", "fingerprint"])
def test_prepared_definition_still_validates_inactive_entrants(completed, change):
    raw = json.loads((completed[0] / "benchmark.json").read_bytes())
    assert raw["evaluation_targets"] == ["first"]
    if change == "command":
        raw["bots"][2]["command"] = []
    elif change == "placeholder":
        raw["bots"][2]["command"] = ["${BROKEN-PATH}"]
    elif change == "targets":
        raw["evaluation_targets"] = None
    else:
        raw["evaluation_engine_identity"] = None
    with pytest.raises(definition.BenchmarkError):
        definition.parse_benchmark(raw)


def test_snapshot_rejects_matchups_outside_the_frozen_panel(completed):
    directory, _ = completed
    config = panel.full_config(definition.load_benchmark(directory))
    selected = snapshot.select_blocks(config, panel.sources(directory))
    selected[("cached-llm", "first")] = next(iter(selected.values()))
    with pytest.raises(snapshot.SnapshotError, match="outside the reference panel"):
        snapshot.materialize(config, selected, benchmark_id=directory.name, label="2026-10-05")
