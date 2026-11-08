"""The all_pairs deck pairing: its schedule, the leaderboard's deck grid, the benchmark field and the page."""

from __future__ import annotations

import copy
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from arena_helpers import builtin, leaderboard, ledger_rows, make_config, roomy_machine, run, TEST_RUN_SECRET
from spellbench.arena import deck_grid
from spellbench.arena.config import TournamentConfig, TournamentError
from spellbench.arena.schedule import schedule
from spellbench.arena.validate import validate_tournament_dir
from spellbench.bench.definition import BenchmarkError, load_benchmark, parse_benchmark
from spellbench.site import render
from test_site_render import BENCH

REPO = Path(__file__).resolve().parents[2]
POOL = ("Burn", "Elves", "Faeries")


def _config(tmp_path: Path, **extra: Any) -> TournamentConfig:
    bots = [builtin("uniform", seed=3), builtin("first"), builtin("heuristic")]
    settings = {"deck_pool": POOL, "pairs": 9, "deck_pairing": "all_pairs", "include_self_play": False, **extra}
    return TournamentConfig.from_json(make_config(tmp_path / "t", bots, **settings))


# ---------------- config and schedule ----------------


def test_cycle_is_every_ordered_pairing_mirrors_first_within_each_deck(tmp_path: Path) -> None:
    config = _config(tmp_path)
    cycle = [(first.catalog_id, second.catalog_id) for first, second in config.deck_cycle()]
    assert cycle == [("Burn", "Burn"), ("Burn", "Elves"), ("Elves", "Burn"), ("Burn", "Faeries"), ("Faeries", "Burn"),
                     ("Elves", "Elves"), ("Elves", "Faeries"), ("Faeries", "Elves"), ("Faeries", "Faeries")]
    # a reversed pairing is the same engine reset, so preflight resets each unordered pairing once
    assert len(config.preflight_deck_pairs()) == 6
    assert config.to_json()["deck_pairing"] == "all_pairs"
    assert TournamentConfig.from_json(config.to_json()) == config


def test_every_bot_pilots_every_deck_in_every_seat_equally(tmp_path: Path) -> None:
    config = _config(tmp_path, pairs=18)
    games = schedule(config, TEST_RUN_SECRET)
    assert len(games) == 3 * 18 * 2
    for matchup in range(3):
        block = [game for game in games if game.matchup_index == matchup]
        pairings = Counter((game.decks[0].catalog_id, game.decks[1].catalog_id) for game in block)
        assert set(pairings.values()) == {4}  # two cycles, two games per pair
        seats = Counter((spec.name, seat, game.decks[int(seat[1])].catalog_id)
                        for game in block for seat, spec in game.seat_specs)
        assert len(set(seats.values())) == 1  # each bot holds each deck in each seat equally often


def test_mirror_configs_keep_their_bytes_and_shape(tmp_path: Path) -> None:
    config = _config(tmp_path, deck_pairing="mirror", pairs=3)
    assert "deck_pairing" not in config.to_json()
    assert [pair[0] == pair[1] for pair in config.deck_cycle()] == [True] * 3


@pytest.mark.parametrize(("extra", "message"), [
    ({"pairs": 6}, "not a multiple of 9"),
    ({"deck_pairing": "everything"}, "deck_pairing: must be one of"),
])
def test_all_pairs_config_errors(tmp_path: Path, extra: dict[str, Any], message: str) -> None:
    with pytest.raises(TournamentError, match=message):
        _config(tmp_path, **extra)


def test_all_pairs_needs_a_pool(tmp_path: Path) -> None:
    document = make_config(tmp_path / "t", [builtin("uniform"), builtin("first")], decks=("Burn", "Elves"),
                           deck_pairing="all_pairs")
    with pytest.raises(TournamentError, match="needs a deck_pool"):
        TournamentConfig.from_json(document)


# ---------------- the deck grid over synthetic rows ----------------


@dataclass
class _Row:
    game_index: int
    decks: tuple[dict[str, Any], dict[str, Any]]
    bots: tuple[str, str]
    winner: str | None
    pair_index: int
    pair_slot: int
    rated: bool = True

    def bot_id_at(self, seat: str) -> str:
        return self.bots[int(seat[1])]

    @property
    def winner_bot_id(self) -> str | None:
        return None if self.winner is None else self.bot_id_at(self.winner)


def _deck(name: str) -> dict[str, Any]:
    return {"catalog_id": name, "deck_id": "sha256:" + name.encode().hex().ljust(64, "0")[:64], "name": name}


def _rows(winner_of: Any, cycles: int = 4) -> list[_Row]:
    """Two bots over every ordered pairing of three decks; ``winner_of(p0_deck, p1_deck, p0_bot)`` picks the seat."""
    rows: list[_Row] = []
    cycle = [(a, b) for a in POOL for b in POOL]
    for pair_index in range(cycles * len(cycle)):
        first, second = cycle[pair_index % len(cycle)]
        for slot, bots in enumerate((("a", "b"), ("b", "a"))):
            rows.append(_Row(len(rows), (_deck(first), _deck(second)), bots,
                             winner_of(first, second, bots[0]), pair_index, slot))
    return rows


TABLE = [{"bot_id": "a", "name": "a", "rated": True}, {"bot_id": "b", "name": "b", "rated": True}]


def test_mirror_only_ledgers_have_no_grid() -> None:
    rows = [row for row in _rows(lambda first, second, p0: "p0") if row.decks[0] == row.decks[1]]
    assert deck_grid.build_deck_grid(rows, TABLE, base_seed=1, bootstrap_replicates=1000) is None


def test_deck_strength_is_measured_net_of_the_pilot_and_the_seat() -> None:
    # Burn always beats Elves, whoever pilots and whichever seat it holds; elsewhere the a bot always wins.
    def winner(first: str, second: str, p0_bot: str) -> str:
        if {first, second} == {"Burn", "Elves"}:
            return "p0" if first == "Burn" else "p1"
        return "p0" if p0_bot == "a" else "p1"

    grid = deck_grid.build_deck_grid(_rows(winner), TABLE, base_seed=7, bootstrap_replicates=1000)
    assert grid is not None and grid["status"] == "ok" and grid["decks"] == list(POOL)
    report = grid["reports"][0]
    cells = {(cell["deck"], cell["opponent"]): cell for cell in report["cells"]}
    assert list(cells) == [("Burn", "Elves"), ("Burn", "Faeries"), ("Elves", "Faeries")]
    burn_elves = cells[("Burn", "Elves")]
    assert burn_elves["score"] == {"num": 32, "den": 32} and burn_elves["wins"] == 16 and burn_elves["complete_pairs"] == 8
    # the a bot wins every other game, but it pilots both decks of every pair: the pairing reads even
    assert cells[("Burn", "Faeries")]["score"] == {"num": 16, "den": 32}
    assert cells[("Elves", "Faeries")]["score"] == {"num": 16, "den": 32}
    ratings_rows = {row["deck"]: row for row in report["deck_ratings"]["rows"]}
    assert ratings_rows["Burn"]["elo_milli"] > ratings_rows["Faeries"]["elo_milli"] > ratings_rows["Elves"]["elo_milli"]
    assert sum(row["rating_log_units_e6"] for row in ratings_rows.values()) in (-1, 0, 1)  # centered
    assert report["deck_ratings"]["bootstrap"]["status"] == "ok"
    # two rated bots: no strong-pilot report
    assert grid["reports"][1]["status"] == "skipped"
    robustness = {bot["bot_id"]: bot for bot in grid["robustness"]}
    own_a = {record["deck"]: record for record in robustness["a"]["by_own_deck"]}
    assert own_a["Faeries"]["wins"] == own_a["Faeries"]["games"]  # a wins every game not decided by Burn vs Elves


def test_the_grid_is_deterministic_and_seeded() -> None:
    rows = _rows(lambda first, second, p0: "p0" if (len(first) + len(second) + ord(p0)) % 3 else "p1")
    first = deck_grid.build_deck_grid(rows, TABLE, base_seed=11, bootstrap_replicates=1000)
    assert first == deck_grid.build_deck_grid(rows, TABLE, base_seed=11, bootstrap_replicates=1000)
    other = deck_grid.build_deck_grid(rows, TABLE, base_seed=12, bootstrap_replicates=1000)
    assert first["reports"][0]["cells"][0]["score_ci95"]["seed"] != other["reports"][0]["cells"][0]["score_ci95"]["seed"]


# ---------------- a whole all_pairs tournament ----------------


def test_an_all_pairs_tournament_rates_bots_and_decks_and_validates(tmp_path: Path, monkeypatch: Any) -> None:
    roomy_machine(monkeypatch)
    bots = [builtin("uniform", seed=3), builtin("first"), builtin("heuristic")]
    config = make_config(tmp_path / "t", bots, deck_pool=POOL, pairs=9, deck_pairing="all_pairs",
                         include_self_play=False)
    run(config, rated=True)
    directory = tmp_path / "t"
    rows = ledger_rows(directory)
    assert sum(row["decks"][0]["name"] != row["decks"][1]["name"] for row in rows) == 3 * 6 * 2
    board = leaderboard(directory)
    assert board["status"] == "ok"
    grid = board["deck_grid"]
    assert grid["status"] == "ok" and len(grid["reports"][0]["cells"]) == 3
    assert [entry["label"] for entry in board["slices"]["deck"]] == list(POOL)  # mirrors only
    markdown = (directory / "LEADERBOARD.md").read_text(encoding="utf-8")
    assert "## Deck grid" in markdown and "### Robustness: score by own deck" in markdown
    assert validate_tournament_dir(directory) == []


# ---------------- the benchmark field ----------------


def _definition(**extra: Any) -> dict[str, Any]:
    """pauper-grid-v1's benchmark.json with ``extra`` fields replaced."""
    raw = json.loads((REPO / "benchmarks" / "pauper-grid-v1" / "benchmark.json").read_text(encoding="utf-8"))
    raw.update(extra)
    return raw


def test_pauper_grid_board_plays_every_pairing_at_the_ladder_budget() -> None:
    benchmark = load_benchmark(REPO / "benchmarks" / "pauper-grid-v1")
    config = TournamentConfig.from_json(benchmark.tournament_config("benchmarks/pauper-grid-v1/runs/check"))
    assert benchmark.pairing == "all_pairs" and config.deck_pairing == "all_pairs"
    assert config.pairs_per_matchup == 64 and len(schedule(config, TEST_RUN_SECRET)) == 15 * 128


def test_all_pairs_needs_pairs_per_deck_a_multiple_of_the_pool() -> None:
    with pytest.raises(BenchmarkError, match="multiple of the 8 pool decks"):
        parse_benchmark(_definition(pairs_per_deck=4))


def test_other_pairings_stay_refused() -> None:
    with pytest.raises(BenchmarkError, match="pairing: must be"):
        parse_benchmark(_definition(pairing="swiss"))


# ---------------- the page ----------------


def _grid_view() -> dict[str, Any]:
    cell = {"games": 4, "complete_pairs": 2}
    cells = [[None, {**cell, "score": 0.75, "low": 0.5, "high": 1.0}],
             [{**cell, "score": 0.25, "low": 0.0, "high": 0.5}, None]]
    return {
        "decks": ["Burn", "Elves"],
        "reports": [{"pilots": "all", "cells": cells, "residual": 0.012,
                     "ratings": [{"deck": "Burn", "elo_milli": 1_595_000, "ci95_elo_milli": [1_550_000, 1_640_000]},
                                 {"deck": "Elves", "elo_milli": 1_405_000, "ci95_elo_milli": None}]}],
        "robustness": [{"name": "heuristic", "label": "heuristic", "description": "", "by_own_deck": [0.9, None],
                        "by_opponent_deck": [0.8, 0.7]}],
    }


def test_the_page_shows_deck_matchups_only_for_a_grid_board() -> None:
    assert "Deck matchups" not in render.render_benchmark(BENCH)
    view = {**copy.deepcopy(BENCH), "deck_grid": _grid_view(), "deck_pairing": "all_pairs"}
    page = render.render_benchmark(view)
    assert "<h2>Deck matchups</h2>" in page and "every deck pairing" in page
    assert 'title="Burn vs Elves: 75% of the points, over 2 complete pairs (4 games), 95% interval 50% to 100%"' in page
    assert "Deck Elo (the average deck is 1500)" in page and "1550 to 1640" in page
    assert "differ from what the deck Elo predicts by 1.2 points" in page


# ---------------- review findings (Sol, 7036c4e) ----------------


def test_a_fixed_off_mirror_ledger_keeps_its_old_artifacts() -> None:
    # One pairing, even an off-mirror one, is a fixed-deck tournament: no grid, as before all_pairs existed.
    rows = [row for row in _rows(lambda first, second, p0: "p0") if (row.decks[0]["name"], row.decks[1]["name"]) == (
        "Burn", "Elves")]
    assert rows and deck_grid.build_deck_grid(rows, TABLE, base_seed=1, bootstrap_replicates=1000) is None


def test_the_snapshot_contract_tells_the_pairings_apart() -> None:
    from dataclasses import replace
    from spellbench.arena import snapshot

    benchmark = load_benchmark(REPO / "benchmarks" / "pauper-grid-v1")
    config = TournamentConfig.from_json(benchmark.tournament_config("benchmarks/pauper-grid-v1/runs/check"))
    config = replace(config, bots=tuple(replace(bot, evaluation_identity="0" * 64) for bot in config.bots))
    grid, mirror = snapshot.contract(config), snapshot.contract(replace(config, deck_pairing="mirror"))
    assert grid["deck_pairing"] == "all_pairs" and "deck_pairing" not in mirror and grid != mirror


def test_self_play_counts_toward_the_grid_bootstrap_budget(tmp_path: Path) -> None:
    document = make_config(tmp_path / "t", [builtin("uniform"), builtin("first")], deck_pool=("Burn", "Elves"),
                           pairs=20_000, deck_pairing="all_pairs", bootstrap_replicates=2000)
    with pytest.raises(TournamentError, match="deck grid's bootstrap"):
        TournamentConfig.from_json(document)


def test_a_human_session_on_an_all_pairs_board_plays_mirrors(monkeypatch: Any) -> None:
    import re
    from dataclasses import replace
    from spellbench.human import session

    board = replace(load_benchmark(REPO / "benchmarks" / "pauper-grid-v1"), ladder=None)
    monkeypatch.setattr(session.definition, "load_benchmark", lambda path: board)
    text = json.dumps(board.tournament_config("check"))
    local = {name: "placeholder" for name in re.findall(r"\$\{([A-Za-z0-9_]+)\}", text)}
    document = session.build_config(benchmark_dir=REPO / "benchmarks" / "pauper-grid-v1", local=local, opponent="g115",
                                    games=16, run_dir=Path("check"), python="python",
                                    decision_log=Path("log.jsonl"), bank_minutes=60)
    assert "deck_pairing" not in document and document["pairs_per_matchup"] == 8
    assert TournamentConfig.from_json(document).deck_pairing == "mirror"
