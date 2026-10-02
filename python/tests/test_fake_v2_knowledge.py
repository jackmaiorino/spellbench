"""Knowledge (spec 6.7): every update-table row, through the validator."""

from __future__ import annotations

from spellbench.observation import OBSERVATION_FLAGS
from spellbench.run_secret import RunSecret

import fake_v2_scenario_knowledge
from fake_v2_knowledge import Knowledge
from fake_v2_world import World
from tour_helpers import play_tour

FLAGS = {**dict.fromkeys(OBSERVATION_FLAGS, False), "known_cards": True}      # the World reads all 13 flags (R2-21)


def _entry(owner, zone, name, top=None, bottom=None, how="revealed") -> dict:
    return {"owner_seat": owner, "zone": zone, "card_name": name, "object_id": None,
            "position_from_top": top, "position_from_bottom": bottom, "how": how}


def fresh(library: int = 10) -> Knowledge:
    """Viewer p0's knowledge, each library holding ``library`` cards (library_count is public)."""
    world = World(RunSecret(bytes(range(32))).game_secret(0), flags=FLAGS)
    for seat in ("p0", "p1"):
        for _ in range(library):
            world.add("Mountain", owner=seat, zone="library")
    return Knowledge(world, "p0")


def test_row_1_a_public_card_to_the_other_hand() -> None:
    knowledge = fresh()
    knowledge.public_to_other_hand("Lightning Bolt")
    assert knowledge.entries() == [_entry("p1", "hand", "Lightning Bolt", how="from_public_zone")]


def test_row_2_a_known_library_card_drawn_in_both_directions() -> None:
    knowledge = fresh()
    knowledge.looked_at("p1", [("Island", "top", 0)], "revealed")
    knowledge.known_library_card_drawn("p1", "top")                          # the other seat draws it: tracked
    assert knowledge.entries() == [_entry("p1", "hand", "Island", how="tracked")]
    own = fresh()
    own.looked_at("p0", [("Mountain", "top", 0)], "looked_at")
    own.known_library_card_drawn("p0", "top")                                # the viewer draws it: its own hand is never listed
    assert own.entries() == []


def test_row_3_a_revealed_hand_replaces_its_entries() -> None:
    knowledge = fresh()
    knowledge.public_to_other_hand("Lightning Bolt")
    knowledge.other_hand_revealed(["Counterspell", "Island"])
    assert knowledge.entries() == [_entry("p1", "hand", "Counterspell"), _entry("p1", "hand", "Island")]


def test_row_4_a_card_leaving_to_a_public_zone_removes_one_entry() -> None:
    knowledge = fresh()
    knowledge.other_hand_revealed(["Counterspell", "Counterspell"])
    knowledge.other_hand_to_public("Counterspell")
    assert knowledge.entries() == [_entry("p1", "hand", "Counterspell")]
    knowledge.other_hand_to_public("Island")                                 # no entry with that name: nothing changes
    assert knowledge.entries() == [_entry("p1", "hand", "Counterspell")]


def test_row_6_a_randomized_hand_is_forgotten() -> None:
    knowledge = fresh()
    knowledge.other_hand_revealed(["Counterspell"])
    knowledge.looked_at("p1", [("Island", "top", 0)], "revealed")
    knowledge.other_hand_randomized()
    assert knowledge.entries() == [_entry("p1", "library", "Island", top=0)]


def test_row_7_a_shuffle_forgets_that_library_only() -> None:
    knowledge = fresh()
    knowledge.looked_at("p0", [("Mountain", "top", 0)], "looked_at")
    knowledge.looked_at("p1", [("Island", "bottom", 0)], "revealed")
    knowledge.library_shuffled("p0")
    assert knowledge.entries() == [_entry("p1", "library", "Island", bottom=0)]


def test_row_12_an_insertion_at_an_unknown_depth_forgets_what_could_shift() -> None:
    knowledge = fresh()                                                      # 10 cards in p0's library before the insertion
    knowledge.looked_at("p0", [("Island", "top", 0), ("Forest", "top", 3)], "looked_at")
    knowledge.looked_at("p0", [("Swamp", "bottom", 0), ("Plains", "bottom", 8)], "looked_at")
    knowledge.ambiguous_insertion("p0", "top", 2)                            # somewhere at or below the second card from the top
    # Island (top 0) cannot move; Forest (top 3) and Swamp (9 from the top) might; Plains (1 from the top) moves
    # exactly one further from the bottom.
    assert knowledge.entries() == [_entry("p0", "library", "Island", top=0, how="looked_at"),
                                   _entry("p0", "library", "Plains", bottom=9, how="looked_at")]


def test_row_13_a_card_leaving_from_an_unknown_position_forgets_that_library() -> None:
    knowledge = fresh()
    knowledge.looked_at("p0", [("Island", "top", 0)], "looked_at")
    knowledge.looked_at("p1", [("Swamp", "bottom", 0)], "revealed")
    knowledge.left_unknown_position("p0")
    assert knowledge.entries() == [_entry("p1", "library", "Swamp", bottom=0)]


def test_hidden_departures_reduce_every_name() -> None:
    knowledge = fresh()
    knowledge.other_hand_revealed(["Counterspell", "Counterspell", "Island"])
    knowledge.other_hand_to_hidden(1)       # row 5: one card went back unseen, so each name's count c becomes max(0, c - 1)
    assert knowledge.entries() == [_entry("p1", "hand", "Counterspell")]


def test_library_ends_renumber() -> None:
    knowledge = fresh()
    knowledge.looked_at("p0", [("Mountain", "top", 0), ("Island", "top", 1)], "looked_at")     # row 8
    knowledge.left_library_end("p0", "top")                                                     # row 9: the top card drawn
    assert knowledge.entries() == [_entry("p0", "library", "Island", top=0, how="looked_at")]
    knowledge.put_on_library_end("p0", "top", None)                                            # row 10: an unknown card on top
    assert knowledge.entries() == [_entry("p0", "library", "Island", top=1, how="looked_at")]
    knowledge.hidden_rearrangement("p0", "top", 2)                                             # row 11: the other seat reorders two
    assert knowledge.entries() == []


def test_the_knowledge_tour_fires_every_row_and_passes_the_validator() -> None:
    decisions = play_tour(fake_v2_scenario_knowledge)
    marked = {int(sd["context"]["text"].split()[1]): sd for sd in decisions if (sd["context"]["text"] or "").startswith("row ")}
    assert sorted(marked) == sorted(fake_v2_scenario_knowledge.EXPECTED) == list(range(1, 14))
    assert {sd["acting_seat"] for sd in marked.values()} == {"p0"}          # every row is read from p0's view (R2-11)
    for row, expected in fake_v2_scenario_knowledge.EXPECTED.items():
        seen = [{k: v for k, v in entry.items() if k != "object_id"} for entry in marked[row]["observation"]["known"]]
        assert seen == [{k: v for k, v in entry.items() if k != "object_id"} for entry in expected], row
