"""Preflight, schedule and per-game setup (spec 11.1, 11.6, 12)."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

from spellbench.arena.config import TournamentConfig, TournamentError
from spellbench.arena.schedule import game_setup, preflight, schedule
from spellbench.digests import deck_id
from spellbench.run_secret import RunSecret

from test_messages import HELLO_OK

TESTS = Path(__file__).resolve().parent
ENGINE = TESTS / "fake_v2_engine.py"
SECRET = RunSecret(bytes(range(32)))


def config(*, engine_args=(), bots=None, **changes) -> TournamentConfig:
    value = {"schema": "spellbench-tournament-config/v2", "tournament_dir": "unused", "format": "pauper-bo1",
             "deck_pool": [{"catalog_id": "Burn"}, {"catalog_id": "Elves"}],
             "engine": {"command": [sys.executable, str(ENGINE), *engine_args]},
             "bots": bots or [{"name": "uniform", "version": "2.0.0", "type": "builtin"},
                              {"name": "first", "version": "2.0.0", "type": "builtin"}],
             "pairs_per_matchup": 2, "stats_seed": 1, "include_self_play": False}
    value.update(changes)
    return TournamentConfig.from_json(value)


def test_preflight_resolves_decks_rules_and_the_domain() -> None:
    setup = preflight(config(), SECRET)
    burn = setup.decks[config().deck_pool[0]]
    assert burn.deck_id == deck_id([{"name": "Lightning Bolt", "count": 4}, {"name": "Mountain", "count": 18}])
    assert setup.rules.mulligan == "none" and setup.rules.starting_seat == "p0"
    assert setup.rules.card_name_domain.names == ("Lightning Bolt", "Mountain")
    assert preflight(config(engine_args=("--london",)), SECRET).rules.mulligan == "london"


def test_the_schedule_uses_opaque_ids_and_swaps_seats() -> None:
    games = schedule(config(), SECRET)
    assert [game.game_id for game in games] == [SECRET.game_id(index) for index in range(4)]
    assert [(game.pair_index, game.pair_slot) for game in games] == [(0, 0), (0, 1), (1, 0), (1, 1)]
    assert games[0].seat_specs[0][1].name == games[1].seat_specs[1][1].name == "uniform"
    assert [game.decks[0].catalog_id for game in games] == ["Burn", "Burn", "Elves", "Elves"]


def test_game_setup_derives_everything_from_the_run_secret() -> None:
    cfg = config()
    setup = preflight(cfg, SECRET)
    one = game_setup(cfg, setup, schedule(cfg, SECRET)[1], SECRET)
    assert one.game_secret_hex == SECRET.game_secret(1).hex()
    assert one.agent_seeds == (SECRET.agent_seed(1, "p0"), SECRET.agent_seed(1, "p1"))
    assert one.own_decks[0].name == "Burn" and one.wire_decks[0].catalog_id == "Burn"


def _canned_engine(tmp_path: Path, hello: dict) -> list[str]:
    script = tmp_path / "canned_engine.py"
    script.write_text(
        "import json, sys\n"
        f"HELLO = {json.dumps(hello)!r}\n"
        "for line in sys.stdin.buffer:\n"
        "    request = json.loads(line)\n"
        "    answer = json.loads(HELLO)\n"
        "    answer['request_id'] = request['request_id']\n"
        "    sys.stdout.write(json.dumps(answer) + '\\n')\n"
        "    sys.stdout.flush()\n",
        encoding="utf-8",
    )
    return [sys.executable, str(script)]


def test_an_nfd_catalog_stops_preflight_naming_the_card_and_deck(tmp_path: Path) -> None:
    hello = copy.deepcopy(HELLO_OK)
    hello["catalog"] = [{"catalog_id": "Vault", "name": "Vault", "decklist": [{"name": "Lim-Du\u0302l's Vault", "count": 4}]}]
    cfg = config(engine={"command": _canned_engine(tmp_path, hello)}, deck_pool=[{"catalog_id": "Vault"}])
    with pytest.raises(TournamentError, match=r"Vault.*Lim-Du\u0302l's Vault.*NFC"):
        preflight(cfg, SECRET)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"deck_pool": [{"catalog_id": "Burn"}, {"catalog_id": "Refuse"}]}, "unsupported_deck"),
        ({"deck_pool": [{"catalog_id": "Burn"}, {"catalog_id": "Nope"}]}, "catalog"),
        ({"format": "modern"}, "format"),
        ({"rules": {"mulligan": "london"}}, "mulligan"),
        ({"extensions": ["x_kernel_v5"]}, "x_kernel_v5"),
    ],
)
def test_config_errors_stop_before_any_game(changes: dict, message: str) -> None:
    with pytest.raises(TournamentError, match=message):
        preflight(config(**changes), SECRET)


def test_a_bot_whose_requirements_are_unmet_is_refused(tmp_path: Path) -> None:
    bot = tmp_path / "needs_poison.py"
    bot.write_text("import sys\nfrom spellbench.bot import serve\n"
                   "sys.exit(serve(choose=lambda d: 0, name='needy', version='1', requires_observation=('poison',)))\n", encoding="utf-8")
    bots = [{"name": "uniform", "version": "2.0.0", "type": "builtin"},
            {"name": "needy", "version": "1", "type": "subprocess", "command": [sys.executable, str(bot)]}]
    with pytest.raises(TournamentError, match="needy.*poison"):
        preflight(config(bots=bots), SECRET)


def test_a_bot_needing_an_extension_the_run_does_not_enable_is_refused(tmp_path: Path) -> None:
    bot = tmp_path / "needs_kernel.py"
    bot.write_text("import sys\nfrom spellbench.bot import serve\n"
                   "sys.exit(serve(choose=lambda d: 0, name='needy', version='1', requires_extensions=('x_kernel_v5',)))\n",
                   encoding="utf-8")
    bots = [{"name": "uniform", "version": "2.0.0", "type": "builtin"},
            {"name": "needy", "version": "1", "type": "subprocess", "command": [sys.executable, str(bot)]}]
    with pytest.raises(TournamentError, match="needy.*x_kernel_v5"):                # requires.extensions (R2-25)
        preflight(config(bots=bots), SECRET)
