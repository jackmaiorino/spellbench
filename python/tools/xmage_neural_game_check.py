"""One unrated Exp1 full-game correctness check and one identical-seed replay.

Run only inside the supervising guarded job. This writes diagnostic outcomes
and public traffic, never a rated tournament, commitment or leaderboard.
"""
from __future__ import annotations

import argparse
import contextlib
import dataclasses
import hashlib
import json
from pathlib import Path

from spellbench import digests, wire
from spellbench.agent_messages import OwnDeck
from spellbench.arena.config import BotSpec
from spellbench.arena.drivers import BuiltinDriver, SubprocessDriver
from spellbench.host.engine_process import EngineProcess
from spellbench.host.game import play_game
from spellbench.host.setup import GameSetup
from spellbench.messages import CardNameDomain, Limits, Resources, Rules, TimeControl, WireDeck
from spellbench.run_secret import RunSecret


class RecordingDriver:
    def __init__(self, driver, traffic):
        self.driver, self.traffic = driver, traffic
        self.process = None

    def start(self, payload, *, timeout_s):
        self.traffic.write(wire.canonical_json_dumps({"event": "game_start", "payload": payload}) + b"\n")
        self.traffic.flush()
        try:
            return self.driver.start(payload, timeout_s=timeout_s)
        finally:
            self.process = getattr(self.driver, "_agent", None)

    def choose(self, payload, *, timeout_s):
        self.traffic.write(wire.canonical_json_dumps({"event": "choose", "payload": payload}) + b"\n")
        self.traffic.flush()
        result = self.driver.choose(payload, timeout_s=timeout_s)
        self.traffic.write(wire.canonical_json_dumps({"event": "choice", "candidate_id": result.candidate_id}) + b"\n")
        self.traffic.flush()
        return result

    def game_over(self, payload, *, timeout_s):
        self.traffic.write(wire.canonical_json_dumps({"event": "game_over", "payload": payload}) + b"\n")
        self.traffic.flush()
        return self.driver.game_over(payload, timeout_s=timeout_s)

    def close(self):
        self.driver.close()

    def stderr_text(self):
        return "" if self.process is None else self.process.stderr_text()


def one(plan, out, index):
    time_control = TimeControl.from_json(plan["time_control"])
    model = BotSpec(name=plan["agent"]["name"], version=plan["agent"]["version"], type="subprocess",
                    command=tuple(plan["agent"]["command"]))
    baseline = BotSpec(name="heuristic", version="2.0.0", type="builtin")
    secret = RunSecret.from_hex(plan["run_secret"])
    with contextlib.ExitStack() as stack:
        engine = EngineProcess(plan["engine_command"], timeout_s=time_control.startup_ms / 1000)
        stack.callback(engine.close)
        hello = engine.hello()
        if plan["format"] not in hello.formats:
            raise ValueError("full-game diagnostic format is not offered")
        decks = [next(d for d in hello.catalog if d.catalog_id == catalog) for catalog in plan["decks"]]
        own = tuple(OwnDeck(digests.deck_id([r.to_json() for r in deck.decklist]), deck.name, deck.decklist)
                    for deck in decks)
        domain = digests.card_name_domain([row.name for deck in decks for row in deck.decklist])
        rules = Rules("visible", "london", "host_assigned", "p0", CardNameDomain.from_json(domain), (), False)
        setup = GameSetup(0, secret.game_id(0), secret.game_secret(0).hex(), plan["format"],
                          tuple(WireDeck(deck.deck_id, catalog_id=catalog) for deck, catalog in zip(own, plan["decks"])),
                          own, rules, time_control, Limits(10000, 100000, 500, 4999, 49999),
                          Resources(2, 4096, False, 1),
                          (secret.agent_seed(0, "p0"), secret.agent_seed(0, "p1")))
        raw_model = SubprocessDriver(model, startup_ms=time_control.startup_ms)
        raw_baseline = BuiltinDriver(baseline)
        stack.callback(raw_model.close)
        stack.callback(raw_baseline.close)
        traffic = stack.enter_context((out / f"public-traffic-{index}.jsonl").open("xb"))
        model_driver = RecordingDriver(raw_model, traffic)
        seats = {"p0": model_driver, "p1": raw_baseline}
        try:
            result = play_game(setup, engine=engine, seats=seats)
        finally:
            # Capture diagnostics before SubprocessDriver forgets its peer.
            (out / f"model-stderr-{index}.txt").write_text(model_driver.stderr_text(), encoding="utf-8")
            (out / f"engine-stderr-{index}.txt").write_text(engine.stderr_text(), encoding="utf-8")
    return dataclasses.asdict(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    raw = args.plan.read_bytes()
    if hashlib.sha256(raw).hexdigest() != args.plan_sha256:
        raise ValueError("prepared full-game diagnostic plan changed")
    plan = json.loads(raw)
    if plan.get("schema") != "spellbench-neural-game-check-plan/v1" or plan.get("rated_games") != 0:
        raise ValueError("full-game check needs its unrated diagnostic plan")
    args.out.mkdir(exist_ok=False, parents=True)
    report = {"schema": "spellbench-neural-game-check/v1", "plan_sha256": args.plan_sha256,
              "rated_games": 0, "published": False, "exit_code": 2, "games": []}
    try:
        for index in range(2):
            result = one(plan, args.out, index)
            report["games"].append(result)
            if result["classification"] != "natural" or result["violation"] is not None:
                raise ValueError("full-game diagnostic did not complete naturally; see retained public traffic and stderr")
        # Timing and stderr are diagnostic. The primary outcome store contains
        # the validated deterministic result fields only.
        stores = [wire.canonical_json_dumps({k: v for k, v in result.items() if k != "diagnostics"})
                  for result in report["games"]]
        for index, payload in enumerate(stores):
            (args.out / f"primary-{index}.json").write_bytes(payload + b"\n")
        report["primary_store_sha256"] = [hashlib.sha256(p + b"\n").hexdigest() for p in stores]
        if stores[0] != stores[1]:
            raise ValueError("identical-seed full-game primary stores differ")
        report.update(exit_code=0, replay_identical=True)
    except BaseException as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        with (args.out / "CHECK.json").open("x", encoding="utf-8") as target:
            json.dump(report, target, indent=2)
            target.write("\n")
    print(json.dumps({"exit_code": report["exit_code"],
                      "natural_games": sum(g["classification"] == "natural" for g in report["games"]),
                      "error": report.get("error"), "rated_games": 0}))
    return report["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
