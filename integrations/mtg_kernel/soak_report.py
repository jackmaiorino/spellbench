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
  T is design section 2's 500 s, fixed here; the entrant's
  ``game_time_basis_seconds`` must equal it. Every counted game must carry a
  finite, nonnegative ``charged_wall_us``, and each rerun game one log. The
  soak host's charged wall per game is always reported.
* Ledger outcomes (entrant wins, losses, draws), forfeits by cause (a
  ``timeout`` forfeit is a board-clock forfeit; AC5 needs zero), halted and
  truncated games, and per-search wall times. Payload size and export time
  are reported only if the logs carry them (``payload_bytes``,
  ``export_us`` on search records).

Exit 0 when every pipeline check passes (inputs present, logs complete and
reconciled, totals consistent); the AC5 verdicts are fields of the report.

Usage: python soak_report.py LOG_DIR --ledger MATCHES.jsonl --entrant NAME --receipts DIR
       [--expect-games N] [--wall-logs DIR] [--wall-causes FILE] [--json OUT]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import shutil
import sys
import tempfile
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
T_SECONDS = 500.0  # design section 2: the entrant's summed charged choose intervals per game
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


def _scan(roots: list[Path], entrant: str, keys: set[tuple[str, str]]) -> tuple[dict, list[str]]:
    """Logs whose header names the entrant and a counted (game id, seat), keyed by it: a list of
    (path, records or None when a line does not parse). Every other log (qualification probes, other bots,
    unreadable headers) is excluded by its first line alone and listed by name."""
    found: dict[tuple[str, str], list[tuple[Path, list[dict] | None]]] = {}
    excluded: list[str] = []
    for root in roots:
        for path in sorted(root.glob("*.jsonl")):
            try:
                with open(path, encoding="utf-8") as handle:
                    header = json.loads(handle.readline())
            except (OSError, ValueError):
                excluded.append(path.name)
                continue
            key = (header.get("game_id"), header.get("seat")) if isinstance(header, dict) else None
            if (not isinstance(header, dict) or header.get("kind") != "header" or header.get("bot_name") != entrant
                    or key not in keys):
                excluded.append(path.name)
                continue
            try:
                records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            except ValueError:
                records = None
            found.setdefault(key, []).append((path, records))
    return found, excluded


def _games(found: dict) -> tuple[dict[tuple[str, str], dict], dict[str, list[str]]]:
    """Per (game id, seat) with exactly one complete, parseable log: its terminal, entrant and search records;
    and the problems (duplicate, malformed and incomplete logs) by kind."""
    out: dict[tuple[str, str], dict] = {}
    problems: dict[str, list[str]] = {"duplicate": [], "malformed": [], "incomplete": []}
    for key, entries in sorted(found.items()):
        if len(entries) > 1:
            problems["duplicate"].extend(path.name for path, _ in entries)
            continue
        path, records = entries[0]
        if records is None:
            problems["malformed"].append(path.name)
            continue
        final = records[-1] if records and records[-1].get("kind") == "availability" else None
        if final is None:
            problems["incomplete"].append(path.name)
            continue
        out[key] = {"header": records[0], "final": final,
                    "entrant": next((r["entrant"] for r in records if r.get("kind") == "entrant"), None),
                    "searches": [r for r in records if r.get("kind") == "search"]}
    return out, problems


def _stats(values: list[float]) -> dict:
    return {"n": len(values), "median": nearest_rank(values, 0.5), "p99": nearest_rank(values, WALL_P),
            "max": max(values, default=None)}


def _wall_seconds(games: dict[tuple[str, str], dict]) -> tuple[dict[str, float], list[str]]:
    """Charged entrant wall per game in seconds, and the games without a finite, nonnegative measurement."""
    walls, missing = {}, []
    for key, game in games.items():
        value = game["final"].get("charged_wall_us")
        if type(value) in (int, float) and math.isfinite(value) and value >= 0:
            walls[key[0]] = value / 1e6
        else:
            missing.append(key[0])
    return walls, sorted(missing)


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
                wall_logs: list[Path] | None = None, wall_causes: dict[str, str] | None = None) -> dict:
    rows = _ledger_rows(ledger, entrant)
    keys = {(row["game_id"], seat["seat"]) for row in rows for seat in row["seats"] if seat.get("name") == entrant}
    found, excluded = _scan(logs, entrant, keys)
    games, problems = _games(found)
    # The availability totals and checks read only the counted games' parseable logs (duplicates included, so
    # its own duplicate check sees them); an unreadable qualification log cannot stop the report.
    with tempfile.TemporaryDirectory() as scratch:
        for entries in found.values():
            for path, records in entries:
                if records is not None:
                    target = Path(scratch) / str(len(list(Path(scratch).iterdir()))) / path.name
                    target.parent.mkdir()
                    shutil.copyfile(path, target)
        base = entrant_availability.report(sorted(Path(scratch).iterdir()), [ledger], entrant, receipts)
    order = sorted(games)
    pairs = [(games[k]["final"]["c5_faults"], games[k]["final"]["eligible"]) for k in order]
    faults, units = sum(f for f, _ in pairs), sum(u for _, u in pairs)
    bound = entrant_availability.upper_bound_95(faults, units)
    r3, r3b = base["r3_ineligible"], base["own_ineligible"]

    # Entrant constants: one record shared by every counted game.
    constants = {json.dumps(g["entrant"], sort_keys=True) for g in games.values()}
    entrant_record = json.loads(next(iter(constants))) if len(constants) == 1 else None
    t_seconds = T_SECONDS

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

    walls, walls_missing = _wall_seconds(games)
    search_walls = [s["wall_us"] / 1e6 for g in games.values() for s in g["searches"] if "wall_us" in s]
    payload_bytes = [s["payload_bytes"] for g in games.values() for s in g["searches"] if "payload_bytes" in s]
    export_us = [s["export_us"] / 1e6 for g in games.values() for s in g["searches"] if "export_us" in s]
    subset = wall_subset([row["game_id"] for row in rows])

    wall = {"soak_host": {"per_game_seconds": dict(sorted(walls.items())), "unmeasured_games": walls_missing,
                          **_stats(list(walls.values()))},
            "subset": subset, "check": None}
    if wall_logs:
        chosen = {s["game_id"] for s in subset}
        rerun_found, _ = _scan(wall_logs, entrant, {k for k in keys if k[0] in chosen})
        rerun, rerun_problems = _games(rerun_found)
        # The rerun must replay the soak's game: the same header (model state, selection, stream seed), the same
        # entrant constants, and the same terminal record but for its wall clock (so a rerun that stopped early,
        # or played another game, is not a wall measurement of this one).
        def same_game(key: tuple[str, str], game: dict) -> bool:
            soak = games.get(key)
            strip = lambda final: {k: v for k, v in final.items() if k != "charged_wall_us"}  # noqa: E731
            return (soak is not None and game["entrant"] == entrant_record and game["header"] == soak["header"]
                    and strip(game["final"]) == strip(soak["final"]))
        other_config = sorted(k[0] for k, g in rerun.items() if not same_game(k, g))
        rerun = {k: g for k, g in rerun.items() if same_game(k, g)}
        rerun_walls, unmeasured = _wall_seconds(rerun)
        check = _wall_check(rerun_walls, t_seconds, wall_causes or {})
        missing = sorted(s["game_id"] for s in subset if s["game_id"] not in rerun_walls)
        bad_logs = sorted(name for names in rerun_problems.values() for name in names)
        wall["check"] = {**check, "missing_games": missing, "unmeasured_games": unmeasured,
                         "duplicate_logs": rerun_problems["duplicate"], "malformed_logs": rerun_problems["malformed"],
                         "incomplete_logs": rerun_problems["incomplete"], "not_the_soak_game": other_config,
                         "pass": check["pass"] and not missing and not bad_logs and not other_config}

    checks = dict(base["checks"])
    checks.update({
        "ledger_names_the_entrant": bool(rows),
        "ledger_games_unique": len({row["game_id"] for row in rows}) == len(rows),
        "totals_consistent": faults == base["c5_faults"] and units == base["eligible"] and len(pairs) == base["games"],
        "one_entrant_record": entrant_record is not None,
        "games_expected": expect_games is None or len({row["game_id"] for row in rows}) == expect_games,
        "t_is_the_design_t": entrant_record is not None
        and float(entrant_record.get("game_time_basis_seconds", -1)) == T_SECONDS,
        "every_game_wall_measured": not walls_missing,
        "counted_logs_parse": not problems["malformed"],
    })
    if wall_logs:
        checks["wall_subset_rerun_complete"] = not wall["check"]["missing_games"]
        checks["wall_rerun_one_complete_log_per_game"] = not (
            wall["check"]["duplicate_logs"] or wall["check"]["malformed_logs"] or wall["check"]["incomplete_logs"])
        checks["wall_rerun_same_game"] = not wall["check"]["not_the_soak_game"]
    ac5_bound = {"units": units, "faults": faults, "share": None if not units else faults / units,
                 "cp_upper_95": bound, "pass": None if bound is None else bound <= AC5_LIMIT,
                 "limit": AC5_LIMIT}
    return {
        "schema": "spellbench-w1-soak-report/v1",
        "entrant": entrant, "entrant_constants": entrant_record,
        "ledger_games": len(rows), "counted_games": len(pairs),
        "logs": {"excluded": len(excluded), "problems": problems},
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
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    causes = json.loads(args.wall_causes.read_text(encoding="utf-8")) if args.wall_causes else None
    result = soak_report(args.logs, args.ledger, args.entrant, args.receipts, expect_games=args.expect_games,
                         wall_logs=args.wall_logs, wall_causes=causes)
    text = json.dumps(result, indent=2, sort_keys=True)
    print(text)
    if args.json:
        args.json.write_text(text + "\n", encoding="utf-8")
    return 0 if result["checks_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
