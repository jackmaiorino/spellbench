from copy import deepcopy
import pytest

from spellbench.reveal_meaning_v3 import (
    SCHEMA, RevealMeaningError, RevealProducerV3, RevealReducerV3, arrival_token,
)


def present(owner="p1", name="Island"):
    return dict(kind="card_revealed", owner_seat=owner, card_name=name, meaning="present")


def arrival(owner="p1", name="Island"):
    return dict(kind="hand_arrival", owner_seat=owner, card_name=name,
                evidence=dict(kind="public_transfer", from_zone="graveyard"))


def moved(token, owner="p1", name="Island"):
    return dict(kind="card_revealed", owner_seat=owner, card_name=name,
                meaning="moved", arrival=token)


def batch(events, sequence=0):
    return dict(schema=SCHEMA, operations=[dict(sequence=sequence, events=events)])


@pytest.mark.parametrize("owner", ["p0", "p1"])
def test_repeats_and_overlapping_arrival_do_not_invent_another_copy(owner):
    producer, reducer = RevealProducerV3(), RevealReducerV3()
    first = producer.operation([present(owner), present(owner)])
    reducer.absorb(first)
    reducer.absorb(first)
    second = producer.operation([arrival(owner), moved(producer.token(0), owner)])
    reducer.absorb(second)
    assert reducer.known_hand() == [dict(owner_seat=owner, card_name="Island", minimum=1)]
    reducer.absorb(producer.operation([arrival(owner)]))
    assert reducer.known_hand()[0]["minimum"] == 2


def test_explicit_search_outcome_binds_only_within_its_atomic_operation():
    reducer = RevealReducerV3()
    search = dict(kind="hand_arrival", owner_seat="p1", card_name=None,
                  evidence=dict(kind="search_reveal"))
    reducer.absorb(batch([search, moved(arrival_token(0, 0))]))
    assert reducer.known_hand()[0]["minimum"] == 1
    with pytest.raises(RevealMeaningError, match="expired"):
        reducer.absorb(batch([moved(arrival_token(0, 0))], 1))
    assert reducer.known_hand()[0]["minimum"] == 1
    with pytest.raises(RevealMeaningError, match="lacks"):
        RevealReducerV3().absorb(batch([search]))


@pytest.mark.parametrize("interruption", [
    dict(kind="hand_departure", owner_seat="p1", card_name=None, count=1),
    dict(kind="hand_departure", owner_seat="p1", card_name="Island", count=1),
    dict(kind="library_shuffled", owner_seat="p1"),
    dict(kind="public_correspondence_lost", owner_seat="p1"),
])
def test_intervening_ambiguity_expires_links_and_failure_is_atomic(interruption):
    reducer = RevealReducerV3()
    with pytest.raises(RevealMeaningError, match="expired"):
        reducer.absorb(batch([arrival(), interruption, moved(arrival_token(0, 0))]))
    assert reducer.known_hand() == []
    reducer.absorb(batch([present()]))  # failed input did not consume sequence 0


def test_named_and_unknown_departures_keep_conservative_survivor_counts():
    reducer = RevealReducerV3()
    reducer.absorb(batch([arrival(), arrival(), arrival(name="Forest"), present()]))
    reducer.absorb(batch([dict(kind="hand_departure", owner_seat="p1", card_name=None, count=1)], 1))
    assert reducer.known_hand() == [dict(owner_seat="p1", card_name="Island", minimum=1)]
    reducer.absorb(batch([dict(kind="hand_departure", owner_seat="p1", card_name="Forest", count=1)], 2))
    assert reducer.known_hand()[0]["minimum"] == 1
    reducer.absorb(batch([dict(kind="hand_departure", owner_seat="p1", card_name="Island", count=1)], 3))
    assert reducer.known_hand() == []


@pytest.mark.parametrize("bad", [
    [arrival(), moved(arrival_token(0, 0), owner="p0")],
    [arrival(), moved(arrival_token(0, 0), name="Forest")],
    [moved(arrival_token(0, 0))],
    [dict(present(), meaning="new_copy")],
    [dict(present(), native_object=123)],
    [dict(arrival(), evidence=dict(kind="anonymous_draw"))],
    [dict(arrival(), evidence=dict(kind="public_transfer", from_zone="library"))],
    [dict(kind="hand_departure", owner_seat="p1", card_name=None, count=True)],
    [dict(kind="hand_departure", owner_seat="p1", card_name=None, count=2**53)],
    [present(name="Lim-Du\u0302l's Vault")],
    [present(name="\ud800")],
    [dict(kind=[])],
])
def test_unjustified_or_private_link_payloads_refuse(bad):
    with pytest.raises(RevealMeaningError):
        RevealReducerV3().absorb(batch(bad))


def test_changed_repeated_operation_refuses_without_changing_prior_facts():
    reducer = RevealReducerV3()
    original = batch([present()])
    reducer.absorb(original)
    changed = deepcopy(original)
    changed["operations"][0]["events"][0]["card_name"] = "Forest"
    with pytest.raises(RevealMeaningError, match="duplicate"):
        reducer.absorb(changed)
    assert reducer.known_hand() == [dict(owner_seat="p1", card_name="Island", minimum=1)]


def test_invalid_later_operation_does_not_commit_an_earlier_operation_in_same_batch():
    reducer = RevealReducerV3()
    wire = batch([present()])
    wire["operations"].append(dict(sequence=1, events=[moved(arrival_token(0, 0))]))
    with pytest.raises(RevealMeaningError):
        reducer.absorb(wire)
    assert reducer.known_hand() == []
    reducer.absorb(batch([present()]))
