"""The bot's training window rule at the London human engine (``--action-windows-seat``; the bridge reset field
``priority_windows``).

The bot's seat plays on the priority windows its model trained with (``action-windows-v1``) while the person's seat
keeps engine windows: the bridge is told the bot's bridge seat (its p0 is the starting seat), the person's and the
bot's seats are never the same, and with the option the bot is asked in steps the HarnessV2 surface never gives it
(upkeep, draw, beginning of combat, combat damage, end of combat, the end step). The bridge-backed tests need
MTG_KERNEL_LONDON_HUMAN_BRIDGE (a bridge with ``priority_windows``) and MTG_KERNEL_PUBLIC_CATALOG.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import sys
from collections import Counter
from pathlib import Path

import pytest

BRIDGE = os.environ.get("MTG_KERNEL_LONDON_HUMAN_BRIDGE")
CATALOG = os.environ.get("MTG_KERNEL_PUBLIC_CATALOG")
needs_catalog = pytest.mark.skipif(not (CATALOG and Path(CATALOG).exists()), reason="needs the public catalog")
needs_bridge = pytest.mark.skipif(not (BRIDGE and CATALOG and Path(BRIDGE).exists()),
                                  reason="needs the London bridge and the public catalog")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE.parents[3] / "python"))

from kernel_engine_london_human_v1 import (FLAT, HISTORY, KernelEngine, NativePeer,  # noqa: E402
                                           native_priority_windows)
from spellbench import wire  # noqa: E402
from spellbench.digests import card_name_domain, deck_id  # noqa: E402

PERSON, BOT = "p0", "p1"
HARNESS_STEPS = {"precombat_main", "declare_attackers", "declare_blockers", "postcombat_main"}
NEW_STEPS = {"upkeep", "draw", "beginning_of_combat", "combat_damage", "end_of_combat", "end_step"}


def test_the_bots_bridge_seat_follows_the_starting_seat() -> None:
    assert native_priority_windows("p1", "p0", "action-windows-v1") == ["harness-v2", "action-windows-v1"]
    assert native_priority_windows("p1", "p1", "action-windows-v1") == ["action-windows-v1", "harness-v2"]
    assert native_priority_windows("p0", "p1", "action-windows-end-step-v1") == ["harness-v2", "action-windows-end-step-v1"]


class Recorder:
    """A bridge stand-in that answers the handshake and records every request."""

    def __init__(self) -> None:
        self.requests: list[dict] = []

    def request(self, value: dict) -> dict:
        self.requests.append(value)
        if value["request_type"] == "hello":
            return {"response_type": "hello_ok", "engine": {"name": "mtg-kernel", "version": "x",
                    "rules_snapshot_id": "r", "card_pool_identity": "c"}}
        return {"response_type": "error", "error": {"code": "unsupported_rule", "message": "recorded"}}


def test_a_seat_has_either_engine_windows_or_a_training_rule() -> None:
    with pytest.raises(ValueError):
        KernelEngine(Recorder(), {"catalog": []}, engine_windows_seat="p1", action_windows_seat="p1")


def test_trainer_choices_cannot_override_the_persons_engine_windows() -> None:
    with pytest.raises(ValueError, match="must differ"):
        KernelEngine(Recorder(), {"catalog": []}, engine_windows_seat="p1", trainer_choice_seat="p1")


def reset_value(catalog: dict, seed: int, *, first: str, person: str = "Faeries", bot: str = "Burn") -> dict:
    decks = {e["catalog_id"]: e["decklist"] for e in catalog["catalog"]}
    names = [r["name"] for d in (person, bot) for r in decks[d]]
    rules = {"opponent_decklist": "visible", "mulligan": "london", "starting_player": "host_assigned",
             "starting_seat": first, "card_name_domain": card_name_domain(names),
             "extensions": [FLAT, HISTORY], "probe": False}
    return {"request_type": "reset", "game_id": f"botwin-{seed}", "format": "pauper-bo1",
            "seats": [{"seat": "p0", "deck": {"catalog_id": person, "deck_id": deck_id(decks[person])}},
                      {"seat": "p1", "deck": {"catalog_id": bot, "deck_id": deck_id(decks[bot])}}],
            "rules": rules, "game_secret": hashlib.sha256(f"botwin-{seed}".encode()).hexdigest(),
            "max_decisions": 1 << 20, "max_steps": 1 << 20}


def send(engine: KernelEngine, value: dict, serial: int = 1) -> dict:
    request = {"protocol": "spellbench/v2", "request_id": f"q{serial}", **value}
    return wire.strict_json_loads(engine.handle(wire.canonical_json_dumps(request)))


@needs_catalog
@pytest.mark.parametrize("first", ["p0", "p1"])
def test_the_reset_carries_priority_windows_only_with_the_option(first: str) -> None:
    catalog = json.loads(Path(CATALOG).read_bytes())
    sent, answers = {}, {}
    for option in (None, BOT):
        peer = Recorder()
        engine = KernelEngine(peer, catalog, engine_windows_seat=PERSON, auto_graveyard_order=True,
                              action_windows_seat=option)
        answers[option] = send(engine, reset_value(catalog, 1, first=first))
        sent[option] = [r for r in peer.requests if r["request_type"] == "reset"][0]
    plain, windows = sent[None], sent[BOT]
    assert "priority_windows" not in plain
    assert windows.pop("priority_windows") == native_priority_windows(BOT, first, "action-windows-v1")
    assert windows == plain  # nothing else in the reset differs
    # The refusal: the earlier text without the option, a text naming bot windows with it.
    assert answers[None]["error"]["message"] == ("the native bridge refused this reset (engine windows and the "
                                                 "graveyard rule need a bridge built with them)")
    assert "bot windows" in answers[BOT]["error"]["message"]


@pytest.mark.parametrize("first", ["p0", "p1"])
@pytest.mark.parametrize("bot_seat", ["p0", "p1"])
@pytest.mark.parametrize("bot_windows", [False, True])
def test_reset_only_sends_trainer_choices_when_selected(first: str, bot_seat: str, bot_windows: bool) -> None:
    catalog = {"schema": "spellbench-kernel-public-catalog/v1", "cards": {},
               "catalog": [{"catalog_id": label, "name": label, "decklist": [{"name": card, "count": 60}]}
                           for label, card in [("Faeries", "Island"), ("Burn", "Mountain")]]}
    person_seat = "p1" if bot_seat == "p0" else "p0"
    p0_deck, p1_deck = ("Burn", "Faeries") if bot_seat == "p0" else ("Faeries", "Burn")
    sent = []
    for choice_seat in (None, bot_seat):
        peer = Recorder()
        engine = KernelEngine(peer, catalog, engine_windows_seat=person_seat,
                              action_windows_seat=bot_seat if bot_windows else None,
                              trainer_choice_seat=choice_seat)
        answer = send(engine, reset_value(catalog, 7, first=first, person=p0_deck, bot=p1_deck))
        assert answer["error"]["code"] == "unsupported_rule"
        if choice_seat is not None:
            assert "trainer_choice_seats" in answer["error"]["message"]
        sent.append(peer.requests[-1])
    plain, opted_in = sent
    assert plain["request_type"] == "reset" and "trainer_choice_seats" not in plain
    native_bot = "p0" if bot_seat == first else "p1"
    assert opted_in.pop("trainer_choice_seats") == [native_bot]
    assert next(seat["deck"]["catalog_id"] for seat in plain["seats"] if seat["seat"] == native_bot) == "Burn"
    assert opted_in == plain


class World:
    def __init__(self, seed: int, *, bot_windows: bool, first: str = "p0") -> None:
        self.catalog = json.loads(Path(CATALOG).read_bytes())
        self.peer = NativePeer(BRIDGE)
        self.engine = KernelEngine(self.peer, self.catalog, engine_windows_seat=PERSON, auto_graveyard_order=True,
                                   action_windows_seat=BOT if bot_windows else None)
        self.serial = 0
        self.current = self.send(reset_value(self.catalog, seed, first=first))

    def send(self, value: dict) -> dict:
        self.serial += 1
        return send(self.engine, value, self.serial)

    def answer(self, candidate: int) -> None:
        sd = self.current["seat_decision"]
        self.current = self.send({"request_type": "step", "game_id": self.current["game_id"],
                                  "expected_step": self.current["step"],
                                  "selection": {"candidate_id": candidate, "semantic_echo": sd["candidates"][candidate]["semantic"]}})

    def close(self) -> None:
        self.peer.close()


def pick(sd: dict, rng: random.Random) -> int:
    """Keep, play lands, cast what can be cast; otherwise a seeded candidate."""
    semantics = [c["semantic"] for c in sd["candidates"]]
    keep = [i for i, s in enumerate(semantics) if s["kind"] == "mulligan" and s["keep"]]
    act = [i for i, s in enumerate(semantics) if s["kind"] in ("play_land", "cast_spell")]
    return (keep or act or [rng.randrange(len(semantics))])[0] if rng.random() < 0.8 else rng.randrange(len(semantics))


def bot_priority_steps(seed: int, *, bot_windows: bool, first: str) -> Counter:
    """Plays one game to its end; the steps of the bot's priority decisions."""
    world = World(seed, bot_windows=bot_windows, first=first)
    rng = random.Random(seed)
    steps: Counter = Counter()
    try:
        for _ in range(20_000):
            if world.current["response_type"] != "decision":
                assert world.current["classification"] == "natural", world.current
                return steps
            sd = world.current["seat_decision"]
            if sd["acting_seat"] == BOT and (sd.get("context") or {}).get("kind") == "priority":
                steps[(sd.get("observation") or {}).get("phase_step")] += 1
            world.answer(pick(sd, rng))
        pytest.fail(f"seed {seed}: the game did not end")
    finally:
        world.close()


@needs_bridge
@pytest.mark.parametrize("first", ["p0", "p1"])
def test_the_bot_is_asked_in_the_steps_its_training_rule_gives_it(first: str) -> None:
    plain, windows = Counter(), Counter()
    for seed in range(1, 4):
        plain += bot_priority_steps(seed, bot_windows=False, first=first)
        windows += bot_priority_steps(seed, bot_windows=True, first=first)
    assert set(plain) <= HARNESS_STEPS, dict(plain)
    assert set(windows) <= HARNESS_STEPS | NEW_STEPS, dict(windows)  # every decision names a known step
    # Several of the steps HarnessV2 never gives the bot, not one alone (the end-step-only rule would show one).
    assert len(set(windows) & NEW_STEPS) >= 3, dict(windows)
    print(f"bot priority steps, harness-v2 {dict(plain)}, action-windows-v1 {dict(windows)}")
