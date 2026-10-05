"""E8 runtime costs from kit evidence: per game set, decisions per kit seat per game, the share answered without a
world (single candidate, plan, ComputerPlayer7's passing steps), priority anchors per game, world build and search
times per anchor, node-cap firings, and game wall times.

    python costs.py SET_DIR [SET_DIR ...]      (each with kit-log.jsonl and games.jsonl)
"""

import json
import os
import statistics
import sys


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else None


def main():
    out = {}
    for d in sys.argv[1:]:
        rows = [json.loads(l) for l in open(os.path.join(d, "kit-log.jsonl"), encoding="utf-8")]
        games = [json.loads(l) for l in open(os.path.join(d, "games.jsonl"), encoding="utf-8")]
        dec = [r for r in rows if r.get("event") == "decision"]
        per_game = {}
        for r in dec:
            per_game.setdefault(r.get("game_id"), []).append(r)
        no_world = [r for r in dec if r["path"] in ("single", "plan", "plan_forced", "cp7_passes_in_step")]
        cp7 = [r for r in dec if r["path"] == "cp7_passes_in_step"]
        anchors = [r for r in dec if r["path"] == "priority_anchor" or r["path"].startswith("fallback_declining:approximate")]
        build = [r["build_ms"] for r in anchors if isinstance(r.get("build_ms"), int)]
        search = [r["search_ms"] for r in anchors if isinstance(r.get("search_ms"), int)]
        total = [r["ms"] for r in dec]
        nodecap = sum(1 for r in anchors if (r.get("nodes") or 0) > 5000)
        out[os.path.basename(os.path.normpath(d))] = {
            "games": len(games),
            "kit_decisions_per_game": round(len(dec) / max(1, len(per_game)), 1),
            "answered_without_a_world": round(len(no_world) / len(dec), 3) if dec else None,
            "cp7_passing_steps_share_of_multi_candidate": round(len(cp7) / max(1, sum(1 for r in dec if r["candidates"] > 1)), 3),
            "anchors_per_game": round(len(anchors) / max(1, len(per_game)), 1),
            "build_ms": {"median": statistics.median(build), "p90": pct(build, 0.9), "max": max(build)} if build else None,
            "search_ms": {"median": statistics.median(search), "p90": pct(search, 0.9), "max": max(search)} if search else None,
            "decision_ms_all": {"median": statistics.median(total), "p90": pct(total, 0.9), "max": max(total)} if total else None,
            "kit_ms_per_game": round(sum(total) / max(1, len(per_game)) / 1000, 1),
            "node_cap_fired": nodecap,
            "game_wall_s": {"mean": round(statistics.mean(g["wall_s"] for g in games), 1),
                            "max": max(g["wall_s"] for g in games)} if games else None,
        }
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
