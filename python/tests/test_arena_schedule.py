"""Deck pools and the self-play switch: what the round-robin schedules."""

from __future__ import annotations

import pytest

pytest.skip("protocol v1 test, migrated in Task 40", allow_module_level=True)

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from spellbench.arena import runner
from spellbench.arena.cli import validate_tournament_dir

from arena_helpers import builtin, ledger_rows, make_config, run

POOL = ("Burn", "Elves", "Faeries")
BOTS = [builtin("heuristic"), builtin("first")]


def _pool_config(directory: Path, **extra: Any) -> dict[str, Any]:
    return make_config(directory, BOTS, deck_pool=POOL, pairs=6, include_self_play=False, **extra)


def test_each_pair_plays_the_next_pool_deck_in_both_seats(tmp_path: Path) -> None:
    run(_pool_config(tmp_path / "t"))
    rows = ledger_rows(tmp_path / "t")
    assert len(rows) == 12  # one matchup x 6 pairs x 2 games
    for row in rows:
        expected = POOL[row["pair_index"] % len(POOL)]
        assert [deck["catalog_id"] for deck in row["decks"]] == [expected, expected]
    per_deck = Counter(row["decks"][0]["catalog_id"] for row in rows)
    assert per_deck == {"Burn": 4, "Elves": 4, "Faeries": 4}  # 2 pairs x 2 games per deck


def test_a_pool_schedule_is_identical_across_runs(tmp_path: Path) -> None:
    run(_pool_config(tmp_path / "a"))
    run(_pool_config(tmp_path / "b"))
    assert (tmp_path / "a" / "matches.jsonl").read_bytes() == (tmp_path / "b" / "matches.jsonl").read_bytes()


def test_pairs_per_matchup_must_be_a_multiple_of_the_pool_size(tmp_path: Path) -> None:
    config = make_config(tmp_path / "t", BOTS, deck_pool=POOL, pairs=4)
    with pytest.raises(runner.TournamentError, match="multiple"):
        runner.TournamentConfig.from_json(config)


def test_decks_and_a_deck_pool_are_exclusive(tmp_path: Path) -> None:
    config = make_config(tmp_path / "t", BOTS, deck_pool=POOL, pairs=3)
    config["decks"] = [{"catalog_id": "Burn"}, {"catalog_id": "Burn"}]
    with pytest.raises(runner.TournamentError, match="deck_pool"):
        runner.TournamentConfig.from_json(config)


def test_a_config_needs_decks_or_a_deck_pool(tmp_path: Path) -> None:
    config = make_config(tmp_path / "t", BOTS)
    del config["decks"]
    with pytest.raises(runner.TournamentError, match="decks"):
        runner.TournamentConfig.from_json(config)


@pytest.mark.parametrize("pool", [[], [{"catalog_id": "Burn"}, {"catalog_id": "Burn"}], "Burn"])
def test_a_deck_pool_is_a_nonempty_list_of_distinct_decks(tmp_path: Path, pool: Any) -> None:
    config = make_config(tmp_path / "t", BOTS, pairs=2)
    del config["decks"]
    config["deck_pool"] = pool
    with pytest.raises(runner.TournamentError, match="deck_pool"):
        runner.TournamentConfig.from_json(config)


def test_self_play_off_schedules_no_mirror_matchups(tmp_path: Path) -> None:
    bots = [builtin("heuristic"), builtin("first"), builtin("uniform", seed=11)]
    run(make_config(tmp_path / "t", bots, pairs=2, include_self_play=False))
    rows = ledger_rows(tmp_path / "t")
    assert len(rows) == 3 * 2 * 2  # 3 matchups x 2 pairs x 2 games
    assert all(row["seats"][0]["name"] != row["seats"][1]["name"] for row in rows)
    assert sorted({row["matchup_index"] for row in rows}) == [0, 1, 2]


def test_self_play_is_on_by_default(tmp_path: Path) -> None:
    run(make_config(tmp_path / "t", BOTS, pairs=1))
    seatings = {(row["seats"][0]["name"], row["seats"][1]["name"]) for row in ledger_rows(tmp_path / "t")}
    assert ("heuristic", "heuristic") in seatings and ("first", "first") in seatings


def test_self_play_off_needs_two_bots(tmp_path: Path) -> None:
    config = make_config(tmp_path / "t", [builtin("heuristic")], include_self_play=False)
    with pytest.raises(runner.TournamentError, match="two bots"):
        runner.TournamentConfig.from_json(config)


def test_include_self_play_must_be_a_boolean(tmp_path: Path) -> None:
    config = make_config(tmp_path / "t", BOTS, include_self_play=0)
    with pytest.raises(runner.TournamentError, match="include_self_play"):
        runner.TournamentConfig.from_json(config)


def test_preflight_tries_every_pool_deck_before_any_game(tmp_path: Path) -> None:
    # "Refuse" (a fake-engine hook) is second in the pool, so a preflight of
    # the first deck alone would miss it.
    directory = tmp_path / "t"
    config = make_config(directory, BOTS, deck_pool=("Burn", "Refuse"), pairs=2, include_self_play=False)
    with pytest.raises(runner.TournamentError, match="unsupported_deck"):
        run(config)
    assert not directory.exists()


def test_preflight_gives_each_pool_deck_its_own_engine_process(tmp_path: Path) -> None:
    # An engine hosts one active game per process (spec section 2), and the
    # fake engine refuses a second reset as the mtg-kernel bridge does, so a
    # preflight that reused one process across decks would fail here.
    assert run(_pool_config(tmp_path / "t")).games_rated == 12


def test_the_recorded_config_keeps_the_pool_and_the_switch(tmp_path: Path) -> None:
    run(_pool_config(tmp_path / "t"))
    recorded = json.loads((tmp_path / "t" / "config.json").read_text(encoding="utf-8"))
    assert "decks" not in recorded
    assert recorded["deck_pool"] == [{"catalog_id": deck} for deck in POOL]
    assert recorded["include_self_play"] is False


def test_a_fixed_deck_config_records_its_decks_and_self_play_on(tmp_path: Path) -> None:
    run(make_config(tmp_path / "t", BOTS, pairs=1))
    recorded = json.loads((tmp_path / "t" / "config.json").read_text(encoding="utf-8"))
    assert recorded["decks"] == [{"catalog_id": "Burn"}, {"catalog_id": "Burn"}]
    assert "deck_pool" not in recorded and recorded["include_self_play"] is True


def test_validate_accepts_pool_and_self_play_off_tournaments(tmp_path: Path) -> None:
    run(_pool_config(tmp_path / "t"))
    assert validate_tournament_dir(tmp_path / "t") == []
