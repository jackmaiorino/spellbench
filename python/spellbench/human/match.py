"""Best-of-three match mode: N matches between two players, each with one bank that carries across games.

``python -m spellbench.human.match`` plays ``--matches`` best-of-three matches between two players, either of
which may be the person (``human``, the play page's relay seat) or any bot entry of the source config. The
source is an arena tournament config file (``--config``, for example a W1 soak config), whose bot commands are
used verbatim, or a benchmark definition (``--benchmark`` with ``--local``), built as ``spellbench.human``
builds it, whose subprocess bots get ``--decision-log``.

The rules (W1 entrant design v7, sections 2, 12 and 13):

- Each player has one bank of ``--bank-ms`` (default 1,500,000 ms) with no increment for the whole match. The
  per-decision cap is the remaining bank: the arena time control gets ``bank_ms`` and ``max_decision_ms`` equal
  to the match bank and ``increment_ms`` 0, and each game starts each seat at the bank the previous game left
  (``GameSetup.starting_bank_ms``). Time between games is off the clock: ``startup_ms`` bounds a seat's start,
  the bank does not.
- A flag is a game's ``forfeit:timeout`` whose loser ended it with 0 bank. It ends the match at once as a loss
  for the player who flagged. A ``timeout`` at a seat's start, with bank left, is an ordinary game loss.
- A match ends when a player has 2 game wins, after a flag, or after 3 games. A game that no one wins (a draw,
  a truncated game or a halt) still uses one of the 3 games. After 3 games the player with more game wins wins
  the match; equal wins make the match a draw.
- Seats alternate every game: in match ``m`` game ``g`` (both from 0) the first player of ``--players`` sits at
  p0 when ``m + g`` is even, so p0, which plays first, alternates within a match and between matches.
- Match ``m`` is a mirror on deck ``m mod len(decks)`` of ``--decks`` (default: the source's deck pool, in
  order), every game of the match.
- Game ``g`` of match ``m`` has ``game_index = 3 * m + g``; its id, game secret and agent seeds come from the
  run secret as an arena run's do, so the same secret replays the same ids and seeds whatever earlier matches
  did. ``matches.json`` carries the secret's commitment while games play and the secret once the run ends.

Games are played one at a time in this process (no worker pool, no throughput qualification: unrated, like a
person's session). The output directory gets ``match-config.json`` (the arena config the games play),
``games.jsonl`` (per game: the ledger row and each seat's bank before and after), ``diagnostics.jsonl`` (operator
diagnostics, if any) and ``matches.json`` (per match and in total, rewritten after every game). Bot vs bot needs
no browser or server; with ``human`` seated the play server starts as in ``spellbench.human``.
"""

from __future__ import annotations

import argparse
import copy
import dataclasses
import json
import os
import sys
import threading
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from ..arena import runner, store
from ..arena.config import DeckSpec, TournamentConfig
from ..arena.manifest import isolation_refusals
from ..arena.schedule import EnginePin, GameContext, preflight
from ..bench import definition
from ..messages import EngineIdentity
from ..run_secret import RunSecret
from . import relay, session
from .server import Hub, make_server

SCHEMA = "spellbench-human-match/v1"
MATCH_BANK_MS = 1_500_000
GAMES_PER_MATCH = 3
WINS_NEEDED = 2
HUMAN = session.HUMAN
HUMAN_STARTUP_MS = 4 * 3_600_000  # the person's seat start waits for "next game" (relay.py)
GAMES_NAME, MATCHES_NAME, CONFIG_NAME, DIAGNOSTICS_NAME = "games.jsonl", "matches.json", "match-config.json", "diagnostics.jsonl"
_PANEL_KEYS = ("opponent_panel", "evaluation_version", "evaluation_engine_identity", "evaluation_engine_inputs", "ladder")


# ---------------------------------------------------------------------------
# The match rules, independent of how a game is played
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GamePlan:
    """One game to play: its place, players by seat, the mirror deck and each seat's starting bank."""

    match_index: int
    game_number: int
    game_index: int
    seats: tuple[str, str]  # player names at p0, p1
    deck: str
    starting_bank_ms: tuple[int, int]  # p0, p1


@dataclass(frozen=True)
class GameReport:
    """One played game: its ledger row (JSON) and each seat's bank when it ended."""

    row: dict[str, Any]
    remaining_bank_ms: dict[str, int]
    diagnostics: tuple[str, ...] = ()
    violation: dict[str, Any] | None = None


class MatchStopped(Exception):
    """The series stopped early: a live-validation violation (the arena stops a run there too, Decision 6)."""


def seat_order(players: tuple[str, str], match_index: int, game_number: int) -> tuple[str, str]:
    """The players at p0 and p1: the first player sits at p0 when ``match_index + game_number`` is even."""
    first, second = players
    return (first, second) if (match_index + game_number) % 2 == 0 else (second, first)


def flagged_seat(row: dict[str, Any], remaining_bank_ms: dict[str, int]) -> str | None:
    """The seat that flagged: lost a ``forfeit:timeout`` with its bank at 0, else None."""
    adjudication = row.get("adjudication") or {}
    if row["reason"] != "forfeit:timeout" or adjudication.get("kind") != "forfeit":
        return None
    loser = adjudication["loser_seat"]
    return loser if remaining_bank_ms[loser] == 0 else None


def play_match(match_index: int, players: tuple[str, str], deck: str, bank_ms: int,
               play: Callable[[GamePlan], GameReport],
               on_game: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    """Play one best-of-three match through ``play``; returns its summary (module docstring gives the rules)."""
    banks = {name: bank_ms for name in players}
    wins = dict.fromkeys(players, 0)
    games: list[dict[str, Any]] = []
    flagged: str | None = None
    for game_number in range(GAMES_PER_MATCH):
        seats = seat_order(players, match_index, game_number)
        plan = GamePlan(match_index=match_index, game_number=game_number,
                        game_index=GAMES_PER_MATCH * match_index + game_number, seats=seats, deck=deck,
                        starting_bank_ms=(banks[seats[0]], banks[seats[1]]))
        report = play(plan)
        row = report.row
        by_seat = dict(zip(("p0", "p1"), seats))
        bank = {seat: {"player": name, "before_ms": banks[name], "after_ms": report.remaining_bank_ms[seat]}
                for seat, name in by_seat.items()}
        for seat, name in by_seat.items():
            banks[name] = report.remaining_bank_ms[seat]
        winner = by_seat[row["winner"]] if row["winner"] is not None else None
        if winner is not None:
            wins[winner] += 1
        flag_seat = flagged_seat(row, report.remaining_bank_ms)
        record = {
            "match_index": match_index, "game_number": game_number, "game_index": plan.game_index,
            "game_id": row["game_id"], "deck": deck, "seats": by_seat, "outcome": row["outcome"],
            "classification": row["classification"], "reason": row["reason"], "winner_seat": row["winner"],
            "winner": winner, "step_count": row["step_count"], "decision_count": row["decision_count"],
            "flag": None if flag_seat is None else by_seat[flag_seat], "bank_ms": bank, "row": row,
        }
        games.append(record)
        if on_game is not None:
            on_game(record)
        if report.violation is not None:
            raise MatchStopped(f"game {plan.game_index} ({row['game_id']}) halted on a live-validation violation: "
                               f"{report.violation.get('rule')}")
        if flag_seat is not None:
            flagged = by_seat[flag_seat]
            break
        if max(wins.values()) >= WINS_NEEDED:
            break
    first, second = players
    if flagged is not None:
        winner, ended_by = (second if flagged == first else first), "flag"
    elif max(wins.values()) >= WINS_NEEDED:
        winner, ended_by = max(players, key=lambda name: wins[name]), "wins"
    else:
        ended_by = "games"
        winner = None if wins[first] == wins[second] else max(players, key=lambda name: wins[name])
    return {
        "match_index": match_index, "deck": deck, "games": [game["game_index"] for game in games],
        "game_ids": [game["game_id"] for game in games], "game_wins": wins,
        "non_decisive_games": sum(1 for game in games if game["winner"] is None),
        "winner": winner, "result": "draw" if winner is None else "win", "ended_by": ended_by,
        "flags": [] if flagged is None else [flagged],
        "bank_used_ms": {name: bank_ms - banks[name] for name in players},
        "bank_remaining_ms": dict(banks),
    }


def totals(players: tuple[str, str], matches: Sequence[dict[str, Any]], games: int) -> dict[str, Any]:
    flags = {name: sum(match["flags"].count(name) for match in matches) for name in players}
    return {
        "matches": len(matches), "games": games, "flags": flags, "flags_total": sum(flags.values()),
        "match_wins": {name: sum(1 for match in matches if match["winner"] == name) for name in players},
        "match_draws": sum(1 for match in matches if match["winner"] is None),
    }


def play_series(players: tuple[str, str], decks: Sequence[str], matches: int, bank_ms: int,
                play: Callable[[GamePlan], GameReport], *,
                on_game: Callable[[dict[str, Any]], None] | None = None,
                on_match: Callable[[list[dict[str, Any]]], None] | None = None) -> list[dict[str, Any]]:
    """Play ``matches`` matches in order, match ``m`` on ``decks[m % len(decks)]``; returns their summaries."""
    summaries: list[dict[str, Any]] = []
    for match_index in range(matches):
        summaries.append(play_match(match_index, players, decks[match_index % len(decks)], bank_ms, play,
                                    on_game=on_game))
        if on_match is not None:
            on_match(summaries)
    return summaries


# ---------------------------------------------------------------------------
# The arena config the games play, from a config file or a benchmark
# ---------------------------------------------------------------------------


def deck_label(deck: dict[str, Any]) -> str:
    return deck.get("catalog_id") or deck["name"]


def benchmark_source(benchmark_dir: Path, local: dict[str, str], run_dir: Path) -> dict[str, Any]:
    """A benchmark's arena config, as ``spellbench.human`` builds it, with every bot of the benchmark."""
    benchmark = dataclasses.replace(definition.load_benchmark(benchmark_dir), evaluation_targets=None,
                                    evaluation_matchups=None)
    return session.resolve_local(benchmark.tournament_config(str(run_dir)), local)


def match_config(source: dict[str, Any], *, players: tuple[str, str], bank_ms: int, run_dir: Path,
                 decks: Sequence[str] | None = None, python: str = sys.executable,
                 decision_log: Path | None = None) -> tuple[dict[str, Any], list[str]]:
    """The arena config of the match games and the deck of each match slot (``--decks`` order).

    The bots are the two players (``human`` is the relay seat), the deck pool the decks the matches use, one worker,
    and the time control the match bank: ``bank_ms`` and ``max_decision_ms`` equal to it and no increment, so a
    decision may use the whole remaining bank. ``decision_log`` adds ``--decision-log`` to subprocess bots (the
    benchmark path); otherwise bot commands stay verbatim.
    """
    if len(players) != 2 or players[0] == players[1]:
        raise SystemExit(f"--players needs two different players, got {list(players)}")
    doc = copy.deepcopy(source)
    for key in _PANEL_KEYS:
        doc.pop(key, None)
    config = TournamentConfig.from_json(doc)  # validates the source and fills in its defaults
    doc = config.to_json()
    by_name = {bot["name"]: bot for bot in doc["bots"]}
    bots = []
    for name in players:
        if name == HUMAN:
            bots.append({"name": HUMAN, "version": relay.VERSION, "type": "subprocess", "owner": "spellbench",
                         "training_style_tags": ["human"], "command": [python, str(Path(relay.__file__).resolve())]})
            continue
        if name not in by_name:
            raise SystemExit(f"player {name!r} is not a bot of the source config: {sorted(by_name)}")
        bot = copy.deepcopy(by_name[name])
        if decision_log is not None and bot["type"] == "subprocess":
            bot["command"] = list(bot["command"]) + ["--decision-log", str(decision_log)]
            bot.pop("evaluation_identity", None)  # the command changed: it logs
        bots.append(bot)
    pool = {}
    for deck in doc.get("deck_pool") or doc["decks"]:
        pool.setdefault(deck_label(deck), deck)
    chosen = list(decks) if decks else list(pool)
    missing = [deck for deck in chosen if deck not in pool]
    if missing:
        raise SystemExit(f"decks {missing} are not in the source's decks {sorted(pool)}")
    distinct = list(dict.fromkeys(chosen))
    doc.pop("decks", None)
    doc["deck_pool"] = [pool[deck] for deck in distinct]
    doc["bots"] = bots
    doc["matchups"] = [list(players)]
    doc["include_self_play"] = False
    doc["rating_anchor"] = players[0]
    doc["pairs_per_matchup"] = len(distinct)
    doc["workers"] = 1
    doc["tournament_dir"] = str(run_dir)
    startup_ms = max(doc["time_control"]["startup_ms"], HUMAN_STARTUP_MS) if HUMAN in players else doc["time_control"]["startup_ms"]
    doc["time_control"] = {**doc["time_control"], "startup_ms": startup_ms, "bank_ms": bank_ms, "increment_ms": 0,
                           "max_decision_ms": bank_ms}
    TournamentConfig.from_json(doc)
    return doc, chosen


# ---------------------------------------------------------------------------
# Playing the games through the arena's game runner
# ---------------------------------------------------------------------------


def arena_player(config: TournamentConfig, run_secret: RunSecret) -> Callable[[GamePlan], GameReport]:
    """Preflight once (the engine, every deck, both bots), then play each planned game with ``runner.play_one``."""
    refusals = isolation_refusals(config)
    if refusals:
        raise SystemExit("; ".join(refusals))
    pin = EnginePin()
    setup = preflight(config, run_secret, pin=pin)
    entries = {entry.name: entry for entry in runner.registry_entries(config, config)}
    specs = {bot.name: bot for bot in config.bots}
    decks = {deck_label(deck.to_json()): deck for deck in config.deck_specs()}

    def play(plan: GamePlan) -> GameReport:
        deck: DeckSpec = decks[plan.deck]
        context = GameContext(
            game_index=plan.game_index, game_id=run_secret.game_id(plan.game_index), matchup_index=plan.match_index,
            pair_index=plan.game_number, pair_slot=plan.game_number % 2,
            seat_specs=(("p0", specs[plan.seats[0]]), ("p1", specs[plan.seats[1]])), decks=(deck, deck))
        outcome = runner.play_one(config, setup, context, run_secret.hex(), entries, recording=None,
                                  starting_bank_ms=plan.starting_bank_ms)
        pin.check(EngineIdentity.from_json(outcome.engine))  # an engine that changed identity stops the series
        assert outcome.remaining_bank_ms is not None
        return GameReport(row=outcome.row.to_json(), remaining_bank_ms=outcome.remaining_bank_ms,
                          diagnostics=outcome.diagnostics, violation=outcome.violation)

    return play


def run(out: Path, config_doc: dict[str, Any], *, players: tuple[str, str], decks: Sequence[str], matches: int,
        bank_ms: int, run_secret: RunSecret, source: str,
        play: Callable[[GamePlan], GameReport] | None = None) -> dict[str, Any]:
    """Play the series into ``out`` and return the final ``matches.json`` document (written after every game)."""
    out.mkdir(parents=True, exist_ok=True)
    if (out / MATCHES_NAME).exists() or (out / GAMES_NAME).exists():
        raise SystemExit(f"{out} already holds a match run; choose another --out")
    store.write_json_atomic(out / CONFIG_NAME, config_doc)
    played: list[dict[str, Any]] = []
    done: list[dict[str, Any]] = []
    document = {
        "schema": SCHEMA, "status": "running", "source": source, "players": list(players), "bank_ms": bank_ms,
        "increment_ms": 0, "games_per_match": GAMES_PER_MATCH, "wins_needed": WINS_NEEDED, "decks": list(decks),
        "matches_scheduled": matches, "run_secret_commitment": run_secret.commitment(), "run_secret": None,
    }

    def write() -> None:
        document["matches"] = done
        document["counts"] = totals(players, done, len(played))
        store.write_json_atomic(out / MATCHES_NAME, document)

    def on_game(record: dict[str, Any]) -> None:
        played.append(record)
        store.append_ledger_row(out / GAMES_NAME, record)
        write()

    def on_match(summaries: list[dict[str, Any]]) -> None:
        done[:] = summaries
        write()

    if play is None:
        play = arena_player(TournamentConfig.from_json(config_doc), run_secret)

    def play_logged(plan: GamePlan) -> GameReport:
        report = play(plan)
        if report.diagnostics:
            store.append_diagnostics(out / DIAGNOSTICS_NAME, report.row["game_id"], report.diagnostics)
        return report

    write()
    try:
        play_series(players, decks, matches, bank_ms, play_logged, on_game=on_game, on_match=on_match)
        document["status"] = "complete"
    except MatchStopped as exc:
        document["status"], document["stopped"] = "stopped", str(exc)
    except BaseException:
        document["status"] = "aborted"
        raise
    finally:
        document["run_secret"] = run_secret.hex()  # revealed whatever the status, as an arena manifest does
        write()
    return document


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m spellbench.human.match", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--players", required=True,
                        help=f"two players, comma-separated: bot names of the source, or {HUMAN!r} for the person")
    parser.add_argument("--matches", type=int, default=8)
    parser.add_argument("--bank-ms", type=int, default=MATCH_BANK_MS, help="each player's bank for a whole match")
    parser.add_argument("--decks", default=None,
                        help="comma-separated decks, match m on deck m mod count (default: the source's pool)")
    parser.add_argument("--config", type=Path, default=None, help="arena tournament config file to take bots from")
    parser.add_argument("--benchmark", type=Path, default=None,
                        help="benchmark definition to take bots from (default pauper-kernel-v2 without --config)")
    parser.add_argument("--local", type=Path, default=None,
                        help="local values file (benchmarks/local.json shape): needed with a benchmark")
    parser.add_argument("--out", type=Path, required=True, help="output directory (must not hold a match run)")
    parser.add_argument("--secret-hex", default=None, help="run secret (64 hex) to replay ids and seeds")
    parser.add_argument("--port", type=int, default=8765, help="play server port when the person plays")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    if args.matches < 1 or args.bank_ms < 1:
        raise SystemExit("--matches and --bank-ms must be at least 1")
    if args.config is not None and args.benchmark is not None:
        raise SystemExit("give --config or --benchmark, not both")
    players = tuple(name.strip() for name in args.players.split(","))
    if len(players) != 2:
        raise SystemExit("--players needs exactly two names")
    out = args.out.resolve()
    local = json.loads(args.local.read_text(encoding="utf-8")) if args.local else {}
    python = local.get("PYTHON") or sys.executable
    if args.config is not None:
        source_doc = json.loads(args.config.read_text(encoding="utf-8"))
        if local:
            source_doc = session.resolve_local(source_doc, local)
        source, decision_log = str(args.config.resolve()), None
    else:
        benchmark = args.benchmark or session.REPO / "benchmarks" / "pauper-kernel-v2"
        if args.local is None:
            raise SystemExit("a benchmark source needs --local")
        source_doc = benchmark_source(benchmark, local, out / "run")
        source, decision_log = str(benchmark.resolve()), out / "decision-logs"
    config_doc, decks = match_config(source_doc, players=players, bank_ms=args.bank_ms, run_dir=out / "run",
                                     decks=[d.strip() for d in args.decks.split(",")] if args.decks else None,
                                     python=python, decision_log=decision_log)
    run_secret = RunSecret.from_hex(args.secret_hex) if args.secret_hex else RunSecret.generate()

    server = None
    if HUMAN in players:
        opponent = players[1] if players[0] == HUMAN else players[0]
        hub = Hub(log_dir=out / "decision-logs", games_total=None, opponent=opponent,
                  label=f"{args.matches} best-of-three matches vs {opponent}, "
                        f"{args.bank_ms // 60_000}-minute match bank")
        server = make_server(hub, port=args.port)
        host, port = server.server_address[:2]
        os.environ[relay.URL_ENV] = f"http://{host}:{port}"
        os.environ[relay.TOKEN_ENV] = server.token
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f"http://{host}:{port}/?t={server.token}"
        print(f"\n  Play here: {url}\n", flush=True)
        if not args.no_browser:
            webbrowser.open(url)
    print(f"  out: {out}", flush=True)
    try:
        document = run(out, config_doc, players=players, decks=decks, matches=args.matches, bank_ms=args.bank_ms,
                       run_secret=run_secret, source=source)
    finally:
        if server is not None:
            server.shutdown()
    counts = document["counts"]
    print(f"match run {document['status']}: {counts['matches']} matches, {counts['games']} games, "
          f"flags {counts['flags']} (total {counts['flags_total']})", flush=True)
    return 0 if document["status"] == "complete" else 1


if __name__ == "__main__":
    sys.exit(main())
