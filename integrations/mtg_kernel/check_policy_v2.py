"""Offline v2 complete-game check with pinned real policies; no model API calls."""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path

from kernel_engine_v2 import KernelEngine, NativePeer, FLAT
from kernel_flat_bot import KernelFlatBot, ScorerProcess, PROPOSAL_SCHEMA
from spellbench import wire
from spellbench.bot import Decision as BotDecision, GameStart
from spellbench.digests import deck_id, card_name_domain
from spellbench.host.validator import LiveValidator
from spellbench.messages import EnvHelloOk, Rules, Decision, Terminal


class ReplayScorer:
    def __init__(self, scorer):
        self.scorer, self.ready = scorer, scorer.ready
        self.counts = {"ordinary": 0, "completion": 0}
        self.digest = hashlib.sha256()

    def score(self, request):
        first = self.scorer.score(request)
        assert self.scorer.score(request) == first, "native score replay diverged"
        self.counts["completion" if request["schema"] == PROPOSAL_SCHEMA else "ordinary"] += 1
        self.digest.update(first[0])
        self.digest.update(wire.canonical_json_dumps(first[1]))
        return first

    def close(self):
        self.scorer.close()


def check(bridge, scorer_executable, config, catalog, deck, *, diagnostics=None):
    peer = NativePeer(bridge)
    engine = KernelEngine(peer, catalog)
    scorer = ReplayScorer(ScorerProcess([scorer_executable, "--config", str(config)]))
    bot = KernelFlatBot(scorer, seed=111, decision_log=None, name=config.stem,
                        version="pauper-v2.0.0", expect_model_state=scorer.ready["model_state_sha256"])
    serial = 0
    digest = hashlib.sha256()

    def exchange(value):
        nonlocal serial
        serial += 1
        payload = wire.canonical_json_dumps({"protocol": "spellbench/v2", "request_id": f"policy-{serial}", **value})
        answer = engine.handle(payload)
        assert engine.handle(payload) == answer, "exact request retry changed the decision"
        digest.update(answer)
        return wire.strict_json_loads(answer)

    try:
        hello = EnvHelloOk.from_json(exchange({"request_type": "hello", "protocol_minor": 0}))
        rows = next(entry["decklist"] for entry in catalog["catalog"] if entry["catalog_id"] == deck)
        rules = {"opponent_decklist": "visible", "mulligan": "none", "starting_player": "host_assigned",
                 "starting_seat": "p1", "card_name_domain": card_name_domain(row["name"] for row in rows),
                 "extensions": [FLAT], "probe": False}
        validator = LiveValidator(hello, Rules.from_json(rules), max_decisions=2048, max_steps=4096)
        game = f"offline-policy-v2-{config.stem}-{deck}"
        bot.on_game_start(GameStart.from_request({"game_id": game, "seat": "p0", "engine": engine.hello["engine"]}))
        current = exchange({"request_type": "reset", "game_id": game, "format": "pauper-bo1",
            "seats": [{"seat": seat, "deck": {"catalog_id": deck, "deck_id": deck_id(rows)}} for seat in ("p0", "p1")],
            "rules": rules, "game_secret": hashlib.sha256(b"offline-policy-v2-5151").hexdigest(),
            "max_decisions": 2048, "max_steps": 4096})
        rng = random.Random(101)
        kinds = set()
        while current["response_type"] == "decision":
            sd = validator.check(Decision.from_json(current))
            kinds.update(candidate["semantic"]["kind"] for candidate in sd["candidates"])
            selected = (bot.choose(BotDecision.from_request({"game_id": game, "decision": sd}))
                        if sd["acting_seat"] == "p0" else rng.randrange(len(sd["candidates"])))
            validator.answered(sd, selected)
            current = exchange({"request_type": "step", "game_id": game, "expected_step": current["step"],
                "selection": {"candidate_id": selected, "semantic_echo": sd["candidates"][selected]["semantic"]}})
        validator.check_terminal(Terminal.from_json(current))
        if current["classification"] != "natural":
            if diagnostics:
                diagnostics.mkdir(parents=True, exist_ok=True)
                (diagnostics / f"policy-failure-{config.stem}-{deck}.json").write_text(json.dumps(engine.current), encoding="utf-8")
            raise AssertionError(current)
        return {"policy": config.stem, "config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
            "model_state_sha256": scorer.ready["model_state_sha256"], "deck": deck, "first_seat": "p1",
            "steps": current["step_count"], "groups": current["decision_count"], "outcome": current["outcome"],
            "score_counts": scorer.counts, "score_replay_equal": True, "exact_retry_equal": True,
            "trace_sha256": digest.hexdigest(), "score_sha256": scorer.digest.hexdigest(),
            "decision_kinds": sorted(kinds), "model_api_requests": 0}
    finally:
        bot.close()
        peer.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bridge", required=True)
    parser.add_argument("--scorer", required=True)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path, action="append")
    parser.add_argument("--deck", action="append")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--diagnostics", type=Path)
    args = parser.parse_args()
    records = []
    catalog = json.loads(args.catalog.read_bytes())
    for deck in args.deck or ["Rally"]:
        for config in args.config:
            record = check(args.bridge, args.scorer, config, catalog, deck,
                           diagnostics=args.diagnostics)
            records.append(record)
            print(json.dumps(record), flush=True)
    args.output.write_text(json.dumps({"schema": "spellbench-kernel-v2-policy-check/v1", "records": records,
        "model_api_requests": 0,
        "bridge_sha256": hashlib.sha256(Path(args.bridge).read_bytes()).hexdigest(),
        "scorer_sha256": hashlib.sha256(Path(args.scorer).read_bytes()).hexdigest(),
        "catalog_sha256": hashlib.sha256(args.catalog.read_bytes()).hexdigest()}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
