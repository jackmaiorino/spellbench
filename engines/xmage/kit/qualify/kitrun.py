"""A1 change 8: qualification and soak of the frozen kit entries on ``fdn-mirror-v0``'s pool, through P's host.

The schedule (``plan``) is one P tournament config (``spellbench-tournament-config/v2``) per workload: for each
admitted entry, the entry against P's ``heuristic`` and against ``uniform`` (seat-swapped pairs over the sixteen FDN
decks, mirrors: pair p plays deck p mod 16 in both seats), plus the declared cross-entry games between entries. The
workloads' run secrets derive from one master secret recorded in the plan, so every machine computes the same games;
the global order interleaves the workloads (P's ``qualification.sample_order``).

Every game runs through ``host.game.play_game`` (routing, the live validator, clocks, caps, adjudication) and its
ledger row is P's own (``runner._outcome``). Each kit seat is a fresh agent process per game (P's subprocess
driver, spec 11.7): a front and its runner in a private temporary directory with its own card database copy, removed
when the agent exits; the run checks that none survives (per-game isolation). Engine processes live one per worker,
restarted after a host halt (as X5's runner).

Launch guard (COMPUTE-POLICY.md; the third review's change 8 criteria):

- ``qualify`` runs P's ``qualification.plan_allocation`` (the scaling comparison on identical representative games,
  the disk reserve, the placement record) and writes ``QUALIFICATION.json``: the allocation, the workload identity
  (plan, engine build, kit jars, entry identities, clock profile, P commit), the matched-digest result, and the
  measured decision tails, combat costs, bank use, cap firings and restarts per rung.
- ``run`` refuses to start unless ``QUALIFICATION.json`` exists, names this workload identity and this host, and,
  for a substantial run, found identical outputs across worker counts; it plays with the qualified worker count,
  checks the reserve again before the first game, and never takes a worker count from the command line.
- ``replay`` is R-1: a fixed 20-game sample replayed serially, digests compared with the run's.
- ``summarize`` applies the pass criteria and writes ``SOAK-SUMMARY.json``.

    python kitrun.py plan --entry h1 --entry h2 --kit KIT --clock kit --out plan.json
    python kitrun.py qualify --plan plan.json --kit KIT --engine-build ENGINE --db DB --cap N --placement TEXT \\
        --p2-commit SHA --out DIR -- ENGINE_ARGV...
    python kitrun.py run --plan plan.json --kit KIT --engine-build ENGINE --db DB --qualification DIR/QUALIFICATION.json \\
        --machine NAME --fraction F --part A|B --p2-commit SHA --out DIR -- ENGINE_ARGV...
    python kitrun.py replay --plan plan.json ... --rows DIR/rows-NAME.jsonl --out DIR -- ENGINE_ARGV...
    python kitrun.py summarize --plan plan.json --rows ROWS.jsonl... --kitlogs DIR... --out SOAK-SUMMARY.json

PYTHONPATH must hold P's ``python`` directory (protocol-v2 at the pinned commit); KIT is ``kit/build.sh``'s output.
Nothing here starts on import.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import multiprocessing
import multiprocessing.util
import os
import platform
import secrets
import shutil
import statistics
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
KIT_DIR = HERE.parent
CATALOG = KIT_DIR.parent / "overlay/src/main/resources/mage/player/spellbench/catalog.json"
REGISTER = KIT_DIR / "xmage/resources/spellbench/kit/xmage/register.json"
FORMAT = "fdn-limited-bo1"
BASH_EXE = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else "bash"
PER_GAME_CORES = 2  # the kit's runner JVM and the engine's share; P's builtin opponent is in-process
BOUND_MS = 300_000

# Clock profiles (frozen in the plan; the run and every opponent use the plan's profile). Coordinator decision
# (2026-10-01): the soak, qualification and fdn-mirror-v0 itself use the kit profile, for every entry and builtin;
# the staged benchmark.json carries the same values.
KIT_CLOCK = {"startup_ms": 300000, "game_start_ms": 300000, "bank_ms": 3600000, "increment_ms": 2000,
             "max_decision_ms": 120000, "engine_step_ms": 120000}
CLOCKS = {"kit": KIT_CLOCK, "fdn-mirror-v0": KIT_CLOCK,
          # A future qualification profile. Historical plans and benchmark
          # clocks stay unchanged; publication must declare this profile too.
          "kit-20261003": dict(KIT_CLOCK, max_decision_ms=600000, engine_step_ms=600000)}
# Pairs per workload (multiples of 16: every deck the same share).
PAIRS = {"heuristic": 256, "uniform": 256, "cross": 64}
ENTRY_DESCRIPTIONS = {
    "kit-mad-1": "XMage's MAD minimax AI (ComputerPlayer7) on one world rebuilt from the seat's permitted inputs "
                 "and sampled hidden cards, through the Spellbench XMage agent kit (kit-wrapped: rebuilding, "
                 "synthesized dialogs, fallback, horizons and budgets affect its play).",
    "kit-mad-k": "As kit-mad-1, voting over four sampled worlds per decision.",
    "kit-mcts": "XMage's MCTS on one sampled world with knowledge-consistent rollouts (30 iterations, rollout cap "
                "1000, truncated rollouts scored by the evaluator); MCTS combat keeps at most 128 engagements per "
                "expansion, the first in upstream's enumeration order, so it is biased toward that prefix (with "
                "eight available attackers, the no-attack engagement is outside it).",
}
for _skill in range(1, 11):
    ENTRY_DESCRIPTIONS[f"xmage-mad7-fair-s{_skill}"] = (
        f"XMage CP7 at UI skill {_skill} (effective depth {max(4, _skill)}) on one sampled hidden world, "
        "with the kit's synchronous 5000-node, 2000-option and 20000-operation budgets, "
        "permitted reconstruction, explicit horizons, dialog heuristics and fallback. "
        "This is a changed fair variant of the native policy.")
ENTRIES = ("h1", "h2", "h3", *(f"mad7-s{s}" for s in range(1, 11)))


# ---------------------------------------------------------------------------
# Identities
# ---------------------------------------------------------------------------


def sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def native(path: Path | str) -> str:
    return str(path).replace("\\", "/")


def entry_identity(kit: Path, entry: str) -> dict[str, str]:
    """The frozen entry's name and version as its front reports them (Entries.main)."""
    out = subprocess.run(["java", "-cp", native(kit / "lib" / "kit-core.jar"), "spellbench.kit.core.Entries", entry],
                         check=True, capture_output=True, text=True).stdout.strip()
    name, version = out.split("\t")
    if name.endswith("-custom"):
        raise SystemExit(f"entry {entry} is not a frozen identity ({name})")
    return {"entry": entry, "name": name, "version": version}


def build_identity(kit: Path, engine_build: Path) -> dict[str, Any]:
    manifest = json.loads((engine_build / "BUILD-MANIFEST.json").read_text(encoding="utf-8"))
    kit_manifest = json.loads((kit / "KIT-MANIFEST.json").read_text(encoding="utf-8"))
    return {"engine_lib_digest": manifest["lib_digest"], "rules_snapshot_id": manifest["rules_snapshot_id"],
            "kit_jars": kit_manifest["jars"], "kit_source_digest": kit_manifest["kit_source_digest"],
            "kit_engine_lib_digest": kit_manifest["engine_lib_digest"]}


def workload_identity(plan_path: Path, build: dict[str, Any], p2_commit: str) -> dict[str, Any]:
    """What shapes the games: the plan (entries, pairs, clock, master secret), the builds and P's commit."""
    return {"plan": sha256_file(plan_path), "build": build, "p2": p2_commit, "per_game_cores": PER_GAME_CORES}


def admitted_decks() -> list[str]:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    register = json.loads(REGISTER.read_text(encoding="utf-8"))
    admission = register["admission"]
    decks = [d["catalog_id"] for d in catalog if FORMAT in d["formats"]]
    refused = [d for d in decks if not admission.get(d, {}).get("admitted")]
    if refused:
        raise SystemExit(f"decks not admitted for kit entries: {refused}")
    return decks


# ---------------------------------------------------------------------------
# The schedule
# ---------------------------------------------------------------------------


def make_plan(args: argparse.Namespace) -> None:
    kit = Path(args.kit)
    identities = [entry_identity(kit, e) for e in args.entry]
    # UI skills 1..4 share depth 4 in this synchronous wrapper. H1 is skill 6.
    # Giving aliases different bot seeds does not make independent policies.
    canonical = ["mad7-s4" if e in ("mad7-s1", "mad7-s2", "mad7-s3", "mad7-s4")
                 else "mad7-s6" if e in ("h1", "mad7-s6") else e for e in args.entry]
    if len(canonical) != len(set(canonical)):
        raise SystemExit("the rated roster contains duplicate CP7 policy aliases")
    if any(i["name"] == "kit-mcts" for i in identities) and not args.allow_mcts:
        raise SystemExit("kit-mcts waits for its own qualification (third review); pass --allow-mcts for that plan")
    master = secrets.token_hex(32)
    workloads = []

    def add(label: str, bots: list[dict[str, Any]], pairs: int) -> None:
        derived = hashlib.sha256(f"spellbench/kit-soak/{label}:".encode() + bytes.fromhex(master)).hexdigest()
        workloads.append({"label": label, "bots": bots, "pairs": pairs, "games": 2 * pairs, "run_secret": derived})

    for ident in identities:
        for opponent in ("heuristic", "uniform"):
            add(f"{ident['name']}-vs-{opponent}", [{"kit": ident["entry"]}, {"builtin": opponent}], args.pairs.get(opponent))
    for i in range(len(identities)):
        for j in range(i + 1, len(identities)):
            a, b = identities[i], identities[j]
            add(f"{a['name']}-vs-{b['name']}", [{"kit": a["entry"]}, {"kit": b["entry"]}], args.pairs["cross"])
    plan = {"schema": "spellbench-kit-soak-plan/v1", "format": FORMAT, "decks": admitted_decks(),
            "clock_profile": args.clock, "time_control": CLOCKS[args.clock], "entries": identities,
            "descriptions": {i["name"]: ENTRY_DESCRIPTIONS[i["name"]] for i in identities},
            "master_secret": master, "workloads": workloads, "games_total": sum(w["games"] for w in workloads),
            "r1_replay_games": 20}
    with Path(args.out).open("x", encoding="utf-8", newline="\n") as frozen:
        frozen.write(json.dumps(plan, indent=1) + "\n")
    print(f"plan: {plan['games_total']} games in {len(workloads)} workloads, clock {args.clock} -> {args.out}")


def agent_command(entry: str, ctx: dict[str, str]) -> list[str]:
    return [BASH_EXE, native(KIT_DIR / "scripts" / "agent.sh"), "--kit", ctx["kit"], "--engine-build", ctx["engine_build"],
            "--db", ctx["db"], "--work", ctx["agents"], "--entry", entry]


def config_json(plan: dict[str, Any], item: dict[str, Any], engine: list[str], ctx: dict[str, str]) -> dict[str, Any]:
    from spellbench.arena.config import CONFIG_SCHEMA
    from spellbench.builtins import BUILTIN_VERSIONS
    ident = {e["entry"]: e for e in plan["entries"]}
    bots = []
    for b in item["bots"]:
        if "kit" in b:
            e = ident[b["kit"]]
            bots.append({"name": e["name"], "version": e["version"], "type": "subprocess",
                         "command": agent_command(b["kit"], ctx)})
        else:
            bots.append({"name": b["builtin"], "version": BUILTIN_VERSIONS[b["builtin"]], "type": "builtin"})
    return {"schema": CONFIG_SCHEMA, "tournament_dir": f"kit-{item['label']}", "format": plan["format"],
            "deck_pool": [{"catalog_id": d} for d in plan["decks"]], "engine": {"command": list(engine)}, "bots": bots,
            "pairs_per_matchup": item["pairs"], "stats_seed": 0, "include_self_play": False,
            "time_control": plan["time_control"], "bootstrap_replicates": 1000}


class Schedule:
    """The workloads, their contexts and the global interleaved order."""

    def __init__(self, plan: dict[str, Any], engine: list[str], ctx: dict[str, str]) -> None:
        from spellbench.arena.config import TournamentConfig
        from spellbench.arena.qualification import sample_order
        from spellbench.arena.schedule import schedule
        from spellbench.run_secret import RunSecret
        self.workloads: list[dict[str, Any]] = []
        groups: list[list[int]] = []
        self.games: list[tuple[int, int]] = []
        for w, item in enumerate(plan["workloads"]):
            config = TournamentConfig.from_json(config_json(plan, item, engine, ctx))
            secret = RunSecret.from_hex(item["run_secret"])
            contexts = schedule(config, secret)
            self.workloads.append({**item, "config": config, "secret": secret, "contexts": contexts})
            group = []
            for context in contexts:
                group.append(len(self.games))
                self.games.append((w, context.game_index))
            groups.append(group)
        self.order = sample_order(groups)

    def share(self, fraction: float, part: str) -> list[int]:
        ids = []
        for i, gid in enumerate(self.order):
            a = math.floor((i + 1) * fraction) > math.floor(i * fraction)
            if a == (part == "A"):
                ids.append(gid)
        return ids


# ---------------------------------------------------------------------------
# Workers: one engine process each, games in sequence, a fresh kit agent per game
# ---------------------------------------------------------------------------

_W: dict[str, Any] = {}


def preflight_once(plan: dict[str, Any], engine: list[str], ctx: dict[str, str]):
    """P's preflight, once: every workload has the same decks, format and rules (the bots do not enter it)."""
    from spellbench.arena.schedule import EnginePin, preflight
    item = Schedule(plan, engine, ctx).workloads[0]
    return preflight(item["config"], item["secret"], pin=EnginePin())


def _init(plan: dict[str, Any], engine: list[str], ctx: dict[str, str], setup: Any) -> None:
    from spellbench.arena import runner
    from spellbench.arena.schedule import EnginePin
    sched = Schedule(plan, engine, ctx)
    _W.update(sched=sched, engine=None, pin=EnginePin(), setup=setup, ctx=ctx)
    # each batch logs to its own directory; the bot command (so the bot id, part of every ledger row) never changes
    os.environ["KIT_LOG_DIR"] = ctx["kitlogs"]
    multiprocessing.util.Finalize(None, _close, exitpriority=10)
    for item in sched.workloads:
        executed = runner.executed_config(item["config"], lambda text: text)
        item["entries"] = {e.name: e for e in runner.registry_entries(item["config"], executed)}


def _engine():
    from spellbench.host.engine_process import EngineProcess
    if _W["engine"] is None:
        config = _W["sched"].workloads[0]["config"]
        engine = EngineProcess(list(config.engine_command), timeout_s=BOUND_MS / 1000)
        hello = engine.hello()
        _W["pin"].check(hello.engine)
        _W.update(engine=engine, identity=hello.engine)
    return _W["engine"]


def leftover_agent_dirs(ctx: dict[str, str]) -> list[str]:
    """Agent directories that survived their game (each agent removes its own when it exits): per-game isolation.
    Checked after every agent has exited (a batch's end), since workers share the directory."""
    root = Path(ctx["agents"])
    return sorted(p.name for p in root.iterdir() if p.name.startswith("kit-agent-")) if root.exists() else []


def play_global(gid: int) -> dict[str, Any]:
    from spellbench.arena import runner
    from spellbench.arena.drivers import make_driver
    from spellbench.arena.schedule import game_setup
    from spellbench.host.game import play_game
    from spellbench.wire import canonical_json_dumps
    sched: Schedule = _W["sched"]
    w, index = sched.games[gid]
    item = sched.workloads[w]
    config, secret = item["config"], item["secret"]
    context = item["contexts"][index]
    setup = _W["setup"]
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
    if host_halt:
        engine.close()
        _W["engine"] = None
    return {"gid": gid, "workload": item["label"], "row": row,
            "row_digest": "sha256:" + hashlib.sha256(data).hexdigest(), "row_bytes": len(data) + 1,
            "seconds": time.monotonic() - start, "violation": outcome.violation, "host_halt": host_halt,
            "pid": os.getpid(),
            "diagnostics": list(result.diagnostics)[:20] if result.classification != "natural" else []}


def _close() -> None:
    if _W.get("engine") is not None:
        _W["engine"].close()
        _W["engine"] = None


def run_games(plan, engine, ctx, gids, workers, setup, on_row=None):
    pool = multiprocessing.get_context("spawn").Pool(workers, initializer=_init, initargs=(plan, engine, ctx, setup))
    start = time.monotonic()
    rows: dict[int, dict[str, Any]] = {}
    try:
        for row in pool.imap_unordered(play_global, gids, chunksize=1):
            rows[row["gid"]] = row
            if on_row is not None:
                on_row(row)
        pool.close()
        pool.join()
    except BaseException:
        pool.terminate()
        raise
    return time.monotonic() - start, [rows[g] for g in gids]


# ---------------------------------------------------------------------------
# Measurements from the kit's per-game logs
# ---------------------------------------------------------------------------


def _pct(xs: list[float], q: float):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else None


def kit_measurements(log_dirs: list[Path]) -> dict[str, Any]:
    """Per entry: decision tails, combat costs, bank use per game, cap firings, restarts, wrapper and cap rates."""
    sys.path.insert(0, str(KIT_DIR / "tests"))
    import e4 as e4mod  # noqa: E402
    import kitlog  # noqa: E402
    by_entry: dict[str, list[Path]] = defaultdict(list)
    for d in log_dirs:
        for p in sorted(Path(d).glob("*.jsonl")):
            name = None
            for line in p.read_text(encoding="utf-8").splitlines():
                r = json.loads(line)
                if r.get("event") == "game_start":
                    name = (r.get("entry") or {}).get("name")
                    break
            by_entry[name or "unknown"].append(p)
    out: dict[str, Any] = {}
    for name, paths in sorted(by_entry.items()):
        rows = kitlog.load([str(p) for p in paths])
        dec = [r for r in rows if r.get("event") == "decision"]
        answer = [r.get("answer_ms") or r.get("ms") or 0 for r in dec]
        combat = [r.get("answer_ms") or 0 for r in dec if r.get("kind") in ("declare_attack", "declare_block") and r.get("counters")]
        per_game = defaultdict(int)
        for r in dec:
            per_game[r.get("game_id")] += r.get("answer_ms") or 0
        overs = [r for r in rows if r.get("event") == "game_over"]
        summary = kitlog.summarize(rows)
        out[name] = {
            "games": len(paths), "decisions": len(dec),
            "decision_ms": {"median": _pct(answer, 0.5), "p90": _pct(answer, 0.9), "p99": _pct(answer, 0.99),
                            "max": max(answer) if answer else None},
            "combat_search_ms": {"count": len(combat), "median": _pct(combat, 0.5), "max": max(combat) if combat else None},
            "bank_used_ms_per_game": {"median": _pct(list(per_game.values()), 0.5),
                                      "max": max(per_game.values()) if per_game else None},
            "tags": summary["tags"], "cap_rate": summary["cap_rate"], "wrapper_rate": summary["wrapper_rate"],
            "wrapper_paths": summary["wrapper_paths"], "tags_by_kind": summary["tags_by_kind"],
            "mapping": summary["mapping"], "combat_option_cap": summary["combat_option_cap"],
            "search_caps": {k: v for k, v in summary["search_counters"].items() if k.startswith("cap:")},
            "runner": {"restarts": sum((o.get("runner") or {}).get("restarts", 0) for o in overs),
                       "kills": sum((o.get("runner") or {}).get("kills", 0) for o in overs),
                       "busy_refusals": sum((o.get("runner") or {}).get("busy_refusals", 0) for o in overs)},
            "e4": e4mod.summarize([str(p) for p in paths]),
        }
        out[name]["e4"]["mad"].pop("anchors", None)
    return out


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def _ctx(args: argparse.Namespace, out: Path, label: str) -> dict[str, str]:
    agents = out / "agents"  # one directory for every batch: the bot command must not change between them
    kitlogs = out / f"kitlogs-{label}"
    agents.mkdir(parents=True, exist_ok=True)
    kitlogs.mkdir(parents=True, exist_ok=True)
    return {"kit": native(Path(args.kit).resolve()), "engine_build": native(Path(args.engine_build).resolve()),
            "db": native(Path(args.db).resolve()), "agents": native(agents.resolve()), "kitlogs": native(kitlogs.resolve())}


def cmd_qualify(args: argparse.Namespace, engine: list[str]) -> int:
    from spellbench.arena.allocation import PlayedGame
    from spellbench.arena.qualification import plan_allocation, workload_id
    plan_path = Path(args.plan)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    build = build_identity(Path(args.kit), Path(args.engine_build))
    ident = workload_identity(plan_path, build, args.p2_commit)
    ctx = _ctx(args, out, "qualify")
    sched = Schedule(plan, engine, ctx)
    setup = preflight_once(plan, engine, ctx)
    log = (out / "qualify-games.jsonl").open("a", encoding="utf-8")
    rungs: list[dict[str, Any]] = []

    def play(workers: int, positions: tuple[int, ...]):
        gids = [sched.order[p] for p in positions]
        rung_ctx = _ctx(args, out, f"rung-{len(rungs)}-w{workers}")
        print(f"[{time.strftime('%H:%M:%S')}] rung: {workers} workers, {len(gids)} games", flush=True)
        wall, rows = run_games(plan, engine, rung_ctx, gids, workers, setup)
        left = leftover_agent_dirs(rung_ctx)
        for p, row in zip(positions, rows):
            log.write(json.dumps({"workers": workers, "position": p, **row}, sort_keys=True) + "\n")
        log.flush()
        rungs.append({"workers": workers, "games": len(gids), "wall_s": round(wall, 1),
                      "games_per_hour": round(len(gids) / wall * 3600, 2) if wall else None,
                      "agent_dirs_left": left,
                      "non_natural": sum(1 for r in rows if r["row"]["classification"] != "natural"),
                      "violations": sum(1 for r in rows if r["violation"]),
                      "kit": kit_measurements([Path(rung_ctx["kitlogs"])])})
        return wall, [PlayedGame(index=p, seconds=row["seconds"], digest=row["row_digest"], row_bytes=row["row_bytes"])
                      for p, row in zip(positions, rows)]

    allocation = plan_allocation(
        games_total=plan["games_total"], cap=args.cap, per_game_cores=PER_GAME_CORES, play=play,
        placement=args.placement, sample=list(range(plan["games_total"])), workload=workload_id(ident), host=args.machine,
        volumes={"run_dir": out, "pin_root": out}, evidence=out / "throughput-evidence.jsonl",
    )
    (out / "allocation.json").write_text(json.dumps(allocation.to_json(), indent=1) + "\n", encoding="utf-8")
    qualification = {"schema": "spellbench-kit-qualification/v1", "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                     "host": allocation.host, "node": platform.node(), "workload": workload_id(ident),
                     "workload_parts": ident,
                     "clock_profile": plan["clock_profile"], "time_control": plan["time_control"],
                     "entries": plan["entries"], "allocation": allocation.to_json(), "kind": allocation.kind,
                     "workers": allocation.workers, "outputs_identical": allocation.outputs_identical,
                     "rungs": rungs}
    (out / "QUALIFICATION.json").write_text(json.dumps(qualification, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: qualification[k] for k in ("kind", "workers", "outputs_identical")}, indent=1))
    return 0


def guard(args: argparse.Namespace, plan_path: Path) -> dict[str, Any]:
    """The launch guard: refuses a run without matching qualification evidence (COMPUTE-POLICY.md item 5)."""
    from spellbench.arena.qualification import workload_id
    q_path = Path(args.qualification)
    if not q_path.exists():
        raise SystemExit(f"refused: no qualification evidence at {q_path} (run qualify first)")
    q = json.loads(q_path.read_text(encoding="utf-8"))
    build = build_identity(Path(args.kit), Path(args.engine_build))
    expected = workload_id(workload_identity(plan_path, build, args.p2_commit))
    problems = []
    if q.get("schema") != "spellbench-kit-qualification/v1":
        problems.append("not a kit qualification record")
    if q.get("workload") != expected:
        problems.append("its workload (plan, engine build, kit jars, entries, clock, P commit) differs from this run's")
    if q.get("host") != args.machine or q.get("node") != platform.node():
        problems.append(f"it was measured on {q.get('host')} ({q.get('node')}), not on {args.machine} ({platform.node()})")
    if q.get("kind") == "substantial" and q.get("outputs_identical") is not True:
        problems.append("its rungs did not give identical outputs across worker counts")
    if q.get("kind") not in ("small", "substantial"):
        problems.append(f"its kind {q.get('kind')!r} is not a measured allocation")
    if any(r.get("agent_dirs_left") for r in q.get("rungs", [])):
        problems.append("an agent directory survived its game during qualification (isolation)")
    if problems:
        raise SystemExit("refused: " + "; ".join(problems))
    return q


def cmd_run(args: argparse.Namespace, engine: list[str]) -> int:
    from spellbench.arena.machine import check_reserve, machine_facts
    from spellbench.arena.qualification import resource_bound
    from spellbench.arena.machine import usable_cpus
    plan_path = Path(args.plan)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    q = guard(args, plan_path)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    check_reserve(machine_facts({"run_dir": out, "pin_root": out}), 0)
    workers = min(int(q["workers"]), resource_bound(usable_cpus(None), PER_GAME_CORES))
    ctx = _ctx(args, out, args.machine)
    sched = Schedule(plan, engine, ctx)
    rows_path = out / f"rows-{args.machine}.jsonl"
    done = set()
    if rows_path.exists():
        for line in rows_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line)["gid"])
    elsewhere = set()  # games another machine recorded (a rebalanced tail): never played twice
    for path in args.skip_rows:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.strip():
                elsewhere.add(json.loads(line)["gid"])
    gids = [g for g in sched.share(args.fraction, args.part) if g not in done and g not in elsewhere]
    if args.limit:
        gids = gids[: args.limit]
    if args.tail:
        gids = gids[-args.tail:]
    print(f"[{time.strftime('%H:%M:%S')}] {args.machine}: {len(gids)} games ({len(done)} already), {workers} qualified "
          f"workers ({q['kind']})", flush=True)
    setup = preflight_once(plan, engine, ctx)
    progress = {"n": 0, "violations": 0, "halts": 0, "start": time.monotonic()}
    status = out / f"progress-{args.machine}.json"
    with rows_path.open("a", encoding="utf-8") as sink:
        def on_row(row: dict[str, Any]) -> None:
            sink.write(json.dumps({"machine": args.machine, **row}, sort_keys=True) + "\n")
            sink.flush()
            progress["n"] += 1
            progress["violations"] += row["violation"] is not None
            progress["halts"] += row["row"]["classification"] == "halted"
            if progress["n"] % 10 == 0 or progress["n"] == len(gids):
                elapsed = time.monotonic() - progress["start"]
                rate = progress["n"] / elapsed * 3600
                status.write_text(json.dumps({
                    "time": time.strftime("%Y-%m-%d %H:%M:%S"), "played": progress["n"], "of": len(gids),
                    "games_per_hour": round(rate, 1), "violations": progress["violations"], "halted": progress["halts"],
                    "eta_hours": round((len(gids) - progress["n"]) / rate, 2) if rate else None}) + "\n")
        wall, _ = run_games(plan, engine, ctx, gids, workers, setup, on_row=on_row)
    left = leftover_agent_dirs(ctx)
    isolation = out / f"ISOLATION-{args.machine}.json"  # merged over a machine's batches (a resume, a tail)
    prior = json.loads(isolation.read_text(encoding="utf-8")) if isolation.exists() else {"agent_dirs_left": []}
    isolation.write_text(json.dumps({"agent_dirs_left": prior["agent_dirs_left"] + left,
                                     "batches": prior.get("batches", 1) + 1 if isolation.exists() else 1}) + "\n",
                         encoding="utf-8")
    for name in left:  # recorded above; removed so a surviving card database copy cannot fill the disk
        shutil.rmtree(Path(ctx["agents"]) / name, ignore_errors=True)
    print(f"[{time.strftime('%H:%M:%S')}] done: {len(gids)} games in {wall:.0f} s, violations {progress['violations']}",
          flush=True)
    return 0


def cmd_replay(args: argparse.Namespace, engine: list[str]) -> int:
    """R-1: twenty games spread over the run, replayed serially (one worker), digests compared with the run's rows."""
    plan_path = Path(args.plan)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    guard(args, plan_path)
    original = {}
    for path in args.rows:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                original[r["gid"]] = r
    gids = sorted(original)
    count = int(plan.get("r1_replay_games", 20))
    pick = [gids[int(i * len(gids) / count)] for i in range(min(count, len(gids)))]
    if args.game_id:  # a chosen set (e.g. games with a deadline-interrupted decision) instead of the spread
        chosen = set(args.game_id)
        pick = [g for g in gids if original[g]["row"]["game_id"] in chosen]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    label = "replay-selected" if args.game_id else "replay"
    ctx = _ctx(args, out, label)
    _, rows = run_games(plan, engine, ctx, pick, 1, preflight_once(plan, engine, ctx))
    differ = [r["gid"] for r in rows if r["row"]["game_digest"] != original[r["gid"]]["row"]["game_digest"]]
    report = {"games": len(pick), "equal": len(pick) - len(differ), "differ": differ,
              "agent_dirs_left": leftover_agent_dirs(ctx),
              "verdict": "PASS" if pick and not differ else "FAIL"}
    (out / ("REPLAY-SELECTED.json" if args.game_id else "R1.json")).write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(report))
    return 0 if report["verdict"] == "PASS" else 1


def cmd_summarize(args: argparse.Namespace) -> int:
    """The change 8 pass criteria over the soak's rows and kit logs."""
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    rows: dict[int, dict[str, Any]] = {}
    mismatched = 0
    for path in args.rows:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r["gid"] in rows and rows[r["gid"]]["row_digest"] != r["row_digest"]:
                mismatched += 1
            rows.setdefault(r["gid"], r)
    reasons = Counter(r["row"]["reason"] for r in rows.values())
    classes = Counter(r["row"]["classification"] for r in rows.values())
    coverage: dict[str, Counter] = defaultdict(Counter)
    for r in rows.values():
        row = r["row"]
        for seat, deck in zip(row["seats"], row["decks"]):
            deck_id = deck.get("catalog_id") or deck.get("name")
            coverage[seat["name"]][f"{deck_id}:{seat['seat']}"] += 1
    expected = {w["label"]: w["games"] for w in plan["workloads"]}
    played = Counter(r["workload"] for r in rows.values())
    kit = kit_measurements([Path(d) for d in args.kitlogs])
    forbidden = {k: reasons.get(k, 0) for k in ("invalid_selection", "malformed_response")}
    criteria = {
        "no_invalid_selection_or_malformed_response": all(v == 0 for v in forbidden.values()),
        "no_live_validator_violation": not any(r["violation"] for r in rows.values()),
        "schedule_complete": all(played.get(k, 0) == v for k, v in expected.items()),
        "per_game_isolation": all(not json.loads(Path(f).read_text(encoding="utf-8"))["agent_dirs_left"]
                                  for f in args.isolation) and bool(args.isolation),
        "no_duplicate_row_with_another_digest": mismatched == 0,
    }
    summary = {"plan_games_total": plan["games_total"], "games_recorded": len(rows),
               "workloads": {k: {"expected": v, "played": played.get(k, 0)} for k, v in expected.items()},
               "classification": dict(classes), "reasons": dict(reasons), "forbidden_reasons": forbidden,
               "violations": [r["violation"] for r in rows.values() if r["violation"]],
               "host_halts": sum(r["host_halt"] for r in rows.values()),
               "non_natural": [{"gid": r["gid"], "workload": r["workload"], "reason": r["row"]["reason"],
                                "adjudication": r["row"]["adjudication"], "diagnostics": r["diagnostics"][:5]}
                               for r in rows.values() if r["row"]["classification"] != "natural"],
               "coverage_min_max": {name: [min(c.values()), max(c.values())] for name, c in coverage.items()},
               "seconds_per_game": {"median": statistics.median([r["seconds"] for r in rows.values()]) if rows else None,
                                    "max": max([r["seconds"] for r in rows.values()], default=None)},
               "kit": kit, "criteria": criteria,
               "verdict": "PASS" if all(criteria.values()) else "FAIL"}
    Path(args.out).write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"games_recorded": len(rows), "criteria": criteria, "verdict": summary["verdict"]}, indent=1))
    return 0 if summary["verdict"] == "PASS" else 1


def main(argv: list[str]) -> int:
    rest, engine = (argv, []) if "--" not in argv else (argv[: argv.index("--")], argv[argv.index("--") + 1:])
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--entry", action="append", required=True, choices=ENTRIES)
    p.add_argument("--kit", required=True)
    p.add_argument("--clock", choices=sorted(CLOCKS), default="kit")
    p.add_argument("--allow-mcts", action="store_true")
    p.add_argument("--out", required=True)
    for name in ("qualify", "run", "replay"):
        q = sub.add_parser(name)
        q.add_argument("--plan", required=True)
        q.add_argument("--kit", required=True)
        q.add_argument("--engine-build", required=True)
        q.add_argument("--db", required=True)
        q.add_argument("--p2-commit", required=True)
        q.add_argument("--out", required=True)
        q.add_argument("--machine", required=True)
        if name == "qualify":
            q.add_argument("--cap", type=int, required=True)
            q.add_argument("--placement", required=True)
        else:
            q.add_argument("--qualification", required=True)
        if name == "run":
            q.add_argument("--fraction", type=float, default=1.0)
            q.add_argument("--part", choices=("A", "B"), default="A")
            q.add_argument("--limit", type=int, default=0, help="the first N of this part's remaining games")
            q.add_argument("--tail", type=int, default=0, help="the last N of this part's remaining games")
            q.add_argument("--skip-rows", action="append", default=[], help="another machine's rows: games it played")
        if name == "replay":
            q.add_argument("--rows", action="append", required=True)
            q.add_argument("--game-id", action="append", default=[], help="replay these games instead of the spread")
    s = sub.add_parser("summarize")
    s.add_argument("--plan", required=True)
    s.add_argument("--rows", action="append", required=True)
    s.add_argument("--kitlogs", action="append", required=True)
    s.add_argument("--isolation", action="append", default=[], help="the run's ISOLATION-*.json files")
    s.add_argument("--out", required=True)
    args = parser.parse_args(rest)
    if args.command == "plan":
        args.pairs = dict(PAIRS)
        make_plan(args)
        return 0
    if args.command == "summarize":
        return cmd_summarize(args)
    if not engine:
        raise SystemExit("the engine command follows --")
    return {"qualify": cmd_qualify, "run": cmd_run, "replay": cmd_replay}[args.command](args, engine)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
