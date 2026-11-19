"""A person is not asked to order cards going to their own graveyard together (`--graveyard-order-seat`).

The engine asks the owner for the graveyard order one card at a time: Balustrade Spy milling a library is dozens of
decisions. With the option the London human engine answers a pure graveyard ordering for the person's seat itself (the
first card the prompt would have listed, every time) and poses nothing; the other seat is asked as before.

Offline tests: what counts as a pure graveyard ordering, the order it gets, and the audit that no card of the decks
reads graveyard order: the deck cards whose rules text mentions a graveyard are a pinned, hand-audited list, so a new
one fails the test until someone has read it (a text pattern is only the second line; it is a heuristic). Tests against
the real London bridge (set MTG_KERNEL_LONDON_HUMAN_BRIDGE and MTG_KERNEL_PUBLIC_CATALOG; skipped otherwise): the
decks of the supplied catalog file (the export the engine wrapper checks deck ids against; this is not a reading of
the decks compiled into the bridge) hold no card outside the audited pool; a Spy mirror in which the person mills their whole
library is never asked to order and ends naturally; the bridge receives exactly the native steps of the game in which
the person takes the first candidate of every ordering decision by hand, and every decision addressed to the other
seat, its model input included, is byte-identical in the two games. A settled ordering is not a step or a decision of
the game: the settled game's counts are lower by exactly the prompts not posed, so under a step or decision cap the
two games can end at different points.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import random
import re
import sys
from pathlib import Path

import pytest

BRIDGE = os.environ.get("MTG_KERNEL_LONDON_HUMAN_BRIDGE")
CATALOG = os.environ.get("MTG_KERNEL_PUBLIC_CATALOG")
needs_bridge = pytest.mark.skipif(not (BRIDGE and CATALOG and Path(BRIDGE).exists()),
                                  reason="needs the London bridge and the public catalog")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE.parents[3] / "python"))

from kernel_engine_london_human_v1 import FLAT, HISTORY, KernelEngine, NativePeer, settle_graveyard_order  # noqa: E402
from kernel_order_v2 import TriggerOrder  # noqa: E402,F401
from kernel_selection_order_v2 import SelectionOrder  # noqa: E402
from spellbench import wire  # noqa: E402
from spellbench.digests import card_name_domain, deck_id  # noqa: E402

MANABREW = HERE.parents[3] / "python" / "spellbench" / "human" / "manabrew"


def cards(names: list[str]) -> list[dict]:
    return [{"object_id": f"o{i:02d}", "card_name": name} for i, name in enumerate(names)]


# -- what is settled, and how ----------------------------------------------------------------------------------------


def test_a_mill_is_settled_in_the_order_the_prompt_lists_the_cards() -> None:
    milled = cards(["Lotleth Giant", "Balustrade Spy", "Dread Return", "Balustrade Spy", "Land Grant"] * 8)
    plan = SelectionOrder(milled, source=None, count=len(milled), destination="graveyard", select=False)
    by_hand = copy.deepcopy(plan)
    while not by_hand.choose(0):  # the person taking the first candidate of every ordering decision
        pass
    assert settle_graveyard_order(plan) is True
    assert plan.result() == by_hand.result()
    order = plan.result()["graveyard"]
    assert len(order) == 40 and set(order) == {c["object_id"] for c in milled}
    names = {c["object_id"]: c["card_name"] for c in milled}
    assert [(names[o], o) for o in order] == sorted((names[o], o) for o in order)  # card name, then object id


def test_a_discard_is_settled_only_after_the_person_has_chosen_the_cards() -> None:
    hand = cards(["Fiery Temper", "Mountain", "Lava Dart", "Faithless Looting"])
    plan = SelectionOrder(hand, source=None, count=2, destination="graveyard", select=True, selection_purpose="discard")
    assert settle_graveyard_order(plan) is False and plan.selecting and plan.selected == []  # choosing is the person's
    plan.choose(1)
    assert settle_graveyard_order(plan) is False
    assert plan.choose(0) is False  # both chosen; the order of the two is still open
    assert settle_graveyard_order(plan) is True
    assert plan.result() == {"graveyard": ("o03", "o00")}  # Faithless Looting, then Fiery Temper: by name


def test_library_order_and_everything_else_is_left_to_the_person() -> None:
    top = SelectionOrder(cards(["Island", "Brainstorm", "Ponder"]), source=None, count=3, destination="top", select=False)
    assert settle_graveyard_order(top) is False and top.order == []
    for other in (None, object(), {"destination": "graveyard"}):
        assert settle_graveyard_order(other) is False


# -- no deck card reads graveyard order ------------------------------------------------------------------------------

# The audit. Every card of the eight decks whose rules text mentions a graveyard, read by hand on 2026-11-19: none
# reads the ORDER of a graveyard (they mill, flash back, return or exile a chosen card, exile a whole graveyard or
# count its cards). A card that joins or leaves this list fails the test below: read the new card, and if it reads
# graveyard order, exclude that case from the automatic order before adding it here.
AUDITED_GRAVEYARD_CARDS = frozenset({
    "Balustrade Spy", "Blood Fountain", "Dread Return", "Eviscerator's Insight", "Faithless Looting", "Fiery Temper",
    "Ichor Wellspring", "Lava Dart", "Lembas", "Lotleth Giant", "Masked Vandal", "Nihil Spellbomb", "Prismatic Strands",
    "Pulse of Murasa", "Sacred Cat", "Sneaky Snacker", "Thraben Charm", "Winding Way"})

# A heuristic second line: rules text that makes the order of a graveyard matter (Nether Shadow, Ashen Ghoul,
# Phyrexian Furnace, Shallow Grave, Death Spark, Corpse Dance and their kind). It cannot be complete; the audited list
# above is the guard.
ORDER_SENSITIVE = re.compile(
    r"top (\w+ ){0,3}cards? (of|in|from) [^.]{0,30}graveyard"
    r"|bottom (\w+ )?card of [^.]*graveyard"
    r"|\b(above|below|beneath)\b[^.]*\bgraveyard"
    r"|graveyard[^.]*\b(above|below|beneath|in order|order of|most recently)\b"
    r"|last [^.]* put into [^.]*graveyard", re.IGNORECASE)


def test_the_pattern_knows_the_cards_that_do_read_graveyard_order() -> None:
    for text in ("At the beginning of your upkeep, if three or more creature cards are above Nether Shadow in your "
                 "graveyard, you may put Nether Shadow onto the battlefield.",
                 "Exile the bottom card of target player's graveyard.",
                 "Return the top creature card of your graveyard to the battlefield.",
                 "Exile the top two cards of target player's graveyard.",
                 "Return the top card from your graveyard to your hand.",
                 "if a creature card is directly above Death Spark in your graveyard"):
        assert ORDER_SENSITIVE.search(text), text
    for text in ("Flashback {R}{R}", "Return target creature card from your graveyard to the battlefield.",
                 "reveal cards from the top of their library until they reveal a land card, then put those cards "
                 "into their graveyard", "Exile target player's graveyard."):
        assert not ORDER_SENSITIVE.search(text), text


def deck_card_names() -> set[str]:
    pool = json.loads((MANABREW / "pauper_decks.json").read_text(encoding="utf-8"))
    names: set[str] = set()

    def walk(value) -> None:
        if isinstance(value, dict):
            if isinstance(value.get("name"), str) and any(key in value for key in ("count", "quantity", "qty")):
                names.add(value["name"])
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(pool)
    return names


def test_the_deck_cards_that_mention_a_graveyard_are_the_audited_ones_and_none_reads_its_order() -> None:
    texts = json.loads((MANABREW / "cards.json").read_text(encoding="utf-8"))
    names = deck_card_names()
    assert len(names) > 80 and "Balustrade Spy" in names
    missing = sorted(name for name in names if not str((texts.get(name) or {}).get("text") or "").strip())
    assert missing == [], f"deck cards with no rules text to read: {missing}"
    mentioning = {name for name in names if "graveyard" in str(texts[name].get("text") or "").lower()}
    assert mentioning == AUDITED_GRAVEYARD_CARDS, (
        "the deck cards that mention a graveyard changed; read the new ones before this list is updated: "
        f"new {sorted(mentioning - AUDITED_GRAVEYARD_CARDS)}, gone {sorted(AUDITED_GRAVEYARD_CARDS - mentioning)}")
    reading = sorted(name for name in names if ORDER_SENSITIVE.search(texts[name].get("text") or ""))
    assert reading == [], f"these deck cards read graveyard order; exclude them from the automatic order: {reading}"


# -- against the real bridge -----------------------------------------------------------------------------------------


class RecordingPeer(NativePeer):
    """The native peer, keeping the steps it sends (private previews are not steps: they change nothing)."""

    def __init__(self, executable: str) -> None:
        super().__init__(executable)
        self.steps: list[tuple] = []

    def request(self, value):
        if value.get("request_type") == "step":
            self.steps.append((value["expected_step"], value["selection"]["candidate_id"]))
        return super().request(value)


@needs_bridge
def test_the_supplied_catalog_files_decks_hold_no_card_outside_the_audited_pool() -> None:
    """The catalog FILE the session is given, not the bridge binary: the bridge picks its compiled decks by catalog
    id and nothing here reads them, so a bridge whose compiled decks differ from this file is not caught."""
    catalog = json.loads(Path(CATALOG).read_bytes())
    in_catalog = {row["name"] for entry in catalog["catalog"] for row in entry["decklist"]}
    assert len(catalog["catalog"]) == 8 and in_catalog
    assert sorted(in_catalog - deck_card_names()) == [], "the catalog lists a card the graveyard audit never saw"


class World:
    def __init__(self, seed: int, *, settle: bool) -> None:
        self.catalog = json.loads(Path(CATALOG).read_bytes())
        self.peer = RecordingPeer(BRIDGE)
        self.engine = KernelEngine(self.peer, self.catalog, graveyard_order_seat="p0" if settle else None)
        rows = next(e["decklist"] for e in self.catalog["catalog"] if e["catalog_id"] == "Spy")
        self.serial = 0
        rules = {"opponent_decklist": "visible", "mulligan": "london", "starting_player": "host_assigned",
                 "starting_seat": "p0", "card_name_domain": card_name_domain(r["name"] for r in rows),
                 "extensions": [FLAT, HISTORY], "probe": False}
        self.current = self.send({"request_type": "reset", "game_id": f"graveyard-order-{seed}", "format": "pauper-bo1",
                                  "seats": [{"seat": s, "deck": {"catalog_id": "Spy", "deck_id": deck_id(rows)}}
                                            for s in ("p0", "p1")],
                                  "rules": rules, "game_secret": hashlib.sha256(f"graveyard-{seed}".encode()).hexdigest(),
                                  "max_decisions": 1 << 20, "max_steps": 1 << 20})

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


def graveyard_ordering(sd: dict) -> bool:
    semantics = [c["semantic"] for c in sd["candidates"]]
    return all(s["kind"] == "order_pick" and s["purpose"] == "other" and "object" in s["item"] for s in semantics)


def play(seed: int, *, settle: bool, limit: int = 6000) -> dict:
    """One Spy mirror. The person (p0) keeps, plays lands, casts Balustrade Spy on themselves whenever they can, and
    otherwise answers by the seeded policy; an ordering decision of theirs takes the first candidate. The other seat
    (p1) answers by the same seeded policy. The policy draws once per decision that is not an ordering of the
    person's, so the two games (asked and not asked) take the same answers."""
    world = World(seed, settle=settle)
    rng = random.Random(seed)
    out = {"ordering_prompts": 0, "ordering_groups": 0, "largest_mill": 0, "bot_messages": [],
           "library_after_mill": None}
    try:
        steps = 0
        while world.current["response_type"] == "decision" and steps < limit:
            steps += 1
            sd = world.current["seat_decision"]
            semantics = [c["semantic"] for c in sd["candidates"]]
            seat = sd["acting_seat"]
            me = next(p for p in sd["observation"]["players"] if p["seat"] == "p0")
            if seat == "p1":
                out["bot_messages"].append(wire.canonical_json_dumps(sd))
            if seat == "p0" and graveyard_ordering(sd):
                out["ordering_prompts"] += 1
                out["ordering_groups"] += semantics[0]["position"] == 0
                out["largest_mill"] = max(out["largest_mill"], semantics[0]["count"])
                world.answer(0)
                continue
            draw = rng.randrange(1 << 30)
            kinds = [s["kind"] for s in semantics]
            pick = draw % len(semantics)
            if seat == "p0":
                spy = [i for i, s in enumerate(semantics) if s["kind"] == "cast_spell"
                       and (s.get("source") or {}).get("card_name") == "Balustrade Spy"]
                own = [i for i, s in enumerate(semantics) if s["kind"] == "choose_target"
                       and (s.get("target") or {}).get("player") == "p0"]
                land = [i for i, k in enumerate(kinds) if k == "play_land"]
                keep = [i for i, s in enumerate(semantics) if s["kind"] == "mulligan" and s["keep"]]
                pick = (keep or spy or own or land or [pick])[0]
            world.answer(pick)
            library = me.get("library_count")
            if library == 0 and out["library_after_mill"] is None:
                out["library_after_mill"] = 0
        out["end"] = {key: world.current.get(key) for key in ("response_type", "outcome", "classification", "reason")}
        out["counts"] = {key: world.current.get(key) for key in ("step_count", "decision_count")}
        out["native_steps"] = list(world.peer.steps)
        out["settled"] = list(getattr(world.engine, "graveyard_orders_settled", []))
        return out
    finally:
        world.close()


def whole_library_seed() -> tuple[int, dict]:
    """The first seed in which the person mills their whole library (asked for nothing), and that game."""
    for seed in range(1, 60):
        game = play(seed, settle=True)
        if game["settled"] and max(game["settled"]) >= 20 and game["library_after_mill"] == 0:
            return seed, game
    pytest.fail("no seed below 60 mills the person's whole library")


@needs_bridge
def test_a_whole_library_spy_mill_asks_the_person_nothing_and_the_game_ends_naturally() -> None:
    seed, game = whole_library_seed()
    assert game["ordering_prompts"] == 0, f"seed {seed}: the person was asked to order {game['ordering_prompts']} times"
    assert max(game["settled"]) >= 20  # the cards of one mill that were ordered for them
    assert game["end"]["response_type"] == "terminal" and game["end"]["classification"] == "natural", game["end"]


@needs_bridge
def test_the_settled_game_is_the_game_of_a_person_who_takes_the_first_card_every_time() -> None:
    seed, settled = whole_library_seed()
    asked = play(seed, settle=False)
    assert asked["ordering_prompts"] >= 19 and asked["largest_mill"] == max(settled["settled"])  # the same mill, asked
    assert asked["settled"] == []
    assert asked["native_steps"] == settled["native_steps"]  # the bridge got the same game
    assert asked["bot_messages"] == settled["bot_messages"]  # and the other seat was shown the same, byte for byte
    assert any(FLAT.encode() in message for message in settled["bot_messages"])  # its model input included
    assert asked["end"] == settled["end"]


@needs_bridge
def test_a_settled_ordering_is_not_a_step_or_a_decision_of_the_game() -> None:
    """The two games are the same game below the caps only: the settled one has taken fewer steps and decisions, by
    exactly the ordering prompts and groups it did not pose, so a step or decision cap is reached later in it."""
    seed, settled = whole_library_seed()
    asked = play(seed, settle=False)
    assert asked["ordering_prompts"] > 0 and asked["ordering_groups"] == len(settled["settled"])
    assert asked["counts"]["step_count"] - settled["counts"]["step_count"] == asked["ordering_prompts"]
    assert asked["counts"]["decision_count"] - settled["counts"]["decision_count"] == asked["ordering_groups"]
