"""Reference ladders: rungs play the rungs within a band, entrants play only their listed rungs."""
from __future__ import annotations

import json
import shutil
import sys

import pytest

from spellbench.arena import snapshot, store
from spellbench.arena.config import TournamentConfig, TournamentError
from spellbench.arena.validate import validate_tournament_dir
from spellbench.bench import definition, panel
from spellbench.site.build import build_site

from arena_helpers import builtin, subprocess_bot
from test_panel import BOT, play, value, write_definition


def ladder_value(directory):
    raw = value(directory)
    first = builtin("first")
    first["display"] = {"label": "first", "author": "fixture", "description": "local test bot", "url": None}
    raw["bots"].insert(2, first)
    raw["opponent_panel"] = ["first", "uniform", "heuristic"]  # rung order, not roster order
    raw["ladder"] = {"band": 1, "entrants": {"cached-llm": ["heuristic"]}}
    return raw


def pairs(config):
    return {tuple(sorted(pair)) for pair in config.matchups}


@pytest.fixture(scope="module")
def completed(tmp_path_factory):
    root = tmp_path_factory.mktemp("ladder")
    directory = root / "fixture"
    write_definition(directory, ladder_value(directory))
    assert set(panel.prepare_benchmark(directory)) == {"uniform", "heuristic", "first", "cached-llm"}
    config = TournamentConfig.from_json(definition.load_benchmark(directory).tournament_config("runs/2026-10-01"))
    assert pairs(config) == {("first", "uniform"), ("heuristic", "uniform"), ("cached-llm", "heuristic")}
    first = play(directory, "2026-10-01")
    assert first.rated and validate_tournament_dir(first.tournament_dir) == []
    composed = panel.compose_benchmark(directory, date="2026-10-01")
    assert validate_tournament_dir(composed) == []
    return directory, composed


def copied(completed, tmp_path):
    directory, _ = completed
    target = tmp_path / directory.name
    shutil.copytree(directory, target)
    return target


def test_ladder_plays_only_band_and_listed_matchups(completed):
    _, composed = completed
    board = store.read_json(composed / "leaderboard.json")
    assert {frozenset((m["a_name"], m["b_name"])) for m in board["matchups"]} == {
        frozenset(("first", "uniform")), frozenset(("heuristic", "uniform")), frozenset(("cached-llm", "heuristic"))}
    assert board["evaluation"]["mode"] == "ladder" and board["evaluation"]["band"] == 1
    assert board["evaluation"]["opponents"] == ["first", "uniform", "heuristic"]
    assert all(row["rated"] for row in board["rows"])
    assert "Ladder rating" in (composed / "LEADERBOARD.md").read_text(encoding="utf-8")


def test_a_new_entrant_plays_only_its_rungs_and_leaves_the_others(completed, tmp_path):
    directory = copied(completed, tmp_path)
    raw = json.loads((directory / "benchmark.json").read_bytes())
    marker = tmp_path / "calls-new.txt"
    added = subprocess_bot("newcomer", [sys.executable, str(BOT), "newcomer", f"--marker={marker}"])
    added["display"] = {"label": "newcomer", "author": "fixture", "description": "new entrant", "url": None}
    raw["bots"].append(added)
    raw["ladder"]["entrants"]["newcomer"] = ["uniform", "first"]
    write_definition(directory, raw)
    assert panel.prepare_benchmark(directory) == ("first", "newcomer", "uniform")
    prepared = definition.load_benchmark(directory)
    assert {tuple(sorted(pair)) for pair in prepared.evaluation_matchups} == {("newcomer", "uniform"),
                                                                             ("first", "newcomer")}
    config = TournamentConfig.from_json(prepared.tournament_config("runs/2026-10-02"))
    assert pairs(config) == {("newcomer", "uniform"), ("first", "newcomer")}
    play(directory, "2026-10-02")
    assert panel.prepare_benchmark(directory) == ()
    composed = panel.compose_benchmark(directory, date="2026-10-02")
    assert validate_tournament_dir(composed) == []
    board = store.read_json(composed / "leaderboard.json")
    assert len(board["matchups"]) == 5 and board["evaluation"]["sources"] == ["2026-10-01", "2026-10-02"]


def test_a_wider_band_or_a_new_rung_reuses_every_played_block(completed, tmp_path):
    directory = copied(completed, tmp_path)
    raw = json.loads((directory / "benchmark.json").read_bytes())
    raw["ladder"]["band"] = 2  # adds first vs heuristic
    top = subprocess_bot("top", [sys.executable, str(BOT), "top", f"--marker={tmp_path / 'calls-top.txt'}"])
    top["display"] = {"label": "top", "author": "fixture", "description": "new top rung", "url": None}
    raw["bots"].append(top)
    raw["opponent_panel"].append("top")  # band 2: plays uniform and heuristic
    write_definition(directory, raw)
    assert panel.prepare_benchmark(directory) == ("first", "heuristic", "top", "uniform")
    prepared = definition.load_benchmark(directory)
    assert {tuple(sorted(pair)) for pair in prepared.evaluation_matchups} == {
        ("first", "heuristic"), ("heuristic", "top"), ("top", "uniform")}
    before = {path.name: path.read_bytes() for path in (directory / "runs" / "2026-10-01").iterdir()}
    play(directory, "2026-10-02")
    assert panel.prepare_benchmark(directory) == ()
    composed = panel.compose_benchmark(directory, date="2026-10-02")
    assert validate_tournament_dir(composed) == []
    receipts = {item["run"]: item["matchups"] for item in store.read_json(composed / "manifest.json")["sources"]}
    assert sorted(map(sorted, receipts["2026-10-01"])) == [["cached-llm", "heuristic"], ["first", "uniform"],
                                                          ["heuristic", "uniform"]]
    assert len(receipts["2026-10-02"]) == 3
    assert before == {path.name: path.read_bytes() for path in (directory / "runs" / "2026-10-01").iterdir()}


def test_a_changed_rung_replays_only_its_own_blocks(completed, tmp_path):
    directory = copied(completed, tmp_path)
    raw = json.loads((directory / "benchmark.json").read_bytes())
    raw["bots"][0]["seed"] = 101  # uniform, which plays first and heuristic
    write_definition(directory, raw)
    assert panel.prepare_benchmark(directory) == ("first", "heuristic", "uniform")
    prepared = definition.load_benchmark(directory)
    assert {tuple(sorted(pair)) for pair in prepared.evaluation_matchups} == {("first", "uniform"),
                                                                             ("heuristic", "uniform")}


def test_ladder_definitions_are_checked(tmp_path):
    directory = tmp_path / "fixture"
    raw = ladder_value(directory)
    for change, message in (
        (lambda r: r["ladder"]["entrants"].pop("cached-llm"), "needs its rungs; missing cached-llm"),
        (lambda r: r["ladder"]["entrants"].update({"cached-llm": ["nobody"]}), "must list distinct rungs"),
        (lambda r: r["ladder"]["entrants"].update({"cached-llm": []}), "must list distinct rungs"),
        (lambda r: r["ladder"]["entrants"].update({"first": ["uniform"]}), "outside the panel"),
        (lambda r: r["ladder"].update({"band": 3}), "band"),
        (lambda r: r["ladder"].update({"band": 0}), "band"),
        (lambda r: r["ladder"].update({"extra": 1}), "band and entrants"),
    ):
        changed = json.loads(json.dumps(raw))
        change(changed)
        with pytest.raises(definition.BenchmarkError, match=message):
            definition.parse_benchmark(changed)
    no_panel = json.loads(json.dumps(raw))
    for key in ("opponent_panel", "evaluation_version"):
        no_panel.pop(key)
    with pytest.raises(definition.BenchmarkError, match="require opponent_panel"):
        definition.parse_benchmark(no_panel)


def test_config_refuses_matchups_off_the_ladder(tmp_path):
    raw = ladder_value(tmp_path / "fixture")
    document = definition.parse_benchmark(raw).tournament_config("runs/check")
    document["matchups"].append(["first", "heuristic"])
    with pytest.raises(TournamentError, match="only ladder matchups"):
        TournamentConfig.from_json(document)


def test_panel_configs_keep_their_bytes(tmp_path):
    from test_panel import value as panel_value
    config = TournamentConfig.from_json(
        definition.parse_benchmark(panel_value(tmp_path / "fixture")).tournament_config("runs/check"))
    assert config.ladder is None and "ladder" not in config.to_json()


def test_site_labels_the_ladder(completed, tmp_path):
    directory = copied(completed, tmp_path)
    site = tmp_path / "site"
    build_site(tmp_path, site)
    page = (site / "b" / directory.name / "index.html").read_text(encoding="utf-8")
    assert "Ladder rating" in page


def test_inserting_a_rung_that_drops_played_rung_matchups_is_refused(completed, tmp_path):
    directory = copied(completed, tmp_path)
    raw = json.loads((directory / "benchmark.json").read_bytes())
    middle = subprocess_bot("middle", [sys.executable, str(BOT), "middle", f"--marker={tmp_path / 'calls-mid.txt'}"])
    middle["display"] = {"label": "middle", "author": "fixture", "description": "inserted rung", "url": None}
    raw["bots"].append(middle)
    raw["opponent_panel"] = ["first", "middle", "uniform", "heuristic"]  # first vs uniform leaves band 1
    for key in ("evaluation_targets", "evaluation_matchups"):  # the last shard named the old graph
        raw.pop(key)
    write_definition(directory, raw)
    with pytest.raises(definition.BenchmarkError, match="drop rated rung matchups it has played: first vs uniform"):
        panel.prepare_benchmark(directory)


def test_an_excluded_run_is_kept_but_never_measured(completed, tmp_path):
    directory = copied(completed, tmp_path)
    raw = json.loads((directory / "benchmark.json").read_bytes())
    raw["excluded_runs"] = [{"run": "2026-10-01", "reason": "fixture: failed the validity rule"}]
    write_definition(directory, raw)
    assert panel.sources(directory) == []
    assert set(panel.prepare_benchmark(directory)) == {"uniform", "heuristic", "first", "cached-llm"}
    assert (directory / "runs" / "2026-10-01" / "manifest.json").is_file()
    from spellbench.site.build import board_run_dir
    assert (directory / "snapshots" / "2026-10-01").is_dir()  # rated, but it cites the excluded run
    assert board_run_dir(directory) is None
    site = tmp_path / "site"
    build_site(tmp_path, site)
    assert not (site / "b" / directory.name).exists() and not (site / "charts" / f"{directory.name}.svg").exists()
    with pytest.raises(definition.BenchmarkError, match="excluded_runs"):
        definition.parse_benchmark({**raw, "excluded_runs": [{"run": "yesterday", "reason": "x"}]})


def test_a_ladder_placeholder_must_name_a_file(tmp_path, monkeypatch):
    directory = tmp_path / "fixture"
    raw = ladder_value(directory)
    raw["bots"][3]["command"].append("${SEARCH_BUDGET}")
    write_definition(directory, raw)
    monkeypatch.setenv("SEARCH_BUDGET", "65536")
    with pytest.raises(definition.BenchmarkError, match="placeholder must name a regular file"):
        panel.prepare_benchmark(directory)
    setting = tmp_path / "budget.txt"
    setting.write_text("65536", encoding="utf-8")
    monkeypatch.setenv("SEARCH_BUDGET", str(setting))
    assert "cached-llm" in panel.prepare_benchmark(directory)
