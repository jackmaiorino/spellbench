"""Tournament config v2."""

from __future__ import annotations

import pytest

from spellbench.arena.config import DEFAULT_LIMITS, DEFAULT_TIME_CONTROL, DeckSpec, TournamentConfig, TournamentError

BURN = [{"name": "Lightning Bolt", "count": 4}, {"name": "Mountain", "count": 18}]


def config(**changes) -> dict:
    value = {"schema": "spellbench-tournament-config/v2", "tournament_dir": "out/t", "format": "pauper-bo1",
             "decks": [{"catalog_id": "Burn"}, {"name": "My Burn", "decklist": BURN}],
             "engine": {"command": ["engine"]},
             "bots": [{"name": "uniform", "version": "2.0.0", "type": "builtin", "seed": 11},
                      {"name": "heuristic", "version": "2.0.0", "type": "builtin"}],
             "pairs_per_matchup": 2, "stats_seed": 7}
    value.update(changes)
    return value


def test_defaults_and_round_trip() -> None:
    parsed = TournamentConfig.from_json(config())
    assert parsed.time_control == DEFAULT_TIME_CONTROL and parsed.limits == DEFAULT_LIMITS
    assert parsed.rules.to_json() == {"opponent_decklist": "visible", "mulligan": "auto", "starting_player": "host_assigned", "starting_seat": "p0"}
    assert TournamentConfig.from_json(parsed.to_json()).to_json() == parsed.to_json()
    assert parsed.per_game_cores() == 1 and parsed.deck_specs()[1] == DeckSpec(name="My Burn", decklist=parsed.deck_specs()[1].decklist)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"base_seed": 1}, "stats_seed"),
        ({"engine": {"command": ["engine"], "timeout_ms": 5}}, "engine_step_ms"),
        ({"bots": [{"name": "uniform", "version": "1.0.0", "type": "builtin"}]}, "2.0.0"),
        ({"decks": [{"catalog_id": "Burn"}, {"decklist": BURN}]}, "name"),
        ({"decks": [{"catalog_id": "Burn"}, {"name": "x", "decklist": [{"name": "Lim-Du\u0302l's Vault", "count": 1}]}]}, "NFC"),
        ({"rules": {"starting_player": "toss_winner_chooses"}}, "starting_seat"),
        ({"rules": {"mulligan": "vancouver"}}, "mulligan"),
        ({"native_id_audits": {"x_kernel_v5": "https://example.org/audit"}}, "extensions"),
        ({"limits": {**DEFAULT_LIMITS.to_json(), "max_seat_steps_per_game": 50000}}, "half"),
        ({"workers": 62}, "workers"),
        ({"probe": True}, "probe"),
    ],
)
def test_invalid_configs_name_the_field(changes: dict, message: str) -> None:
    with pytest.raises(TournamentError, match=message):
        TournamentConfig.from_json(config(**changes))


def test_a_toss_rule_needs_no_seat_and_subprocess_bots_count_their_cores() -> None:
    toss = TournamentConfig.from_json(config(rules={"starting_player": "toss_winner_chooses", "starting_seat": None}))
    assert toss.rules.starting_seat is None
    sub = TournamentConfig.from_json(config(
        bots=[{"name": "uniform", "version": "2.0.0", "type": "builtin"},
              {"name": "mine", "version": "1", "type": "subprocess", "command": ["python", "bot.py"]}],
        resources={"cpus": 2, "memory_mb": 4096, "gpu": False, "engine_cpus": 1}))
    assert sub.per_game_cores() == 5


def test_a_pool_rotates_and_must_divide_the_pairs() -> None:
    pool = config(deck_pool=[{"catalog_id": "Burn"}, {"catalog_id": "Elves"}], pairs_per_matchup=4)
    del pool["decks"]
    parsed = TournamentConfig.from_json(pool)
    assert [parsed.decks_for_pair(index)[0].catalog_id for index in range(4)] == ["Burn", "Elves", "Burn", "Elves"]
    with pytest.raises(TournamentError, match="multiple"):
        TournamentConfig.from_json({**pool, "pairs_per_matchup": 3})
