"""V5: hidden zones, knowledge entries and hidden-card candidate order (spec 6.7, 7.1)."""

import pytest

from spellbench.host.hidden import check_hidden_zones, hidden_candidate_key, known_sort_key
from spellbench.host.violation import ValidatorViolation

from v2_sample_semantics import R_BOLT, SAMPLES, seat_decision

LIB = lambda object_id, name: {"object_id": object_id, "card_name": name, "owner_seat": "p0", "controller_seat": "p0", "zone": "library"}


def _known(entry_overrides: dict) -> dict:
    return {"owner_seat": "p1", "zone": "hand", "card_name": "Counterspell", "object_id": None,
            "position_from_top": None, "position_from_bottom": None, "how": "revealed", **entry_overrides}


def _with(mutate) -> dict:
    decision = seat_decision()
    mutate(decision["observation"])
    return decision


def test_the_spec_example_passes() -> None:
    check_hidden_zones(seat_decision())


@pytest.mark.parametrize(
    "mutate",
    [
        lambda o: o["players"][1].update(hand=[]),                                 # the other seat's hand shown
        lambda o: o["players"][0].update(hand_count=3),                             # hand and hand_count disagree
        lambda o: o["players"][0]["hand"][1].update(zone="library"),                # a library object in a zone array
        lambda o: o.update(known=list(reversed(o["known"]))),                       # unsorted
        lambda o: o["known"].append(_known({"owner_seat": "p0"})),                  # the viewer's own hand listed
        lambda o: o["known"].append(_known({"position_from_top": 0})),              # a hand entry with a position
        lambda o: o["known"].insert(1, _known({"owner_seat": "p0", "zone": "library", "how": "looked_at", "card_name": "Mountain"})),
        lambda o: o["known"].extend([_known({})] * 3),                              # 4 entries for a hand of 3
        lambda o: o["known"].append(_known({"how": "from_public_zone", "object_id": "o-1"})),
        lambda o: o["known"][0].update(position_from_top=46),                       # p0's library holds 46 cards (R2-25)
    ],
)
def test_v5_violations(mutate) -> None:
    with pytest.raises(ValidatorViolation) as caught:
        check_hidden_zones(_with(mutate))
    assert caught.value.rule == "V5"


def test_a_search_entry_may_have_no_position() -> None:
    # Null positions sort first, so the search entry precedes the positioned Mountain.
    check_hidden_zones(_with(lambda o: o["known"].insert(0, _known(
        {"owner_seat": "p0", "zone": "library", "card_name": "Mountain", "how": "searching", "object_id": "o-9"}))))


def test_hidden_card_candidates_are_in_name_then_id_order() -> None:
    search = lambda ref: {**SAMPLES["select_object"], "purpose": "search", "choice": {"object": ref}, "minimum": 0}
    ordered = [search(LIB("o-b", "Island")), search(LIB("o-a", "Mountain")), SAMPLES["finish_selection"]]
    check_hidden_zones(seat_decision(ordered, kind="choice"))
    with pytest.raises(ValidatorViolation, match="order"):
        check_hidden_zones(seat_decision(list(reversed(ordered[:2])), kind="choice"))


def test_the_sort_key_puts_nulls_first() -> None:
    entries = [_known({"zone": "library", "how": "looked_at", "position_from_top": 0}),
               _known({"zone": "library", "how": "looked_at", "position_from_bottom": 0})]
    assert sorted(entries, key=known_sort_key) == [entries[1], entries[0]]


OPPONENT = lambda object_id, name: {"object_id": object_id, "card_name": name, "owner_seat": "p1", "controller_seat": "p1", "zone": "hand"}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda o: o["players"][0].update(hand=None),                                          # the viewer's hand null
        lambda o: o["players"][1]["battlefield"][0].update(zone="library"),                   # a library object on a battlefield
        lambda o: o["known"].insert(0, _known({"owner_seat": "p0"})),                         # the viewer's own hand
        lambda o: o["known"].append(_known({"position_from_bottom": 0})),                     # a hand entry with a bottom position
        # a library entry with no position
        lambda o: o["known"].insert(0, _known({"owner_seat": "p0", "zone": "library", "how": "looked_at", "card_name": "Mountain"})),
        lambda o: o["known"][0].update(position_from_bottom=0),                               # a library entry with two positions
        lambda o: o["known"][0].update(how="searching", position_from_bottom=0),              # a search entry with two positions
        lambda o: o["known"][0].update(position_from_top=None, position_from_bottom=46),      # past the bottom of p0's library
        lambda o: o["known"].insert(1, _known({"how": "from_public_zone", "object_id": "o-1"})),  # an id on older knowledge
    ],
)
def test_each_v5_rule_alone(mutate) -> None:
    # Each entry sits at its sorted position, so the order rule cannot be what fails.
    with pytest.raises(ValidatorViolation) as caught:
        check_hidden_zones(_with(mutate))
    assert caught.value.rule == "V5" and "out of order" not in caught.value.detail


@pytest.mark.parametrize(
    "mutate",
    [
        lambda o: o["known"].extend([_known({})] * 2),                                        # 3 equal entries for a hand of 3
        lambda o: o["known"].append(_known({"zone": "library", "how": "looked_at", "position_from_top": 46})),  # p1's library holds 47
        lambda o: o["known"][0].update(object_id="o-7"),                                      # a card looked at in this decision
        lambda o: o["known"][1].update(object_id="o-8"),                                      # a card revealed in this decision
    ],
)
def test_v5_accepts(mutate) -> None:
    check_hidden_zones(_with(mutate))


def test_hidden_card_candidates_are_ordered_among_themselves() -> None:
    search = lambda ref: {**SAMPLES["select_object"], "purpose": "search", "choice": {"object": ref}, "minimum": 0}
    island, mountain, finish = search(LIB("o-b", "Island")), search(LIB("o-a", "Mountain")), SAMPLES["finish_selection"]
    check_hidden_zones(seat_decision([island, finish, mountain], kind="choice"))          # other candidates may sit between
    top, bottom = ({**SAMPLES["arrange_card"], "card": LIB("o-a", "Island"), "destination": end} for end in ("top", "bottom"))
    check_hidden_zones(seat_decision([top, bottom], kind="choice"))                        # one card twice: equal keys
    discard = lambda ref: {**SAMPLES["select_object"], "choice": {"object": ref}}
    for unordered in ([mountain, finish, island],
                      [discard(OPPONENT("o-a", "Spellstutter Sprite")), discard(OPPONENT("o-b", "Counterspell"))]):
        with pytest.raises(ValidatorViolation, match="order"):
            check_hidden_zones(seat_decision(unordered, kind="choice"))


def test_the_hidden_candidate_key() -> None:
    assert hidden_candidate_key(SAMPLES["cast_spell"], "p0") is None                       # the viewer's own hand
    assert hidden_candidate_key(SAMPLES["cast_spell"], "p1") is not None                   # p0's hand is hidden from p1
    piles = lambda first, second: {**SAMPLES["choose_pile"], "piles": [[first], [R_BOLT, second]]}
    mountain, island, forest = LIB("o-2", "Mountain"), LIB("o-1", "Island"), LIB("o-3", "Forest")
    key = lambda semantic: hidden_candidate_key(semantic, "p0")
    assert key(piles(mountain, forest)) < key(piles(mountain, island))                     # every hidden reference counts
    assert key(piles(island, mountain)) < key(piles(mountain, island))                     # in object_references order
    assert key({**SAMPLES["select_object"], "choice": {"object": LIB("o-z", None)}}) < key(piles(forest, island))  # null first


def test_the_rules_follow_the_acting_seat() -> None:
    def p1_view(mutate=lambda o: None) -> dict:
        decision = seat_decision([SAMPLES["pass"]], acting_seat="p1")
        o = decision["observation"]
        o.update(viewer="p1", known=[_known({"owner_seat": "p0", "card_name": "Lightning Bolt"}), o["known"][0]])
        o["players"][0].update(hand=None)
        o["players"][1].update(hand=[], hand_count=0)
        mutate(o)
        return decision

    check_hidden_zones(p1_view())
    for mutate in (lambda o: o["players"][0].update(hand=[]),                              # p0's hand shown to p1
                   lambda o: o["known"].append(_known({}))):                               # p1's own hand listed
        with pytest.raises(ValidatorViolation) as caught:
            check_hidden_zones(p1_view(mutate))
        assert caught.value.rule == "V5"
    with pytest.raises(ValidatorViolation) as caught:                                      # p0's view sent to p1: V2 halts
        check_hidden_zones(seat_decision([SAMPLES["pass"]], acting_seat="p1"))            # it first, but V5 alone still
    assert caught.value.detail.startswith("observation.players[0].hand must be null")      # guards the seat receiving it


def _library_entry(**fields) -> dict:
    return _known({"zone": "library", "how": "looked_at", **fields})


@pytest.mark.parametrize(
    ("earlier", "later"),
    [
        (_known({"card_name": "Counterspell"}), _known({"card_name": "Spellstutter Sprite"})),            # card_name
        (_known({"how": "from_public_zone"}), _known({"how": "revealed"})),                                # how
        (_known({}), _known({"object_id": "o-1"})),                                                        # a null id first
        (_known({"object_id": "o-1"}), _known({"object_id": "o-2"})),                                      # object_id
        (_known({"card_name": "Zodiac"}),                                                                  # zone before card_name
         _known({"zone": "library", "card_name": "Aether", "how": "looked_at", "position_from_top": 0})),
        (_library_entry(position_from_top=0), _library_entry(position_from_top=1)),                        # position_from_top
        (_library_entry(position_from_bottom=0), _library_entry(position_from_bottom=1)),                  # position_from_bottom
        (_library_entry(how="searching"), _library_entry(how="searching", position_from_bottom=0)),        # a null bottom first
        (_library_entry(card_name="Counterspell", position_from_top=1),                                    # card_name before positions
         _library_entry(card_name="Island", position_from_top=0)),
        (_library_entry(how="revealed", position_from_bottom=0), _library_entry(position_from_bottom=1)),  # positions before how
        (_known({"how": "looked_at", "object_id": "o-2"}), _known({"object_id": "o-1"})),                  # how before object_id
    ],
)
def test_each_known_key_component(earlier, later) -> None:
    check_hidden_zones(_with(lambda o: o.update(known=[earlier, later])))
    with pytest.raises(ValidatorViolation, match="out of order"):
        check_hidden_zones(_with(lambda o: o.update(known=[later, earlier])))


def test_same_name_hidden_candidates_are_in_id_order() -> None:
    search = lambda ref: {**SAMPLES["select_object"], "purpose": "search", "choice": {"object": ref}, "minimum": 0}
    first, second = search(LIB("o-a", "Island")), search(LIB("o-b", "Island"))
    check_hidden_zones(seat_decision([first, second, SAMPLES["finish_selection"]], kind="choice"))
    with pytest.raises(ValidatorViolation, match="order"):
        check_hidden_zones(seat_decision([second, first, SAMPLES["finish_selection"]], kind="choice"))
