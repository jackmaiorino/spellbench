"""X4 soak: whole games on the XMage engine through P's host with its live validator (spec 11.2, 11.3).

Runs the conformance games' configuration (builtin ``first`` against ``uniform``, seat-swapped pairs over the
catalog decks, london mulligan where the engine supports it) for many games, sharded over engine processes. Each
shard keeps one engine process for its games (one game at a time, spec 2) and restarts it after any host halt
(spec 11.3). One JSON line per game goes to ``--out``; the summary goes to stdout.

    PYTHONPATH=<p2>/python python soak.py --games 200 --shards 8 --out games.jsonl -- <engine argv...>
    PYTHONPATH=<p2>/python python soak.py --replay 0 --run-secret HEX --out replay.jsonl -- <engine argv...>

``--replay N`` plays game N of the schedule twice in one engine process, then twice more in a second process, and
reports the four game digests (spec 11.8). An engine process refuses a reused ``game_id`` (spec 9.2), so each
repetition after the first in a process runs under a fresh ``game_id`` and its digest is chained with that field
put back to the scheduled id: equal digests then mean equal traffic in every other byte.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import multiprocessing
import statistics
import sys
import time
from collections import Counter
from typing import Any

from spellbench.arena.config import CONFIG_SCHEMA, DEFAULT_TIME_CONTROL, TournamentConfig
from spellbench.arena.drivers import BuiltinDriver
from spellbench.arena.schedule import EnginePin, game_setup, preflight, schedule
from spellbench.builtins import BUILTIN_VERSIONS
from spellbench import digests as _digests
from spellbench.host import game as _host_game
from spellbench.host.engine_process import EngineProcess
from spellbench.host.game import play_game
from spellbench.run_secret import RunSecret


def make_config(argv: list[str], fmt: str, decks: list[str], games: int,
                bots: tuple[str, ...] = ("first", "uniform")) -> TournamentConfig:
    pairs = math.ceil(math.ceil(games / 2) / len(decks)) * len(decks)
    bound_ms = 300_000
    return TournamentConfig.from_json({
        "schema": CONFIG_SCHEMA,
        "tournament_dir": "x4-soak",
        "format": fmt,
        "deck_pool": [{"catalog_id": deck} for deck in decks],
        "engine": {"command": list(argv)},
        "bots": [{"name": name, "version": BUILTIN_VERSIONS[name], "type": "builtin"} for name in bots],
        "pairs_per_matchup": pairs,
        "stats_seed": 0,
        "include_self_play": len(bots) == 1,
        "time_control": {**DEFAULT_TIME_CONTROL.to_json(), "startup_ms": bound_ms, "engine_step_ms": bound_ms},
        "bootstrap_replicates": 1000,
    })


def _open(config: TournamentConfig, pin: EnginePin) -> EngineProcess:
    engine = EngineProcess(list(config.engine_command), timeout_s=config.time_control.startup_ms / 1000)
    hello = engine.hello()
    pin.check(hello.engine)
    return engine


def _row(context, result, wall_s: float) -> dict[str, Any]:
    adjudication = result.adjudication or {}
    (_, first), (_, second) = context.seat_specs
    return {
        "game_index": context.game_index,
        "deck_p0": context.decks[0].catalog_id,
        "deck_p1": context.decks[1].catalog_id,
        "bot_p0": first.name,
        "bot_p1": second.name,
        "outcome": result.outcome,
        "classification": result.classification,
        "reason": result.reason,
        "host_halt": adjudication.get("kind") == "halt",
        "violation": result.violation,
        "step_count": result.step_count,
        "decision_count": result.decision_count,
        "decisions_checked": result.decisions_checked,
        "game_digest": result.game_digest,
        "wall_s": round(wall_s, 3),
        "detail": adjudication.get("detail"),
    }


class _RenamedDigest(_digests.GameDigest):
    """A game digest chained as if every message carried ``scheduled`` as its game_id."""

    scheduled = ""

    @classmethod
    def _as_scheduled(cls, message):
        if isinstance(message, dict) and "game_id" in message:
            message = dict(message, game_id=cls.scheduled)
        return message

    def __init__(self, reset_request):
        super().__init__(self._as_scheduled(dict(reset_request)))

    def _chain(self, message):
        super()._chain(self._as_scheduled(dict(message)))


def _worker(args: tuple) -> list[dict[str, Any]]:
    argv, fmt, decks, games, secret_hex, indexes, bots = args
    config = make_config(argv, fmt, decks, games, bots)
    secret = RunSecret.from_hex(secret_hex)
    pin = EnginePin()
    setup = preflight(config, secret, pin=pin)
    contexts = {c.game_index: c for c in schedule(config, secret)}
    rows = []
    engine = _open(config, pin)
    try:
        played: Counter[int] = Counter()
        for index in indexes:
            context = contexts[index]
            seats = {seat: BuiltinDriver(spec) for seat, spec in context.seat_specs}
            start = time.monotonic()
            game = game_setup(config, setup, context, secret)
            repeat = played[index]
            played[index] += 1
            if repeat:
                # a replay in the same process: a fresh game_id (spec 9.2), the digest chained under the scheduled one
                _RenamedDigest.scheduled = game.game_id
                game = dataclasses.replace(game, game_id=f"{game.game_id}r{repeat}")
                _host_game.GameDigest = _RenamedDigest
            try:
                result = play_game(game, engine=engine, seats=seats)
            finally:
                _host_game.GameDigest = _digests.GameDigest
                for driver in seats.values():
                    driver.close()
            row = _row(context, result, time.monotonic() - start)
            rows.append(row)
            print(json.dumps(row, sort_keys=True), flush=True, file=sys.stderr)
            if row["host_halt"]:
                engine.close()                 # spec 11.3: restart the engine before any further game
                engine = _open(config, pin)
    finally:
        engine.close()
    return rows


def summarize(rows: list[dict[str, Any]], wall_s: float, shards: int) -> dict[str, Any]:
    games = len(rows)
    steps = [r["step_count"] for r in rows]
    groups = [r["decision_count"] for r in rows]
    walls = [r["wall_s"] for r in rows]
    halted = Counter(r["reason"] for r in rows if r["classification"] == "halted")
    return {
        "games": games,
        "classification": dict(Counter(r["classification"] for r in rows)),
        "outcome": dict(Counter(r["outcome"] for r in rows)),
        "winner_bot": dict(Counter(
            (r["bot_p0"] if r["outcome"] == "p0_win" else r["bot_p1"]) if r["outcome"] in ("p0_win", "p1_win")
            else r["outcome"] for r in rows)),
        "natural_reasons": dict(Counter(r["reason"] for r in rows if r["classification"] == "natural")),
        "halted_by_reason": dict(halted),
        "halted_rate": round(sum(halted.values()) / games, 4) if games else 0,
        "host_halts": sum(1 for r in rows if r["host_halt"]),
        "violations": [r["violation"] for r in rows if r["violation"]],
        "decisions_checked": sum(r["decisions_checked"] for r in rows),
        "steps_per_game": {"mean": round(statistics.mean(steps), 1), "median": statistics.median(steps),
                           "min": min(steps), "max": max(steps)} if steps else None,
        "groups_per_game": {"mean": round(statistics.mean(groups), 1), "median": statistics.median(groups)}
        if groups else None,
        "wall_s_per_game": {"mean": round(statistics.mean(walls), 2), "median": statistics.median(walls),
                            "max": max(walls)} if walls else None,
        "total_wall_s": round(wall_s, 1),
        "shards": shards,
        "games_per_minute": round(games / wall_s * 60, 1) if wall_s else None,
    }


def replay_same_process(argv: list[str], fmt: str, decks: list[str], secret_hex: str, index: int,
                        bots: tuple[str, ...]) -> list[dict]:
    return _worker((argv, fmt, decks, max(index + 1, 2), secret_hex, [index, index], bots))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--format", default="standard-2022-25-bo1")
    parser.add_argument("--deck", action="append", default=None)
    parser.add_argument("--games", type=int, default=200)
    parser.add_argument("--shards", type=int, default=8)
    parser.add_argument("--run-secret", default=None)
    parser.add_argument("--replay", type=int, default=None)
    parser.add_argument("--bots", default="first,uniform", help="builtin bots; one bot plays itself")
    parser.add_argument("--out", required=True)
    parser.add_argument("engine", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    argv = args.engine[1:] if args.engine and args.engine[0] == "--" else args.engine
    decks = args.deck or ["Standard16-RG", "Standard16-UB"]
    secret_hex = args.run_secret or RunSecret.generate().hex()
    bots = tuple(args.bots.split(","))
    start = time.monotonic()
    if args.replay is not None:
        same = replay_same_process(argv, args.format, decks, secret_hex, args.replay, bots)
        other = replay_same_process(argv, args.format, decks, secret_hex, args.replay, bots)
        rows = [dict(r, process=0, run=i) for i, r in enumerate(same)] + \
               [dict(r, process=1, run=i) for i, r in enumerate(other)]
        with open(args.out, "w", encoding="utf-8") as out:
            for r in rows:
                out.write(json.dumps(r, sort_keys=True) + "\n")
        digests = [r["game_digest"] for r in rows]
        print(json.dumps({"run_secret": secret_hex, "game_index": args.replay, "digests": digests,
                          "identical": len(set(digests)) == 1,
                          "step_counts": [r["step_count"] for r in rows]}, indent=1))
        return 0 if len(set(digests)) == 1 else 1
    indexes = list(range(args.games))
    shards = [indexes[k::args.shards] for k in range(args.shards) if indexes[k::args.shards]]
    jobs = [(argv, args.format, decks, args.games, secret_hex, s, bots) for s in shards]
    with multiprocessing.get_context("spawn").Pool(len(jobs)) as pool:
        results = pool.map(_worker, jobs)
    rows = sorted((r for rs in results for r in rs), key=lambda r: r["game_index"])
    wall = time.monotonic() - start
    with open(args.out, "w", encoding="utf-8") as out:
        for r in rows:
            out.write(json.dumps(r, sort_keys=True) + "\n")
    summary = summarize(rows, wall, len(jobs))
    summary["run_secret"] = secret_hex
    summary["bots"] = list(bots)
    print(json.dumps(summary, indent=1, sort_keys=True))
    return 0 if summary["host_halts"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
