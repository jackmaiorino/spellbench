"""Offline complete-game validation of the human-play London engine; no agents, no model.

Plays whole games through `kernel_engine_london_human_v1.py` over the London bridge with scripted answers, validates
every decision with the host's live validator (the same one a rated run uses), replays each game on a second engine
for byte equality, and records what the opening did: mulligans taken per seat, the `mulligan_bottom` groups, hand
sizes. A pregame answer script is `keep`, `mulligan` (to zero cards) or `random`.

    python check_engine_london_human_v1.py --bridge <agent_bridge_v1.exe> --catalog <pauper-v2-catalog.json> \
        --output <result.json> [--deck Burn] [--script random] [--seed 5]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kernel_engine_london_human_v1 import FLAT, HISTORY, KernelEngine, NativePeer  # noqa: E402
from spellbench import wire  # noqa: E402
from spellbench.digests import card_name_domain, deck_id  # noqa: E402
from spellbench.host.validator import LiveValidator  # noqa: E402
from spellbench.messages import Decision, EnvHelloOk, Rules, Terminal  # noqa: E402

NATIVE_IDENTITY_MARKERS = ("obj-", "arena_id", "x_kernel_v5")


def assert_no_native_identity(message):
    text = message.decode("utf-8") if isinstance(message, bytes) else message
    found = [marker for marker in NATIVE_IDENTITY_MARKERS if marker in text]
    if found:
        raise AssertionError(f"bot-facing message carries native identity: {', '.join(found)}")


def foreign_refs(value, viewer, zones):
    """Object references in ``value`` owned by the other seat in one of ``zones``."""
    found = []
    if isinstance(value, dict):
        if value.get("object_id") and value.get("owner_seat") not in (None, viewer) and value.get("zone") in zones:
            found.append(value)
        for item in value.values():
            found += foreign_refs(item, viewer, zones)
    elif isinstance(value, list):
        for item in value:
            found += foreign_refs(item, viewer, zones)
    return found


def pick(rng, script, semantics):
    kinds = {s["kind"] for s in semantics}
    if kinds == {"mulligan"} and script != "random":
        want = script == "keep"
        return next(i for i, s in enumerate(semantics) if s["keep"] is want)
    return rng.randrange(len(semantics))


def check(executable, catalog, deck, first, extensions, *, script="random", seed=101, secret=b"london-human-fixture-4242"):
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
        assert answers[0] == answers[1], "London deterministic replay diverged"
        assert engines[0].handle(payload) == answers[0], "exact retry changed its answer"
        assert_no_native_identity(answers[0])
        digest.update(answers[0])
        return wire.strict_json_loads(answers[0])

    try:
        hello = EnvHelloOk.from_json(exchange({"request_type": "hello", "protocol_minor": 0}))
        rows = next(entry["decklist"] for entry in catalog["catalog"] if entry["catalog_id"] == deck)
        rules = {"opponent_decklist": "visible", "mulligan": "london", "starting_player": "host_assigned",
                 "starting_seat": first, "card_name_domain": card_name_domain(row["name"] for row in rows),
                 "extensions": extensions, "probe": False}
        validator = LiveValidator(hello, Rules.from_json(rules), max_decisions=4096, max_steps=8192)
        current = exchange({"request_type": "reset", "game_id": f"london-check-{deck}-{first}-{seed}", "format": "pauper-bo1",
                            "seats": [{"seat": seat, "deck": {"catalog_id": deck, "deck_id": deck_id(rows)}} for seat in ("p0", "p1")],
                            "rules": rules, "game_secret": hashlib.sha256(secret + str(seed).encode()).hexdigest(),
                            "max_decisions": 4096, "max_steps": 8192})
        rng = random.Random(seed)
        kinds = set()
        pregame_scanned = [0]
        pregame = {"p0": [], "p1": []}
        groups = []
        last_taken = {"p0": 0, "p1": 0}
        while current["response_type"] == "decision":
            sd = validator.check(Decision.from_json(current))
            semantics = [c["semantic"] for c in sd["candidates"]]
            kinds.update(s["kind"] for s in semantics)
            seat = sd["acting_seat"]
            kind = semantics[0]["kind"]
            if sd["observation"]["phase_step"] == "pregame":
                # Hidden information: a pregame decision never names, lists or counts as a card the other seat's
                # hand or library, and shows the other seat's hand as a count only.
                other = sd["observation"]["players"][1 if seat == "p0" else 0]
                assert other["hand"] is None, "the other seat's hand is listed in the pregame"
                leaked = foreign_refs(sd, seat, ("hand", "library"))
                assert not leaked, f"pregame decision names the other seat's cards: {leaked[:2]}"
                pregame_scanned[0] += 1
            if kind == "mulligan":
                pregame[seat].append(("mulligan", semantics[0]["hand_size"], semantics[0]["mulligans_taken"]))
                assert sd["observation"]["phase_step"] == "pregame" and sd["observation"]["turn"] == 0
                assert sd["observation"]["players"][0 if seat == "p0" else 1]["hand_count"] == semantics[0]["hand_size"]
            if kind == "order_pick" and semantics[0]["purpose"] == "mulligan_bottom":
                g = sd["group"]
                assert g["substep_count"] == semantics[0]["count"] and g["substep_index"] == semantics[0]["position"], (g, semantics[0])
                assert len(semantics) == sd["observation"]["players"][0 if seat == "p0" else 1]["hand_count"], "one item per hand card"
                groups.append((seat, g["substep_index"], g["substep_count"]))
            candidate = pick(rng, script, semantics)
            validator.answered(sd, candidate)
            current = exchange({"request_type": "step", "game_id": current["game_id"], "expected_step": current["step"],
                                "selection": {"candidate_id": candidate, "semantic_echo": sd["candidates"][candidate]["semantic"]}})
        if current["response_type"] != "terminal":
            raise AssertionError(current)
        validator.check_terminal(Terminal.from_json(current))
        if current["classification"] != "natural":
            raise AssertionError(current)
        return {"deck": deck, "first_seat": first, "script": script, "seed": seed, "extensions": extensions,
                "steps": current["step_count"], "groups": current["decision_count"], "outcome": current["outcome"],
                "mulligan_decisions": {seat: len(rows) for seat, rows in pregame.items()},
                "bottom_substeps": len(groups), "pregame_decisions_leak_scanned": pregame_scanned[0], "decision_kinds": sorted(kinds), "replay_equal": True,
                "exact_retry_equal": True, "trace_sha256": digest.hexdigest(), "model_requests": 0}
    finally:
        for peer in peers:
            peer.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bridge", required=True)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--deck", action="append")
    parser.add_argument("--script", choices=("keep", "mulligan", "random"), default="random")
    parser.add_argument("--seed", type=int, action="append")
    parser.add_argument("--first", choices=("p0", "p1"), action="append")
    parser.add_argument("--extension", action="append", choices=(FLAT, HISTORY), default=[])
    args = parser.parse_args()
    catalog = json.loads(args.catalog.read_bytes())
    records = []
    for deck in args.deck or [entry["catalog_id"] for entry in catalog["catalog"]]:
        for seed in args.seed or [101]:
            for first in args.first or ["p0"]:
                record = check(args.bridge, catalog, deck, first, args.extension, script=args.script, seed=seed)
                records.append(record)
                print(json.dumps(record), flush=True)
    result = {"schema": "spellbench-kernel-london-human-offline-replay/v1", "records": records, "model_requests": 0,
              "bridge_sha256": hashlib.sha256(Path(args.bridge).read_bytes()).hexdigest(),
              "catalog_sha256": hashlib.sha256(args.catalog.read_bytes()).hexdigest()}
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
