"""Hidden information in the London opening: what the human seat is shown never depends on the bot's hand or on
what it put on the bottom.

Two-world tests against the real London bridge (set MTG_KERNEL_LONDON_HUMAN_BRIDGE and MTG_KERNEL_PUBLIC_CATALOG;
skipped otherwise). The worlds share a seed, a deck pair and every answer of the human seat (p0, who keeps). They differ
only in the bot's (p1's) opening answers:

  A: the bot keeps seven.            B: it takes one mulligan, bottoms a card, keeps.
  C: as B, but bottoms a different card (a different name).

Every message the engine addresses to the human seat is compared through the human's first in-game decision. B and C
must be byte-identical (nothing about the bottomed card, its name or id, reaches the human); A and B may differ only in
the public counts the protocol makes public (the bot's mulligans taken, hand and library counts) and the public events
that follow from them.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

BRIDGE = os.environ.get("MTG_KERNEL_LONDON_HUMAN_BRIDGE")
CATALOG = os.environ.get("MTG_KERNEL_PUBLIC_CATALOG")
pytestmark = pytest.mark.skipif(not (BRIDGE and CATALOG and Path(BRIDGE).exists()),
                                reason="needs the London bridge and the public catalog")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE.parents[2] / "python"))

from kernel_engine_london_human_v1 import FLAT, HISTORY, KernelEngine, NativePeer  # noqa: E402
from spellbench import wire  # noqa: E402
from spellbench.digests import card_name_domain, deck_id  # noqa: E402


class World:
    def __init__(self, deck: str, seed: int) -> None:
        self.catalog = json.loads(Path(CATALOG).read_bytes())
        self.peer = NativePeer(BRIDGE)
        self.engine = KernelEngine(self.peer, self.catalog)
        rows = next(e["decklist"] for e in self.catalog["catalog"] if e["catalog_id"] == deck)
        self.serial = 0
        rules = {"opponent_decklist": "visible", "mulligan": "london", "starting_player": "host_assigned",
                 "starting_seat": "p0", "card_name_domain": card_name_domain(r["name"] for r in rows),
                 "extensions": [FLAT, HISTORY], "probe": False}
        self.current = self.send({"request_type": "reset", "game_id": f"hidden-{deck}-{seed}", "format": "pauper-bo1",
                                  "seats": [{"seat": s, "deck": {"catalog_id": deck, "deck_id": deck_id(rows)}}
                                            for s in ("p0", "p1")],
                                  "rules": rules, "game_secret": hashlib.sha256(f"hidden-{seed}".encode()).hexdigest(),
                                  "max_decisions": 4096, "max_steps": 8192})

    def send(self, value: dict) -> dict:
        self.serial += 1
        request = {"protocol": "spellbench/v2", "request_id": f"q{self.serial}", **value}
        return wire.strict_json_loads(self.engine.handle(wire.canonical_json_dumps(request)))

    def answer(self, candidate: int) -> None:
        sd = self.current["seat_decision"]
        self.current = self.send({"request_type": "step", "game_id": self.current["game_id"],
                                  "expected_step": self.current["step"],
                                  "selection": {"candidate_id": candidate, "semantic_echo": sd["candidates"][candidate]["semantic"]}})

    def close(self) -> None:
        self.peer.close()


def names(sd: dict) -> list:
    return [(c["semantic"].get("item") or {}).get("object", {}).get("card_name") for c in sd["candidates"]]


def play(deck: str, seed: int, bot: str, bottom_name_rank: int = 0) -> tuple[list[dict], dict]:
    """Plays the opening with the human (p0) keeping and the bot (p1) answering per ``bot``; returns every decision
    message addressed to the human through its first in-game decision, and the facts the bot knew (for the tests)."""
    world = World(deck, seed)
    human_messages: list[dict] = []
    facts: dict = {"bottomed": None, "bot_first": False}
    try:
        while world.current["response_type"] == "decision":
            decision = world.current
            sd = decision["seat_decision"]
            semantics = [c["semantic"] for c in sd["candidates"]]
            if sd["acting_seat"] == "p0":
                message = copy.deepcopy(decision)
                message.pop("request_id", None)
                human_messages.append(message)
                if sd["observation"]["phase_step"] != "pregame":
                    break
                world.answer(next(i for i, s in enumerate(semantics) if s["kind"] == "mulligan" and s["keep"]))
                continue
            kind = semantics[0]["kind"]
            if sd["observation"]["phase_step"] != "pregame":
                facts["bot_first"] = True  # the bot acts in-game before the human: this seed cannot be compared
                break
            if kind == "mulligan":
                taken = semantics[0]["mulligans_taken"]
                want_keep = bot == "keep" or taken >= 1
                world.answer(next(i for i, s in enumerate(semantics) if s["keep"] is want_keep))
            else:
                assert kind == "order_pick" and semantics[0]["purpose"] == "mulligan_bottom"
                ranked = sorted(range(len(semantics)), key=lambda i: (names(sd)[i], i))
                distinct = [i for n, i in {names(sd)[i]: i for i in ranked}.items()]
                pick = distinct[min(bottom_name_rank, len(distinct) - 1)]
                facts["bottomed"] = names(sd)[pick]
                facts["hand"] = sorted(names(sd))
                world.answer(pick)
        return human_messages, facts
    finally:
        world.close()


def p1_hand_refs(value) -> list:
    """Every object reference in ``value`` that names a card in p1's hand (none may ever be sent to p0)."""
    found = []
    if isinstance(value, dict):
        if value.get("owner_seat") == "p1" and value.get("zone") == "hand" and value.get("object_id"):
            found.append(value)
        for item in value.values():
            found += p1_hand_refs(item)
    elif isinstance(value, list):
        for item in value:
            found += p1_hand_refs(item)
    return found


def strip_public_counts(message: dict) -> dict:
    """The human message without the fields that are public counts of the bot's opening."""
    stripped = copy.deepcopy(message)
    sd = stripped["seat_decision"]
    for player in sd["observation"]["players"]:
        if player["seat"] == "p1":
            for key in ("mulligans_taken", "hand_count", "library_count"):
                player.pop(key, None)
    sd["extensions"].pop(HISTORY, None)
    sd["extensions"].pop(FLAT, None)
    return stripped


@pytest.mark.parametrize("deck,seed", [("Burn", 3), ("Rally", 4), ("Faeries", 5), ("Burn", 6), ("Spy", 7), ("Affinity", 8)])
def test_what_the_bot_bottoms_never_reaches_the_human(deck: str, seed: int) -> None:
    b, facts_b = play(deck, seed, "mulligan", 0)
    c, facts_c = play(deck, seed, "mulligan", 1)
    if facts_b["bot_first"] or facts_c["bot_first"]:
        pytest.skip("the bot acts first in this game: no human decision to compare")
    assert facts_b["hand"] == facts_c["hand"], "the two worlds must show the bot the same new seven"
    if facts_b["bottomed"] == facts_c["bottomed"]:
        pytest.skip("this hand has one distinct card name")
    assert len(b) == len(c) >= 2
    assert b == c, "a human-bound message depends on which card the bot bottomed"
    assert not p1_hand_refs(b), "a human-bound message names a card of the bot's hand"


@pytest.mark.parametrize("deck,seed", [("Burn", 3), ("Burn", 6), ("Spy", 7), ("Affinity", 8)])
def test_the_bots_keep_or_mulligan_changes_only_the_public_counts(deck: str, seed: int) -> None:
    a, facts_a = play(deck, seed, "keep")
    b, facts_b = play(deck, seed, "mulligan", 0)
    if facts_a["bot_first"] or facts_b["bot_first"]:
        pytest.skip("the bot acts first in this game: no human decision to compare")
    assert len(a) == len(b) == 2 or len(a) >= 2
    # The human's own hand is the same in both worlds: the bot's answer cannot change what the human drew.
    for x, y in zip(a, b):
        px = {p["seat"]: p for p in x["seat_decision"]["observation"]["players"]}
        py = {p["seat"]: p for p in y["seat_decision"]["observation"]["players"]}
        assert px["p0"]["hand"] == py["p0"]["hand"]
        assert px["p1"]["hand"] is None and py["p1"]["hand"] is None
        assert px["p0"]["library_count"] == py["p0"]["library_count"]
    # The last message (the first in-game decision) differs from the first only in the bot's public counts.
    sa, sb = strip_public_counts(a[-1]), strip_public_counts(b[-1])
    assert sa["seat_decision"]["observation"]["players"] == sb["seat_decision"]["observation"]["players"]
    pa = {p["seat"]: p for p in a[-1]["seat_decision"]["observation"]["players"]}
    pb = {p["seat"]: p for p in b[-1]["seat_decision"]["observation"]["players"]}
    assert (pa["p1"]["mulligans_taken"], pb["p1"]["mulligans_taken"]) == (0, 1)
    assert (pa["p1"]["hand_count"], pb["p1"]["hand_count"]) == (7, 6)


def test_a_human_decision_never_lists_the_other_seats_hand() -> None:
    messages, _ = play("Burn", 7, "mulligan", 0)
    for message in messages:
        for player in message["seat_decision"]["observation"]["players"]:
            if player["seat"] == "p1":
                assert player["hand"] is None
        assert not p1_hand_refs(message)
        flat = message["seat_decision"]["extensions"].get(FLAT)
        assert flat is None or flat["acting_seat"] == "p0"
