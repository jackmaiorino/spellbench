"""Kit games through P's host (spec 11.2, 11.3): a kit entry, as a subprocess v2 agent, against a builtin bot on the
XMage engine, every decision checked by the live validator. Modeled on engines/xmage/tests/x4/soak.py.

    PYTHONPATH=<p2>/python python play.py --games 4 --out games.jsonl --kit-entry h1 \
        --kit-cmd '["bash", "kit/scripts/agent.sh", ...]' --opponent heuristic -- <engine argv...>

Seat-swapped pairs over the deck list; one engine process per shard, one fresh agent process per game (spec 11.7).
One JSON line per game goes to --out; the summary to stdout.
"""

from __future__ import annotations

import argparse
import json
import math
import multiprocessing
import statistics
import sys
import time
from collections import Counter
from typing import Any

from spellbench.arena.config import CONFIG_SCHEMA, TournamentConfig
from spellbench.arena.drivers import BuiltinDriver, make_driver
from spellbench.arena.schedule import EnginePin, game_setup, preflight, schedule
from spellbench.builtins import BUILTIN_VERSIONS
from spellbench.host.engine_process import EngineProcess
from spellbench.host.game import play_game
from spellbench.run_secret import RunSecret

KIT_TIME_CONTROL = {"startup_ms": 300_000, "game_start_ms": 300_000, "bank_ms": 3_600_000, "increment_ms": 2_000,
                    "max_decision_ms": 120_000, "engine_step_ms": 300_000}


def read_dck(path: str) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("SB") or line.startswith("NAME") or line.startswith("LAYOUT") or line.startswith("#"):
            continue
        count, rest = line.split(" ", 1)
        if rest.startswith("["):
            rest = rest.split("]", 1)[1].strip()
        counts[rest] = counts.get(rest, 0) + int(count)
    name = path.replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return {"name": name, "decklist": [{"name": n, "count": c} for n, c in sorted(counts.items())]}


def make_config(engine_argv, fmt, decks, games, kit_name, kit_version, kit_cmd, opponent, time_control):
    pairs = max(1, math.ceil(math.ceil(games / 2) / len(decks)) * len(decks))
    return TournamentConfig.from_json({
        "schema": CONFIG_SCHEMA,
        "tournament_dir": "kit-play",
        "format": fmt,
        "deck_pool": [d if isinstance(d, dict) else {"catalog_id": d} for d in decks],
        "engine": {"command": list(engine_argv)},
        "bots": [
            {"name": kit_name, "version": kit_version, "type": "subprocess", "command": list(kit_cmd)},
            {"name": opponent, "version": BUILTIN_VERSIONS[opponent], "type": "builtin"},
        ],
        "pairs_per_matchup": pairs,
        "stats_seed": 0,
        "include_self_play": False,
        "time_control": time_control,
        "bootstrap_replicates": 1000,
    })


def _row(context, result, wall_s):
    adjudication = result.adjudication or {}
    (_, first), (_, second) = context.seat_specs
    return {
        "game_index": context.game_index,
        "deck_p0": context.decks[0].catalog_id or context.decks[0].name,
        "deck_p1": context.decks[1].catalog_id or context.decks[1].name,
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


def _worker(args):
    engine_argv, fmt, decks, games, secret_hex, indexes, kit_name, kit_version, kit_cmd, opponent, tc = args
    config = make_config(engine_argv, fmt, decks, games, kit_name, kit_version, kit_cmd, opponent, tc)
    secret = RunSecret.from_hex(secret_hex)
    pin = EnginePin()
    setup = preflight(config, secret, pin=pin)
    contexts = {c.game_index: c for c in schedule(config, secret)}
    rows = []
    engine = EngineProcess(list(config.engine_command), timeout_s=config.time_control.startup_ms / 1000)
    pin.check(engine.hello().engine)
    try:
        for index in indexes:
            context = contexts[index]
            seats = {seat: make_driver(spec, config.time_control) for seat, spec in context.seat_specs}
            start = time.monotonic()
            game = game_setup(config, setup, context, secret)
            try:
                result = play_game(game, engine=engine, seats=seats)
            finally:
                for driver in seats.values():
                    driver.close()
            row = _row(context, result, time.monotonic() - start)
            rows.append(row)
            print(json.dumps(row, sort_keys=True), flush=True, file=sys.stderr)
            if row["host_halt"]:
                engine.close()
                engine = EngineProcess(list(config.engine_command), timeout_s=config.time_control.startup_ms / 1000)
                pin.check(engine.hello().engine)
    finally:
        engine.close()
    return rows


def summarize(rows, wall_s, kit_name):
    games = len(rows)
    walls = [r["wall_s"] for r in rows]
    kit_wins = sum(1 for r in rows if (r["outcome"] == "p0_win" and r["bot_p0"] == kit_name)
                   or (r["outcome"] == "p1_win" and r["bot_p1"] == kit_name))
    return {
        "games": games,
        "classification": dict(Counter(r["classification"] for r in rows)),
        "outcome_reasons": dict(Counter(r["reason"] for r in rows)),
        "kit_wins": kit_wins,
        "violations": [r["violation"] for r in rows if r["violation"]],
        "host_halts": sum(1 for r in rows if r["host_halt"]),
        "forfeits": [r["reason"] for r in rows if r["classification"] == "forfeit"],
        "decisions_checked": sum(r["decisions_checked"] for r in rows),
        "steps_per_game": {"mean": round(statistics.mean([r["step_count"] for r in rows]), 1)} if rows else None,
        "wall_s_per_game": {"mean": round(statistics.mean(walls), 2), "max": max(walls)} if walls else None,
        "total_wall_s": round(wall_s, 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--games", type=int, default=2)
    parser.add_argument("--shards", type=int, default=1)
    parser.add_argument("--format", default="standard-2022-25-bo1")
    parser.add_argument("--deck", action="append", default=None)
    parser.add_argument("--dck", action="append", default=None)
    parser.add_argument("--run-secret", default=None)
    parser.add_argument("--out", required=True)
    parser.add_argument("--kit-name", required=True)
    parser.add_argument("--kit-version", default="0.1.0")
    parser.add_argument("--kit-cmd", required=True, help="JSON list: the agent command")
    parser.add_argument("--opponent", default="heuristic")
    parser.add_argument("--index", type=int, action="append", default=None, help="play only these schedule indexes")
    parser.add_argument("engine", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    engine_argv = args.engine[1:] if args.engine and args.engine[0] == "--" else args.engine
    decks: list = []
    for d in args.deck or []:
        decks.append(d)
    for p in args.dck or []:
        decks.append(read_dck(p))
    if not decks:
        decks = ["Standard16-RG", "Standard16-UB"]
    import secrets
    secret_hex = args.run_secret or secrets.token_hex(32)
    kit_cmd = json.loads(args.kit_cmd)
    indexes = args.index if args.index else list(range(args.games))
    shards = max(1, min(args.shards, len(indexes)))
    chunks = [indexes[i::shards] for i in range(shards)]
    start = time.monotonic()
    jobs = [(engine_argv, args.format, decks, args.games, secret_hex, chunk, args.kit_name, args.kit_version, kit_cmd,
             args.opponent, KIT_TIME_CONTROL) for chunk in chunks]
    if shards == 1:
        results = [_worker(jobs[0])]
    else:
        with multiprocessing.Pool(shards) as pool:
            results = pool.map(_worker, jobs)
    rows = sorted((r for rs in results for r in rs), key=lambda r: r["game_index"])
    with open(args.out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True) + "\n")
    summary = summarize(rows, time.monotonic() - start, args.kit_name)
    summary["run_secret"] = secret_hex
    print(json.dumps(summary, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
