"""Offline complete-game v2 validation and deterministic replay; no agents."""
from __future__ import annotations
import argparse
import hashlib
import json
import random
from pathlib import Path

from kernel_engine_v2 import KernelEngine, NativePeer
from spellbench import wire
from spellbench.digests import deck_id, card_name_domain
from spellbench.host.validator import LiveValidator
from spellbench.messages import EnvHelloOk, Rules, Decision, Terminal


def check(executable, catalog, deck, first, extensions, *, diagnostics=None):
    peers = [NativePeer(executable), NativePeer(executable)]
    engines = [KernelEngine(peer, catalog) for peer in peers]
    serial = 0
    digest = hashlib.sha256()
    def exchange(value):
        nonlocal serial
        serial += 1
        request = {"protocol": "spellbench/v2", "request_id": f"q{serial}", **value}
        payload = wire.canonical_json_dumps(request)
        answers = [engine.handle(payload) for engine in engines]
        assert answers[0] == answers[1], "v2 deterministic replay diverged"
        assert engines[0].handle(payload) == answers[0], "exact retry changed its answer"
        digest.update(answers[0])
        return wire.strict_json_loads(answers[0])
    try:
        hello = EnvHelloOk.from_json(exchange({"request_type": "hello", "protocol_minor": 0}))
        rows = next(entry["decklist"] for entry in catalog["catalog"] if entry["catalog_id"] == deck)
        rules = {"opponent_decklist": "visible", "mulligan": "none", "starting_player": "host_assigned",
            "starting_seat": first, "card_name_domain": card_name_domain(row["name"] for row in rows),
            "extensions": extensions, "probe": False}
        validator = LiveValidator(hello, Rules.from_json(rules), max_decisions=2048, max_steps=4096)
        current = exchange({"request_type": "reset", "game_id": f"v2-check-{deck}-{first}", "format": "pauper-bo1",
            "seats": [{"seat": seat, "deck": {"catalog_id": deck, "deck_id": deck_id(rows)}} for seat in ("p0", "p1")],
            "rules": rules, "game_secret": hashlib.sha256(b"offline-kernel-v2-fixture-5151").hexdigest(),
            "max_decisions": 2048, "max_steps": 4096})
        rng = random.Random(101)
        kinds = set()
        last_native = None
        while current["response_type"] == "decision":
            sd = validator.check(Decision.from_json(current))
            kinds.update(candidate["semantic"]["kind"] for candidate in sd["candidates"])
            candidate = rng.randrange(len(sd["candidates"]))
            validator.answered(sd, candidate)
            last_native = engines[0].current
            current = exchange({"request_type": "step", "game_id": current["game_id"], "expected_step": current["step"],
                "selection": {"candidate_id": candidate, "semantic_echo": sd["candidates"][candidate]["semantic"]}})
        if current["response_type"] != "terminal":
            raise AssertionError(current)
        validator.check_terminal(Terminal.from_json(current))
        if current["classification"] != "natural":
            if diagnostics is not None:
                diagnostics.mkdir(parents=True, exist_ok=True)
                failure = diagnostics / f"v2-failure-{deck}.json"
                failure.write_text(json.dumps(engines[0].current), encoding="utf-8")
                (diagnostics / f"v2-before-failure-{deck}.json").write_text(json.dumps(last_native), encoding="utf-8")
                print(f"Native failure saved at {failure}", flush=True)
            raise AssertionError(current)
        return {"deck": deck, "first_seat": first, "extensions": extensions,
            "steps": current["step_count"], "groups": current["decision_count"], "outcome": current["outcome"],
            "decision_kinds": sorted(kinds), "replay_equal": True, "exact_retry_equal": True,
            "trace_sha256": digest.hexdigest(), "model_requests": 0}
    finally:
        for peer in peers:
            peer.close()


def check_buffer_cap_reset(executable, catalog):
    """Exercise an actual reset cap inside a group, then reuse the environment."""
    fixture_deck = "Elves"
    rows = next(entry["decklist"] for entry in catalog["catalog"] if entry["catalog_id"] == fixture_deck)
    rules = {"opponent_decklist": "visible", "mulligan": "none", "starting_player": "host_assigned",
        "starting_seat": "p0", "card_name_domain": card_name_domain(row["name"] for row in rows),
        "extensions": [], "probe": False}
    reset = {"request_type": "reset", "format": "pauper-bo1",
        "seats": [{"seat": seat, "deck": {"catalog_id": fixture_deck, "deck_id": deck_id(rows)}} for seat in ("p0", "p1")],
        "rules": rules, "game_secret": hashlib.sha256(b"offline-kernel-v2-fixture-5151").hexdigest(),
        "max_decisions": 2048, "max_steps": 4096}
    cap = None
    for attempt in ("find", "cap"):
        peer = NativePeer(executable)
        engine = KernelEngine(peer, catalog)
        serial = 0
        def exchange(value):
            nonlocal serial
            serial += 1
            payload = wire.canonical_json_dumps({"protocol": "spellbench/v2", "request_id": f"cap-{serial}", **value})
            answer = engine.handle(payload)
            assert engine.handle(payload) == answer, "cap/reset retry diverged"
            return wire.strict_json_loads(answer)
        try:
            current = exchange({**reset, "game_id": "buffer-cap-fixture", "max_steps": cap or 4096})
            first_decision = current["seat_decision"]
            rng = random.Random(101)
            while current["response_type"] == "decision":
                sd = current["seat_decision"]
                group = sd["group"]
                if attempt == "find" and engine.buffer is not None and group["substep_count"] > 1:
                    cap = current["step"] + 1
                    break
                candidate = rng.randrange(len(sd["candidates"]))
                current = exchange({"request_type": "step", "game_id": current["game_id"], "expected_step": current["step"],
                    "selection": {"candidate_id": candidate, "semantic_echo": sd["candidates"][candidate]["semantic"]}})
            if attempt == "find":
                assert cap is not None, "fixture did not reach a buffered group"
                continue
            assert current["classification"] == "truncated" and current["reason"] == "max_steps", current
            assert engine.buffer is not None and engine.current["response_type"] == "decision"
            old_pid = peer.child.pid
            next_game = exchange({**reset, "game_id": "buffer-cap-next-game"})
            assert next_game["response_type"] == "decision", next_game
            assert peer.child.pid != old_pid, "unfinished native child was reused"
            assert next_game["seat_decision"] == first_decision, "reset retained prior game state"
            return {"deck": fixture_deck, "max_steps": cap, "classification": "truncated",
                "native_child_restarted": True, "next_reset_equals_fresh": True, "exact_retry_equal": True,
                "model_requests": 0}
        finally:
            peer.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bridge", required=True)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--deck", action="append")
    parser.add_argument("--diagnostics", type=Path)
    args = parser.parse_args()
    catalog = json.loads(args.catalog.read_bytes())
    records = []
    for deck in args.deck or [entry["catalog_id"] for entry in catalog["catalog"]]:
        record = check(args.bridge, catalog, deck, "p0", [], diagnostics=args.diagnostics)
        records.append(record)
        print(json.dumps(record), flush=True)
    result = {"schema": "spellbench-kernel-v2-offline-replay/v1", "records": records,
        "buffer_cap_reset": check_buffer_cap_reset(args.bridge, catalog), "model_requests": 0,
        "bridge_sha256": hashlib.sha256(Path(args.bridge).read_bytes()).hexdigest(),
        "catalog_sha256": hashlib.sha256(args.catalog.read_bytes()).hexdigest()}
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
