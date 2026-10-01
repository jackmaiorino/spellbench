"""E4 from kit evidence logs (A1 result review, change 7: corrected accounting), against the thresholds written
before measuring in kit/evidence/E4-threshold.md.

MAD (clause 1, 25%): per priority anchor whose worlds hold a horizon-flagged stack object, the share of the
evaluated root alternatives whose subtree met the horizon at least once (affected root alternatives over evaluated
root alternatives; never above 1). Horizon encounters (how often a search stopped at the horizon, counted per node)
are reported separately and are not part of the share. Anchors answered without search (the E4 outcome, the
register) are counted as declined.

MCTS (clause 2, 50%): truncated rollouts over completed rollouts, and truncated expansions over expanded children,
reported separately; horizon stops in rollouts and in expansion, and rollout-cap stops, as counts.

    python e4.py LOG [LOG ...]
"""

import json
import os
import sys


def ratio(a, b):
    return round(a / b, 3) if b else None


def main():
    anchors = []
    declined = 0
    mcts = {"iterations": 0, "simulations": 0, "truncated_rollouts": 0, "expanded_children": 0,
            "truncated_expansions": 0, "horizon_rollout_stops": 0, "horizon_expansion_stops": 0, "rollout_cap_stops": 0}
    for path in sys.argv[1:]:
        for line in open(path, encoding="utf-8"):
            r = json.loads(line)
            if r.get("event") != "decision":
                continue
            p = r.get("path") or ""
            if "approximate_state_without_search" in p:
                declined += 1
            if p not in ("priority_anchor", "priority_forced") and not p.startswith("fallback_ranked"):
                continue
            c = r.get("counters") or {}
            mcts["iterations"] += c.get("mcts:iterations", 0)
            mcts["simulations"] += c.get("mcts:simulations", 0)
            mcts["truncated_rollouts"] += c.get("mcts:truncated_rollouts", 0)
            mcts["expanded_children"] += c.get("mcts:expanded_children", 0)
            mcts["truncated_expansions"] += c.get("mcts:truncated_expansions", 0)
            mcts["horizon_rollout_stops"] += c.get("horizon:mcts_rollout", 0)
            mcts["horizon_expansion_stops"] += c.get("horizon:mcts_expansion", 0)
            mcts["rollout_cap_stops"] += c.get("cap:rollout", 0)
            flags = r.get("world_flags") or []
            if "horizon:stack_object" not in flags or c.get("mcts:iterations"):
                continue
            evaluated = r.get("root_alternatives") or 0
            affected = r.get("root_alternatives_horizon") or 0
            anchors.append({"log": os.path.basename(os.path.dirname(path)), "game_id": r.get("game_id"),
                            "seat_step": r["seat_step"], "evaluated_root_alternatives": evaluated,
                            "affected_root_alternatives": affected, "horizon_encounters": c.get("horizon:mad", 0),
                            "share": ratio(affected, evaluated),
                            "causes": sorted({f.split(":")[1] for f in flags if f.startswith("approximate:")})})
    over = [a for a in anchors if a["share"] is not None and a["share"] > 0.25]
    bad = [a for a in anchors if a["share"] is not None and a["share"] > 1]
    out = {"mad": {"flagged_anchors_searched": len(anchors), "over_threshold": len(over),
                   "shares_above_one": len(bad), "declined_without_search": declined, "anchors": anchors},
           "mcts": dict(mcts, truncated_rollout_share=ratio(mcts["truncated_rollouts"], mcts["simulations"]),
                        truncated_expansion_share=ratio(mcts["truncated_expansions"],
                                                        mcts["expanded_children"] + mcts["truncated_expansions"]))}
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
