"""One human play session: a person against a benchmark bot, as an ordinary arena run (``python -m spellbench.human``).

The session builds an arena config from a benchmark definition (default ``pauper-kernel-v2``): the benchmark's
engine, deck pool, rules, extensions and limits; the bots ``human`` (``relay.py``) and the opponent entry, which
gets ``--decision-log``; one explicit matchup with ``ceil(games / 2)`` seat-swapped pairs, so pair ``p`` plays deck
``p % 8`` in both seats; one worker; and a clock sized for a person (``--bank-minutes``). It then starts the play
server on 127.0.0.1, prints the page URL, and runs the tournament into ``<out>/runs/<name>/`` (ledger, manifest).

The launch guard's throughput measurement is not run: a person plays one game at a time, and its qualification
games would be games the person plays outside the ledger. The run publishes as ``unmeasured`` and unrated.
Ctrl+C publishes the games played so far (status ``aborted``).

With ``--record`` (the default) the operator engine recording is on (``spellbench.arena.engine_records``): each
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
from typing import Any

from ..arena import engine_records, runner
from ..arena.allocation import Allocation
from ..bench import definition
from ..run_secret import RunSecret
from . import relay
from .server import Hub, make_server

REPO = Path(__file__).resolve().parents[3]
HUMAN = "human"


def build_config(*, benchmark_dir: Path, local: dict[str, str], opponent: str, games: int, run_dir: Path,
                 python: str, decision_log: Path, bank_minutes: int, decks: list[str] | None = None) -> dict[str, Any]:
    benchmark = dataclasses.replace(definition.load_benchmark(benchmark_dir), evaluation_targets=None,
                                    evaluation_matchups=None)
    doc = benchmark.tournament_config(str(run_dir))
    for key in ("opponent_panel", "evaluation_version", "evaluation_engine_identity", "evaluation_engine_inputs"):
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
    # Every deck plays equally often (the arena requires it): whole rotations of seat-swapped pairs.
    rotations = max(1, math.ceil(games / (2 * len(doc["deck_pool"]))))
    doc["pairs_per_matchup"] = rotations * len(doc["deck_pool"])
    doc["workers"] = 1
    bank = bank_minutes * 60_000
    # startup_ms also bounds the human seat's hello, which waits for "next game" between games.
    doc["time_control"] = {**doc["time_control"], "startup_ms": 4 * 3_600_000, "bank_ms": bank,
                           "max_decision_ms": bank}
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
    """Write the bounded recording config the runner reads from the environment; returns its path and hash."""
    path = out / "engine-records" / "recording.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"schema": "spellbench-engine-recording/v1", "root": str(out / "engine-records" / "hot"),
            "per_game_cap_bytes": 128 * 2**20, "collection_timeout_seconds": 600,
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
    args = parser.parse_args(argv)

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

    games_total = 2 * config_doc["pairs_per_matchup"]
    # Both seats log to one directory as <game_id>.<seat>.jsonl, the layout the misplay review converter reads.
    hub = Hub(log_dir=out / "decision-logs", games_total=games_total, opponent=args.opponent,
              label=f"{games_total} games vs {args.opponent}, {args.bank_minutes}-minute bank")
    server = make_server(hub, port=args.port)
    host, port = server.server_address[:2]
    os.environ[relay.URL_ENV] = f"http://{host}:{port}"
    os.environ[relay.TOKEN_ENV] = server.token
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://{host}:{port}/?t={server.token}"
    print(f"\n  Play here: {url}\n", flush=True)
    print(f"  run: {run_dir}\n  config: {config_path}\n", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    started = time.monotonic()
    try:
        summary = runner.run_tournament(config, run_secret=RunSecret.generate(), allocation=Allocation.unmeasured(1))
        print(f"tournament published: {summary.tournament_dir} status {summary.status}, "
              f"{summary.games_total} games, {round((time.monotonic() - started) / 60)} minutes", flush=True)
    finally:
        stop.set()
        server.shutdown()
    return 0
