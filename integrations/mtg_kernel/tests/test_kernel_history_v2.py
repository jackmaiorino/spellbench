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
