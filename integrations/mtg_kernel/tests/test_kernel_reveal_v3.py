"""Native public-operation intake, seat mapping, and duplicate delivery."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
from kernel_observation_v2 import ProjectionError
from kernel_reveal_v3 import RevealHistoryV3, SUPPORT_SCHEMA
from spellbench.reveal_meaning_v3 import SCHEMA, RevealProducerV3, RevealReducerV3


def support(first=(), second=()):
    return {"schema": SUPPORT_SCHEMA, "viewers": [
        {"viewer": viewer, "transcript": {"schema": SCHEMA, "operations": list(operations)}}
        for viewer, operations in enumerate((first, second))]}


def present(owner="p1", name="Island"):
    return {"kind": "card_revealed", "owner_seat": owner, "card_name": name, "meaning": "present"}


@pytest.mark.parametrize("viewer", [0, 1])
@pytest.mark.parametrize("first", ["p0", "p1"])
def test_four_reveal_classes_pass_through_native_intake_and_wire_reducer(viewer, first):
    owner = ("p1", "p0")[viewer]
    producer = RevealProducerV3()
    operations = []
    # An ordinary draw does not license an arrival link. Showing either an
    # old or newly drawn same-name copy supplies the same presence event.
    operations += producer.operation([present(owner)])["operations"]
    operations += producer.operation([present(owner)])["operations"]
    operations += producer.operation([
        {"kind": "hand_arrival", "owner_seat": owner, "card_name": None,
         "evidence": {"kind": "search_reveal"}},
        {**present(owner), "meaning": "moved", "arrival": producer.token(0)},
    ])["operations"]
    operations += producer.operation([
        {"kind": "hand_arrival", "owner_seat": owner, "card_name": "Island",
         "evidence": {"kind": "public_transfer", "from_zone": "stack"}},
        {**present(owner), "meaning": "moved", "arrival": producer.token(0)},
    ])["operations"]
    history = RevealHistoryV3()
    rows = [[], []]
    rows[viewer] = operations
    history.absorb(support(*rows))
    history.absorb(support(*rows))  # native retry is delivered only once
    mapping = {"p0": first, "p1": "p1" if first == "p0" else "p0"}
    wire = history.drain(viewer, mapping.__getitem__)
    assert len(wire["operations"]) == 4
    assert wire["operations"][2]["events"][1]["arrival"] == "arrival:2:0"
    reducer = RevealReducerV3()
    reducer.absorb(wire)
    expected = [{"owner_seat": mapping[owner], "card_name": "Island", "minimum": 2}]
    assert reducer.known_hand() == history.known_hand(viewer, mapping.__getitem__) == expected
    assert history.drain(viewer, mapping.__getitem__)["operations"] == []
    assert history.drain(1 - viewer, mapping.__getitem__)["operations"] == []


def test_malformed_second_viewer_rolls_back_both_viewers_and_private_fields_refuse():
    operation = {"sequence": 0, "events": [present()]}
    good = support([operation], [operation])
    history = RevealHistoryV3()
    bad = deepcopy(good)
    bad["viewers"][1]["transcript"]["operations"][0]["events"][0]["native_id"] = 888
    with pytest.raises(ProjectionError):
        history.absorb(bad)
    for viewer in (0, 1):
        assert history.known_hand(viewer, lambda seat: seat) == []
        assert history.drain(viewer, lambda seat: seat)["operations"] == []
    history.absorb(good)
    assert len(history.drain(0, lambda seat: seat)["operations"]) == 1
    assert len(history.drain(1, lambda seat: seat)["operations"]) == 1


def test_duplicate_operations_within_one_batch_are_queued_once():
    operation = {"sequence": 0, "events": [present()]}
    history = RevealHistoryV3()
    history.absorb(support([operation, deepcopy(operation)]))
    assert history.drain(0, lambda seat: seat)["operations"] == [operation]


def test_invalid_seat_mapping_does_not_consume_pending_operations():
    operation = {"sequence": 0, "events": [present()]}
    history = RevealHistoryV3()
    history.absorb(support([operation]))
    with pytest.raises(ProjectionError):
        history.drain(0, lambda seat: "p0")
    assert history.drain(0, lambda seat: seat)["operations"] == [operation]


@pytest.mark.parametrize("viewers", [[], [0], [0, 0], [True, 1], [0, 2]])
def test_incomplete_duplicate_or_invalid_viewers_refuse(viewers):
    history = RevealHistoryV3()
    value = support()
    value["viewers"] = [{"viewer": viewer, "transcript": {"schema": SCHEMA, "operations": []}}
                        for viewer in viewers]
    with pytest.raises(ProjectionError):
        history.absorb(value)
