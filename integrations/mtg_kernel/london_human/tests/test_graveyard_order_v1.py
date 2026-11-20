"""Graveyard order in human play (`--auto-graveyard-order` on the London human engine).

Graveyard order is a real rule: the owner of cards put into a graveyard at once orders them, and the engine asks one
card at a time (Balustrade Spy milling a library is dozens of decisions). Every training episode of the play bots'
lineages runs the engine's rule `resolution-boundary-v1`, under which that order is never posed and the cards keep
the order the effect bound them in. With the option, in a game in which no card of either deck list reads graveyard
order (`spellbench.human.graveyard_order`), the engine asks the bridge for that rule, so neither seat is asked; in a
game with such a card both seats are asked, as the rules say.

Offline: the audit of the card data (every deck card whose rules text mentions a graveyard is a listed reader or a
listed non-reader, and the text pattern, a heuristic only, finds nothing among the non-readers), and which cards make
a game order-relevant. Against the real London bridge (set MTG_KERNEL_LONDON_HUMAN_BRIDGE and
MTG_KERNEL_PUBLIC_CATALOG; skipped otherwise, and skipped for a bridge built without the rule): Spy mirrors in which
both seats cast Balustrade Spy on themselves pose no graveyard ordering to either seat and end naturally; up to the
first graveyard ordering the same games pose without the option, both seats' decisions are byte-identical, model
input included.
"""
from __future__ import annotations

import functools
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
needs_catalog = pytest.mark.skipif(not (CATALOG and Path(CATALOG).exists()), reason="needs the public catalog")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE.parents[3] / "python"))

from kernel_engine_london_human_v1 import (FLAT, HISTORY, KernelEngine, NativePeer, graveyard_readers,  # noqa: E402
                                           settle_graveyard_order)
from kernel_selection_order_v2 import SelectionOrder  # noqa: E402
from spellbench import wire  # noqa: E402
from spellbench.digests import card_name_domain, deck_id  # noqa: E402
from spellbench.human import graveyard_order  # noqa: E402

MANABREW = HERE.parents[3] / "python" / "spellbench" / "human" / "manabrew"


# -- the card data -------------------------------------------------------------------------------------------------

# A heuristic second line: rules text that makes the order of a graveyard matter (Nether Shadow, Ashen Ghoul,
# Phyrexian Furnace, Shallow Grave, Death Spark, Corpse Dance and their kind). It cannot be complete; the audited
# lists in graveyard_order_cards_v1.json are the guard.
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
    return {row["name"] for rows in pool["decks"].values() for row in rows}


def test_every_deck_card_that_mentions_a_graveyard_is_audited_and_none_of_the_eight_decks_reads_its_order() -> None:
    texts = json.loads((MANABREW / "cards.json").read_text(encoding="utf-8"))
    names = deck_card_names()
    assert len(names) > 80 and "Balustrade Spy" in names
    missing = sorted(name for name in names if not str((texts.get(name) or {}).get("text") or "").strip())
    assert missing == [], f"deck cards with no rules text to read: {missing}"
    mentioning = {name for name in names if "graveyard" in str(texts[name].get("text") or "").lower()}
    data = graveyard_order.cards()
    unaudited = sorted(name for name in mentioning if not graveyard_order.audited(name))
    assert unaudited == [], f"read these deck cards and list them in graveyard_order_cards_v1.json: {unaudited}"
    # The non-readers list is exactly the deck cards that mention a graveyard: a card that leaves the decks leaves
    # the list too, so the audit never claims a card it no longer covers.
    assert set(data["not_readers"]) == mentioning
    assert graveyard_order.readers(names) == []  # no game of the eight decks is order-relevant today
    flagged = sorted(name for name in data["not_readers"] if ORDER_SENSITIVE.search(texts[name].get("text") or ""))
    assert flagged == [], f"listed as not reading graveyard order, but the text pattern flags: {flagged}"


@needs_catalog
def test_the_catalog_the_engine_reads_has_the_clients_decks_card_for_card_and_no_reader() -> None:
    """The wrapper and the session decide relevance from the catalog file; the audit above reads the client's deck
    lists. They agree deck by deck (a card moved between decks is caught), and the catalog holds no reader."""
    catalog = graveyard_order.catalog_decks(json.loads(Path(CATALOG).read_bytes()))
    pool = json.loads((MANABREW / "pauper_decks.json").read_text(encoding="utf-8"))["decks"]
    assert sorted(catalog) == sorted(pool)
    for deck, names in catalog.items():
        assert set(names) == {row["name"] for row in pool[deck]}, deck
        assert graveyard_order.game_readers(catalog, [deck]) == [], deck


def test_a_reader_in_either_deck_list_makes_the_game_order_relevant() -> None:
    decks = {"A": [{"name": "Balustrade Spy", "count": 4}], "B": [{"name": "Gurmag Angler", "count": 2}]}
    seat = lambda deck: {"deck": {"catalog_id": deck}}  # noqa: E731
    assert graveyard_readers(decks, [seat("A"), seat("A")]) == []
    assert graveyard_readers(decks, [seat("A"), seat("B")]) == ["Gurmag Angler"]
    assert graveyard_readers(decks, [seat("B"), seat("A")]) == ["Gurmag Angler"]
    assert graveyard_order.readers(["Gurmag Angler", "Gurmag Angler", "Island"]) == ["Gurmag Angler"]


def names_to_cards(names: list[str]) -> list[dict]:
    return [{"object_id": f"o{i:02d}", "card_name": name} for i, name in enumerate(names)]


def test_the_ordering_step_after_a_discard_is_settled_in_the_order_the_prompt_lists_the_cards() -> None:
    hand = names_to_cards(["Fiery Temper", "Mountain", "Lava Dart", "Faithless Looting"])
    plan = SelectionOrder(hand, source=None, count=2, destination="graveyard", select=True, selection_purpose="discard")
    assert settle_graveyard_order(plan) is False and plan.selecting  # choosing the cards is the seat's own decision
    plan.choose(1)
    assert plan.choose(0) is False  # both chosen; the order of the two is the protocol's extra step
    assert settle_graveyard_order(plan) is True
    assert plan.result() == {"graveyard": ("o03", "o00")}  # Faithless Looting, then Fiery Temper: first listed


def test_library_orders_and_anything_else_are_never_settled() -> None:
    top = SelectionOrder(names_to_cards(["Island", "Brainstorm", "Ponder"]), source=None, count=3, destination="top",
                         select=False)
    assert settle_graveyard_order(top) is False and top.order == []
    for other in (None, object(), {"destination": "graveyard"}):
        assert settle_graveyard_order(other) is False


# -- against the real bridge ---------------------------------------------------------------------------------------


@functools.lru_cache(maxsize=1)
def bridge_has_the_rule() -> bool:
    """Whether the bridge takes ``auto_graveyard_order`` (an older one refuses the field)."""
    peer = NativePeer(BRIDGE)
    try:
        peer.request({"request_type": "hello"})
        answer = peer.request({"request_type": "reset", "game_id": "probe", "format": "pauper-bo1",
                               "seats": [{"seat": s, "deck": {"catalog_id": "Burn"}} for s in ("p0", "p1")],
                               "game_seed": 1, "max_decisions": 100, "max_steps": 100, "auto_graveyard_order": True})
        return answer.get("response_type") == "decision"
    finally:
        peer.close()


def require_the_rule() -> None:
    if not bridge_has_the_rule():
        pytest.skip("this bridge was built without the graveyard rule (auto_graveyard_order)")


class World:
    def __init__(self, seed: int, *, auto: bool) -> None:
        self.catalog = json.loads(Path(CATALOG).read_bytes())
        self.peer = NativePeer(BRIDGE)
        self.engine = KernelEngine(self.peer, self.catalog, auto_graveyard_order=auto)
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
    """A batch of cards put into a graveyard at once, ordered one card at a time (the native graveyard order)."""
    semantics = [c["semantic"] for c in sd["candidates"]]
    return all(s["kind"] == "order_pick" and s["purpose"] == "other" and "object" in s["item"] for s in semantics)


def look_ordering(sd: dict) -> bool:
    """The ordering step of a look (an arrangement): the protocol's fixed 2n - 1 group, not a graveyard batch."""
    semantics = [c["semantic"] for c in sd["candidates"]]
    return all(s["kind"] == "order_pick" and s["purpose"] == "arrangement" for s in semantics)


def pick(sd: dict, rng: random.Random) -> int:
    """Both seats keep, cast Balustrade Spy whenever they can and aim it at themselves, play lands, and otherwise take
    a seeded candidate. An ordering takes its first candidate and draws nothing."""
    semantics = [c["semantic"] for c in sd["candidates"]]
    if graveyard_ordering(sd):
        return 0
    seat = sd["acting_seat"]
    draw = rng.randrange(1 << 30) % len(semantics)
    keep = [i for i, s in enumerate(semantics) if s["kind"] == "mulligan" and s["keep"]]
    spy = [i for i, s in enumerate(semantics) if s["kind"] == "cast_spell"
           and (s.get("source") or {}).get("card_name") == "Balustrade Spy"]
    own = [i for i, s in enumerate(semantics) if s["kind"] == "choose_target" and (s.get("target") or {}).get("player") == seat]
    land = [i for i, s in enumerate(semantics) if s["kind"] == "play_land"]
    return (keep or spy or own or land or [draw])[0]


def play(seed: int, *, auto: bool, stop_at_first_ordering: bool = False, limit: int = 8000) -> dict:
    world = World(seed, auto=auto)
    rng = random.Random(seed)
    out = {"decisions": [], "graveyard_orderings": {"p0": 0, "p1": 0}, "look_orderings": {"p0": 0, "p1": 0},
           "graveyard_order": world.engine.graveyard_order}
    try:
        while world.current["response_type"] == "decision" and len(out["decisions"]) < limit:
            sd = world.current["seat_decision"]
            seat = sd["acting_seat"]
            if graveyard_ordering(sd):
                out["graveyard_orderings"][seat] += 1
                if stop_at_first_ordering:
                    out["stopped"] = len(out["decisions"])
                    break
            if look_ordering(sd):
                out["look_orderings"][seat] += 1
            out["decisions"].append(wire.canonical_json_dumps(sd))
            world.answer(pick(sd, rng))
        out["end"] = {key: world.current.get(key) for key in ("response_type", "outcome", "classification", "reason")}
        return out
    finally:
        world.close()


SEEDS = range(1, 9)


@needs_bridge
def test_with_the_rule_neither_seat_orders_a_graveyard_batch_and_spy_mirrors_end_naturally() -> None:
    require_the_rule()
    asked = 0
    for seed in SEEDS:
        on = play(seed, auto=True)
        assert on["graveyard_order"] == {"how": "settled", "readers": []}, seed
        assert on["graveyard_orderings"] == {"p0": 0, "p1": 0}, (seed, on["graveyard_orderings"])
        assert on["end"]["response_type"] == "terminal" and on["end"]["classification"] == "natural", (seed, on["end"])
        off = play(seed, auto=False)
        asked += sum(off["graveyard_orderings"].values())
    assert asked > 20, f"the same games without the rule posed only {asked} graveyard orderings"


@needs_bridge
def test_a_game_the_data_calls_order_free_but_the_engine_refuses_is_not_played(monkeypatch) -> None:
    """The engine's own check (Delve) refused the rule although the data lists no reader: the session already said
    nobody is asked, so the wrapper refuses the game instead of asking anyway. Simulated by the bridge's answer."""
    require_the_rule()
    original = NativePeer.request

    def refusing(self, value):
        answer = original(self, value)
        if value.get("request_type") == "reset" and value.get("auto_graveyard_order"):
            answer["extensions"]["x_kernel_v2_support"]["graveyard_order"] = "asked"
        return answer

    monkeypatch.setattr(NativePeer, "request", refusing)
    world = World(1, auto=True)
    try:
        assert world.current["response_type"] == "error", world.current
        assert "does not list it" in world.current["error"]["message"]
        assert world.engine.game is None
    finally:
        world.close()


@needs_bridge
def test_both_seats_decisions_are_byte_identical_up_to_the_first_ordering_the_old_rule_poses() -> None:
    require_the_rule()
    compared = 0
    for seed in SEEDS:
        off = play(seed, auto=False, stop_at_first_ordering=True)
        on = play(seed, auto=True, limit=len(off["decisions"]))
        assert on["decisions"] == off["decisions"], f"seed {seed}: a decision before the first ordering differs"
        assert any(FLAT in d.decode() for d in on["decisions"])  # model input included
        compared += len(off["decisions"])
    assert compared > 200, compared
