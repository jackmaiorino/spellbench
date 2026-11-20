"""One human play session: a person against a benchmark bot, as an ordinary arena run (``python -m spellbench.human``).

The session builds an arena config from a benchmark definition (default ``pauper-kernel-v2``): the benchmark's
engine, deck pool, rules, extensions and limits; the bots ``human`` (``relay.py``) and the opponent entry, which
gets ``--decision-log``; one explicit matchup with whole deck rotations of seat-swapped pairs (at least ``games``
games), so pair ``p`` plays deck ``p % len(pool)`` in both seats; one worker; and a clock sized for a person (``--bank-minutes``). It then starts the play
server on 127.0.0.1, prints the page URL, and runs the tournament into ``<out>/runs/<name>/`` (ledger, manifest).

The launch guard's throughput measurement is not run: a person plays one game at a time, and its qualification
games would be games the person plays outside the ledger. The run publishes as ``unmeasured`` and unrated.
Ctrl+C publishes the games played so far (status ``aborted``).

Unless ``--no-record`` is given, the operator engine recording is on (``spellbench.arena.engine_records``): each
game's complete engine transcript lands in ``<out>/engine-records/hot``, and a local collector thread keeps the
pinned two-copy custody (gzip copies on the cold and recovery roots) that the runner waits for after each game.
"""

from __future__ import annotations

import argparse
import copy
import dataclasses
import hashlib
import json
import math
import os
import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from ..arena import engine_records, runner
from ..arena.allocation import Allocation
from ..bench import definition
from ..run_secret import RunSecret
from . import graveyard_order, relay
from .advisor import Advisor, AdvisorError, scorer_argv
from .server import Hub, make_server

REPO = Path(__file__).resolve().parents[3]
HUMAN = "human"


def build_config(*, benchmark_dir: Path, local: dict[str, str], opponent: str, games: int, run_dir: Path,
                 python: str, decision_log: Path, bank_minutes: int, decks: list[str] | None = None) -> dict[str, Any]:
    benchmark = dataclasses.replace(definition.load_benchmark(benchmark_dir), evaluation_targets=None,
                                    evaluation_matchups=None)
    doc = benchmark.tournament_config(str(run_dir))
    for key in ("opponent_panel", "evaluation_version", "evaluation_engine_identity", "evaluation_engine_inputs",
                "export_blocks"):
        doc.pop(key, None)
    names = {bot["name"] for bot in doc["bots"]}
    if opponent not in names:
        raise SystemExit(f"opponent {opponent!r} is not a bot of {benchmark_dir.name}: {sorted(names)}")
    bots = []
    for bot in doc["bots"]:
        if bot["name"] == opponent:
            bot = copy.deepcopy(bot)
            bot["command"] = list(bot["command"]) + ["--decision-log", str(decision_log)]
            bot.pop("evaluation_identity", None)  # the command changed: it logs
            bots.append(bot)
        elif bot["name"] == doc["rating_anchor"]:
            bots.append(bot)
    bots.insert(0, {"name": HUMAN, "version": relay.VERSION, "type": "subprocess", "owner": "spellbench",
                    "training_style_tags": ["human"],
                    "command": [python, str(Path(relay.__file__).resolve())]})
    doc["bots"] = bots
    doc["matchups"] = [[HUMAN, opponent]]
    if decks:
        pool = {deck.get("catalog_id"): deck for deck in doc["deck_pool"]}
        missing = [deck for deck in decks if deck not in pool]
        if missing:
            raise SystemExit(f"decks {missing} are not in the pool {sorted(pool)}")
        doc["deck_pool"] = [pool[deck] for deck in decks]
    # A human session plays pool mirrors, even on an all_pairs board: its 64-pair rotation would turn a short
    # session into 128 games. Every deck plays equally often (the arena requires it): whole rotations of
    # seat-swapped pairs.
    doc.pop("deck_pairing", None)
    rotations = max(1, math.ceil(games / (2 * len(doc["deck_pool"]))))
    doc["pairs_per_matchup"] = rotations * len(doc["deck_pool"])
    doc["workers"] = 1
    bank = bank_minutes * 60_000
    # startup_ms also bounds the human seat's hello, which waits for "next game" between games.
    doc["time_control"] = {**doc["time_control"], "startup_ms": 4 * 3_600_000, "bank_ms": bank,
                           "max_decision_ms": bank}
    return resolve_local(doc, local)


def start_advisor(*, benchmark_dir: Path, local: dict[str, str], name: str, run_dir: Path,
                  label: str | None = None) -> Advisor:
    """The advisor of ``--advisor NAME``: a scorer process of the session's own, loaded with the checkpoint of the
    board's bot NAME (its command names the scorer and its config). It stops the session when NAME is not a kernel
    flat policy of the board or its scorer does not come up: a session asked to advise never plays unadvised
    without saying so."""
    doc = definition.load_benchmark(benchmark_dir).tournament_config(str(run_dir))
    bot = next((bot for bot in doc["bots"] if bot["name"] == name), None)
    if bot is None:
        raise SystemExit(f"advisor {name!r} is not a bot of {benchmark_dir.name}: "
                         f"{sorted(bot['name'] for bot in doc['bots'])}")
    try:
        argv = scorer_argv(resolve_local({"command": bot["command"]}, local)["command"])
    except ValueError as exc:
        raise SystemExit(f"advisor {name!r}: {exc}; only a kernel flat policy can advise") from exc
    label = label or (bot.get("display") or {}).get("label") or name
    try:
        return Advisor(argv, name=name, label=str(label))
    except AdvisorError as exc:
        raise SystemExit(f"advisor {name!r}: {exc}") from exc


def resolve_local(doc: dict[str, Any], local: dict[str, str]) -> dict[str, Any]:
    """``doc`` with every ``${NAME}`` placeholder replaced from the local values file (an environment variable of a
    name the file lists wins); a placeholder left without a value stops the session."""
    values = {**local, **{k: v for k, v in os.environ.items() if k in local}}

    def resolve(node: Any) -> Any:
        if isinstance(node, str):
            return definition.substitute(node, values)
        if isinstance(node, list):
            return [resolve(x) for x in node]
        if isinstance(node, dict):
            return {k: resolve(v) for k, v in node.items()}
        return node

    resolved = resolve(doc)
    text = json.dumps(resolved)
    if "${" in text:
        raise SystemExit("an engine or bot placeholder has no value in the local values file")
    return resolved


def recording_settings(out: Path, cold: Path) -> tuple[Path, str]:
    """Write the bounded recording config the runner reads from the environment; returns its path and hash.

    ``on_cap: truncate``: a game whose transcript reaches the per-game cap keeps the complete lines written so far and
    plays on unrecorded (one line on stderr, ``truncated_at_bytes`` in its receipt). Without it the arena aborts the
    run, which would end a person's session and lose the game in progress: a bot that mills itself with Balustrade Spy
    writes 100 MiB or more of ordering decisions in one turn."""
    path = out / "engine-records" / "recording.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"schema": "spellbench-engine-recording/v1", "root": str(out / "engine-records" / "hot"),
            "per_game_cap_bytes": 128 * 2**20, "on_cap": "truncate", "collection_timeout_seconds": 600,
            "cold_source": str(cold), "recovery": str(out / "engine-records" / "recovery"),
            "transport": {"ssh_target": "local", "poll_seconds": 1, "command_timeout_seconds": 60,
                          "copy_timeout_seconds": 120, "compression": "gzip"},
            "remote_config_path": str(path), "cold_cap_bytes": 64 * 2**30, "recovery_cap_bytes": 64 * 2**30,
            "reserve_bytes": 60 * 2**30}
    data["source_sha256"] = engine_records.identity(data)["source_sha256"]
    raw = (json.dumps(data, indent=1) + "\n").encode("utf-8")
    if not path.exists() or path.read_bytes() != raw:
        path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest()


def collect_locally(stop: threading.Event) -> None:
    """The collector the runner waits for, on this machine: copy each READY record, then acknowledge it."""
    sys.path.insert(0, str(REPO / "python" / "tools"))
    from xmage_engine_record_collect import preserve  # noqa: E402 - the pinned custody steps

    data = engine_records.settings()
    root = Path(data["root"])
    while not stop.is_set():
        if root.is_dir():
            for bundle in sorted(root.iterdir()):
                if (bundle / "READY.json").exists() and not (bundle / "COLLECTED.json").exists():
                    try:
                        ack = preserve(bundle, data)
                        partial = bundle / "COLLECTED.json.partial"
                        partial.write_bytes(json.dumps(ack, sort_keys=True).encode() + b"\n")
                        os.replace(partial, bundle / "COLLECTED.json")
                    except Exception as exc:  # the runner times out and keeps the hot copy
                        print(f"recording collection failed for {bundle.name}: {exc}", file=sys.stderr, flush=True)
        stop.wait(data["transport"]["poll_seconds"])


def page_closer(hub: Hub) -> Any:
    """The runner's ``on_game`` hook: ends each recorded game on the page. A game the host ends (a spent bank, a
    halt) closes the relay before its ``game_over`` reaches the page; without this the page keeps the withdrawn
    decision and never offers the next game. A game the page already ended is left as it is."""
    def after_game(row: Any) -> None:
        record = row.to_json()
        hub.close_game(record["game_id"], {key: record[key] for key in ("outcome", "classification", "winner",
                                                                          "reason")})
    return after_game


# Reasons the session itself gives a game it ended: the person conceded or left the table, their connection did not
# come back, the relay connection was lost, or the host failed. The arena can only file each as the human seat's
# forfeit, so the ends file says why.
PERSON_ENDED = ("conceded", "connection_lost", "relay_lost", "host_fault")


def person_end(final: dict[str, Any] | None, ledger: Mapping[str, Any] | None) -> str | None:
    """Why the person's side ended game ``final`` (the page's result row), or None. The arena's ledger row is the
    truth: a concession or lost connection counts only when the ledger filed the game as a forfeit. When the engine
    had already ended the game (the bot's move won it a moment before the person gave up), the ledger keeps its
    natural result and the page's row is corrected to it, so the ledger and the ends file never disagree."""
    if not final or final.get("reason") not in PERSON_ENDED:
        return None
    if ledger is None or ledger.get("classification") == "forfeit":
        return final["reason"]
    winner = ledger.get("winner")
    final["reason"] = ledger.get("reason")
    final["result"] = "draw" if winner is None else ("win" if winner == final.get("seat") else "loss")
    return None


class DeckPlan:
    """The decks of the game that comes next, decided when the person picks at the table (not when the game starts),
    so the bot's deck in the lobby is the deck it will play. The person is dealt their pick when it is a training deck,
    else the next deck of ``rotation``; the bot plays the same deck (``mirror``), a fixed deck, or ``random``: one draw
    per game, made the first time it is asked for and kept, so the lobby and the game agree."""

    def __init__(self, rotation: list[str], opponent_deck: str, order: list[str], rng: Any) -> None:
        self.rotation, self.opponent_deck, self.order, self.rng = rotation, opponent_deck, order, rng
        self.drawn: list[str] = []

    def human(self, pick: str | None, played: int) -> str:
        return pick if pick is not None else self.rotation[played % len(self.rotation)]

    def bot(self, human: str, played: int) -> str:
        if self.opponent_deck == "mirror":
            return human
        if self.opponent_deck == "random":
            while len(self.drawn) <= played:
                self.drawn.append(self.rng.choice(self.order))
            return self.drawn[played]
        return self.opponent_deck


def pick_note(start: Mapping[str, Any], human: str) -> str:
    """What the log, the console and the name row say when the person is not dealt the deck they picked at the table
    (empty when they are)."""
    if start.get("human_pick") is not None:
        return ""
    picked = start.get("picked_name")
    what = f"you picked {picked} at the table, which is not a training deck" if picked else "you picked no training deck"
    return f"Deck note: {what}, so you are dealt {human} instead."


class OneGame(Exception):
    """Raised by the per-game hook: a picked game is the first game of a one-pair run."""


def picked_game_config(base: dict[str, Any], *, human_deck: str, bot_deck: str, human_first: bool,
                       run_dir: Path, opponent: str, full_priority: bool = False,
                       auto_graveyard_order: bool = False) -> dict[str, Any]:
    """One game with the decks the person picked: a one-pair run whose first game puts the person in seat p0
    (``human_first``) or p1, with the person's deck in that seat; the hook stops the run after that game.
    ``full_priority``: the engine of this game is told the person's seat (``--engine-windows-seat``), which it gives
    every priority window; ``auto_graveyard_order``: the engine gets ``--auto-graveyard-order`` (graveyard order
    settled for both seats in a game in which no card reads it). The engine must be one that takes the arguments
    (the London human engine)."""
    doc = copy.deepcopy(base)
    seat = "p0" if human_first else "p1"
    extra = (["--engine-windows-seat", seat] if full_priority else []) + (
        ["--auto-graveyard-order"] if auto_graveyard_order else [])
    if extra:
        doc["engine"] = {**doc["engine"], "command": [*doc["engine"]["command"], *extra]}
    doc["tournament_dir"] = str(run_dir)
    doc.pop("deck_pool", None)
    doc.pop("deck_pairing", None)
    if human_first:
        doc["matchups"] = [[HUMAN, opponent]]
        doc["decks"] = [{"catalog_id": human_deck}, {"catalog_id": bot_deck}]
    else:
        doc["matchups"] = [[opponent, HUMAN]]
        doc["decks"] = [{"catalog_id": bot_deck}, {"catalog_id": human_deck}]
    doc["pairs_per_matchup"] = 1
    return doc


def play_picked_games(args: Any, base: dict[str, Any], hub: Hub, server: Any, stop: threading.Event, *, out: Path,
                      name: str, shown: str) -> int:
    """The Manabrew table: each game plays the deck the person picks there (one of the training decks), against
    the bot's deck for that pick (``--opponent-deck``). Each game is its own run ``<name>-gNN``, stopped after its
    first game (so it publishes as aborted with that one game); the person alternates between seat p0 and p1.
    A pick that is not a training deck is replaced by the next deck of ``--decks`` (or the pool), and the play log,
    the player's name row and the console say so. The bot's deck is chosen when the person picks (``DeckPlan``), so
    its lobby deck is the one it plays."""
    import random
    from .manabrew import decks as pool, host as manabrew_host

    rotation = [d.strip() for d in args.decks.split(",")] if args.decks else list(pool.ORDER)
    plan = DeckPlan(rotation, args.opponent_deck, list(pool.ORDER), random.Random(f"{name}:opponent-deck"))
    played = 0

    def bot_deck_for(pick: str | None) -> str:
        return plan.bot(plan.human(pick, played), played)

    bridge = manabrew_host.Bridge(hub, relay_url=args.relay_url, relay_key=args.relay_key, room_name=args.room_name,
                                  bot_name=shown, bot_deck=manabrew_host.pool_deck(), bot_deck_for=bot_deck_for,
                                  allow_remote_relay=args.allow_remote_relay, pace=args.pace)
    bridge.start()
    print(f"  Manabrew: join table '{args.room_name}', pick a training deck, press Start game\n", flush=True)
    picks = out / "runs" / f"{name}.picks.jsonl"
    try:
        while played < args.games:
            try:
                start = bridge.next_start()
            except manabrew_host.RelayLost as exc:
                print(f"\n  Session ended: {exc}. Games recorded so far stay in {out / 'runs'}.", flush=True)
                return 2
            human = plan.human(start.get("human_pick"), played)
            bot = plan.bot(human, played)
            note = pick_note(start, human)
            human_first = played % 2 == 0
            bridge.dealt = {"human": human, "bot": bot, "differs": bool(note)}
            line = (f"Game {played + 1}: you play {human}, {shown} plays {bot}; "
                    f"you are seat {'p0' if human_first else 'p1'}")
            print(f"\n  ==== {line} ====\n" + (f"  {note}\n" if note else ""), flush=True)
            bridge.announce(line)
            if note:
                bridge.announce(note)
            run_name = f"{name}-g{played + 1:02d}"
            run_dir = out / "runs" / run_name
            doc = picked_game_config(base, human_deck=human, bot_deck=bot, human_first=human_first, run_dir=run_dir,
                                     opponent=args.opponent, full_priority=args.full_priority,
                                     auto_graveyard_order=args.auto_graveyard_order)
            if args.auto_graveyard_order:
                hub.set_graveyard_readers(graveyard_order.readers(pool.card_names(human) + pool.card_names(bot)))
            (out / "runs" / f"{run_name}.config.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
            with picks.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"game": played + 1, "run": run_name, "human_deck": human, "bot_deck": bot,
                                         "picked": start.get("picked_name"),
                                         "human_seat": "p0" if human_first else "p1",
                                         "opponent_deck_rule": args.opponent_deck}) + "\n")
            closer = page_closer(hub)
            ledger: list[dict[str, Any]] = []

            def after_game(row: Any, closer: Any = closer, ledger: list[dict[str, Any]] = ledger) -> None:
                ledger.append(row.to_json())
                closer(row)
                raise OneGame()

            try:
                runner.run_tournament(runner.TournamentConfig.from_json(doc), run_secret=RunSecret.generate(),
                                      allocation=Allocation.unmeasured(1), on_game=after_game)
            except OneGame:
                pass
            played += 1
            final = next((r for r in reversed(hub.results) if r.get("game_id") == (hub.game or {}).get("game_id")), None)
            ended = person_end(final, ledger[0] if ledger else None)
            if ended:  # the arena's ledger can only say forfeit:agent_error for this; the session says why
                with (out / "runs" / f"{name}.ends.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps({"game": played, "run": run_name, "game_id": final["game_id"],
                                             "result": final["result"], "reason": ended}) + "\n")
            print(f"  game {played} recorded in {run_dir}"
                  + (f" (ended by {ended.replace('_', ' ')}, a loss for you; the ledger shows forfeit:agent_error for "
                     f"the human seat, {out / 'runs' / (name + '.ends.jsonl')} says why)" if ended else ""), flush=True)
    finally:
        bridge.close()
        hub.close_advisor()
        stop.set()
        server.shutdown()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m spellbench.human", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--games", type=int, default=16,
                        help="games to schedule, rounded up to whole rotations of the deck pool (2 games per deck)")
    parser.add_argument("--decks", default=None, help="comma-separated deck subset, in play order (default: the pool)")
    parser.add_argument("--opponent", default="oh2-r2s1-b512")
    parser.add_argument("--benchmark", type=Path, default=REPO / "benchmarks" / "pauper-kernel-v2")
    parser.add_argument("--local", type=Path, required=True, help="local values file (benchmarks/local.json shape)")
    parser.add_argument("--out", type=Path, required=True, help="session root: runs, logs, records")
    parser.add_argument("--name", default=None, help="run name (default: a timestamp)")
    parser.add_argument("--bank-minutes", type=int, default=30)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--cold", type=Path, default=None, help="cold copy root for engine records")
    parser.add_argument("--no-record", action="store_true", help="skip the operator engine recording")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--client", choices=("page", "manabrew"), default="page",
                        help="page: the built-in play page; manabrew: host a room on a local Manabrew relay")
    parser.add_argument("--relay-url", default="ws://127.0.0.1:9443", help="Manabrew relay (a ws:// URL on this machine)")
    parser.add_argument("--allow-remote-relay", action="store_true",
                        help="accept a --relay-url that is not on this machine (the connection is not encrypted)")
    parser.add_argument("--relay-key", default="forge", help="the relay's shared key (MANABREW_SERVER_KEY)")
    parser.add_argument("--room-name", default="Spellbench", help="the Manabrew room the session opens")
    parser.add_argument("--opponent-deck", default="mirror",
                        help="manabrew: the bot's deck against the person's pick: mirror (default), random (drawn "
                             "from the pool for each game, recorded), or a pool deck name")
    parser.add_argument("--exclude-decks", default="",
                        help="manabrew: comma-separated board decks this session leaves out (the table does not offer "
                             "them, none is dealt to either seat)")
    parser.add_argument("--game-banner", default="",
                        help="a line shown first in every game's log and written in each game's record header (for "
                             "a session whose conditions the person should always see)")
    parser.add_argument("--advisor", default="",
                        help="a kernel flat bot of the board (the opponent or another) whose model reads the person's "
                             "own decisions in a scorer of the session's own: the Manabrew client's local panel shows "
                             "the probability it gives each choice and its value estimate. Advised play: every game's "
                             "log and record say so")
    parser.add_argument("--advisor-label", default="",
                        help="the advisor's name on screen and in the records (default: its board label)")
    parser.add_argument("--pace", type=float, default=1.0,
                        help="manabrew: display pacing, so a person can follow the opponent's turn: each position the "
                             "session passed through stays on the board 0.2 to 0.9 s by what changed (times this "
                             "factor), at most about 4 s of drawing per state. 0: only stack changes, 0.2 s apart. "
                             "The engine and the bot never wait for it; the prompt of your next decision comes after "
                             "the drawing, and your decision clock runs from when the engine asks, so that drawing "
                             "counts against your bank; nothing is waited for while your bank is under two minutes")
    parser.add_argument("--full-priority", action="store_true",
                        help="manabrew, London human engine: you get priority in every step the rules give it (upkeep, "
                             "draw, beginning of combat, combat damage, end of combat, the end step) and while your own "
                             "spell is on the stack; stops are taken in the step they name. The bot keeps the windows "
                             "it trained on: it does not respond to what you do in those six steps. Windows with only "
                             "mana abilities go to the client (its AUTOPASS countdown or Full control answers them)")
    parser.add_argument("--auto-graveyard-order", action="store_true",
                        help="manabrew, London human engine: in a game in which no card of either deck reads "
                             "graveyard order (every game of the eight training decks), neither you nor the bot is "
                             "asked to order cards put into a graveyard together (Balustrade Spy milling a library): "
                             "they keep the order the effect put them there, the rule the bots trained with. In a game "
                             "with such a card both players are asked, you in one step. Any other card ordering you are "
                             "asked (a library order, a put-back) is one step too. Leave the option out to be asked "
                             "card by card")
    parser.add_argument("--keep-mana-autopass", action="store_true",
                        help="with --full-priority: the session keeps passing windows with only mana abilities itself "
                             "(no client countdown; the client's Full control then has nothing to act on)")
    args = parser.parse_args(argv)
    if args.pace < 0:
        parser.error("--pace must be 0 or more")
    if (args.full_priority or args.auto_graveyard_order) and args.client != "manabrew":
        parser.error("--full-priority and --auto-graveyard-order need --client manabrew (the engine is told the "
                     "person's seat for each game)")
    if args.keep_mana_autopass and not args.full_priority:
        parser.error("--keep-mana-autopass only goes with --full-priority")
    if args.exclude_decks:
        from .manabrew import decks as board_decks
        left_out = [d.strip() for d in args.exclude_decks.split(",") if d.strip()]
        try:
            board_decks.exclude(left_out)
        except ValueError as exc:
            parser.error(f"--exclude-decks: {exc}")
        named = {d.strip() for d in (args.decks or "").split(",") if d.strip()} | {args.opponent_deck}
        if named & set(left_out):
            parser.error(f"--decks and --opponent-deck name an excluded deck: {', '.join(sorted(named & set(left_out)))}")
    if args.client == "manabrew":
        from .manabrew import ws as manabrew_ws
        try:
            manabrew_ws.require_loopback(args.relay_url, args.allow_remote_relay)
        except ValueError as exc:
            parser.error(str(exc))

    name = args.name or datetime.now().strftime("session-%Y%m%d-%H%M%S")
    out = args.out.resolve()
    run_dir = out / "runs" / name
    if run_dir.exists():
        raise SystemExit(f"{run_dir} exists; choose another --name")
    local = json.loads(args.local.read_text(encoding="utf-8"))
    python = local.get("PYTHON") or sys.executable
    config_doc = build_config(benchmark_dir=args.benchmark, local=local, opponent=args.opponent, games=args.games,
                              run_dir=run_dir, python=python, decision_log=out / "decision-logs",
                              bank_minutes=args.bank_minutes,
                              decks=[d.strip() for d in args.decks.split(",")] if args.decks else None)
    config_path = out / "runs" / f"{name}.config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config_doc, indent=1) + "\n", encoding="utf-8")
    config = runner.TournamentConfig.from_json(config_doc)

    stop = threading.Event()
    if not args.no_record:
        cold = args.cold or out / "engine-records" / "cold"
        path, digest = recording_settings(out, cold)
        os.environ[engine_records.CONFIG_ENV], os.environ[engine_records.HASH_ENV] = str(path), digest
        threading.Thread(target=collect_locally, args=(stop,), daemon=True).start()
    else:
        os.environ.pop(engine_records.CONFIG_ENV, None)
        os.environ.pop(engine_records.HASH_ENV, None)

    advisor = None
    if args.advisor:
        advisor = start_advisor(benchmark_dir=args.benchmark, local=local, name=args.advisor, run_dir=run_dir,
                                label=args.advisor_label or None)
        print(f"  advisor: {advisor.label} ({args.advisor}) reads your decisions; advised play\n", flush=True)
    games_total = 2 * config_doc["pairs_per_matchup"]
    # Both seats log to one directory as <game_id>.<seat>.jsonl, the layout the misplay review converter reads.
    shown = next(((bot.get("display") or {}).get("label") for bot in config_doc["bots"] if bot["name"] == args.opponent),
                 None) or args.opponent  # the page names the opponent by its board label
    hub = Hub(log_dir=out / "decision-logs", games_total=games_total, opponent=shown, banner=args.game_banner or None,
              label=f"{games_total} games vs {args.opponent}, {args.bank_minutes}-minute bank",
              record_root=None if args.no_record else out / "engine-records" / "hot",
              real_action_stops=args.client == "manabrew", advisor=advisor, full_priority=args.full_priority,
              auto_graveyard_order=args.auto_graveyard_order,
              client_autopass=args.full_priority and not args.keep_mana_autopass)
    server = make_server(hub, port=args.port)
    host, port = server.server_address[:2]
    os.environ[relay.URL_ENV] = f"http://{host}:{port}"
    os.environ[relay.TOKEN_ENV] = server.token
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://{host}:{port}/?t={server.token}"
    print(f"\n  Play here: {url}\n", flush=True)
    print(f"  run: {run_dir}\n  config: {config_path}\n", flush=True)
    if args.client == "manabrew":
        return play_picked_games(args, config_doc, hub, server, stop, out=out, name=name, shown=str(shown))
    if not args.no_browser:
        webbrowser.open(url)
    started = time.monotonic()
    try:
        summary = runner.run_tournament(config, run_secret=RunSecret.generate(), allocation=Allocation.unmeasured(1),
                                        on_game=page_closer(hub))
        print(f"tournament published: {summary.tournament_dir} status {summary.status}, "
              f"{summary.games_total} games, {round((time.monotonic() - started) / 60)} minutes", flush=True)
    finally:
        hub.close_advisor()
        stop.set()
        server.shutdown()
    return 0
