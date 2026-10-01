"""X5: the live-validated conformance run of the XMage engine on both benchmark pools, through P's host.

The schedule is six P tournament configs (``spellbench-tournament-config/v2``): for each pool (Standard 2022-25,
16 decks, ``standard-2022-25-bo1``; FDN, 16 decks, ``fdn-limited-bo1``) the matchups ``uniform`` against itself,
``heuristic`` against ``uniform`` and ``first`` against ``uniform``, as seat-swapped pairs over the pool's decks
(mirrors: pair p plays deck p mod 16 in both seats). P's ``arena.schedule`` builds each config's games, ids,
secrets and seeds from the config's run secret (spec 11.6); each config's secret is derived from one master secret
recorded in the plan (``plan.json``), so every machine computes the same games. The global order interleaves the
six configs (``qualification.sample_order``), and a machine's share is a proportional, interleaved part of it.

Every game runs through ``host.game.play_game`` (routing, the live validator V1 to V10, clocks, caps,
adjudication), and its ledger row is P's own (``runner._outcome``). The only difference from ``runner.play_one``
is the engine lifetime: one engine process per worker plays its games in sequence (one game at a time, spec 2)
and is restarted after any host halt (spec 11.3), instead of a JVM start and a 259 MB card database copy per
game. The launch guard is P's ``qualification.plan_allocation`` (COMPUTE-POLICY.md), fed by this module's
``play``.

    python x5run.py plan --out plan.json                      # once: master secret and workloads
    python x5run.py qualify --plan plan.json --machine NAME --cap N --placement TEXT --out DIR -- ENGINE...
    python x5run.py run --plan plan.json --machine NAME --workers N --fraction F --part A|B --out DIR -- ENGINE...
    python x5run.py summarize --plan plan.json ROWS.jsonl... --stats DIR... --out summary.json

PYTHONPATH must hold P's ``python`` directory (protocol-v2 at the pinned commit).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import multiprocessing
import multiprocessing.util
import os
import secrets
import statistics
import sys
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from spellbench.arena import runner
from spellbench.arena.allocation import PlayedGame
from spellbench.arena.config import CONFIG_SCHEMA, DEFAULT_TIME_CONTROL, TournamentConfig
from spellbench.arena.drivers import make_driver
from spellbench.arena.qualification import plan_allocation, sample_order, workload_id
from spellbench.arena.schedule import EnginePin, game_setup, preflight, schedule
from spellbench.builtins import BUILTIN_VERSIONS
from spellbench.host.engine_process import EngineProcess
from spellbench.host.game import play_game
from spellbench.run_secret import RunSecret
from spellbench.wire import canonical_json_dumps

HERE = Path(__file__).resolve().parent
CATALOG = HERE.parents[1] / "overlay/src/main/resources/mage/player/spellbench/catalog.json"
POOLS = {"standard": "standard-2022-25-bo1", "fdn": "fdn-limited-bo1"}
MATCHUPS = {"uu": ("uniform",), "hu": ("heuristic", "uniform"), "fu": ("first", "uniform")}
# Pairs per matchup per pool (multiples of 16, so every deck gets the same share): 5,056 games per pool.
PAIRS = {"uu": 1216, "hu": 1120, "fu": 192}
BOUND_MS = 300_000


# ---------------------------------------------------------------------------
# The schedule
# ---------------------------------------------------------------------------


def _decks(fmt: str) -> list[str]:
    return [d["catalog_id"] for d in json.loads(CATALOG.read_text(encoding="utf-8")) if fmt in d["formats"]]


def config_json(pool: str, matchup: str, pairs: int, engine: list[str]) -> dict[str, Any]:
    bots = MATCHUPS[matchup]
    return {
        "schema": CONFIG_SCHEMA,
        "tournament_dir": f"x5-{pool}-{matchup}",
        "format": POOLS[pool],
        "deck_pool": [{"catalog_id": deck} for deck in _decks(POOLS[pool])],
        "engine": {"command": list(engine)},
        "bots": [{"name": name, "version": BUILTIN_VERSIONS[name], "type": "builtin"} for name in bots],
        "pairs_per_matchup": pairs,
        "stats_seed": 0,
        "include_self_play": len(bots) == 1,
        "time_control": {**DEFAULT_TIME_CONTROL.to_json(), "startup_ms": BOUND_MS, "engine_step_ms": BOUND_MS},
        "bootstrap_replicates": 1000,
    }


class Schedule:
    """The six configs, their contexts and the global interleaved order."""

    def __init__(self, plan: dict[str, Any], engine: list[str]) -> None:
        self.plan = plan
        self.workloads: list[dict[str, Any]] = []
        groups: list[list[int]] = []
        self.games: list[tuple[int, int]] = []  # global id -> (workload, game_index)
        for w, item in enumerate(plan["workloads"]):
            config = TournamentConfig.from_json(config_json(item["pool"], item["matchup"], item["pairs"], engine))
            secret = RunSecret.from_hex(item["run_secret"])
            contexts = schedule(config, secret)
            self.workloads.append({**item, "config": config, "secret": secret, "contexts": contexts})
            group = []
            for context in contexts:
                group.append(len(self.games))
                self.games.append((w, context.game_index))
            groups.append(group)
        self.order = sample_order(groups)  # positions in global order -> global ids

    def share(self, fraction: float, part: str) -> list[int]:
        """Global ids of one machine's share: position i of the order goes to part A when floor((i+1)f) > floor(if)."""
        ids = []
        for i, gid in enumerate(self.order):
            a = math.floor((i + 1) * fraction) > math.floor(i * fraction)
            if a == (part == "A"):
                ids.append(gid)
        return ids


def make_plan(out: Path) -> None:
    master = secrets.token_hex(32)
    workloads = []
    for pool in POOLS:
        for matchup in MATCHUPS:
            label = f"{pool}-{matchup}"
            derived = hashlib.sha256(f"spellbench/x5/{label}:".encode() + bytes.fromhex(master)).hexdigest()
            workloads.append({"label": label, "pool": pool, "matchup": matchup, "pairs": PAIRS[matchup],
                              "games": 2 * PAIRS[matchup],
                              "run_secret": derived})
    plan = {"schema": "spellbench-x5-plan/v1", "master_secret": master, "workloads": workloads,
            "games_total": sum(w["games"] for w in workloads)}
    out.write_text(json.dumps(plan, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"plan: {plan['games_total']} games in {len(workloads)} workloads -> {out}")


# ---------------------------------------------------------------------------
# Workers: one engine process each, games in sequence
# ---------------------------------------------------------------------------

_W: dict[str, Any] = {}


def _setups(sched: Schedule) -> dict[str, Any]:
    """P's preflight once per pool (the setup depends on the decks and rules, not the bots), pools in parallel.

    Diagnostics only: ``X5_SETUP_CACHE`` names a pickle that keeps the setups between invocations."""
    cache = os.environ.get("X5_SETUP_CACHE")
    if cache and os.path.exists(cache):
        import pickle
        with open(cache, "rb") as f:
            return pickle.load(f)
    setups: dict[str, Any] = {}
    errors: list[BaseException] = []
    pin = EnginePin()

    def one(item: dict[str, Any]) -> None:
        try:
            setups[item["pool"]] = preflight(item["config"], item["secret"], pin=pin)
        except BaseException as exc:  # noqa: BLE001 (re-raised below)
            errors.append(exc)

    firsts = {}
    for item in sched.workloads:
        firsts.setdefault(item["pool"], item)
    threads = [threading.Thread(target=one, args=(item,)) for item in firsts.values()]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if errors:
        raise errors[0]
    if cache:
        import pickle
        with open(cache, "wb") as f:
            pickle.dump(setups, f)
    return setups


def _init(plan: dict[str, Any], engine: list[str], setups: dict[str, Any], stats_dir: str | None,
          prewarm: bool = False) -> None:
    if stats_dir:
        os.environ["SPELLBENCH_XMAGE_STATS"] = stats_dir
    sched = Schedule(plan, engine)
    _W.update(sched=sched, setups=setups, engine=None, pin=EnginePin(), argv=engine)
    # close this worker's engine when the pool lets the worker exit (pool.close then join, never terminate)
    multiprocessing.util.Finalize(None, _close, exitpriority=10)
    for item in sched.workloads:
        executed = runner.executed_config(item["config"], lambda text: text)
        item["entries"] = {e.name: e for e in runner.registry_entries(item["config"], executed)}
    if prewarm:  # the engine starts before the worker takes its first game (startup is timed separately)
        started = time.monotonic()
        _engine()
        _W["startup_s"] = time.monotonic() - started


def _engine() -> EngineProcess:
    if _W["engine"] is None:
        config = _W["sched"].workloads[0]["config"]
        engine = EngineProcess(list(config.engine_command), timeout_s=BOUND_MS / 1000)
        hello = engine.hello()
        _W["pin"].check(hello.engine)
        _W.update(engine=engine, identity=hello.engine)
    return _W["engine"]


def play_global(gid: int) -> dict[str, Any]:
    sched: Schedule = _W["sched"]
    w, index = sched.games[gid]
    item = sched.workloads[w]
    config, secret = item["config"], item["secret"]
    context = item["contexts"][index]
    setup = _W["setups"][item["pool"]]
    start = time.monotonic()
    engine = _engine()
    seats = {seat: make_driver(spec, config.time_control) for seat, spec in context.seat_specs}
    try:
        result = play_game(game_setup(config, setup, context, secret), engine=engine, seats=seats)
    finally:
        for driver in seats.values():
            driver.close()
    outcome = runner._outcome(config, setup, context, item["entries"], result, _W["identity"])
    row = outcome.row.to_json()
    data = canonical_json_dumps(row)
    host_halt = (result.adjudication or {}).get("kind") == "halt"
    if host_halt:  # spec 11.3: a fresh engine before any further game
        engine.close()
        _W["engine"] = None
    return {
        "gid": gid,
        "workload": item["label"],
        "row": row,
        "row_digest": "sha256:" + hashlib.sha256(data).hexdigest(),
        "row_bytes": len(data) + 1,
        "seconds": time.monotonic() - start,
        "violation": outcome.violation,
        "host_halt": host_halt,
        "diagnostics": list(result.diagnostics)[:20] if result.classification != "natural" else [],
        "pid": os.getpid(),
        "engine_startup_s": _W.pop("startup_s", None),
    }


def _close() -> None:
    if _W.get("engine") is not None:
        _W["engine"].close()
        _W["engine"] = None


def run_games(plan: dict[str, Any], engine: list[str], setups: dict[str, Any], gids: list[int], workers: int,
              stats_dir: str | None, on_row=None, prewarm: bool = False) -> tuple[float, list[dict[str, Any]]]:
    """Play ``gids`` with ``workers`` worker processes (fresh ones); rows in the order given."""
    ctx = multiprocessing.get_context("spawn")
    start = time.monotonic()
    rows: dict[int, dict[str, Any]] = {}
    pool = ctx.Pool(workers, initializer=_init, initargs=(plan, engine, setups, stats_dir, prewarm))
    try:
        for row in pool.imap_unordered(play_global, gids, chunksize=1):
            rows[row["gid"]] = row
            if on_row is not None:
                on_row(row)
        pool.close()  # workers exit normally, and each closes its engine (_init's finalizer)
        pool.join()
    except BaseException:
        pool.terminate()
        raise
    return time.monotonic() - start, [rows[g] for g in gids]


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def _engine_argv(argv: list[str]) -> tuple[list[str], list[str]]:
    split = argv.index("--")
    return argv[:split], argv[split + 1:]


def cmd_qualify(args: argparse.Namespace, engine: list[str]) -> int:
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    sched = Schedule(plan, engine)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    setups = _setups(sched)
    stats_dir = str(out / "stats-qualify")
    os.makedirs(stats_dir, exist_ok=True)
    trials_log = (out / "qualify-games.jsonl").open("a", encoding="utf-8")

    def play(workers: int, positions: tuple[int, ...]) -> tuple[float, list[PlayedGame]]:
        gids = [sched.order[p] for p in positions]
        print(f"[{time.strftime('%H:%M:%S')}] rung: {workers} workers, {len(gids)} games", flush=True)
        wall, rows = run_games(plan, engine, setups, gids, workers, stats_dir, prewarm=True)
        for p, row in zip(positions, rows):
            trials_log.write(json.dumps({"workers": workers, "position": p, **row}, sort_keys=True) + "\n")
        trials_log.flush()
        print(f"[{time.strftime('%H:%M:%S')}]   wall {wall:.1f} s, games/min {len(gids) / wall * 60:.1f}", flush=True)
        return wall, [PlayedGame(index=p, seconds=row["seconds"], digest=row["row_digest"], row_bytes=row["row_bytes"])
                      for p, row in zip(positions, rows)]

    workload = workload_id({"x5_plan": hashlib.sha256(Path(args.plan).read_bytes()).hexdigest(),
                            "engine": args.build_digest, "p2": args.p2_commit})
    allocation = plan_allocation(
        games_total=plan["games_total"], cap=args.cap, per_game_cores=1, play=play, placement=args.placement,
        sample=list(range(plan["games_total"])), workload=workload, volumes={"run_dir": out, "pin_root": out},
    )
    (out / "allocation.json").write_text(json.dumps(allocation.to_json(), indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"kind": allocation.kind, "workers": allocation.workers,
                      "trials": [t.to_json() for t in allocation.trials] if allocation.trials else None,
                      "outputs_identical": allocation.outputs_identical}, indent=1))
    return 0


def cmd_run(args: argparse.Namespace, engine: list[str]) -> int:
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    sched = Schedule(plan, engine)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows_path = out / f"rows-{args.machine}.jsonl"
    done = set()
    if rows_path.exists():
        for line in rows_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line)["gid"])
    gids = [g for g in sched.share(args.fraction, args.part) if g not in done]
    if args.gids_file:  # a chosen subset (verification checks), in the file's order
        wanted = [int(x) for x in Path(args.gids_file).read_text(encoding="utf-8").split()]
        gids = [g for g in wanted if g not in done]
    if args.limit:
        gids = gids[: args.limit]
    print(f"[{time.strftime('%H:%M:%S')}] {args.machine}: {len(gids)} games to play ({len(done)} already), "
          f"{args.workers} workers", flush=True)
    setups = _setups(sched)
    stats_dir = str(out / f"stats-{args.machine}")
    os.makedirs(stats_dir, exist_ok=True)
    progress = {"n": 0, "violations": 0, "halts": 0, "start": time.monotonic()}
    status = out / f"progress-{args.machine}.json"
    with rows_path.open("a", encoding="utf-8") as sink:
        def on_row(row: dict[str, Any]) -> None:
            sink.write(json.dumps({"machine": args.machine, **row}, sort_keys=True) + "\n")
            sink.flush()
            progress["n"] += 1
            progress["violations"] += row["violation"] is not None
            progress["halts"] += row["row"]["classification"] == "halted"
            if progress["n"] % 25 == 0 or progress["n"] == len(gids):
                elapsed = time.monotonic() - progress["start"]
                rate = progress["n"] / elapsed * 60
                status.write_text(json.dumps({
                    "time": time.strftime("%Y-%m-%d %H:%M:%S"), "played": progress["n"], "of": len(gids),
                    "games_per_minute": round(rate, 1), "violations": progress["violations"],
                    "halted": progress["halts"],
                    "eta_minutes": round((len(gids) - progress["n"]) / rate, 1) if rate else None}) + "\n")
        wall, _ = run_games(plan, engine, setups, gids, args.workers, stats_dir, on_row=on_row)
    print(f"[{time.strftime('%H:%M:%S')}] done: {len(gids)} games in {wall:.0f} s "
          f"({len(gids) / wall * 60 if wall else 0:.1f} games/min), violations {progress['violations']}", flush=True)
    return 0


def _dist(values: list[float]) -> dict[str, Any] | None:
    if not values:
        return None
    return {"mean": round(statistics.mean(values), 1), "median": statistics.median(values), "min": min(values),
            "max": max(values)}


def cmd_summarize(args: argparse.Namespace) -> int:
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    rows: dict[int, dict[str, Any]] = {}
    duplicates = mismatched = 0
    for path in args.rows:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r["gid"] in rows:
                duplicates += 1
                if rows[r["gid"]]["row_digest"] != r["row_digest"]:
                    mismatched += 1
                continue
            rows[r["gid"]] = r
    stats_by_game: dict[str, dict[str, int]] = {}
    for d in args.stats or []:
        for p in Path(d).glob("stats-*.jsonl"):
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    s = json.loads(line)
                    stats_by_game[s["game_id"]] = s["stats"]
    by_pool: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_workload: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows.values():
        by_pool[r["workload"].split("-")[0]].append(r)
        by_workload[r["workload"]].append(r)

    def block(items: list[dict[str, Any]]) -> dict[str, Any]:
        games = len(items)
        cls = Counter(r["row"]["classification"] for r in items)
        reasons = Counter(f"{r['row']['classification']}:{r['row']['reason']}" for r in items)
        winners = Counter()
        for r in items:
            row = r["row"]
            if row["winner"] is None:
                winners[row["outcome"]] += 1
            else:
                seat = next(s for s in row["seats"] if s["seat"] == row["winner"])
                winners[f"{seat['name']}:{row['winner']}"] += 1
        counters: Counter[str] = Counter()
        games_with: Counter[str] = Counter()
        joined = 0
        for r in items:
            s = stats_by_game.get(r["row"]["game_id"])
            if s is None:
                continue
            joined += 1
            for k, v in s.items():
                counters[k] += v
                games_with[k] += 1
        attribution: Counter[str] = Counter()
        for r in items:
            row = r["row"]
            if row["classification"] in ("halted", "truncated"):
                last = row.get("last_selection")
                name = None
                if last:
                    name = next((s["name"] for s in row["seats"] if s["seat"] == last["seat"]), None)
                attribution[f"{row['reason']} after {name}:{last['seat'] if last else None}"] += 1
        return {
            "games": games,
            "classification": dict(cls),
            "halt_truncation_attribution": dict(sorted(attribution.items())),
            "rates": {k: round(v / games, 5) for k, v in cls.items()} if games else {},
            "reasons": dict(sorted(reasons.items())),
            "winners": dict(sorted(winners.items())),
            "violations": [r["violation"] for r in items if r["violation"]],
            "host_halts": sum(r["host_halt"] for r in items),
            "decisions_checked": sum(r["row"]["decisions_checked"] for r in items),
            "steps_per_game": _dist([r["row"]["step_count"] for r in items]),
            "groups_per_game": _dist([r["row"]["decision_count"] for r in items]),
            "seconds_per_game": _dist([round(r["seconds"], 2) for r in items]),
            "engine_counters_games": joined,
            "posed_kinds": {k: {"total": counters[k], "games": games_with[k]} for k in sorted(counters)
                            if k.startswith("posed:")},
            "other_counters": {k: {"total": counters[k], "games": games_with[k]} for k in sorted(counters)
                               if not k.startswith("posed:")},
            "non_natural": [{"gid": r["gid"], "workload": r["workload"], "game_index": r["row"]["game_index"],
                             "reason": r["row"]["reason"], "adjudication": r["row"]["adjudication"],
                             "diagnostics": r["diagnostics"][:5]}
                            for r in items if r["row"]["classification"] != "natural"],
        }

    summary = {
        "plan_games_total": plan["games_total"],
        "games_recorded": len(rows),
        "duplicate_rows": duplicates,
        "duplicate_rows_with_different_digest": mismatched,
        "machines": dict(Counter(r["machine"] for r in rows.values())),
        "violations_total": sum(1 for r in rows.values() if r["violation"]),
        "pools": {pool: block(items) for pool, items in sorted(by_pool.items())},
        "workloads": {w: {k: v for k, v in block(items).items() if k not in ("posed_kinds", "other_counters",
                                                                              "non_natural")}
                      for w, items in sorted(by_workload.items())},
    }
    Path(args.out).write_text(json.dumps(summary, indent=1, sort_keys=False) + "\n", encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("games_recorded", "machines", "violations_total",
                                               "duplicate_rows_with_different_digest")}))
    for pool, b in summary["pools"].items():
        print(pool, b["games"], b["classification"], "violations", len(b["violations"]))
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    """Game digests of the games two row files share: equal for every game, or the run is not deterministic."""
    def load(path: str) -> dict[int, dict[str, Any]]:
        out = {}
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                out[r["gid"]] = r
        return out

    a, b = load(args.a), load(args.b)
    shared = sorted(set(a) & set(b))
    differ = [g for g in shared if a[g]["row"]["game_digest"] != b[g]["row"]["game_digest"]]
    report = {"a": args.a, "b": args.b, "shared": len(shared), "equal": len(shared) - len(differ),
              "differ": [{"gid": g, "workload": a[g]["workload"], "a": a[g]["row"]["reason"],
                          "b": b[g]["row"]["reason"]} for g in differ[:50]],
              "verdict": "PASS" if shared and not differ else "FAIL"}
    Path(args.out).write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: report[k] for k in ("shared", "equal", "verdict")}))
    return 0 if report["verdict"] == "PASS" else 1


def main(argv: list[str]) -> int:
    rest, engine = (argv, []) if "--" not in argv else _engine_argv(argv)
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--out", required=True)
    q = sub.add_parser("qualify")
    q.add_argument("--plan", required=True)
    q.add_argument("--machine", required=True)
    q.add_argument("--cap", type=int, required=True)
    q.add_argument("--placement", required=True)
    q.add_argument("--build-digest", required=True)
    q.add_argument("--p2-commit", required=True)
    q.add_argument("--out", required=True)
    r = sub.add_parser("run")
    r.add_argument("--plan", required=True)
    r.add_argument("--machine", required=True)
    r.add_argument("--workers", type=int, required=True)
    r.add_argument("--fraction", type=float, required=True)
    r.add_argument("--part", choices=("A", "B"), required=True)
    r.add_argument("--limit", type=int, default=0)
    r.add_argument("--gids-file", default=None, help="play only these global ids (whitespace separated)")
    r.add_argument("--out", required=True)
    s = sub.add_parser("summarize")
    s.add_argument("--plan", required=True)
    s.add_argument("rows", nargs="+")
    s.add_argument("--stats", action="append")
    s.add_argument("--out", required=True)
    c = sub.add_parser("compare")
    c.add_argument("a")
    c.add_argument("b")
    c.add_argument("--out", required=True)
    args = parser.parse_args(rest)
    if args.command == "plan":
        make_plan(Path(args.out))
        return 0
    if args.command == "qualify":
        return cmd_qualify(args, engine)
    if args.command == "run":
        return cmd_run(args, engine)
    if args.command == "compare":
        return cmd_compare(args)
    return cmd_summarize(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
