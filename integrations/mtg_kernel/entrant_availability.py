"""Availability report for the W1 search entrant from its decision logs.

Reads every ``<game>.<seat>.jsonl`` written by kernel_search_bot.py
(``--decision-log``) and totals, per entrant: eligible decisions, searched
decisions and group walks, policy answers by reason (refusal predicate R1 to
R8b, allowance, order map, faults), C5 faults with a one-sided 95 percent
upper bound on their share of eligible decisions (design 13 AC5), searches,
units charged and tree transitions.

Acceptance checks (fairness gate G8): one log per game and seat, each ending
in its terminal availability record; with ``--ledger``, every ledger game of
the entrant has its log and the totals cover the ledger games only (other
logs, such as the arena's qualification games, are reported apart); with
``--receipts``, each game's engine-side receipts (the bridge's and the
adapter's) reconcile with the entrant's record; every attempted search is
counted, errors included; charge never exceeds the allowance or a group's
cap; no refusal is unclassified. The command exits 1 when a check fails.

Usage: python entrant_availability.py LOG_DIR [LOG_DIR ...] [--ledger MATCHES.jsonl ...]
       [--entrant NAME] [--receipts DIR] [--json OUT]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path


def upper_bound_95(faults: int, n: int) -> float | None:
    """Clopper-Pearson one-sided 95 percent upper bound (bisection on the binomial tail)."""
    if n == 0:
        return None
    if faults >= n:
        return 1.0

    def tail(p: float) -> float:  # P(X <= faults), summed in log space
        if p <= 0.0:
            return 1.0
        if p >= 1.0:
            return 0.0
        lp, lq = math.log(p), math.log1p(-p)
        logs = [math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1) + k * lp + (n - k) * lq
                for k in range(faults + 1)]
        top = max(logs)
        return math.exp(top) * sum(math.exp(x - top) for x in logs)

    lo, hi = faults / n, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if tail(mid) > 0.05:
            lo = mid
        else:
            hi = mid
    return hi


def _read_log(path: Path) -> tuple[dict | None, list[dict], dict | None]:
    """(header, records, terminal availability record or None)."""
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    header = records[0] if records and records[0].get("kind") == "header" else None
    final = records[-1] if records and records[-1].get("kind") == "availability" else None
    return header, records, final


def _ledger_games(ledgers: list[Path], entrant: str | None) -> dict[tuple[str, str], dict]:
    """(game_id, seat) of the entrant in every ledger row."""
    games = {}
    for ledger in ledgers:
        for line in ledger.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            for seat in row.get("seats", []):
                if entrant is None or seat.get("name") == entrant:
                    games[(row["game_id"], seat["seat"])] = row
    return games


def _bot_refusals(tally: dict) -> dict[str, int]:
    return {key[8:]: n for key, n in tally.items() if key.startswith("refusal:")}


def _reconcile(receipts: Path, game: str, seat: str, final: dict, records: list[dict]) -> dict:
    """One game's engine-side receipts against the entrant's record. The
    bridge counts a refusal at every eligible decision it refuses and the
    entrant once per unit (a buffered group once), so the two must name the
    same refusal subclasses, the bridge with at least the entrant's count of
    each, and the bridge's subclass counts must cover its code counts."""
    safe = "".join(c if c.isalnum() or c == "-" else "_" for c in game)
    out: dict = {"game_id": game, "seat": seat}
    bridge_path, adapter_path = receipts / f"{safe}.bridge.json", receipts / f"{safe}.adapter.json"
    if not bridge_path.exists():
        out["error"] = "bridge receipt missing"
        out["reconciled"] = False
        return out
    if not adapter_path.exists():
        out["error"] = "adapter receipt missing"
        out["reconciled"] = False
        return out
    adapter = json.loads(adapter_path.read_text(encoding="utf-8"))
    bridge = json.loads(bridge_path.read_text(encoding="utf-8"))
    # The bridge counts by native seat; the adapter seats the starting player
    # as native p0.
    native = adapter.get("native_seats", {}).get(seat)
    if native not in ("p0", "p1"):
        out["error"] = "adapter receipt lacks the seat mapping"
        out["reconciled"] = False
        return out
    index = 0 if native == "p0" else 1
    side = bridge["tally"][index]
    engine_refusals = dict(side.get("by_subclass", {}))
    bot_refusals = _bot_refusals(final["tally"])
    by_code: Counter[str] = Counter()
    for key, n in engine_refusals.items():
        by_code[key.split(":", 1)[0]] += n
    # A committing group's later native points are posed by the bridge but
    # shown to no bot; the adapter tallies them by native seat.
    internal = adapter.get("internal", {}).get(native, {"eligible": 0, "refusals": {}})
    expected_refusals = Counter(bot_refusals)
    expected_refusals.update(internal["refusals"])
    out.update(native_seat=native, bridge_eligible=bridge["eligible"][index],
               entrant_units=final["eligible"] + final.get("r3_ineligible", 0) + final.get("own_ineligible", 0),
               internal_eligible=internal["eligible"], internal_refusals=internal["refusals"],
               bridge_refusals=engine_refusals, entrant_refusals=bot_refusals,
               bridge_order_map_missing=bridge["order_map_missing"][index],
               composition=adapter["composition"])
    # Exact: the bridge's eligible decisions are the entrant's units plus the
    # internal ones, its refusals by subclass likewise, and its code counts
    # are the sums of its subclasses.
    out["reconciled"] = (out["bridge_eligible"] == out["entrant_units"] + internal["eligible"]
                         and engine_refusals == {k: n for k, n in expected_refusals.items() if n}
                         and dict(by_code) == {k: n for k, n in side.get("by_code", {}).items() if n})
    # G6: every committed group with a composition re-traced the previewed
    # points and committed the rows of its wire answer's completion, and the
    # entrant's completed walks planned exactly those rows.
    groups = adapter.get("groups", [])
    checked = [g for g in groups if g.get("composition")]
    out["commit_groups"] = len(checked)
    out["commit_ok"] = all(g.get("views_equal") and g.get("keys_equal") for g in checked)
    mine = [g for g in checked if g.get("root_seat") == native]
    plans = [r for r in records if r.get("kind") == "group_plan" and r.get("mode") == "walk"]
    # Pi may stop before the last point (one completion left): its rows and
    # its points' tensors are a prefix of the committed ones, never longer.
    # Every point whose tensors differ fails. Each is classified: a
    # known-hand divergence when the known opponent hands differ and the
    # known-hand-masked digests are equal (kernel_g6_digest; the export's
    # knowledge follows V's information where the engine's known-hand rows
    # follow copies, R5), else a drift. A divergence stays unverified: the
    # observation digest, which includes the known hand, cannot be compared
    # without it until the kernel reports one.
    divergent: list[dict] = []
    drifted: list[dict] = []

    def at(record: dict, key: str, i: int):
        values = record.get(key) or []
        return values[i] if i < len(values) else None

    def point_matches(r: dict, g: dict, i: int) -> bool:
        if r["tensors"][i] == g["committed_tensors"][i]:
            return True
        masked = (at(r, "masked_tensors", i), at(g, "committed_masked_tensors", i))
        hands = (at(r, "known_hands", i), at(g, "committed_known_hands", i))
        known_hand = None not in masked and None not in hands and masked[0] == masked[1] and hands[0] != hands[1]
        (divergent if known_hand else drifted).append({"step": r.get("step"), "point": i})
        return False

    out["plans_match"] = len(plans) == len(mine) and all(
        len(r["plan"]) <= len(g.get("committed_keys") or [])
        and r["plan"] == g["committed_keys"][:len(r["plan"])]
        and len(r.get("tensors", [])) == len(r["plan"])
        and len(g.get("committed_tensors", [])) >= len(r["plan"])
        and all([point_matches(r, g, i) for i in range(len(r["plan"]))])
        for r, g in zip(plans, mine))
    out["known_hand_divergent_points"] = divergent
    out["drifted_points"] = drifted
    # Witnesses: the groups rooted at this seat (each counted once per game).
    out["witness"] = {k: sum(1 for g in mine if g.get("witness", {}).get(k))
                      for k in ("multi_attacker", "multi_blocker", "three_triggers")}
    out["reconciled"] = out["reconciled"] and out["commit_ok"] and out["plans_match"]
    return out


def report(paths: list[Path], ledgers: list[Path] | None = None, entrant: str | None = None,
           receipts: Path | None = None) -> dict:
    tally: Counter[str] = Counter()
    games, c5, eligible, searched, searches, zero_tree_searches, transitions = 0, 0, 0, 0, 0, 0, []
    r3_ineligible, search_errors, group_over_cap, allowance_over, unbalanced = 0, 0, 0, [], 0
    own_ineligible = 0
    seen: set[tuple[str, str]] = set()
    duplicates, incomplete, unledgered, reconciliation = [], [], [], []
    ledger = _ledger_games(ledgers, entrant) if ledgers else None
    for root in paths:
        for path in sorted(root.glob("*.jsonl")):
            header, records, final = _read_log(path)
            if header is None or final is None:
                incomplete.append(path.name)
                continue
            if entrant is not None and header.get("bot_name") != entrant:
                continue
            key = (header["game_id"], header["seat"])
            if key in seen:
                duplicates.append(path.name)
                continue
            seen.add(key)
            if ledger is not None and key not in ledger:
                unledgered.append(path.name)
                continue
            games += 1
            tally.update(final["tally"])
            c5 += final["c5_faults"]
            eligible += final["eligible"]
            searched += final["searched_decisions"]
            r3_ineligible += final.get("r3_ineligible", 0)
            own_ineligible += final.get("own_ineligible", 0)
            charged = final["tally"].get("units_charged", 0)
            if (final["allowance_remaining"] < 0 or charged > final["allowance"]
                    or charged != final["allowance"] - final["allowance_remaining"]):
                allowance_over.append(path.name)
            for record in records:
                if record.get("kind") != "search":
                    continue
                # Every attempt, failed ones included, logs its balances.
                if "allowance_remaining" not in record or "group_remaining" not in record:
                    unbalanced += 1
                elif record["allowance_remaining"] < 0:
                    allowance_over.append(f"{path.name}:{record.get('step')}")
                if record.get("group_remaining") is not None and record["group_remaining"] < 0:
                    group_over_cap += 1
                if "tree_transitions" in record:
                    searches += 1
                    trees = record["tree_transitions"]
                    transitions.extend(trees)
                    zero_tree_searches += any(t == 0 for t in trees)
                else:
                    search_errors += 1
            if receipts is not None:
                reconciliation.append(_reconcile(receipts, *key, final, records))
    missing = sorted(f"{g}.{s}" for g, s in (set(ledger) - seen)) if ledger is not None else []
    policy = {key[7:]: n for key, n in sorted(tally.items()) if key.startswith("policy:")}
    faults = {key[6:]: n for key, n in sorted(tally.items()) if key.startswith("fault:")}
    refusals = {key[8:]: n for key, n in sorted(tally.items()) if key.startswith("refusal:")}
    unclassified = sum(n for key, n in refusals.items() if key.endswith(":unclassified"))
    # Allowance-limited eligible decisions, in the unit of `eligible` (a
    # buffered group counts once): ordinary decisions answered by policy for
    # the allowance, plus groups with at least one point decided by policy
    # for it. Points are reported separately.
    allowance_limited = tally["policy:allowance"] + tally["allowance_groups"]
    bound = upper_bound_95(c5, eligible)
    # G6 (AC3 committed trajectories): reported with its own witness bar
    # (design 13: 5 multi-attacker, 5 multi-blocker, 1 three-trigger group);
    # a short run may not reach it, which the report says.
    witness = {k: sum(r.get("witness", {}).get(k, 0) for r in reconciliation)
               for k in ("multi_attacker", "multi_blocker", "three_triggers")}
    commit_check = None if receipts is None else {
        "groups": sum(r.get("commit_groups", 0) for r in reconciliation),
        "all_ok": all(r.get("commit_ok", False) and r.get("plans_match", False) for r in reconciliation),
        # Walked points whose tensors differ, by class (each fails G6).
        "known_hand_divergent_points": sum(len(r.get("known_hand_divergent_points", [])) for r in reconciliation),
        "drifted_points": sum(len(r.get("drifted_points", [])) for r in reconciliation),
        "witness": witness,
        "witnesses_met": witness["multi_attacker"] >= 5 and witness["multi_blocker"] >= 5
        and witness["three_triggers"] >= 1}
    checks = {
        # Gate inputs: the declared ledger (naming the entrant), the receipts
        # and at least one counted game, so no check passes vacuously.
        "entrant_given": entrant is not None,
        "ledger_given": bool(ledger),
        "receipts_given": receipts is not None,
        "games_counted": games > 0,
        "every_search_balanced": unbalanced == 0,
        "one_log_per_game_and_seat": not duplicates,
        "every_log_complete": not incomplete,
        "every_ledger_game_logged": not missing,
        "charge_within_allowance": not allowance_over,
        "group_charge_within_cap": group_over_cap == 0,
        "no_unclassified_refusal": unclassified == 0,
        "receipts_reconcile": all(r.get("reconciled") for r in reconciliation),
    }
    return {
        "games": games, "eligible": eligible, "searched_decisions": searched, "group_walk_answers": tally["walk"],
        "searches": searches, "search_errors": search_errors, "attempted_searches": searches + search_errors,
        "searches_with_a_zero_transition_tree": zero_tree_searches,
        "tree_transitions": {"trees": len(transitions), "min": min(transitions, default=None),
                             "median": sorted(transitions)[len(transitions) // 2] if transitions else None,
                             "max": max(transitions, default=None)},
        "units_charged": tally["units_charged"], "policy_by_reason": policy, "c5_by_reason": faults,
        "allowance_limited": {"decisions": tally["policy:allowance"], "groups": tally["allowance_groups"],
                              "group_points": tally["allowance_points"],
                              "share_of_eligible": None if not eligible else allowance_limited / eligible},
        "group_points": {"searched": tally["searched_points"], "policy": tally["policy_points"]},
        "c5_faults": c5, "c5_share": None if not eligible else c5 / eligible, "c5_upper_95": bound,
        "c5_pass_below_1pct": None if bound is None else bound < 0.01,
        "searched_share_of_eligible": None if not eligible else searched / eligible,
        # Amendment 43.1: R3 decisions are ineligible, reported beside the units.
        "r3_ineligible": r3_ineligible,
        # Amendment 43.2: V's own library searches are ineligible; their share
        # of eligible-plus-own units, and the declared 2 percent soak trigger
        # (above it, exporting the searched library returns to the lead).
        "own_ineligible": own_ineligible,
        "own_share": None if not eligible + own_ineligible else own_ineligible / (eligible + own_ineligible),
        "own_share_over_2pct": None if not eligible + own_ineligible
        else own_ineligible / (eligible + own_ineligible) > 0.02,
        # Amendment 43.1 part 2: every refusal by code and subclass (decisions
        # and group roots); "unclassified" means the bridge sent no subclass.
        "refusals_by_subclass": refusals,
        "unclassified_refusals": unclassified,
        "logs": {"counted": games, "duplicates": duplicates, "incomplete": incomplete, "unledgered": unledgered,
                 "missing_for_ledger_games": missing, "ledger_games": None if ledger is None else len(ledger)},
        "charge": {"games_over_allowance": allowance_over, "searches_over_group_cap": group_over_cap},
        "receipts": reconciliation if receipts is not None else None,
        "commit_check": commit_check,
        "checks": checks, "checks_pass": all(checks.values()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("logs", nargs="+", type=Path)
    parser.add_argument("--ledger", action="append", type=Path, help="a run's matches.jsonl (repeatable)")
    parser.add_argument("--entrant", help="the entrant's bot name in the ledger")
    parser.add_argument("--receipts", type=Path, help="the engine-side receipt directory")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    result = report(args.logs, args.ledger, args.entrant, args.receipts)
    text = json.dumps(result, indent=2, sort_keys=True)
    print(text)
    if args.json:
        args.json.write_text(text + "\n", encoding="utf-8")
    return 0 if result["checks_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
