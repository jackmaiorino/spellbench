"""A scripted person for the play server: it reads the page's state and answers like a hurried human.

usage: python human_autoplay.py URL_WITH_TOKEN [--games N] [--seed S]

Combat screens get plans (attack with every listed creature, no blocks); other decisions pick a random non-pass
candidate half the time. Between games it presses "next". Used to smoke-test a session end to end.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import urllib.request
from urllib.parse import parse_qs, urlparse


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--games", type=int, default=1)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    url = urlparse(args.url)
    base = f"{url.scheme}://{url.netloc}"
    token = parse_qs(url.query)["t"][0]
    rng = random.Random(args.seed)

    def call(path: str, body: dict | None = None) -> dict:
        request = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(),
                                         method="GET" if body is None else "POST",
                                         headers={"X-Human-Token": token, "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read())

    version, answered, done = -1, set(), 0
    while True:
        state = call(f"/api/state?since={version}")
        version = state["version"]
        if len(state["results"]) > done:
            done = len(state["results"])
            print("game", done, state["results"][-1], flush=True)
            if done >= args.games:
                return 0
        if state["hello_waiting"]:
            call("/api/control", {"action": "next" if state["game"] else "start"})
            continue
        pending = state["pending"]
        if pending is None or pending["seq"] in answered:
            continue
        answered.add(pending["seq"])
        if pending["screen"] == "attack":
            attackers = sorted({c["semantic"]["attacker"]["object_id"] for c in pending["candidates"]})
            mine = [c["object_id"] for p in state["observation"]["players"] if p["seat"] == state["game"]["seat"]
                    for c in p["battlefield"] if "creature" in c["characteristics"]["types"]]
            result = call("/api/plan", {"seq": pending["seq"], "plan": {"kind": "attack", "attackers": attackers + mine}})
        elif pending["screen"] == "block":
            result = call("/api/plan", {"seq": pending["seq"], "plan": {"kind": "block", "blocks": {}}})
        else:
            options = [c for c in pending["candidates"] if c["kind"] != "pass"]
            passing = [c for c in pending["candidates"] if c["kind"] == "pass"]
            pick = rng.choice(options) if options and (not passing or rng.random() < 0.6) else passing[0]
            result = call("/api/answer", {"seq": pending["seq"], "candidate_id": pick["id"]})
        if "error" in result:
            print("refused:", result, file=sys.stderr, flush=True)


if __name__ == "__main__":
    sys.exit(main())
