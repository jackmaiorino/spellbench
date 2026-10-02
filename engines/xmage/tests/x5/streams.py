"""X5 diagnostic: plays one plan game (global id) and writes both seats' seat_decision streams as JSON lines.

    python streams.py --plan plan.json --gid N --out FILE -- ENGINE...

Two runs of the same game must write identical files (spec 11.8); the first differing line names the decision
where a run went its own way.
"""

from __future__ import annotations

import json
import sys

import x5run
from leak import Recording
from spellbench.arena.drivers import BuiltinDriver
from spellbench.arena.schedule import game_setup
from spellbench.builtins import create_builtin_bot
from spellbench.host.game import play_game


def main(argv: list[str]) -> int:
    split = argv.index("--")
    options, engine = argv[:split], argv[split + 1:]
    opts = dict(zip(options[::2], options[1::2]))
    plan = json.loads(open(opts["--plan"], encoding="utf-8").read())
    sched = x5run.Schedule(plan, engine)
    setups = x5run._setups(sched)
    x5run._init(plan, engine, setups, None)
    gid = int(opts["--gid"])
    w, index = sched.games[gid]
    item = sched.workloads[w]
    context = item["contexts"][index]
    log: list = []
    seats = {seat: BuiltinDriver(spec, factory=lambda n=spec.name: Recording(create_builtin_bot(n, seed=0), log))
             for seat, spec in context.seat_specs}
    try:
        result = play_game(game_setup(item["config"], setups[item["pool"]], context, item["secret"]),
                           engine=x5run._engine(), seats=seats)
    finally:
        for d in seats.values():
            d.close()
        x5run._close()
    with open(opts["--out"], "w", encoding="utf-8", newline="\n") as out:
        for d in log:
            out.write(json.dumps(d, sort_keys=True, ensure_ascii=False) + "\n")
    print(json.dumps({"gid": gid, "reason": result.reason, "game_digest": result.game_digest, "decisions": len(log)}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
