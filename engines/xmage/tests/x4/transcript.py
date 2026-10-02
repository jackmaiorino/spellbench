"""X4 debugging aid: play scheduled games in one engine process (as a soak shard does) and write one game's engine
responses, one canonical JSON line each, so two runs can be compared line by line.

    PYTHONPATH=<p2>/python python transcript.py --run-secret HEX --games N --play 2,14,74 --record 74 \
        --out t.jsonl [--bots first,uniform] -- <engine argv...>
"""

from __future__ import annotations

import argparse
import json
import sys

from spellbench.arena.drivers import BuiltinDriver
from spellbench.arena.schedule import EnginePin, game_setup, preflight, schedule
from spellbench.host.engine_process import EngineProcess
from spellbench.host.game import play_game
from spellbench.run_secret import RunSecret

from soak import make_config


class Recording(EngineProcess):
    log: list | None = None

    def reset(self, request):
        response = super().reset(request)
        if self.log is not None:
            self.log.append(self.last_response)
        return response

    def step(self, **kwargs):
        response = super().step(**kwargs)
        if self.log is not None:
            self.log.append(self.last_response)
        return response


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-secret", required=True)
    parser.add_argument("--games", type=int, required=True)
    parser.add_argument("--play", required=True)
    parser.add_argument("--record", type=int, required=True)
    parser.add_argument("--bots", default="first,uniform")
    parser.add_argument("--out", required=True)
    parser.add_argument("engine", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    argv = args.engine[1:] if args.engine and args.engine[0] == "--" else args.engine
    config = make_config(argv, "standard-2022-25-bo1", ["Standard16-RG", "Standard16-UB"], args.games,
                         tuple(args.bots.split(",")))
    secret = RunSecret.from_hex(args.run_secret)
    pin = EnginePin()
    setup = preflight(config, secret, pin=pin)
    contexts = {c.game_index: c for c in schedule(config, secret)}
    engine = Recording(list(config.engine_command), timeout_s=300)
    engine.hello()
    try:
        for index in [int(i) for i in args.play.split(",")]:
            context = contexts[index]
            seats = {seat: BuiltinDriver(spec) for seat, spec in context.seat_specs}
            engine.log = [] if index == args.record else None
            try:
                result = play_game(game_setup(config, setup, context, secret), engine=engine, seats=seats)
            finally:
                for driver in seats.values():
                    driver.close()
            print(index, result.game_digest, file=sys.stderr)
            if index == args.record:
                with open(args.out, "w", encoding="utf-8") as out:
                    for message in engine.log:
                        out.write(json.dumps(message, sort_keys=True, separators=(",", ":")) + "\n")
    finally:
        engine.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
