"""X5 diagnostic: replays plan games (global ids) and prints the last decisions each seat saw before the game ended.

    python lastdec.py --plan plan.json --gids 1,2 [--last N] -- ENGINE...
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


def _short(d: dict) -> dict:
    obs = d.get("observation", {})
    return {
        "seat_step": d.get("seat_step"), "turn": obs.get("turn"), "phase": obs.get("phase_step"),
        "context": d.get("context"), "group": d.get("group"),
        "stack": [(s.get("kind"), (s.get("source") or {}).get("card_name") if isinstance(s.get("source"), dict)
                   else s.get("card_name"), s.get("targets")) for s in obs.get("stack", [])],
        "battlefield": {p.get("seat"): [o.get("card_name") for o in p.get("battlefield", [])]
                        for p in obs.get("players", [])},
        "candidates": [c.get("semantic") for c in d.get("candidates", [])][:12],
    }


def main(argv: list[str]) -> int:
    split = argv.index("--")
    options, engine = argv[:split], argv[split + 1:]
    opts = dict(zip(options[::2], options[1::2]))
    plan = json.loads(open(opts["--plan"], encoding="utf-8").read())
    last = int(opts.get("--last", "3"))
    sched = x5run.Schedule(plan, engine)
    setups = x5run._setups(sched)
    x5run._init(plan, engine, setups, None)
    try:
        for gid in (int(x) for x in opts["--gids"].split(",")):
            w, index = sched.games[gid]
            item = sched.workloads[w]
            context = item["contexts"][index]
            logs: dict[str, list] = {"p0": [], "p1": []}
            seats = {seat: BuiltinDriver(spec, factory=lambda s=seat, n=spec.name: Recording(
                create_builtin_bot(n, seed=0), logs[s])) for seat, spec in context.seat_specs}
            result = play_game(game_setup(item["config"], setups[item["pool"]], context, item["secret"]),
                               engine=x5run._engine(), seats=seats)
            for d in seats.values():
                d.close()
            print(json.dumps({"gid": gid, "reason": result.reason, "game_digest": result.game_digest}))
            for seat in ("p0", "p1"):
                for d in logs[seat][-last:]:
                    print(seat, json.dumps(_short(d), ensure_ascii=False))
            if result.classification != "natural":
                x5run._close()
    finally:
        x5run._close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
