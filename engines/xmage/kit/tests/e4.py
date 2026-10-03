"""E4 from kit evidence logs (A1 result reviews: change 7 and the second review's item 5), against the thresholds
written before measuring in kit/evidence/E4-threshold.md.

MAD (clause 1, 25%): per priority search whose worlds hold a horizon-flagged stack object, the share of evaluated
root alternatives whose subtree met the horizon at least once (affected over evaluated; never above 1). Horizon
encounters (stops counted per node) are reported separately. Decisions answered without search (the E4 outcome,
the register) are counted as declined.

MCTS (clause 2, 50%): every actual MCTS search counts once, priority and combat alike (a decision line that carries
MCTS counters: a combat group is searched at its first substep only). Completed iterations split into actual
rollouts (the `simulate` counter), terminal-node results and empty expansions. The clause-2 share is truncated
rollouts over actual rollouts; truncated expansions over all expanded children is reported beside it. Both are given
with their denominators, per search kind and in total.

    python e4.py LOG [LOG ...]
"""

import json
import os
import sys

MCTS_KEYS = {"iterations": "mcts:iterations", "actual_rollouts": "simulate", "truncated_rollouts": "mcts:truncated_rollouts",
             "terminal_results": "mcts:terminal_results", "empty_expansions": "mcts:empty_expansion",
             "expanded_children": "mcts:expanded_children", "truncated_expansions": "mcts:truncated_expansions",
             "horizon_rollout_stops": "horizon:mcts_rollout", "horizon_expansion_stops": "horizon:mcts_expansion",
             "rollout_cap_stops": "cap:rollout", "non_stack_excluded": "mcts:non_stack_dialog_excluded"}


def ratio(a, b):
    return round(a / b, 4) if b else None


def mcts_block():
    return dict({k: 0 for k in MCTS_KEYS}, searches=0)


def finish(m):
    m["clause2_truncated_rollout_share"] = {"truncated": m["truncated_rollouts"], "actual_rollouts": m["actual_rollouts"],
                                            "share": ratio(m["truncated_rollouts"], m["actual_rollouts"]),
                                            "over_threshold": (ratio(m["truncated_rollouts"], m["actual_rollouts"]) or 0) > 0.5}
    children = m["expanded_children"] + m["truncated_expansions"]
    m["truncated_expansion_share"] = {"truncated": m["truncated_expansions"], "children": children,
                                      "share": ratio(m["truncated_expansions"], children)}
    return m


def summarize(paths):
    """The E4 report over these kit logs (MAD clause 1, MCTS clause 2), as a dict."""
    anchors = []
    declined = 0
    mcts = {"priority": mcts_block(), "combat": mcts_block()}
    for path in paths:
        for line in open(path, encoding="utf-8"):
            r = json.loads(line)
            if r.get("event") != "decision":
                continue
            p = r.get("path") or ""
            if "approximate_state_without_search" in p:
                declined += 1
            c = r.get("counters") or {}
            if c.get("mcts:iterations"):
                kind = "combat" if r.get("kind") in ("declare_attack", "declare_block") else "priority"
                block = mcts[kind]
                block["searches"] += 1
                for k, key in MCTS_KEYS.items():
                    block[k] += c.get(key, 0)
                continue
            if p not in ("priority_anchor", "priority_forced") and not p.startswith("fallback_ranked"):
                continue
            flags = r.get("world_flags") or []
            if "horizon:stack_object" not in flags:
                continue
            evaluated = r.get("root_alternatives") or 0
            affected = r.get("root_alternatives_horizon") or 0
            anchors.append({"log": os.path.basename(os.path.dirname(path)), "game_id": r.get("game_id"),
                            "seat_step": r["seat_step"], "evaluated_root_alternatives": evaluated,
                            "affected_root_alternatives": affected, "horizon_encounters": c.get("horizon:mad", 0),
                            "share": ratio(affected, evaluated),
                            "causes": sorted({f.split(":")[1] for f in flags if f.startswith("approximate:")})})
    total = mcts_block()
    for b in mcts.values():
        for k in total:
            total[k] += b[k]
    over = [a for a in anchors if a["share"] is not None and a["share"] > 0.25]
    out = {"mad": {"flagged_searches": len(anchors), "over_threshold": len(over),
                   "evaluated_root_alternatives": sum(a["evaluated_root_alternatives"] for a in anchors),
                   "affected_root_alternatives": sum(a["affected_root_alternatives"] for a in anchors),
                   "horizon_encounters": sum(a["horizon_encounters"] for a in anchors),
                   "shares_above_one": sum(1 for a in anchors if a["share"] is not None and a["share"] > 1),
                   "declined_without_search": declined, "anchors": anchors},
           "mcts": {"priority": finish(mcts["priority"]), "combat": finish(mcts["combat"]), "total": finish(total)}}
    return out


def main():
    print(json.dumps(summarize(sys.argv[1:]), indent=1))


if __name__ == "__main__":
    main()
