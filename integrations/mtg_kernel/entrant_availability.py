"""Availability report for the W1 search entrant from its decision logs.

Reads every ``<game>.<seat>.jsonl`` written by kernel_search_bot.py
(``--decision-log``) and totals, per entrant: eligible decisions, searched
decisions and group walks, policy answers by reason (refusal predicate R1 to
R8b, allowance, order map, faults), C5 faults with a one-sided 95 percent
upper bound on their share of eligible decisions (design 13 AC5), searches,
units charged and tree transitions.

Usage: python entrant_availability.py LOG_DIR [LOG_DIR ...] [--json OUT]
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


def report(paths: list[Path]) -> dict:
    tally: Counter[str] = Counter()
    games, c5, eligible, searched, searches, zero_tree_searches, transitions = 0, 0, 0, 0, 0, 0, []
    r3_ineligible = 0
    for root in paths:
        for path in sorted(root.glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                record = json.loads(line)
                kind = record.get("kind")
                if kind == "availability":
                    games += 1
                    tally.update(record["tally"])
                    c5 += record["c5_faults"]
                    eligible += record["eligible"]
                    searched += record["searched_decisions"]
                    r3_ineligible += record.get("r3_ineligible", 0)
                elif kind == "search" and "tree_transitions" in record:
                    searches += 1
                    trees = record["tree_transitions"]
                    transitions.extend(trees)
                    zero_tree_searches += any(t == 0 for t in trees)
    policy = {key[7:]: n for key, n in sorted(tally.items()) if key.startswith("policy:")}
    faults = {key[6:]: n for key, n in sorted(tally.items()) if key.startswith("fault:")}
    # Allowance-limited eligible decisions, in the unit of `eligible` (a
    # buffered group counts once): ordinary decisions answered by policy for
    # the allowance, plus groups with at least one point decided by policy
    # for it. Points are reported separately.
    allowance_limited = tally["policy:allowance"] + tally["allowance_groups"]
    bound = upper_bound_95(c5, eligible)
    return {
        "games": games, "eligible": eligible, "searched_decisions": searched, "group_walk_answers": tally["walk"],
        "searches": searches, "searches_with_a_zero_transition_tree": zero_tree_searches,
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
        # Amendment 43.1 part 2: every refusal by code and subclass (decisions
        # and group roots); "unclassified" means the bridge sent no subclass.
        "refusals_by_subclass": {key[8:]: n for key, n in sorted(tally.items()) if key.startswith("refusal:")},
        "unclassified_refusals": sum(n for key, n in tally.items()
                                     if key.startswith("refusal:") and key.endswith(":unclassified")),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("logs", nargs="+", type=Path)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    result = report(args.logs)
    text = json.dumps(result, indent=2, sort_keys=True)
    print(text)
    if args.json:
        args.json.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
