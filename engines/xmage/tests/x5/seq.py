"""X5 diagnostic: plays plan games (global ids) in sequence in ONE engine process and prints each game's digests.

    python seq.py --plan plan.json --gids 1,2,3 [--positions 0-43] -- ENGINE...

``--positions A-B`` takes the global order's positions A to B inclusive. Used to find games whose digest depends
on the games played before them in the same engine process (spec 11.8).
"""

from __future__ import annotations

import json
import sys

import x5run


def main(argv: list[str]) -> int:
    split = argv.index("--")
    options, engine = argv[:split], argv[split + 1:]
    opts = dict(zip(options[::2], options[1::2]))
    plan = json.loads(open(opts["--plan"], encoding="utf-8").read())
    sched = x5run.Schedule(plan, engine)
    gids: list[int] = []
    if "--positions" in opts:
        a, b = (int(x) for x in opts["--positions"].split("-"))
        gids += [sched.order[p] for p in range(a, b + 1)]
    if "--gids" in opts:
        gids += [int(x) for x in opts["--gids"].split(",")]
    setups = x5run._setups(sched)
    x5run._init(plan, engine, setups, None)
    try:
        for gid in gids:
            row = x5run.play_global(gid)
            print(json.dumps({"gid": gid, "workload": row["workload"], "game_digest": row["row"]["game_digest"],
                              "steps": row["row"]["step_count"], "reason": row["row"]["reason"]}), flush=True)
            if row["row"]["classification"] != "natural" and x5run._W.get("engine") is not None:
                lines = x5run._W["engine"].stderr_text().splitlines()
                for line in lines[-int(opts.get("--stderr-lines", "60")):]:
                    print("  stderr: " + line, flush=True)
    finally:
        x5run._close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
