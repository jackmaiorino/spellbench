"""E4 from kit evidence logs: per priority anchor whose world holds a flagged (approximate) stack object, the share of
MAD's root alternatives that ended at the search horizon, against the threshold of kit/evidence/E4-threshold.md
(clause 1: 25%); and the MCTS truncation share (clause 2: 50%).

    python e4.py LOG [LOG ...]
"""

import json
import os
import sys


def main():
    anchors = []
    mcts = {"iterations": 0, "truncated": 0, "horizon": 0}
    for path in sys.argv[1:]:
        for line in open(path, encoding="utf-8"):
            r = json.loads(line)
            if r.get("event") != "decision" or r.get("path") != "priority_anchor":
                continue
            c = r.get("counters") or {}
            mcts["iterations"] += c.get("mcts:iterations", 0)
            mcts["truncated"] += c.get("mcts:truncated_rollouts", 0)
            mcts["horizon"] += c.get("horizon:mcts_expansion", 0) + c.get("horizon:mcts_rollout", 0)
            flags = r.get("world_flags") or []
            if not any(f.startswith("horizon:stack_object") for f in flags):
                continue
            alt = r.get("root_alternatives") or 0
            stops = c.get("horizon:mad", 0)
            anchors.append({"log": os.path.basename(os.path.dirname(path)), "seat_step": r["seat_step"],
                            "horizon_stops": stops, "root_alternatives": alt,
                            "share": round(stops / alt, 3) if alt else None,
                            "causes": sorted({f.split(":")[1] for f in flags if f.startswith("approximate:stack")})})
    over = [a for a in anchors if a["share"] is not None and a["share"] > 0.25]
    out = {"flagged_anchors": len(anchors), "over_threshold": len(over), "anchors": anchors,
           "mcts": dict(mcts, truncated_share=round(mcts["truncated"] / mcts["iterations"], 3) if mcts["iterations"] else None)}
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
