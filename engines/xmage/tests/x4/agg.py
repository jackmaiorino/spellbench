"""Sums the per-game mapping counters an engine writes under SPELLBENCH_XMAGE_STATS (a directory of
stats-<pid>.jsonl files): each counter's total and the number of games it occurred in.

    python agg.py DIR [--json OUT]
"""

from __future__ import annotations

import collections
import glob
import json
import os
import sys


def main() -> int:
    paths = sorted(glob.glob(os.path.join(sys.argv[1], "stats-*.jsonl")))
    totals: collections.Counter[str] = collections.Counter()
    games_with: collections.Counter[str] = collections.Counter()
    games = 0
    for path in paths:
        for line in open(path, encoding="utf-8"):
            row = json.loads(line)
            games += 1
            for key, value in row["stats"].items():
                totals[key] += value
                games_with[key] += 1
    report = {"games": games, "counters": {k: {"total": totals[k], "games": games_with[k]} for k in sorted(totals)}}
    if "--json" in sys.argv:
        with open(sys.argv[sys.argv.index("--json") + 1], "w", encoding="utf-8") as out:
            json.dump(report, out, indent=1, sort_keys=True)
    print("games", games)
    for key in sorted(totals):
        print(f"{totals[key]:9d} {games_with[key]:5d} {key}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
