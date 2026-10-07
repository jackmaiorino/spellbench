"""Per-viewer public history from the private omniscient slice."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
from kernel_history_v2 import PublicHistory  # noqa: E402
from kernel_observation_v2 import ProjectionError  # noqa: E402


class Projection:
    """The two projection facts drain reads: seat mapping and current ids."""

    def __init__(self, visible=None, first="p0"):
        self.stable_refs = {(arena, 0, "zone"): {"object_id": object_id} for arena, object_id in (visible or {}).items()}
        self.map = {"p0": first, "p1": "p1" if first == "p0" else "p0"}

    def seat(self, native):
        return self.map[native]


def objects(*cards):
    return [{"object": index, "owner": owner, "card_name": name, "is_token": False, "copy": False}
            for index, (owner, name) in enumerate(cards)]


def slice_(events=(), notes=(), new_objects=(), history=None):
    history = history or PublicHistory()
    return {"events_from": history.events_seen, "events": list(events),
            "notes_from": history.notes_seen, "notes": list(notes),
            "objects_from": len(history.objects), "objects": list(new_objects)}


DECKS = objects((0, "Lightning Bolt"), (0, "Mountain"), (1, "Counterspell"), (1, "Island"))


def test_draws_name_the_card_only_for_the_drawer():
    history = PublicHistory()
    history.absorb(slice_(
        events=[{"Draw": {"player": 0, "object": 0}}, {"Draw": {"player": 1, "object": 2}}],
        notes=[{"history_len": 0, "kind": "library_removal", "owner": 0, "position": 0},
               {"history_len": 1, "kind": "library_removal", "owner": 1, "position": 0}],
        new_objects=DECKS))
    mine = history.drain(0, Projection({0: "own-bolt"}))
    assert mine["schema"] == "x_public_history_v1"
    assert mine["events"] == [
        {"kind": "draw", "seat": "p0", "card": {"object_id": "own-bolt", "card_name": "Lightning Bolt", "owner_seat": "p0"}},
        {"kind": "draw", "seat": "p1", "card": None},
    ]
    theirs = history.drain(1, Projection())
    assert [event["card"] for event in theirs["events"]] == [
        None, {"object_id": None, "card_name": "Counterspell", "owner_seat": "p1"}]
    assert history.drain(0, Projection())["events"] == []


def test_public_moves_are_named_and_hidden_moves_are_counts():
    history = PublicHistory()
    history.absorb(slice_(new_objects=DECKS))
    history.absorb(slice_(history=history, events=[
        {"Draw": {"player": 1, "object": 2}},
        {"SpellCast": {"spell": 2, "controller": 1}},
        {"ZoneChange": {"object": 2, "from": "Stack", "to": "Graveyard", "controller_before": 1}},
        {"ZoneChange": {"object": 3, "from": "Library", "to": "Hand", "controller_before": 1}},
    ], notes=[{"history_len": 3, "kind": "library_removal", "owner": 1, "position": 2}]))
    events = history.drain(0, Projection({2: "their-counterspell"}))["events"]
    assert events[1] == {"kind": "zone_move", "owner_seat": "p1", "from": {"zone": "hand"}, "to": {"zone": "stack"},
                         "card": {"object_id": None, "card_name": "Counterspell", "owner_seat": "p1"}}
    # The graveyard card is the same incarnation the viewer sees now.
    assert events[2]["card"]["object_id"] == "their-counterspell"
    # A tutor between the opponent's hidden zones shows only that a card moved,
    # from its public position.
    assert events[3] == {"kind": "zone_move", "owner_seat": "p1", "card": None,
                         "from": {"zone": "library", "position_from_top": 2}, "to": {"zone": "hand"}}


def test_ids_never_link_across_a_later_zone_change():
    history = PublicHistory()
    history.absorb(slice_(new_objects=DECKS))
    history.absorb(slice_(history=history, events=[
        {"ZoneChange": {"object": 2, "from": "Library", "to": "Graveyard", "controller_before": 1}},
        {"ZoneChange": {"object": 2, "from": "Graveyard", "to": "Hand", "controller_before": 1}},
        {"SpellCast": {"spell": 2, "controller": 1}},
    ]))
    events = history.drain(0, Projection({2: "on-the-stack"}))["events"]
    assert [event["card"]["object_id"] for event in events] == [None, None, "on-the-stack"]


def test_notes_reach_only_their_observers_and_rearrangements_are_counts():
    history = PublicHistory()
    history.absorb(slice_(new_objects=DECKS))
    history.absorb(slice_(history=history, notes=[
        {"history_len": 0, "kind": "library_looked", "observer": 0, "owner": 1, "positions": [[0, 3]]},
        {"history_len": 0, "kind": "library_scried", "owner": 1, "retained_top": [3], "ordered_bottom": [2]},
        {"history_len": 0, "kind": "hand_card_revealed", "observer": 0, "owner": 1, "object": 2},
        {"history_len": 0, "kind": "library_randomized", "owner": 1},
    ]))
    viewer = history.drain(0, Projection())["events"]
    owner = history.drain(1, Projection())["events"]
    assert [event["kind"] for event in viewer] == ["looked_at", "library_rearranged", "card_revealed", "library_shuffled"]
    assert viewer[1] == {"kind": "library_rearranged", "owner_seat": "p1", "top_count": 1, "bottom_count": 1}
    assert [event["kind"] for event in owner] == ["library_rearranged", "looked_at", "library_shuffled"]
    assert owner[1]["cards"] == [
        {"position_from_top": 0, "card": {"object_id": None, "card_name": "Island", "owner_seat": "p1"}},
        {"position_from_bottom": 0, "card": {"object_id": None, "card_name": "Counterspell", "owner_seat": "p1"}}]


def test_turns_count_rounds_and_seats_follow_the_projection_mapping():
    history = PublicHistory()
    history.absorb(slice_(new_objects=DECKS, events=[{"UpkeepBegan": {"player": 0}}, {"UpkeepBegan": {"player": 1}},
                                                     {"UpkeepBegan": {"player": 0}}]))
    events = history.drain(0, Projection(first="p1"))["events"]
    # Turn numbers count rounds, as the observation's turn does.
    assert events == [{"kind": "turn_began", "turn": 1, "active_seat": "p1"},
                      {"kind": "turn_began", "turn": 1, "active_seat": "p0"},
                      {"kind": "turn_began", "turn": 2, "active_seat": "p1"}]


def test_slices_must_be_contiguous_and_well_formed():
    history = PublicHistory()
    history.absorb(slice_(new_objects=DECKS))
    stale = slice_(new_objects=DECKS)
    with pytest.raises(ProjectionError, match="contiguous"):
        history.absorb(stale)
    with pytest.raises(ProjectionError, match="malformed"):
        history.absorb({"events": []})
    bad_zone = slice_(history=history, events=[{"ZoneChange": {"object": 0, "from": "Library", "to": "Sideboard",
                                                               "controller_before": 0}}])
    with pytest.raises(ProjectionError, match="zone"):
        history.absorb(bad_zone)


# -- knowledge tracker (spec Section 6.7) ----------------------------------------

def names(history, viewer, owner):
    return sorted((fact["name"], fact["how"]) for fact in history.knowledge(viewer)["hand"][owner])


def test_a_known_top_card_drawn_by_its_owner_stays_known_by_name():
    history = PublicHistory()
    history.absorb(slice_(new_objects=DECKS, notes=[
        {"history_len": 0, "kind": "library_looked", "observer": 0, "owner": 1, "positions": [[0, 2]]}]))
    assert history.knowledge(0)["library"][1] == {0: {"native": 2, "name": "Counterspell", "how": "looked_at"}}
    history.absorb(slice_(history=history, events=[{"Draw": {"player": 1, "object": 2}}],
                          notes=[{"history_len": 0, "kind": "library_removal", "owner": 1, "position": 0}]))
    assert history.knowledge(0)["library"][1] == {}
    assert names(history, 0, 1) == [("Counterspell", "tracked")]
    assert history.knowledge(0)["hand_truth"][1] == {"Counterspell": 1}
    # The card leaves identified, so its fact goes with it.
    history.absorb(slice_(history=history, events=[{"SpellCast": {"spell": 2, "controller": 1}}]))
    assert names(history, 0, 1) == []


def test_hidden_departures_cost_every_name_one_fact_and_unbind_copies():
    cards = objects((1, "Island"), (1, "Island"), (1, "Counterspell"), (0, "Mountain"))
    history = PublicHistory()
    history.absorb(slice_(new_objects=cards, events=[
        {"ZoneChange": {"object": index, "from": "Library", "to": "Battlefield", "controller_before": 1}}
        for index in (0, 1, 2)]))
    history.absorb(slice_(history=history, events=[
        {"ZoneChange": {"object": index, "from": "Battlefield", "to": "Hand", "controller_before": 1}}
        for index in (0, 1, 2)]))
    assert names(history, 0, 1) == [("Counterspell", "from_public_zone"), ("Island", "from_public_zone"),
                                    ("Island", "from_public_zone")]
    assert 1 not in history.knowledge(1)["hand"]  # a viewer never tracks its own hand
    history.absorb(slice_(history=history, events=[
        {"ZoneChange": {"object": 1, "from": "Hand", "to": "Library", "controller_before": 1}}]))
    facts = history.knowledge(0)["hand"][1]
    assert sorted(fact["name"] for fact in facts) == ["Island"]
    assert all(fact["native"] is None for fact in facts)


def test_a_reveal_binds_an_existing_fact_and_waits_for_the_card_to_reach_the_hand():
    history = PublicHistory()
    history.absorb(slice_(new_objects=DECKS, events=[
        {"ZoneChange": {"object": 3, "from": "Library", "to": "Battlefield", "controller_before": 1}}]))
    # The kernel reveals a card returned to hand before committing the move
    # event, so the note carries the move's own history index.
    history.absorb(slice_(history=history, events=[
        {"ZoneChange": {"object": 3, "from": "Battlefield", "to": "Hand", "controller_before": 1}}],
        notes=[{"history_len": 1, "kind": "hand_card_revealed", "observer": 0, "owner": 1, "object": 3}]))
    assert history.knowledge(0)["hand"][1] == [{"name": "Island", "how": "from_public_zone", "native": 3}]


def test_scry_mirrors_the_kernel_for_owner_and_other_viewer():
    cards = objects(*[(1, f"Card {index}") for index in range(5)])
    history = PublicHistory()
    history.absorb(slice_(new_objects=cards, notes=[
        {"history_len": 0, "kind": "library_looked", "observer": 0, "owner": 1, "positions": [[0, 0], [3, 3]]}]))
    history.absorb(slice_(history=history, notes=[
        {"history_len": 0, "kind": "library_scried", "owner": 1, "retained_top": [], "ordered_bottom": [0]}]))
    # The other viewer keeps its single known scried card at the bottom and
    # the tail fact shifts up by one.
    assert {position: fact["native"] for position, fact in history.knowledge(0)["library"][1].items()} == {2: 3, 4: 0}
    assert {position: fact["native"] for position, fact in history.knowledge(1)["library"][1].items()} == {4: 0}
    history.absorb(slice_(history=history, notes=[{"history_len": 0, "kind": "library_randomized", "owner": 1}]))
    assert history.knowledge(0)["library"][1] == {}


def test_hand_facts_absorb_current_reveals_and_never_overclaim():
    from collections import Counter
    from kernel_observation_v2 import KernelProjection

    projection = KernelProjection.__new__(KernelProjection)
    projection.seat_map = {"p0": "p1", "p1": "p0"}
    facts = [{"name": "Island", "how": "from_public_zone", "native": None},
             {"name": "Island", "how": "tracked", "native": None}]
    revealed = {"owner_seat": "p0", "zone": "hand", "card_name": "Island", "object_id": "now",
                "position_from_top": None, "position_from_bottom": None, "how": "revealed"}
    known = [dict(revealed)]
    projection.add_hand_knowledge(known, {"hand": {1: facts}, "hand_truth": {1: Counter(Island=2)}}, [7, 2])
    # Native p1 is wire p0 here; the current reveal stands in for one fact.
    assert [(entry["how"], entry["object_id"]) for entry in known] == [("revealed", "now"), ("from_public_zone", None)]
    with pytest.raises(ProjectionError, match="does not hold"):
        projection.add_hand_knowledge([], {"hand": {1: facts}, "hand_truth": {1: Counter(Island=1)}}, [7, 2])
    with pytest.raises(ProjectionError, match="hand count"):
        projection.add_hand_knowledge([dict(revealed)], {"hand": {1: facts + [{"name": "Bolt", "how": "revealed",
                                                                                 "native": 4}]},
                                                         "hand_truth": {1: Counter(Island=2, Bolt=1)}}, [7, 2])
