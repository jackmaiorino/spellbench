"""AC5 soak report for a W1 search entrant (W1 design 11, 13 AC5; gate packet 10.20 R4).

Computes, from one soak's decision logs, ledger and engine-side receipts:

* **The AC5 bound (binding, R4).** Units are the eligible units of the
  ledger games naming the entrant (rows of the run's ``matches.jsonl``);
  qualification probes and other unledgered logs are excluded. A buffered
  group counts once at its root, as ``entrant_availability.py`` counts it.
  R3 (opponent library search, amendment 43.1) and R3b (own library search,
  amendment 43.2) are not eligible; every other refusal and every other C5
  reason is a fault (``kernel_search_bot.is_fault``). The bound is the
  one-sided 95 percent Clopper-Pearson upper bound on faults / units
  (``entrant_availability.upper_bound_95``); it passes at or below 1 percent.
* Reported with it: faults per reason and per refusal subclass, the R3 and
  R3b counts, the own share and its 2 percent trigger (43.2), the
  ``receipts_reconcile`` check and the rest of ``entrant_availability``'s
  checks.
* **Report only, not a gate:** a game-clustered bound. Per-game
  (faults, units) pairs, ratio estimator sum(faults) / sum(units), 10,000
  resamples of the games with replacement from ``random.Random(20261105)``
  (games in (game id, seat) order, each draw ``randrange(n)``), the 95th
  percentile by nearest rank (the ceil(0.95 x 10,000)-th smallest ratio).
  A resample without units counts as ratio 1.
* **Wall check (design 11, 13 AC5; review round 2 item 6).** The subset is
  the 32 ledger games with the smallest sha256("w1-ac5-wall:" + game id)
  (hex order). With ``--wall-logs`` (the subset rerun on the deployment host
  under the load profile) the criterion is: per-game charged entrant wall
  (the availability record's ``charged_wall_us``) with p99 at or below T and
  maximum at or below 1.5 T, where p99 is the nearest-rank value (the
  ceil(0.99 n)-th smallest; for 32 games, the maximum), and every game above
  T with a recorded cause (``--wall-causes``, a JSON object game id -> text).
  T is the entrant's ``game_time_basis_seconds`` unless ``--t-seconds``
  overrides it. The soak host's charged wall per game is always reported.
* Ledger outcomes (entrant wins, losses, draws), forfeits by cause (a
  ``timeout`` forfeit is a board-clock forfeit; AC5 needs zero), halted and
  truncated games, and per-search wall times. Payload size and export time
  are reported only if the logs carry them (``payload_bytes``,
  ``export_us`` on search records).

Exit 0 when every pipeline check passes (inputs present, logs complete and
reconciled, totals consistent); the AC5 verdicts are fields of the report.

Usage: python soak_report.py LOG_DIR --ledger MATCHES.jsonl --entrant NAME --receipts DIR
       [--expect-games N] [--wall-logs DIR] [--wall-causes FILE] [--t-seconds T] [--json OUT]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import entrant_availability  # noqa: E402

AC5_LIMIT = 0.01
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 20261105
BOOTSTRAP_QUANTILE = 0.95
WALL_DOMAIN = "w1-ac5-wall:"
WALL_SUBSET = 32
WALL_P = 0.99
WALL_MAX_FACTOR = 1.5
CLOCK_FORFEIT = "timeout"


def nearest_rank(values: list[float], q: float) -> float | None:
    """The ceil(q x n)-th smallest value (at least the first), or None for no values."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(1, math.ceil(q * len(ordered))) - 1]


def wall_key(game_id: str) -> str:
    return hashlib.sha256((WALL_DOMAIN + game_id).encode("utf-8")).hexdigest()


def wall_subset(game_ids: list[str], size: int = WALL_SUBSET) -> list[dict]:
    """The ``size`` games with the smallest sha256("w1-ac5-wall:" + game id), in that order."""
    keyed = sorted((wall_key(g), g) for g in set(game_ids))
    return [{"game_id": g, "sha256": k} for k, g in keyed[:size]]


def cluster_bootstrap_upper(pairs: list[tuple[int, int]], resamples: int = BOOTSTRAP_RESAMPLES,
                            seed: int = BOOTSTRAP_SEED, q: float = BOOTSTRAP_QUANTILE) -> float | None:
    """Nearest-rank q quantile of sum(faults) / sum(units) over resamples of the games with replacement."""
    n = len(pairs)
    if n == 0:
        return None
    rng = random.Random(seed)
    ratios = []
    for _ in range(resamples):
        faults = units = 0
        for _ in range(n):
            f, u = pairs[rng.randrange(n)]
            faults += f
            units += u
        ratios.append(faults / units if units else 1.0)
    return nearest_rank(ratios, q)


def _ledger_rows(ledger: Path, entrant: str) -> list[dict]:
    rows = []
    for line in ledger.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if any(seat.get("name") == entrant for seat in row.get("seats", [])):
                rows.append(row)
    return rows


def _games(logs: list[Path], keys: set[tuple[str, str]], entrant: str) -> dict[tuple[str, str], dict]:
    """Per ledger game and seat: the terminal record, the entrant record and the search records."""
    out: dict[tuple[str, str], dict] = {}
    for root in logs:
        for path in sorted(root.glob("*.jsonl")):
            header, records, final = entrant_availability._read_log(path)
            if header is None or final is None or header.get("bot_name") != entrant:
                continue
            key = (header["game_id"], header["seat"])
            if key not in keys or key in out:
                continue
            entrant_record = next((r["entrant"] for r in records if r.get("kind") == "entrant"), None)
            out[key] = {"final": final, "entrant": entrant_record,
                        "searches": [r for r in records if r.get("kind") == "search"]}
    return out


def _stats(values: list[float]) -> dict:
    return {"n": len(values), "median": nearest_rank(values, 0.5), "p99": nearest_rank(values, WALL_P),
            "max": max(values, default=None)}


def _wall_check(walls: dict[str, float], t_seconds: float, causes: dict[str, str]) -> dict:
    values = list(walls.values())
    p99, top = nearest_rank(values, WALL_P), max(values, default=None)
    excess = sorted(g for g, w in walls.items() if w > t_seconds)
    uncaused = [g for g in excess if not str(causes.get(g, "")).strip()]
    return {
        "games": len(values), "t_seconds": t_seconds, "p99_seconds": p99, "max_seconds": top,
        "p99_at_or_below_t": None if p99 is None else p99 <= t_seconds,
        "max_at_or_below_1_5t": None if top is None else top <= WALL_MAX_FACTOR * t_seconds,
        "over_t": [{"game_id": g, "seconds": walls[g], "cause": causes.get(g)} for g in excess],
        "over_t_without_cause": uncaused,
        "pass": bool(values) and p99 <= t_seconds and top <= WALL_MAX_FACTOR * t_seconds and not uncaused,
    }


def soak_report(logs: list[Path], ledger: Path, entrant: str, receipts: Path, *, expect_games: int | None = None,
                wall_logs: list[Path] | None = None, wall_causes: dict[str, str] | None = None,
                t_seconds: float | None = None) -> dict:
    base = entrant_availability.report(logs, [ledger], entrant, receipts)
    rows = _ledger_rows(ledger, entrant)
    keys = {(row["game_id"], seat["seat"]) for row in rows for seat in row["seats"] if seat.get("name") == entrant}
    games = _games(logs, keys, entrant)
    order = sorted(games)
    pairs = [(games[k]["final"]["c5_faults"], games[k]["final"]["eligible"]) for k in order]
    faults, units = sum(f for f, _ in pairs), sum(u for _, u in pairs)
    bound = entrant_availability.upper_bound_95(faults, units)
    r3, r3b = base["r3_ineligible"], base["own_ineligible"]

    # Entrant constants: one record shared by every counted game.
    constants = {json.dumps(g["entrant"], sort_keys=True) for g in games.values()}
    entrant_record = json.loads(next(iter(constants))) if len(constants) == 1 else None
    if t_seconds is None and entrant_record is not None:
        t_seconds = float(entrant_record["game_time_basis_seconds"])

    # Outcomes, forfeits, halts from the ledger, from the entrant's side.
    outcome = Counter()
    forfeits, other = [], Counter()
    for row in rows:
        seat = next(s["seat"] for s in row["seats"] if s.get("name") == entrant)
        if row.get("classification") in ("natural", "forfeit"):
            outcome["draw" if row.get("winner") is None else ("win" if row["winner"] == seat else "loss")] += 1
        else:
            other[row.get("classification")] += 1
        if row.get("classification") == "forfeit":
            adj = row.get("adjudication") or {}
            forfeits.append({"game_id": row["game_id"], "cause": adj.get("cause"),
                             "entrant_lost": adj.get("loser_seat") == seat})
    clock_forfeits = sum(1 for f in forfeits if f["cause"] == CLOCK_FORFEIT)

    walls = {k[0]: g["final"].get("charged_wall_us", 0) / 1e6 for k, g in games.items()}
    search_walls = [s["wall_us"] / 1e6 for g in games.values() for s in g["searches"] if "wall_us" in s]
    payload_bytes = [s["payload_bytes"] for g in games.values() for s in g["searches"] if "payload_bytes" in s]
    export_us = [s["export_us"] / 1e6 for g in games.values() for s in g["searches"] if "export_us" in s]
    subset = wall_subset([row["game_id"] for row in rows])

    wall = {"soak_host": {"per_game_seconds": dict(sorted(walls.items())), **_stats(list(walls.values()))},
            "subset": subset, "check": None}
    if wall_logs:
        chosen = {s["game_id"] for s in subset}
        rerun = _games(wall_logs, {k for k in keys if k[0] in chosen}, entrant)
        rerun_walls = {k[0]: g["final"].get("charged_wall_us", 0) / 1e6 for k, g in rerun.items()}
        check = _wall_check(rerun_walls, t_seconds, wall_causes or {}) if t_seconds is not None else None
        missing = sorted(s["game_id"] for s in subset if s["game_id"] not in rerun_walls)
        wall["check"] = {**(check or {}), "missing_games": missing,
                         "pass": bool(check and check["pass"] and not missing)}

    checks = dict(base["checks"])
    checks.update({
        "ledger_names_the_entrant": bool(rows),
        "totals_consistent": faults == base["c5_faults"] and units == base["eligible"] and len(pairs) == base["games"],
        "one_entrant_record": entrant_record is not None,
        "games_expected": expect_games is None or len(rows) == expect_games,
        "t_known": t_seconds is not None,
    })
    if wall_logs:
        checks["wall_subset_rerun_complete"] = not wall["check"]["missing_games"]
    ac5_bound = {"units": units, "faults": faults, "share": None if not units else faults / units,
                 "cp_upper_95": bound, "pass": None if bound is None else bound <= AC5_LIMIT,
                 "limit": AC5_LIMIT}
    return {
        "schema": "spellbench-w1-soak-report/v1",
        "entrant": entrant, "entrant_constants": entrant_record,
        "ledger_games": len(rows), "counted_games": len(pairs),
        "outcomes": {"win": outcome["win"], "loss": outcome["loss"], "draw": outcome["draw"],
                     "halted": other["halted"], "truncated": other["truncated"]},
        "forfeits": forfeits, "clock_forfeits": clock_forfeits,
        "ac5_bound": ac5_bound,
        "faults_by_reason": base["c5_by_reason"],
        "refusals_by_subclass": base["refusals_by_subclass"],
        "r3_opponent": r3, "r3b_own": r3b, "own_share": base["own_share"],
        "own_share_over_2pct": base["own_share_over_2pct"],
        "receipts_reconcile": base["checks"]["receipts_reconcile"],
        "bootstrap": {"report_only": True, "per_game": [{"game_id": k[0], "seat": k[1], "faults": f, "units": u}
                                                       for k, (f, u) in zip(order, pairs)],
                      "ratio": None if not units else faults / units, "resamples": BOOTSTRAP_RESAMPLES,
                      "seed": BOOTSTRAP_SEED, "upper_95": cluster_bootstrap_upper(pairs)},
        "wall": wall,
        "search_wall_seconds": _stats(search_walls),
        "payload_bytes": _stats(payload_bytes) if payload_bytes else "not logged",
        "export_seconds": _stats(export_us) if export_us else "not logged",
        "allowance_limited": base["allowance_limited"],
        "searched_share_of_eligible": base["searched_share_of_eligible"],
        "attempted_searches": base["attempted_searches"], "search_errors": base["search_errors"],
        "commit_check": base["commit_check"],
        "availability": base,
        "checks": checks, "checks_pass": all(checks.values()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("logs", nargs="+", type=Path)
    parser.add_argument("--ledger", type=Path, required=True, help="the soak run's matches.jsonl")
    parser.add_argument("--entrant", required=True, help="the entrant's bot name in the ledger")
    parser.add_argument("--receipts", type=Path, required=True, help="the engine-side receipt directory")
    parser.add_argument("--expect-games", type=int, help="ledger games naming the entrant (128 for a soak)")
    parser.add_argument("--wall-logs", action="append", type=Path, help="decision logs of the wall-subset rerun")
    parser.add_argument("--wall-causes", type=Path, help="JSON object: game id -> recorded cause of a game over T")
    parser.add_argument("--t-seconds", type=float, help="T (default: the entrant's game_time_basis_seconds)")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    causes = json.loads(args.wall_causes.read_text(encoding="utf-8")) if args.wall_causes else None
    result = soak_report(args.logs, args.ledger, args.entrant, args.receipts, expect_games=args.expect_games,
                         wall_logs=args.wall_logs, wall_causes=causes, t_seconds=args.t_seconds)
    text = json.dumps(result, indent=2, sort_keys=True)
    print(text)
    if args.json:
        args.json.write_text(text + "\n", encoding="utf-8")
    return 0 if result["checks_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
