"""Best-of-three match mode (``spellbench.human.match``): bank carry, flags, draws, schedule and output files."""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

import pytest

from spellbench.arena.config import TournamentConfig, TournamentError
from spellbench.human import match, relay
from spellbench.human.match import GamePlan, GameReport
from spellbench.human.server import Hub, make_server
from spellbench.run_secret import RunSecret

from arena_helpers import TEST_RUN_SECRET, builtin, make_config, roomy_machine, subprocess_bot

PLAYERS = ("search", "b512")
BANK = 1_500_000


def row(plan: GamePlan, *, winner: str | None, reason: str = "score", classification: str = "natural",
        loser: str | None = None) -> dict:
    """A ledger-like row: ``winner`` is a seat or None; a forfeit names its loser seat."""
    adjudication = None
    if classification == "forfeit":
        adjudication = {"kind": "forfeit", "cause": reason.split(":", 1)[1], "loser_seat": loser, "detail": "test"}
    outcome = f"{winner}_win" if winner else ("halted" if classification == "halted" else "draw")
    return {"game_id": f"g-{plan.game_index}", "outcome": outcome, "classification": classification,
            "reason": reason, "winner": winner, "adjudication": adjudication, "step_count": 10, "decision_count": 8}


class Script:
    """A fake game runner: each game spends the scripted milliseconds per player and ends as scripted.

    ``games`` is a list of ``(spend, ending)`` where ``spend`` maps player names to ms and ``ending`` is a player
    name (that player wins), ``"draw"``, ``"halt"``, ``("flag", name)`` or ``("start_timeout", name)``.
    """

    def __init__(self, games: list) -> None:
        self.games, self.plans = list(games), []

    def __call__(self, plan: GamePlan) -> GameReport:
        self.plans.append(plan)
        spend, ending = self.games.pop(0)
        seat_of = {name: seat for seat, name in zip(("p0", "p1"), plan.seats)}
        other = {"p0": "p1", "p1": "p0"}
        remaining = {seat: max(0, start - spend.get(name, 0))
                     for seat, name, start in zip(("p0", "p1"), plan.seats, plan.starting_bank_ms)}
        if ending == "draw":
            return GameReport(row(plan, winner=None), remaining)
        if ending == "halt":
            return GameReport(row(plan, winner=None, reason="host_engine_fault:timeout", classification="halted"),
                              remaining)
        if isinstance(ending, tuple):
            kind, name = ending
            loser = seat_of[name]
            if kind == "flag":
                remaining[loser] = 0
            else:
                remaining[loser] = plan.starting_bank_ms[0 if loser == "p0" else 1]
            return GameReport(row(plan, winner=other[loser], reason="forfeit:timeout", classification="forfeit",
                                  loser=loser), remaining)
        return GameReport(row(plan, winner=seat_of[ending]), remaining)


def test_a_two_nil_match_carries_each_players_bank_across_seat_swaps() -> None:
    script = Script([({"search": 400_000, "b512": 1_000}, "search"), ({"search": 300_000, "b512": 2_000}, "search")])
    summary = match.play_match(0, PLAYERS, "Burn", BANK, script)
    first, second = script.plans
    assert first.seats == ("search", "b512") and second.seats == ("b512", "search")
    assert first.starting_bank_ms == (BANK, BANK)
    assert second.starting_bank_ms == (BANK - 1_000, BANK - 400_000)       # b512 at p0 now
    assert (first.game_index, second.game_index) == (0, 1) and first.deck == second.deck == "Burn"
    assert summary["winner"] == "search" and summary["ended_by"] == "wins" and summary["game_wins"] == {
        "search": 2, "b512": 0}
    assert summary["bank_used_ms"] == {"search": 700_000, "b512": 3_000}
    assert summary["bank_remaining_ms"] == {"search": BANK - 700_000, "b512": BANK - 3_000}
    assert summary["flags"] == [] and summary["games"] == [0, 1]


def test_a_flag_ends_the_match_as_a_loss_for_the_player_who_flagged() -> None:
    games = []
    script = Script([({"search": 900_000}, "search"), ({"search": 600_000}, ("flag", "search")), ({}, "search")])
    summary = match.play_match(2, PLAYERS, "Elves", BANK, script, on_game=games.append)
    assert len(script.plans) == 2                                           # the third game is never played
    assert summary["winner"] == "b512" and summary["ended_by"] == "flag" and summary["flags"] == ["search"]
    assert summary["game_wins"] == {"search": 1, "b512": 1}
    assert summary["bank_remaining_ms"]["search"] == 0
    assert [game["flags"] for game in games] == [[], ["search"]]
    assert games[1]["bank_ms"]["p1"] == {"player": "search", "before_ms": BANK - 900_000, "after_ms": 0}
    assert [plan.game_index for plan in script.plans] == [6, 7]             # 3 * match + game


def test_a_bank_spent_exactly_on_a_winning_game_is_still_a_flag() -> None:
    """Running out of bank loses, whatever the game: a decision may use exactly the bank, and that leaves 0."""
    script = Script([({"b512": BANK}, "b512")])
    summary = match.play_match(0, PLAYERS, "Burn", BANK, script)
    assert len(script.plans) == 1 and summary["flags"] == ["b512"] and summary["winner"] == "search"
    assert summary["game_wins"] == {"search": 0, "b512": 1} and summary["ended_by"] == "flag"


def test_both_banks_at_zero_draw_the_match() -> None:
    summary = match.play_match(0, PLAYERS, "Burn", BANK, Script([({"search": BANK, "b512": BANK}, "draw")]))
    assert summary["flags"] == ["search", "b512"] and summary["winner"] is None and summary["result"] == "draw"


def test_a_start_timeout_with_bank_left_is_a_game_loss_not_a_flag() -> None:
    script = Script([({}, ("start_timeout", "b512")), ({}, "b512"), ({}, "search")])
    summary = match.play_match(0, PLAYERS, "Burn", BANK, script)
    assert summary["flags"] == [] and summary["winner"] == "search" and summary["ended_by"] == "wins"
    assert summary["games"] == [0, 1, 2]


@pytest.mark.parametrize("endings, winner, result", [
    (["search", "draw", "halt"], "search", "win"),       # more game wins after 3 games
    (["search", "b512", "draw"], None, "draw"),          # equal wins after 3 games
    (["draw", "draw", "draw"], None, "draw"),
])
def test_games_no_one_wins_use_one_of_the_three_games(endings, winner, result) -> None:
    summary = match.play_match(0, PLAYERS, "Burn", BANK, Script([({}, ending) for ending in endings]))
    assert (summary["winner"], summary["result"], summary["ended_by"]) == (winner, result, "games")
    assert len(summary["games"]) == 3 and summary["non_decisive_games"] == endings.count("draw") + endings.count("halt")


def test_seats_alternate_every_game_and_every_match() -> None:
    assert [match.seat_order(PLAYERS, m, g)[0] for m in range(2) for g in range(3)] == [
        "search", "b512", "search", "b512", "search", "b512"]


def test_a_series_plays_one_deck_per_match_and_counts_flags() -> None:
    script = Script([({}, "search"), ({}, "search"),
                     ({"b512": BANK}, ("flag", "b512")),
                     ({}, "b512"), ({}, "b512")])
    summaries = match.play_series(PLAYERS, ["Burn", "Elves"], 3, BANK, script)
    assert [s["deck"] for s in summaries] == ["Burn", "Elves", "Burn"]
    assert [s["winner"] for s in summaries] == ["search", "search", "b512"]
    counts = match.totals(PLAYERS, summaries, games=len(script.plans))
    assert counts == {"matches": 3, "games": 5, "flags": {"search": 0, "b512": 1}, "flags_total": 1,
                      "match_wins": {"search": 2, "b512": 1}, "match_draws": 0}


def test_run_writes_games_and_matches(tmp_path: Path) -> None:
    script = Script([({"search": 10}, "search"), ({"b512": 20}, "search"), ({}, "b512"), ({}, "b512")])
    document = match.run(tmp_path / "out", {"stand-in": "config"}, players=PLAYERS, decks=["Burn"], matches=2,
                         bank_ms=BANK, run_secret=TEST_RUN_SECRET, source="test", play=script)
    out = tmp_path / "out"
    games = [json.loads(line) for line in (out / match.GAMES_NAME).read_text(encoding="utf-8").splitlines()]
    assert [game["game_index"] for game in games] == [0, 1, 3, 4]
    assert games[0]["bank_ms"]["p0"] == {"player": "search", "before_ms": BANK, "after_ms": BANK - 10}
    assert set(games[0]) >= {"outcome", "reason", "classification", "step_count", "row", "flags", "winner"}
    written = json.loads((out / match.MATCHES_NAME).read_text(encoding="utf-8"))
    assert written == document and written["status"] == "complete"
    assert written["run_secret"] == TEST_RUN_SECRET.hex()
    assert written["run_secret_commitment"] == TEST_RUN_SECRET.commitment()
    assert written["counts"]["flags_total"] == 0 and written["counts"]["games"] == 4
    assert json.loads((out / match.CONFIG_NAME).read_text(encoding="utf-8")) == {"stand-in": "config"}
    with pytest.raises(SystemExit):
        match.run(out, {}, players=PLAYERS, decks=["Burn"], matches=1, bank_ms=BANK, run_secret=TEST_RUN_SECRET,
                  source="test", play=script)


def test_after_game_sees_every_record(tmp_path: Path) -> None:
    seen = []
    match.run(tmp_path, {}, players=PLAYERS, decks=["Burn"], matches=1, bank_ms=BANK, run_secret=TEST_RUN_SECRET,
              source="test", play=Script([({}, "search"), ({}, "search")]), after_game=seen.append)
    assert [record["game_index"] for record in seen] == [0, 1]


def test_a_failed_preflight_still_reveals_its_secret(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    roomy_machine(monkeypatch)
    source = make_config(tmp_path / "src", [builtin("uniform", seed=3), builtin("first")], deck_pool=("Burn",),
                         pairs=1, engine=tmp_path / "no-such-engine.py")
    doc, decks = match.match_config(source, players=("uniform", "first"), bank_ms=BANK, run_dir=tmp_path / "run")
    with pytest.raises(TournamentError):
        match.run(tmp_path / "out", doc, players=("uniform", "first"), decks=decks, matches=1, bank_ms=BANK,
                  run_secret=TEST_RUN_SECRET, source="test")
    written = json.loads((tmp_path / "out" / match.MATCHES_NAME).read_text(encoding="utf-8"))
    assert written["status"] == "aborted" and written["run_secret"] == TEST_RUN_SECRET.hex()
    assert written["counts"]["games"] == 0


def test_an_interrupted_run_still_reveals_its_secret(tmp_path: Path) -> None:
    def broken(plan: GamePlan) -> GameReport:
        raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        match.run(tmp_path, {}, players=PLAYERS, decks=["Burn"], matches=1, bank_ms=BANK,
                  run_secret=TEST_RUN_SECRET, source="test", play=broken)
    written = json.loads((tmp_path / match.MATCHES_NAME).read_text(encoding="utf-8"))
    assert written["status"] == "aborted" and written["run_secret"] == TEST_RUN_SECRET.hex()


def soak_shaped(directory: Path) -> dict:
    """A config in the W1 soak shape: an anchor builtin, two subprocess bots, an 8-deck pool and a soak clock."""
    bots = [builtin("uniform", seed=11),
            subprocess_bot("b512", ["py", "flat.py", "--name", "b512"], engine="mtg-kernel"),
            subprocess_bot("search", ["py", "search.py", "--decision-log", "C:\\soak\\decisions"],
                           engine="mtg-kernel")]
    decks = ("Wildfire", "Rally", "Affinity", "Elves", "Spy", "Burn", "CawGates", "Faeries")
    return make_config(directory, bots, deck_pool=decks, pairs=64, include_self_play=False,
                       matchups=[["search", "b512"]], rating_anchor="uniform", workers=7,
                       time_control={"bank_ms": 7200000, "engine_step_ms": 120000, "game_start_ms": 60000,
                                     "increment_ms": 30000, "max_decision_ms": 180000, "startup_ms": 120000})


def test_a_soak_config_becomes_the_match_config(tmp_path: Path) -> None:
    source = soak_shaped(tmp_path / "soak")
    doc, decks = match.match_config(source, players=PLAYERS, bank_ms=BANK, run_dir=tmp_path / "run")
    config = TournamentConfig.from_json(doc)
    assert [bot.name for bot in config.bots] == list(PLAYERS)
    assert config.bots[0].command == ("py", "search.py", "--decision-log", "C:\\soak\\decisions")   # verbatim
    assert config.time_control.to_json() == {"bank_ms": BANK, "engine_step_ms": 120000, "game_start_ms": 60000,
                                             "increment_ms": 0, "max_decision_ms": BANK, "startup_ms": 120000}
    assert decks == ["Wildfire", "Rally", "Affinity", "Elves", "Spy", "Burn", "CawGates", "Faeries"]
    assert config.workers == 1 and config.matchups == (PLAYERS,)
    doc, decks = match.match_config(source, players=("human", "b512"), bank_ms=BANK, run_dir=tmp_path / "run",
                                    decks=["Burn", "Elves", "Burn"])
    config = TournamentConfig.from_json(doc)
    assert config.bots[0].name == "human" and config.time_control.startup_ms == match.HUMAN_STARTUP_MS
    assert decks == ["Burn", "Elves", "Burn"] and [d.catalog_id for d in config.deck_pool] == ["Burn", "Elves"]
    with pytest.raises(SystemExit):
        match.match_config(source, players=PLAYERS, bank_ms=BANK, run_dir=tmp_path, decks=["Stompy"])
    with pytest.raises(SystemExit):
        match.match_config(source, players=("search", "nobody"), bank_ms=BANK, run_dir=tmp_path)
    with pytest.raises(SystemExit):
        match.match_config(source, players=("b512", "b512"), bank_ms=BANK, run_dir=tmp_path)


def test_decision_logs_are_added_only_on_request(tmp_path: Path) -> None:
    source = soak_shaped(tmp_path / "soak")
    doc, _ = match.match_config(source, players=("b512", "uniform"), bank_ms=BANK, run_dir=tmp_path,
                                decision_log=tmp_path / "logs")
    assert doc["bots"][0]["command"][-2:] == ["--decision-log", str(tmp_path / "logs")]
    assert "command" not in doc["bots"][1]                                   # a builtin has none
    doc, _ = match.match_config(source, players=("b512", "uniform"), bank_ms=BANK, run_dir=tmp_path)
    assert doc["bots"][0]["command"] == ["py", "flat.py", "--name", "b512"]


def test_builtin_bots_play_matches_through_the_arena_runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The fake engine and two builtin bots: real games, the bank carried, deterministic ids, no flags."""
    roomy_machine(monkeypatch)
    source = make_config(tmp_path / "src", [builtin("uniform", seed=3), builtin("first")],
                         deck_pool=("Burn",), pairs=1)
    players = ("uniform", "first")
    doc, decks = match.match_config(source, players=players, bank_ms=BANK, run_dir=tmp_path / "run")
    document = match.run(tmp_path / "out", doc, players=players, decks=decks, matches=2, bank_ms=BANK,
                         run_secret=TEST_RUN_SECRET, source="test")
    assert document["status"] == "complete" and document["counts"]["flags_total"] == 0
    assert document["counts"]["matches"] == 2 and 4 <= document["counts"]["games"] <= 6
    games = [json.loads(line) for line in (tmp_path / "out" / match.GAMES_NAME).read_text().splitlines()]
    for game in games:
        assert game["game_id"] == TEST_RUN_SECRET.game_id(game["game_index"])
        for seat in ("p0", "p1"):
            assert 0 < game["bank_ms"][seat]["after_ms"] <= game["bank_ms"][seat]["before_ms"] <= BANK
    first_match = [game for game in games if game["match_index"] == 0]
    assert first_match[1]["bank_ms"]["p1"]["before_ms"] == first_match[0]["bank_ms"]["p0"]["after_ms"]


def test_the_page_closes_a_game_the_host_ended_without_its_relay() -> None:
    """A human timeout closes the relay before its game_over: the page withdraws the decision and records the end."""
    hub = Hub()
    hub.game_start({"game_id": "g-1", "seat": "p1", "own_deck": {"name": "Burn"}, "opponent_deck": {"name": "Burn"}})
    hub.pending = {"seq": 1}
    terminal = {"outcome": "p0_win", "classification": "forfeit", "winner": "p0", "reason": "forfeit:timeout"}
    hub.close_game("g-0", terminal)                                          # another game: nothing happens
    assert hub.results == [] and hub.pending is not None
    hub.close_game("g-1", terminal)
    assert hub.pending is None and hub.results[-1]["result"] == "loss" and hub.game_over["reason"] == "forfeit:timeout"
    hub.close_game("g-1", terminal)                                          # already closed: once only
    assert len(hub.results) == 1


def test_the_person_plays_a_match_through_the_relay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    roomy_machine(monkeypatch)
    hub = Hub(log_dir=tmp_path / "logs")
    server = make_server(hub)
    host, port = server.server_address[:2]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv(relay.URL_ENV, f"http://{host}:{port}")
    monkeypatch.setenv(relay.TOKEN_ENV, server.token)
    stop = threading.Event()

    def player() -> None:  # a person who presses "next" and takes the last offered candidate
        seen = set()
        while not stop.is_set():
            with hub.cond:
                hub.cond.wait(0.05)
                pending, waiting = hub.pending, hub.hello_waiting
            if waiting:
                hub.control("next", {})
            if pending is not None and pending["seq"] not in seen:
                seen.add(pending["seq"])
                if pending["screen"] in ("attack", "block"):
                    hub.plan_with(pending["seq"], {"kind": pending["screen"], "attackers": [], "blocks": {}})
                else:
                    hub.answer_with(pending["seq"], pending["candidates"][-1]["id"])
    threading.Thread(target=player, daemon=True).start()
    source = make_config(tmp_path / "src", [builtin("uniform", seed=3)], deck_pool=("Burn",), pairs=1)
    players = ("human", "uniform")
    doc, decks = match.match_config(source, players=players, bank_ms=BANK, run_dir=tmp_path / "run",
                                    python=sys.executable)
    try:
        document = match.run(tmp_path / "out", doc, players=players, decks=decks, matches=1, bank_ms=BANK,
                             run_secret=RunSecret(bytes(32)), source="test")
    finally:
        stop.set()
        server.shutdown()
    assert document["status"] == "complete" and document["counts"]["flags_total"] == 0
    assert 2 <= document["counts"]["games"] <= 3
    games = [json.loads(line) for line in (tmp_path / "out" / match.GAMES_NAME).read_text().splitlines()]
    assert all(game["classification"] != "forfeit" for game in games)
    assert len(hub.results) == len(games)
