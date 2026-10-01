"""Summaries of kit front evidence logs (one JSON line per decision; game_start, game_over and rewind events).

    python kitlog.py LOG [LOG ...] [--detail]

Prints the counts of answer tags and paths per decision kind, the cap and wrapper rates, the world flags seen, the
priority-anchor timings (world build and search, per world), and the runner restarts, as one JSON document.
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import Counter


def load(paths):
    rows = []
    for p in paths:
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    return rows


def pct(xs, q):
    xs = sorted(xs)
    if not xs:
        return None
    return xs[min(len(xs) - 1, int(q * len(xs)))]


def summarize(rows):
    d = [r for r in rows if r.get("event") == "decision"]
    tags = Counter(r["tag"] for r in d)
    paths = Counter(r["path"].split(":")[0] for r in d)
    by_kind = {}
    for r in d:
        k = by_kind.setdefault(r["kind"], Counter())
        k[r["tag"]] += 1
    flags = Counter()
    for r in d:
        for f in r.get("world_flags") or []:
            flags[f.split(":")[0] + ":" + f.split(":")[1] if ":" in f else f] += 1
    anchors = [r for r in d if r["path"] == "priority_anchor"]
    build = [r["build_ms"] for r in anchors if isinstance(r.get("build_ms"), int)]
    search = [r["search_ms"] for r in anchors if isinstance(r.get("search_ms"), int)]
    total = [r["ms"] for r in anchors]
    nodes = [r.get("nodes", 0) for r in anchors]
    counters = Counter()
    for r in d:
        for k, v in (r.get("counters") or {}).items():
            counters[k] += v
    caps = [r for r in d if r["tag"] == "cap"]
    wrappers = Counter(r["path"] for r in d if r["tag"] == "wrapper")
    overs = [r for r in rows if r.get("event") == "game_over"]
    rts = [r for r in rows if r.get("event") == "roundtrip" and not r.get("failed")]
    rt_paths = Counter()
    for r in rts:
        for dpath in r.get("diff") or []:
            rt_paths["/".join(p for p in dpath.split(" ")[0].split("/") if not p.isdigit())] += 1
    roundtrip = {
        "checked": len(rts),
        "failed_calls": sum(1 for r in rows if r.get("event") == "roundtrip" and r.get("failed")),
        "exact": sum(1 for r in rts if r.get("exact")),
        "exact_rate": round(sum(1 for r in rts if r.get("exact")) / len(rts), 4) if rts else None,
        "by_kind": {k: {"checked": sum(1 for r in rts if r.get("kind") == k),
                        "exact": sum(1 for r in rts if r.get("kind") == k and r.get("exact"))}
                    for k in sorted({r.get("kind") for r in rts})},
        "by_phase": {k: {"checked": sum(1 for r in rts if r.get("phase_step") == k),
                         "exact": sum(1 for r in rts if r.get("phase_step") == k and r.get("exact"))}
                     for k in sorted({r.get("phase_step") for r in rts})},
        "diff_paths": dict(rt_paths.most_common(25)),
    } if rts else None
    return {
        "roundtrip": roundtrip,
        "decisions": len(d),
        "tags": dict(tags),
        "cap_rate": round(len(caps) / len(d), 4) if d else None,
        "wrapper_rate": round(tags.get("wrapper", 0) / len(d), 4) if d else None,
        "paths": dict(paths),
        "tags_by_kind": {k: dict(v) for k, v in by_kind.items()},
        "wrapper_paths": dict(wrappers),
        "world_flags": dict(flags),
        "priority_anchor": {
            "count": len(anchors),
            "approximate_world_share": round(sum(1 for r in anchors if any(
                f.startswith("approximate:") or f.startswith("unsupported:") for f in (r.get("world_flags") or []))) / len(anchors), 4) if anchors else None,
            "build_ms": {"median": statistics.median(build), "p90": pct(build, 0.9), "max": max(build)} if build else None,
            "search_ms": {"median": statistics.median(search), "p90": pct(search, 0.9), "max": max(search)} if search else None,
            "decision_ms": {"median": statistics.median(total), "p90": pct(total, 0.9), "max": max(total)} if total else None,
            "nodes": {"median": statistics.median(nodes), "max": max(nodes)} if nodes else None,
        },
        "search_counters": dict(counters),
        "rewinds": sum(1 for r in rows if r.get("event") == "rewind"),
        "continuation_mismatch": sum(1 for r in rows if r.get("event") == "continuation_mismatch"),
        "games_over": len(overs),
        "runner": [o.get("runner") for o in overs],
    }


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    rows = load(args)
    out = summarize(rows)
    if "--detail" in sys.argv:
        out["non_bot"] = [{k: r.get(k) for k in ("game_id", "seat_step", "kind", "path", "tag", "candidates", "candidate",
                                                 "cap", "runner_error", "ms")}
                          for r in rows if r.get("event") == "decision" and r["tag"] != "bot"]
    print(json.dumps(out, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
