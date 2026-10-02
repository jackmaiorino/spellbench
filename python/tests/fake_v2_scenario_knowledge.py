"""The knowledge tour (spec 6.7): every update-table row fired in order, read from p0's view.

Each numbered event applies the matching ``Knowledge`` row (``fake_v2_knowledge``), whose
``entries()`` writes ``world.known["p0"]``, and is followed by one decision posed to p0 whose
``context.text`` is ``"row <n>"``. The entries are name-level and carry no object ids, so the
scenario never takes a look id and ``World.end_looks`` has nothing to end. ``EXPECTED`` pins p0's
entries after each row; it is written by hand from the spec's update table, never computed with
``Knowledge`` (R2-11), so the tour checks the model rather than its forwarding.
"""

from __future__ import annotations

from fake_v2_knowledge import Knowledge
from fake_v2_world import Posed, Scenario

PASS = {"kind": "pass"}


def _entry(owner, zone, name, top=None, bottom=None, how="revealed") -> dict:
    return {"owner_seat": owner, "zone": zone, "card_name": name,
            "position_from_top": top, "position_from_bottom": bottom, "how": how}


def _hand_names(world, seat) -> list[str]:
    return sorted(obj.name for obj in world.objects.values() if obj.zone == "hand" and obj.owner == seat)


def _script(world):
    knowledge = Knowledge(world, "p0")

    def pose(text):
        knowledge.entries()                      # write world.known["p0"] for the observation
        return Posed("p0", [PASS], text=text)

    # Setup: a Lightning Bolt in p1's graveyard, an Island and a Grizzly Bears in p1's hand, a
    # Preordain on top of p1's library over nine Mountains, and ten Mountains in p0's library.
    bolt = world.add("Lightning Bolt", owner="p1", zone="graveyard")
    island = world.add("Island", owner="p1", zone="hand")
    bears = world.add("Grizzly Bears", owner="p1", zone="hand")
    preordain = world.add("Preordain", owner="p1", zone="library")
    for _ in range(9):
        world.add("Mountain", owner="p1", zone="library")
    for _ in range(10):
        world.add("Mountain", owner="p0", zone="library")

    # Row 1: the Bolt returns from p1's graveyard (a public zone) to p1's hand.
    world.move(bolt, "hand")
    knowledge.public_to_other_hand("Lightning Bolt")
    yield pose("row 1")
    # Row 2: p1's top card is revealed to p0, then p1 draws it; p0 tracks it into p1's hand.
    knowledge.looked_at("p1", [("Preordain", "top", 0)], "revealed")
    knowledge.known_library_card_drawn("p1", "top")
    world.move(preordain, "hand")
    yield pose("row 2")
    # Row 3: p1 reveals its hand to p0.
    knowledge.other_hand_revealed(_hand_names(world, "p1"))
    yield pose("row 3")
    # Row 4: p1 casts the Bears; a card leaves the other hand to a public zone.
    world.move(bears, "battlefield")
    knowledge.other_hand_to_public("Grizzly Bears")
    yield pose("row 4")
    # Row 5: p1 puts a card from its hand on top of its library, unidentified to p0 (the Bolt).
    knowledge.other_hand_to_hidden(1)
    world.move(bolt, "library", library_position=0)
    yield pose("row 5")
    # p1 reveals its hand again (the Island and the Preordain), then row 6: it is shuffled away.
    knowledge.other_hand_revealed(_hand_names(world, "p1"))
    knowledge.other_hand_randomized()
    for card in (island, preordain):
        world.move(card, "library", library_position=0)
    yield pose("row 6")
    # p1 draws a card (unknown to p0), then p0 looks at each library's top card.
    world.move(world.libraries["p1"][0], "hand")
    knowledge.looked_at("p0", [("Mountain", "top", 0)], "looked_at")
    knowledge.looked_at("p1", [("Island", "top", 0)], "looked_at")
    # Row 7: p0 shuffles its own library; only its entries are forgotten.
    knowledge.library_shuffled("p0")
    yield pose("row 7")
    # Row 8: p0 looks at the top two cards of its own library.
    knowledge.looked_at("p0", [("Mountain", "top", 0), ("Mountain", "top", 1)], "looked_at")
    yield pose("row 8")
    # Row 9: p0's top card is milled into its graveyard; the other entries from that end renumber.
    knowledge.left_library_end("p0", "top")
    world.move(world.libraries["p0"][0], "graveyard")
    yield pose("row 9")
    # Row 10: p1 puts its hand card on top of its library, unidentified to p0.
    knowledge.put_on_library_end("p1", "top", None)
    world.move(_only_hand_card(world, "p1"), "library", library_position=0)
    yield pose("row 10")
    # Row 11: p1 scries and orders the top two cards of its library, hidden from p0.
    knowledge.hidden_rearrangement("p1", "top", 2)
    world.libraries["p1"][:2] = world.libraries["p1"][:2][::-1]
    yield pose("row 11")
    # p0's deeper look saw the card at top 3; row 12: an unknown card goes into p0's library at
    # least two cards down, so everything at or beyond the second card is forgotten.
    knowledge.looked_at("p0", [("Mountain", "top", 3)], "looked_at")
    knowledge.ambiguous_insertion("p0", "top", 2)
    newcomer = world.add("Mountain", owner="p0", zone="library")    # add() appends at the bottom
    world.libraries["p0"].remove(newcomer)
    world.libraries["p0"].insert(3, newcomer)
    yield pose("row 12")
    # p0 looks at p1's top card; row 13: p0 tutors a card out of its own library without a
    # shuffle, so every entry of that library is forgotten.
    knowledge.looked_at("p1", [("Island", "top", 0)], "looked_at")
    knowledge.left_unknown_position("p0")
    world.move(world.libraries["p0"][5], "hand")
    yield pose("row 13")


def _only_hand_card(world, seat) -> int:
    (card,) = [obj.internal for obj in world.objects.values() if obj.zone == "hand" and obj.owner == seat]
    return card


# p0's known entries after each row, written by hand from the spec 6.7 update table as literals,
# never computed with Knowledge (R2-11).
EXPECTED = {
    1: [_entry("p1", "hand", "Lightning Bolt", how="from_public_zone")],
    2: [_entry("p1", "hand", "Lightning Bolt", how="from_public_zone"),
        _entry("p1", "hand", "Preordain", how="tracked")],
    3: [_entry("p1", "hand", "Grizzly Bears"),
        _entry("p1", "hand", "Island"),
        _entry("p1", "hand", "Lightning Bolt"),
        _entry("p1", "hand", "Preordain")],
    4: [_entry("p1", "hand", "Island"),
        _entry("p1", "hand", "Lightning Bolt"),
        _entry("p1", "hand", "Preordain")],
    5: [],
    6: [],
    7: [_entry("p1", "library", "Island", top=0, how="looked_at")],
    8: [_entry("p0", "library", "Mountain", top=0, how="looked_at"),
        _entry("p0", "library", "Mountain", top=1, how="looked_at"),
        _entry("p1", "library", "Island", top=0, how="looked_at")],
    9: [_entry("p0", "library", "Mountain", top=0, how="looked_at"),
        _entry("p1", "library", "Island", top=0, how="looked_at")],
    10: [_entry("p0", "library", "Mountain", top=0, how="looked_at"),
         _entry("p1", "library", "Island", top=1, how="looked_at")],
    11: [_entry("p0", "library", "Mountain", top=0, how="looked_at")],
    12: [_entry("p0", "library", "Mountain", top=0, how="looked_at")],
    13: [_entry("p1", "library", "Island", top=0, how="looked_at")],
}


SCENARIO = Scenario(
    name="knowledge",
    decklist=[{"name": "Grizzly Bears", "count": 4}, {"name": "Lightning Bolt", "count": 4},
              {"name": "Preordain", "count": 4}, {"name": "Island", "count": 20}, {"name": "Mountain", "count": 28}],
    engine_args=("--flags", "known_cards"),
    script=_script,
)
