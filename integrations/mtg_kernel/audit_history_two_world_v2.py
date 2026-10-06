"""Two-world audit of x_public_history_v1 and the knowledge tracker (Section 14).

Plays complete games through the real bridge with the history extension and
known_cards enabled, recording every private slice the adapter absorbs and
every per-viewer output it produces. For each viewer it then builds a second
world that differs only in hidden cards: the names of every card that viewer
never saw (never in a public zone, never drawn, revealed or looked at by it)
are permuted among themselves. Replaying the second world through a fresh
tracker must give that viewer byte-identical history and knowledge at every
one of its decisions. A difference means a hidden identity reached the viewer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from copy import deepcopy
from pathlib import Path

from kernel_engine_v2 import HISTORY, KernelEngine, NativePeer
from kernel_history_v2 import PUBLIC_ZONES, PublicHistory
from spellbench import wire
from spellbench.digests import card_name_domain, deck_id
from spellbench.host.validator import LiveValidator
from spellbench.messages import Decision, EnvHelloOk, Rules, Terminal


class Recorder:
    """Records absorbed slices and per-viewer outputs of one game, in order."""

    def __init__(self):
        self.ops = []

    def install(self):
        recorder, absorb, drain, knowledge = self, PublicHistory.absorb, PublicHistory.drain, PublicHistory.knowledge

        def recorded_absorb(history, value):
            recorder.ops.append(("absorb", deepcopy(value)))
            return absorb(history, value)

        def recorded_drain(history, viewer, projection):
            result = drain(history, viewer, projection)
            current = {arena: ref["object_id"] for (arena, _zcc, _zone), ref in projection.stable_refs.items()}
            recorder.ops.append(("drain", viewer, current, dict(projection.seat_map), result))
            return result

        def recorded_knowledge(history, viewer):
            result = knowledge(history, viewer)
            recorder.ops.append(("knowledge", viewer, public_knowledge(result)))
            return result

        PublicHistory.absorb, PublicHistory.drain, PublicHistory.knowledge = (
            recorded_absorb, recorded_drain, recorded_knowledge)
        return absorb, drain, knowledge


def public_knowledge(knowledge: dict) -> dict:
    """What the viewer is shown, minus native ids and the omniscient check."""
    return {"library": {owner: {position: (fact["name"], fact["how"]) for position, fact in facts.items()}
                        for owner, facts in knowledge["library"].items()},
            "hand": {owner: sorted((fact["name"], fact["how"]) for fact in facts)
                     for owner, facts in knowledge["hand"].items()}}


class Replay:
    seat_map: dict
    stable_refs: dict

    def __init__(self, current: dict, seat_map: dict):
        self.stable_refs = {(arena, 0, "zone"): {"object_id": object_id} for arena, object_id in current.items()}
        self.seat_map = seat_map

    def seat(self, native):
        return self.seat_map[native]


def seen_by(slices: list, viewer: int) -> set[int]:
    """Native objects whose identity the viewer could learn: its own draws,
    anything that touched a public zone, and every look or reveal it got."""
    seen = set()
    owners = {entry["object"]: entry["owner"] for value in slices for entry in value["objects"]}
    for value in slices:
        for event in value["events"]:
            (kind, body), = event.items()
            if kind == "Draw" and body["player"] == viewer and body["object"] is not None:
                seen.add(body["object"])
            elif kind == "ZoneChange" and (body["from"].lower() in PUBLIC_ZONES or body["to"].lower() in PUBLIC_ZONES
                                           or owners[body["object"]] == viewer):
                # An owner sees its own cards move between its hidden zones
                # (it picks the tutored card, it sees what it puts back).
                seen.add(body["object"])
            elif kind in ("SpellCast", "CreateToken"):
                seen.add(body["spell" if kind == "SpellCast" else "object"])
        for note in value["notes"]:
            kind = note["kind"]
            if kind == "library_looked" and note["observer"] == viewer:
                seen.update(native for _, native in note["positions"])
            elif kind == "library_reordered" and viewer in note["revealed_to"]:
                seen.update(note["ordered"])
            elif kind == "library_scried" and note["owner"] == viewer:
                seen.update(note["retained_top"] + note["ordered_bottom"])
            elif kind == "hand_card_revealed" and note["observer"] == viewer:
                seen.add(note["object"])
    return seen


def second_world(slices: list, viewer: int, seed: int) -> tuple[list, int]:
    """The slices with every card unseen by the viewer renamed by a
    permutation within its owner; returns the slices and how many names moved."""
    seen = seen_by(slices, viewer)
    objects = [entry for value in slices for entry in value["objects"]]
    rng = random.Random(seed)
    renamed = {}
    for owner in (0, 1):
        hidden = [entry["object"] for entry in objects if entry["owner"] == owner and entry["object"] not in seen
                  and not entry["is_token"] and not entry["copy"]]
        names = [objects[native]["card_name"] for native in hidden]
        shuffled = names[:]
        rng.shuffle(shuffled)
        renamed.update(zip(hidden, shuffled))
    world = deepcopy(slices)
    moved = 0
    for value in world:
        for entry in value["objects"]:
            if entry["object"] in renamed:
                moved += entry["card_name"] != renamed[entry["object"]]
                entry["card_name"] = renamed[entry["object"]]
    return world, moved


def audit_game(ops: list, seed: int) -> dict:
    slices = [op[1] for op in ops if op[0] == "absorb"]
    report = {}
    for viewer in (0, 1):
        world, moved = second_world(slices, viewer, seed + viewer)
        replay, worlds = PublicHistory(), iter(world)
        compared = 0
        for op in ops:
            if op[0] == "absorb":
                replay.absorb(next(worlds))
            elif op[0] == "drain" and op[1] == viewer:
                if replay.drain(viewer, Replay(op[2], op[3])) != op[4]:
                    raise AssertionError(f"viewer {viewer}: history differs in the second world at op {compared}")
                compared += 1
            elif op[0] == "drain":
                replay.drain(op[1], Replay(op[2], op[3]))
            elif op[0] == "knowledge" and op[1] == viewer:
                if public_knowledge(replay.knowledge(viewer)) != op[2]:
                    raise AssertionError(f"viewer {viewer}: knowledge differs in the second world at op {compared}")
                compared += 1
        report[f"p{viewer}"] = {"renamed": moved, "compared": compared}
    return report


def play(bridge: str, catalog: dict, deck: str, first: str, seed: int) -> tuple[dict, list]:
    recorder = Recorder()
    originals = recorder.install()
    try:
        engine = KernelEngine(NativePeer(bridge), catalog, known_cards=True)
        serial = 0

        def exchange(value):
            nonlocal serial
            serial += 1
            payload = wire.canonical_json_dumps({"protocol": "spellbench/v2", "request_id": f"q{serial}", **value})
            return wire.strict_json_loads(engine.handle(payload))

        hello = EnvHelloOk.from_json(exchange({"request_type": "hello", "protocol_minor": 0}))
        rows = next(entry["decklist"] for entry in catalog["catalog"] if entry["catalog_id"] == deck)
        rules = {"opponent_decklist": "visible", "mulligan": "none", "starting_player": "host_assigned",
                 "starting_seat": first, "card_name_domain": card_name_domain(row["name"] for row in rows),
                 "extensions": [HISTORY], "probe": False}
        validator = LiveValidator(hello, Rules.from_json(rules), max_decisions=2048, max_steps=4096)
        current = exchange({"request_type": "reset", "game_id": f"two-world-{deck}-{first}-{seed}",
            "format": "pauper-bo1",
            "seats": [{"seat": seat, "deck": {"catalog_id": deck, "deck_id": deck_id(rows)}} for seat in ("p0", "p1")],
            "rules": rules, "game_secret": hashlib.sha256(f"two-world-{seed}".encode()).hexdigest(),
            "max_decisions": 2048, "max_steps": 4096})
        rng = random.Random(seed)
        while current["response_type"] == "decision":
            sd = validator.check(Decision.from_json(current))
            candidate = rng.randrange(len(sd["candidates"]))
            validator.answered(sd, candidate)
            current = exchange({"request_type": "step", "game_id": current["game_id"],
                "expected_step": current["step"],
                "selection": {"candidate_id": candidate, "semantic_echo": sd["candidates"][candidate]["semantic"]}})
        validator.check_terminal(Terminal.from_json(current))
        engine.peer.close()
        return {"classification": current["classification"], "reason": current.get("reason")}, recorder.ops
    finally:
        PublicHistory.absorb, PublicHistory.drain, PublicHistory.knowledge = originals


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bridge", required=True)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--seeds", type=int, nargs="+", default=[7])
    args = parser.parse_args()
    catalog = json.loads(args.catalog.read_bytes())
    failures = 0
    for seed in args.seeds:
        for entry in catalog["catalog"]:
            for first in ("p0", "p1"):
                outcome, ops = play(args.bridge, catalog, entry["catalog_id"], first, seed)
                try:
                    outcome["two_world"] = audit_game(ops, seed)
                except AssertionError as exc:
                    failures += 1
                    outcome["two_world"] = f"FAILED: {exc}"
                print(json.dumps({"deck": entry["catalog_id"], "first": first, "seed": seed, **outcome}), flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
