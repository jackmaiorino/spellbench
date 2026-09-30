"""Preflight, schedule and per-game setup (spec 11.1, 11.6, 12)."""

from __future__ import annotations

import copy
import json
import sys
from itertools import combinations_with_replacement
from pathlib import Path

import pytest

from spellbench.arena.config import TournamentConfig, TournamentError
from spellbench.arena.schedule import EnginePin, game_setup, preflight, schedule
from spellbench.digests import deck_id
from spellbench.host.engine_process import EngineProcess
from spellbench.messages import EngineIdentity
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


def fixed_decks(**changes) -> TournamentConfig:
    value = config(**changes).to_json()
    value["decks"] = [{"catalog_id": "Burn"}, {"catalog_id": "Elves"}]
    del value["deck_pool"]
    return TournamentConfig.from_json(value)


def test_preflight_resolves_decks_rules_and_the_domain() -> None:
    setup = preflight(config(), SECRET)
    burn = setup.decks[config().deck_pool[0]]
    assert burn.deck_id == deck_id([{"name": "Lightning Bolt", "count": 4}, {"name": "Mountain", "count": 18}])
    assert setup.rules.mulligan == "none" and setup.rules.starting_seat == "p0"
    assert setup.rules.card_name_domain.names == ("Lightning Bolt", "Mountain")
    london = config(engine_args=("--london", "--toss"), deck_pool=[{"catalog_id": "Scenario:pregame"}])
    assert preflight(london, SECRET).rules.mulligan == "london"


def test_a_declared_but_unplayable_rule_stops_preflight_before_any_game() -> None:
    with pytest.raises(TournamentError) as caught:
        preflight(config(engine_args=("--london",)), SECRET)     # declares london, but these decks cannot play it
    message = str(caught.value)
    assert "fake-v2-engine" in message and "Burn" in message     # names the engine and the decks
    assert "unsupported_rule" in message and "mulligan" in message
    toss = {"rules": {"starting_player": "toss_winner_chooses", "starting_seat": None}}
    with pytest.raises(TournamentError, match="starting_player"):
        preflight(config(engine_args=("--toss",), **toss), SECRET)


def test_the_schedule_uses_opaque_ids_and_swaps_seats() -> None:
    games = schedule(config(), SECRET)
    assert [game.game_id for game in games] == [SECRET.game_id(index) for index in range(4)]
    assert [(game.pair_index, game.pair_slot) for game in games] == [(0, 0), (0, 1), (1, 0), (1, 1)]
    assert games[0].seat_specs[0][1].name == games[1].seat_specs[1][1].name == "uniform"
    assert [game.decks[0].catalog_id for game in games] == ["Burn", "Burn", "Elves", "Elves"]


def test_the_schedule_counts_games_across_matchups_with_distinct_secrets() -> None:
    bots = [{"name": name, "version": "2.0.0", "type": "builtin"} for name in ("uniform", "first", "heuristic")]
    pool = [{"catalog_id": name} for name in ("Burn", "Elves", "Faeries")]
    cfg = config(bots=bots, deck_pool=pool, pairs_per_matchup=3, include_self_play=True)
    games = schedule(cfg, SECRET)
    assert len(games) == 6 * 3 * 2
    assert [game.game_index for game in games] == list(range(len(games)))
    assert [game.game_id for game in games] == [SECRET.game_id(index) for index in range(len(games))]
    assert len({game.game_id for game in games}) == len(games)
    assert len({SECRET.game_secret(game.game_index) for game in games}) == len(games)
    names = [spec.name for spec in cfg.bots]
    matchups = [(names[i], names[j]) for i, j in combinations_with_replacement(range(len(bots)), 2)]
    assert [(game.seat_specs[0][1].name, game.seat_specs[1][1].name) for game in games[::6]] == matchups
    assert [game.decks[0].catalog_id for game in games[:6]] == ["Burn", "Burn", "Elves", "Elves", "Faeries", "Faeries"]


def test_decks_stay_in_seat_position_while_the_bots_swap() -> None:
    cfg = fixed_decks()
    setup = preflight(cfg, SECRET)
    games = schedule(cfg, SECRET)
    assert games[0].seat_specs[0][1].name == "uniform" and games[1].seat_specs[0][1].name == "first"
    for game in games:
        one = game_setup(cfg, setup, game, SECRET)
        assert [deck.catalog_id for deck in one.wire_decks] == ["Burn", "Elves"]
        assert [deck.name for deck in one.own_decks] == ["Burn", "Elves"]


def test_game_setup_derives_everything_from_the_run_secret() -> None:
    cfg = config()
    setup = preflight(cfg, SECRET)
    one = game_setup(cfg, setup, schedule(cfg, SECRET)[1], SECRET)
    assert one.game_secret_hex == SECRET.game_secret(1).hex()
    assert one.agent_seeds == (SECRET.agent_seed(1, "p0"), SECRET.agent_seed(1, "p1"))
    assert one.own_decks[0].name == "Burn" and one.wire_decks[0].catalog_id == "Burn"


def test_preflight_resets_use_host_internal_secrets_and_the_games_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    requests = []
    real_reset = EngineProcess.reset

    def recording(self, request):
        requests.append(request)
        return real_reset(self, request)

    monkeypatch.setattr(EngineProcess, "reset", recording)
    cfg = config()
    setup = preflight(cfg, SECRET)
    games = schedule(cfg, SECRET)
    assert [request.game_id for request in requests] == [SECRET.preflight_game_id(k) for k in range(2)]
    assert [request.game_secret for request in requests] == [SECRET.preflight_secret(k).hex() for k in range(2)]
    assert not {request.game_id for request in requests} & {game.game_id for game in games}
    scheduled_secrets = {SECRET.game_secret(game.game_index).hex() for game in games}
    assert not {request.game_secret for request in requests} & scheduled_secrets
    assert [request.rules for request in requests] == [setup.rules] * 2


def test_the_preflight_reset_is_bounded_by_engine_step_ms(monkeypatch: pytest.MonkeyPatch) -> None:
    timeouts = []
    real_set = EngineProcess.set_timeout

    def recording(self, seconds):
        timeouts.append(seconds)
        return real_set(self, seconds)

    monkeypatch.setattr(EngineProcess, "set_timeout", recording)
    cfg = config()      # the spec 11.4 example values: startup_ms 300000, engine_step_ms 120000
    preflight(cfg, SECRET)
    assert cfg.time_control.startup_ms != cfg.time_control.engine_step_ms
    assert timeouts == [cfg.time_control.engine_step_ms / 1000] * 2     # one reset per deck pairing


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
        ({"deck_pool": [{"catalog_id": "Burn"}, {"catalog_id": "Nope"}]}, "not in the engine's hello_ok.catalog"),
        ({"format": "modern"}, "does not support format"),
        ({"rules": {"mulligan": "london"}}, "is not in the engine's rules_supported.mulligan"),
        ({"rules": {"starting_player": "toss_winner_chooses", "starting_seat": None}},
         "is not in the engine's rules_supported.starting_player"),
        ({"extensions": ["x_kernel_v5"]}, "not declared in the engine's hello_ok.extensions"),
        ({"deck_pool": [{"name": "Pile", "decklist": [{"name": "Mountain", "count": 22}]}]},
         "declares no decklist deck source"),
    ],
)
def test_config_errors_stop_before_any_game(changes: dict, message: str) -> None:
    with pytest.raises(TournamentError, match=message):
        preflight(config(**changes), SECRET)


def test_a_catalog_deck_without_the_catalog_source_is_refused(tmp_path: Path) -> None:
    hello = copy.deepcopy(HELLO_OK)
    hello["deck_sources"] = ["decklist"]
    hello["catalog"] = []
    cfg = config(engine={"command": _canned_engine(tmp_path, hello)})
    with pytest.raises(TournamentError, match="declares no catalog deck source"):
        preflight(cfg, SECRET)


def test_a_native_ids_extension_without_an_audit_is_refused(tmp_path: Path) -> None:
    cfg = config(engine={"command": _canned_engine(tmp_path, copy.deepcopy(HELLO_OK))},
                 deck_pool=[{"catalog_id": "Burn"}], extensions=["x_kernel_v5"])
    with pytest.raises(TournamentError, match=r"x_kernel_v5.*audit"):
        preflight(cfg, SECRET)


def test_inline_decklists_resolve_ids_and_the_domain_over_every_deck() -> None:
    mountains = [{"name": "Mountain", "count": 22}]
    relics = [{"name": "Mountain", "count": 18}, {"name": "Relic of Progenitus", "count": 4}]
    pool = [{"name": "Mountains", "decklist": mountains}, {"name": "Relics", "decklist": relics}]
    cfg = config(engine_args=("--decklists",), deck_pool=pool)
    setup = preflight(cfg, SECRET)
    assert setup.decks[cfg.deck_pool[0]].deck_id == deck_id(mountains)
    assert setup.decks[cfg.deck_pool[1]].deck_id == deck_id(relics)
    assert setup.rules.card_name_domain.names == ("Mountain", "Relic of Progenitus")


def test_a_second_engine_process_with_a_different_identity_is_refused(tmp_path: Path) -> None:
    counter = tmp_path / "count"
    script = tmp_path / "drifting_engine.py"
    script.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(TESTS)!r})\n"
        "from pathlib import Path\n"
        "from fake_v2_engine import serve\n"
        f"counter = Path({str(counter)!r})\n"
        "n = int(counter.read_text()) if counter.exists() else 0\n"
        "counter.write_text(str(n + 1))\n"
        "sys.exit(serve(['--name', 'drifter-' + str(n)]))\n",
        encoding="utf-8",
    )
    with pytest.raises(TournamentError, match="drifted"):
        preflight(config(engine={"command": [sys.executable, str(script)]}), SECRET)


def test_the_engine_pin_refuses_drift_and_an_empty_pin() -> None:
    pin = EnginePin()
    with pytest.raises(TournamentError, match="no engine identity"):
        _ = pin.identity
    identity = EngineIdentity("a", "1", None, "r", "c")
    pin.check(identity)
    pin.check(identity)
    assert pin.identity is identity
    with pytest.raises(TournamentError, match="drifted"):
        pin.check(EngineIdentity("b", "1", None, "r", "c"))


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


def test_a_bot_answering_as_another_entry_is_refused(tmp_path: Path) -> None:
    bot = tmp_path / "impostor.py"
    bot.write_text("import sys\nfrom spellbench.bot import serve\n"
                   "sys.exit(serve(choose=lambda d: 0, name='impostor', version='1'))\n", encoding="utf-8")
    bots = [{"name": "uniform", "version": "2.0.0", "type": "builtin"},
            {"name": "real", "version": "1", "type": "subprocess", "command": [sys.executable, str(bot)]}]
    with pytest.raises(TournamentError, match=r"real.*'impostor'"):
        preflight(config(bots=bots), SECRET)


def test_a_bot_never_sees_spellbench_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPELLBENCH_SECRETS_DIR", str(tmp_path / "secrets"))         # where a committed run keeps its secret
    monkeypatch.setenv("SPELLBENCH_PIN_ROOT", str(tmp_path / "pins"))               # and the other local values (R3-9)
    monkeypatch.setenv("SPELLBENCH_ARTIFACT_REGISTER", str(tmp_path / "register.jsonl"))
    bot = tmp_path / "env_bot.py"
    bot.write_text("import os, sys\nfrom spellbench.bot import serve\n"
                   "name = 'leaky' if any(key.startswith('SPELLBENCH_') for key in os.environ) else 'clean'\n"
                   "sys.exit(serve(choose=lambda d: 0, name=name, version='1'))\n", encoding="utf-8")
    bots = [{"name": "uniform", "version": "2.0.0", "type": "builtin"},
            {"name": "clean", "version": "1", "type": "subprocess", "command": [sys.executable, str(bot)]}]
    preflight(config(bots=bots), SECRET)        # a bot that saw SPELLBENCH_* would name itself "leaky" and be refused


def test_a_hostile_bot_string_is_escaped_in_the_refusal(tmp_path: Path) -> None:
    hostile = "poison\x1b[31m\r\n"
    bot = tmp_path / "hostile.py"
    bot.write_text(f"import sys\nfrom spellbench.bot import serve\n"
                   f"sys.exit(serve(choose=lambda d: 0, name='needy', version='1', requires_observation=({hostile!r},)))\n",
                   encoding="utf-8")
    bots = [{"name": "uniform", "version": "2.0.0", "type": "builtin"},
            {"name": "needy", "version": "1", "type": "subprocess", "command": [sys.executable, str(bot)]}]
    with pytest.raises(TournamentError) as caught:
        preflight(config(bots=bots), SECRET)
    message = str(caught.value)
    assert "needy" in message and repr(hostile) in message
    assert "\x1b" not in message and "\r" not in message and "\n" not in message
