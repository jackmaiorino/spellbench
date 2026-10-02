"""Preflight, schedule and per-game setup (spec 11.1, 11.6, 12)."""

from __future__ import annotations

import copy
import dataclasses
import json
import sys
import time
from itertools import combinations_with_replacement
from pathlib import Path

import pytest

from spellbench.agent_messages import OwnDeck
from spellbench.arena.config import DEFAULT_TIME_CONTROL, DeckSpec, TournamentConfig, TournamentError
from spellbench.arena.ledger import LedgerDeck
from spellbench.arena.schedule import EnginePin, ResolvedDeck, game_setup, preflight, schedule
from spellbench.digests import card_name_domain, deck_id
from spellbench.host.agent_process import AgentProcess
from spellbench.host.engine_process import EngineProcess
from spellbench.host.setup import GameSetup
from spellbench.messages import CardNameDomain, DeckRow, EngineIdentity, Limits, Resources, Rules, TimeControl, WireDeck
from spellbench.run_secret import RunSecret

from test_messages import HELLO_OK

TESTS = Path(__file__).resolve().parent
ENGINE = TESTS / "fake_v2_engine.py"
SECRET = RunSecret(bytes(range(32)))
UNIFORM = {"name": "uniform", "version": "2.0.0", "type": "builtin"}
# The list of every fake engine catalog deck, and of HELLO_OK's Burn.
BURN_ROWS = (DeckRow("Lightning Bolt", 4), DeckRow("Mountain", 18))
BURN_ID = deck_id([row.to_json() for row in BURN_ROWS])
DOMAIN = CardNameDomain.from_json(card_name_domain(["Lightning Bolt", "Mountain"]))
AUDIT = "benchmarks/pauper/audits/x_kernel_v5.md"
# Blocks unlike the defaults, so a game setup cannot take the defaults in place of the config's values.
TIME_CONTROL = {"startup_ms": 250000, "game_start_ms": 50000, "bank_ms": 500000, "increment_ms": 1000,
                "max_decision_ms": 40000, "engine_step_ms": 100000}
LIMITS = {"max_decisions": 9000, "max_steps": 90000, "max_seat_decisions_per_turn": 400,
          "max_seat_decisions_per_game": 4000, "max_seat_steps_per_game": 40000}
RESOURCES = {"cpus": 2, "memory_mb": 2048, "gpu": True, "engine_cpus": 2}


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


def _silent(tmp_path: Path) -> list[str]:
    """A process that reads its requests and never answers; it exits when its stdin closes, or after 5 s."""
    script = tmp_path / "silent.py"
    script.write_text(
        "import os, sys, threading, time\n"
        "def drain():\n"
        "    for _ in sys.stdin.buffer:\n"
        "        pass\n"
        "    os._exit(0)\n"
        "threading.Thread(target=drain, daemon=True).start()\n"
        "time.sleep(5)\n",
        encoding="utf-8",
    )
    return [sys.executable, str(script)]


def _bot(tmp_path: Path, name: str, *, before: str = "", **serve_args: object) -> dict:
    """A subprocess bot entry, ``name`` version 1, whose script runs ``before`` and then serves."""
    script = tmp_path / f"bot_{name}.py"
    arguments = "".join(f", {key}={value!r}" for key, value in serve_args.items())
    script.write_text(f"import sys\n{before}from spellbench.bot import serve\n"
                      f"sys.exit(serve(choose=lambda d: 0, name={name!r}, version='1'{arguments}))\n", encoding="utf-8")
    return {"name": name, "version": "1", "type": "subprocess", "command": [sys.executable, str(script)]}


def _record_resets(monkeypatch: pytest.MonkeyPatch, *, forward: bool = True) -> list:
    """Every reset request preflight sends, in order; unless ``forward``, the engine never gets one.

    A canned engine answers every request with its hello_ok, so it cannot play a reset.
    """
    requests = []
    real_reset = EngineProcess.reset

    def recording(self, request):
        requests.append(request)
        return real_reset(self, request) if forward else None

    monkeypatch.setattr(EngineProcess, "reset", recording)
    return requests


def _record_closes(monkeypatch: pytest.MonkeyPatch) -> list:
    """Every ``EngineProcess`` and ``AgentProcess`` that preflight closes, in order."""
    closed = []
    for kind in (EngineProcess, AgentProcess):
        def recording(self, _real=kind.close):
            closed.append(self)
            _real(self)

        monkeypatch.setattr(kind, "close", recording)
    return closed


def _startup_ms(value: int) -> dict:
    """The default time control with ``startup_ms`` set to ``value``."""
    return {**DEFAULT_TIME_CONTROL.to_json(), "startup_ms": value}


def _expected_setup(rules: Rules, index: int, decks: tuple[str, str]) -> GameSetup:
    """Game ``index`` of a config holding the blocks above, with catalog ``decks`` (p0, p1), built by hand."""
    return GameSetup(
        game_index=index,
        game_id=SECRET.game_id(index),
        game_secret_hex=SECRET.game_secret(index).hex(),
        format="pauper-bo1",
        wire_decks=(WireDeck(BURN_ID, catalog_id=decks[0]), WireDeck(BURN_ID, catalog_id=decks[1])),
        own_decks=(OwnDeck(BURN_ID, decks[0], BURN_ROWS), OwnDeck(BURN_ID, decks[1], BURN_ROWS)),
        rules=rules,
        time_control=TimeControl(**TIME_CONTROL),
        limits=Limits(**LIMITS),
        resources=Resources(**RESOURCES),
        agent_seeds=(SECRET.agent_seed(index, "p0"), SECRET.agent_seed(index, "p1")),
    )


def test_preflight_resolves_decks_rules_and_the_domain() -> None:
    cfg = config()
    setup = preflight(cfg, SECRET)
    assert list(setup.decks) == list(cfg.deck_pool)
    assert list(setup.decks.values()) == [ResolvedDeck(BURN_ID, name, name, BURN_ROWS) for name in ("Burn", "Elves")]
    assert setup.rules == Rules("visible", "none", "host_assigned", "p0", DOMAIN, (), False)
    assert setup.native_id_extensions == ()
    assert setup.engine == EngineIdentity("fake-v2-engine", "0.2.0", None, "fake-v2-rules", "fake-v2-cards")
    assert setup.profile == setup.hello.profile
    london = config(engine_args=("--london", "--toss"), deck_pool=[{"catalog_id": "Scenario:pregame"}])
    assert preflight(london, SECRET).rules.mulligan == "london"


def test_preflight_keeps_the_configured_information_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    resets = _record_resets(monkeypatch)
    setup = preflight(config(rules={"opponent_decklist": "hidden", "mulligan": "none", "starting_seat": "p1"}), SECRET)
    assert setup.rules == Rules("hidden", "none", "host_assigned", "p1", DOMAIN, (), False)
    assert [request.rules for request in resets] == [setup.rules] * 2


def test_a_declared_but_unplayable_rule_stops_preflight_before_any_game() -> None:
    with pytest.raises(TournamentError) as caught:
        preflight(config(engine_args=("--london",)), SECRET)     # declares london, but these decks cannot play it
    message = str(caught.value)
    # Names the engine and the decks.
    assert message.startswith(
        "preflight: engine 'fake-v2-engine' '0.2.0' could not start a game with decks ['Burn', 'Burn']: "
    )
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
    expected = []
    for matchup, (i, j) in enumerate(combinations_with_replacement(range(len(bots)), 2)):
        for pair in range(3):
            deck = cfg.deck_pool[pair]      # pair p plays deck p in both seats, in every matchup
            expected.append((matchup, pair, 0, names[i], names[j], deck, deck))
            expected.append((matchup, pair, 1, names[j], names[i], deck, deck))
    actual = [(game.matchup_index, game.pair_index, game.pair_slot, game.seat_specs[0][1].name,
               game.seat_specs[1][1].name, *game.decks) for game in games]
    assert actual == expected
    assert {tuple(seat for seat, _ in game.seat_specs) for game in games} == {("p0", "p1")}


def test_decks_stay_in_seat_position_while_the_bots_swap() -> None:
    cfg = fixed_decks(time_control=TIME_CONTROL, limits=LIMITS, resources=RESOURCES)
    setup = preflight(cfg, SECRET)
    games = schedule(cfg, SECRET)
    assert [game.seat_specs[0][1].name for game in games] == ["uniform", "first", "uniform", "first"]
    assert [game_setup(cfg, setup, game, SECRET) for game in games] == [
        _expected_setup(setup.rules, index, ("Burn", "Elves")) for index in range(4)
    ]


def test_game_setup_derives_every_field_from_the_config_the_rules_and_the_run_secret() -> None:
    cfg = config(time_control=TIME_CONTROL, limits=LIMITS, resources=RESOURCES)
    setup = preflight(cfg, SECRET)
    decks = [("Burn", "Burn"), ("Burn", "Burn"), ("Elves", "Elves"), ("Elves", "Elves")]
    assert [game_setup(cfg, setup, game, SECRET) for game in schedule(cfg, SECRET)] == [
        _expected_setup(setup.rules, index, pair) for index, pair in enumerate(decks)
    ]


def test_preflight_resets_use_host_internal_secrets_and_the_games_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    requests = _record_resets(monkeypatch)
    cfg = config()
    setup = preflight(cfg, SECRET)
    games = schedule(cfg, SECRET)
    assert [request.game_id for request in requests] == [SECRET.preflight_game_id(k) for k in range(2)]
    assert [request.game_secret for request in requests] == [SECRET.preflight_secret(k).hex() for k in range(2)]
    assert not {request.game_id for request in requests} & {game.game_id for game in games}
    scheduled_secrets = {SECRET.game_secret(game.game_index).hex() for game in games}
    assert not {request.game_secret for request in requests} & scheduled_secrets
    assert [request.rules for request in requests] == [setup.rules] * 2


def test_each_preflight_reset_is_bounded_by_engine_step_ms(monkeypatch: pytest.MonkeyPatch) -> None:
    events = []
    real_set, real_reset = EngineProcess.set_timeout, EngineProcess.reset

    def set_timeout(self, seconds):
        events.append(("set_timeout", seconds))
        return real_set(self, seconds)

    def reset(self, request):
        events.append(("reset", request.game_id))
        return real_reset(self, request)

    monkeypatch.setattr(EngineProcess, "set_timeout", set_timeout)
    monkeypatch.setattr(EngineProcess, "reset", reset)
    cfg = config()      # the spec 11.4 example values: startup_ms 300000, engine_step_ms 120000
    preflight(cfg, SECRET)
    assert cfg.time_control.startup_ms != cfg.time_control.engine_step_ms
    bound = ("set_timeout", cfg.time_control.engine_step_ms / 1000)     # before each reset: one per deck pairing
    assert events == [bound, ("reset", SECRET.preflight_game_id(0)), bound, ("reset", SECRET.preflight_game_id(1))]


def test_a_silent_engine_fails_preflight_within_startup_ms(tmp_path: Path) -> None:
    cfg = config(engine={"command": _silent(tmp_path)}, time_control=_startup_ms(200))
    started = time.monotonic()
    with pytest.raises(TournamentError, match="^preflight: engine hello failed: timeout waiting for peer stdout"):
        preflight(cfg, SECRET)
    assert time.monotonic() - started < 4       # unbounded, hello would wait for the engine to give up after 5 s


def test_a_silent_bot_fails_preflight_within_startup_ms(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _record_resets(monkeypatch, forward=False)
    silent = {"name": "silent", "version": "1", "type": "subprocess", "command": _silent(tmp_path)}
    engine = {"command": _canned_engine(tmp_path, copy.deepcopy(HELLO_OK))}    # answers hello well within startup_ms
    cfg = config(engine=engine, deck_pool=[{"catalog_id": "Burn"}], bots=[UNIFORM, silent], time_control=_startup_ms(500))
    started = time.monotonic()
    with pytest.raises(TournamentError) as caught:
        preflight(cfg, SECRET)
    assert str(caught.value) == "preflight: bot 'silent': timeout: no answer to hello within 500 ms"
    assert time.monotonic() - started < 4       # unbounded, hello would wait for the bot to give up after 5 s


def test_preflight_closes_every_engine_and_bot_it_starts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    closed = _record_closes(monkeypatch)
    preflight(config(bots=[_bot(tmp_path, "one"), _bot(tmp_path, "two")]), SECRET)
    # An engine process per deck pairing (Burn, Elves), then each subprocess bot.
    assert [type(process) for process in closed] == [EngineProcess, EngineProcess, AgentProcess, AgentProcess]
    assert len({id(process) for process in closed}) == 4


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


def test_enabled_extensions_reach_the_rules_every_reset_and_the_audit_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resets = _record_resets(monkeypatch, forward=False)
    hello = copy.deepcopy(HELLO_OK)                     # declares x_kernel_v5 with native_ids: true
    hello["extensions"].append({"name": "x_trace_v1", "native_ids": False})
    cfg = config(engine={"command": _canned_engine(tmp_path, hello)}, deck_pool=[{"catalog_id": "Burn"}],
                 extensions=["x_kernel_v5", "x_trace_v1"], native_id_audits={"x_kernel_v5": AUDIT})
    setup = preflight(cfg, SECRET)
    assert setup.rules.extensions == ("x_kernel_v5", "x_trace_v1")
    # Only the native_ids: true extension, with its audit (spec 12.2, 14).
    assert setup.native_id_extensions == ({"name": "x_kernel_v5", "audit": AUDIT},)
    assert [request.rules for request in resets] == [setup.rules]


def test_auto_mulligan_takes_london_wherever_the_engine_lists_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _record_resets(monkeypatch, forward=False)
    hello = copy.deepcopy(HELLO_OK)
    hello["rules_supported"]["mulligan"] = ["none", "london"]      # london listed, though not first (spec 12.2)
    cfg = config(engine={"command": _canned_engine(tmp_path, hello)}, deck_pool=[{"catalog_id": "Burn"}])
    assert preflight(cfg, SECRET).rules.mulligan == "london"


def test_a_catalog_deck_keeps_its_published_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _record_resets(monkeypatch, forward=False)
    hello = copy.deepcopy(HELLO_OK)
    hello["catalog"][0]["name"] = "Mono-Red Burn"                  # published under the catalog id Burn
    cfg = config(engine={"command": _canned_engine(tmp_path, hello)}, deck_pool=[{"catalog_id": "Burn"}])
    deck = preflight(cfg, SECRET).decks[cfg.deck_pool[0]]
    assert deck == ResolvedDeck(BURN_ID, "Mono-Red Burn", "Burn", BURN_ROWS)
    assert deck.wire() == WireDeck(BURN_ID, catalog_id="Burn")
    assert deck.own() == OwnDeck(BURN_ID, "Mono-Red Burn", BURN_ROWS)
    assert deck.ledger() == LedgerDeck(BURN_ID, "Mono-Red Burn", "Burn")


def test_an_engine_that_cannot_start_a_game_is_named_escaped(tmp_path: Path) -> None:
    hello = copy.deepcopy(HELLO_OK)
    hello["engine"] = {**hello["engine"], "name": "kernel\x1b[31m\r\n", "version": "0.0.5\x07"}
    cfg = config(engine={"command": _canned_engine(tmp_path, hello)}, deck_pool=[{"catalog_id": "Burn"}])
    with pytest.raises(TournamentError) as caught:
        preflight(cfg, SECRET)          # the canned engine answers reset with its hello_ok
    assert str(caught.value) == (
        "preflight: engine 'kernel\\x1b[31m\\r\\n' '0.0.5\\x07' could not start a game with decks ['Burn', 'Burn']: "
        "hello_ok response to a non-hello request"
    )


def test_inline_decklists_resolve_ids_and_the_domain_over_every_deck() -> None:
    mountains = [{"name": "Mountain", "count": 22}]
    relics = [{"name": "Mountain", "count": 18}, {"name": "Relic of Progenitus", "count": 4}]
    pool = [{"name": "Mountains", "decklist": mountains}, {"name": "Relics", "decklist": relics}]
    cfg = config(engine_args=("--decklists",), deck_pool=pool)
    setup = preflight(cfg, SECRET)
    assert setup.decks[cfg.deck_pool[0]].deck_id == deck_id(mountains)
    assert setup.decks[cfg.deck_pool[1]].deck_id == deck_id(relics)
    assert setup.rules.card_name_domain.names == ("Mountain", "Relic of Progenitus")


def test_an_inline_deck_built_in_code_is_checked_and_sorted() -> None:
    pile = [{"name": "Pile", "decklist": [{"name": "Mountain", "count": 22}]}]
    base = config(engine_args=("--decklists",), deck_pool=pile)
    # Built directly, not by DeckSpec.from_json, so nothing sorted or checked the rows yet.
    relics = DeckSpec(name="Relics", decklist=(DeckRow("Relic of Progenitus", 4), DeckRow("Mountain", 18)))
    setup = preflight(dataclasses.replace(base, deck_pool=(relics,)), SECRET)
    rows = (DeckRow("Mountain", 18), DeckRow("Relic of Progenitus", 4))
    relics_id = deck_id([row.to_json() for row in rows])
    assert setup.decks[relics] == ResolvedDeck(relics_id, "Relics", None, rows)
    assert setup.decks[relics].wire() == WireDeck(relics_id, decklist=rows)
    twice = DeckSpec(name="Twice", decklist=(DeckRow("Mountain", 10), DeckRow("Mountain", 12)))
    with pytest.raises(TournamentError) as caught:
        preflight(dataclasses.replace(base, deck_pool=(twice,)), SECRET)
    assert str(caught.value) == "preflight: deck 'Twice': decklist[1].name: card name 'Mountain' appears twice"


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


def test_a_missing_engine_or_bot_executable_stops_preflight(tmp_path: Path) -> None:
    missing = str(tmp_path / "missing")
    with pytest.raises(TournamentError, match="^preflight: the engine could not start: "):
        preflight(config(engine={"command": [missing]}), SECRET)
    ghost = {"name": "ghost", "version": "1", "type": "subprocess", "command": [missing]}
    with pytest.raises(TournamentError, match="^preflight: bot 'ghost': could not start: "):
        preflight(config(bots=[UNIFORM, ghost]), SECRET)


def test_a_bot_needing_an_observation_flag_passes_only_where_the_engine_declares_it(tmp_path: Path) -> None:
    bots = [UNIFORM, _bot(tmp_path, "needy", requires_observation=("poison",))]
    preflight(config(engine_args=("--flags", "poison"), bots=bots), SECRET)
    with pytest.raises(TournamentError) as caught:
        preflight(config(bots=bots), SECRET)                        # the engine declares poison: false
    assert str(caught.value) == (
        "preflight: bot 'needy': requires the observation flag 'poison', which the engine does not declare"
    )


def test_a_bot_needing_an_extension_passes_only_when_the_run_enables_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _record_resets(monkeypatch, forward=False)
    engine = {"command": _canned_engine(tmp_path, copy.deepcopy(HELLO_OK))}     # declares x_kernel_v5
    bots = [UNIFORM, _bot(tmp_path, "needy", requires_extensions=("x_kernel_v5",))]
    preflight(config(engine=engine, deck_pool=[{"catalog_id": "Burn"}], bots=bots,
                     extensions=["x_kernel_v5"], native_id_audits={"x_kernel_v5": AUDIT}), SECRET)
    with pytest.raises(TournamentError) as caught:                 # the run's extensions, not the engine's (R2-25)
        preflight(config(engine=engine, deck_pool=[{"catalog_id": "Burn"}], bots=bots), SECRET)
    assert str(caught.value) == (
        "preflight: bot 'needy': requires the extension 'x_kernel_v5', which this run does not enable"
    )


def test_a_bot_answering_as_another_entry_is_refused(tmp_path: Path) -> None:
    real = {**_bot(tmp_path, "impostor"), "name": "real"}          # the entry real, whose bot says impostor 1
    with pytest.raises(TournamentError) as caught:
        preflight(config(bots=[UNIFORM, real]), SECRET)
    assert str(caught.value) == "preflight: bot 'real': answered hello as 'impostor' '1'"


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
    bots = [UNIFORM, _bot(tmp_path, "needy", requires_observation=(hostile,))]
    with pytest.raises(TournamentError) as caught:
        preflight(config(bots=bots), SECRET)
    message = str(caught.value)
    assert message == (
        f"preflight: bot 'needy': requires the observation flag {hostile!r}, which the engine does not declare"
    )
    assert "\x1b" not in message and "\r" not in message and "\n" not in message


def test_a_bot_logging_before_its_hello_is_refused_without_its_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    closed = _record_closes(monkeypatch)
    # A bot that logs on stdout answers hello with its log line; its stderr holds a second marker.
    chatty = _bot(tmp_path, "chatty", before=(
        "import time\n"
        "sys.stderr.write('STDERR-MARKER Traceback\\n')\n"
        "sys.stderr.flush()\n"
        "time.sleep(0.2)        # time for the host's stderr reader to keep the marker\n"
        "print('Loading model weights... STDOUT-MARKER', flush=True)\n"
    ))
    with pytest.raises(TournamentError) as caught:
        preflight(config(bots=[UNIFORM, chatty]), SECRET)
    message = str(caught.value)
    # The SeatFailure's cause and detail only, never its diagnostic, which holds the bot's stderr (R3-32).
    assert message == (
        "preflight: bot 'chatty': malformed_response: the answer to hello was not a valid protocol message"
    )
    assert "MARKER" not in message
    # The failed bot is closed too.
    assert [type(process) for process in closed] == [EngineProcess, EngineProcess, AgentProcess]
