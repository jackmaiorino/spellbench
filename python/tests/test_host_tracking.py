"""V3 (seat steps, groups, rewinds) and V7 (id freshness) state (spec 8, 5.3, 11.3)."""

from __future__ import annotations

import pickle

import pytest

from spellbench.host.tracking import GroupTracker, IdTracker
from spellbench.host.violation import RULES, ValidatorViolation


def sd(seat: str, step: int, group: int, index: int = 0, count: int = 1, *, kind: str = "priority", rewind: bool = False) -> dict:
    return {"acting_seat": seat, "seat_step": step, "group": {"group_id": group, "substep_index": index, "substep_count": count},
            "context": {"kind": kind, "source": None, "purpose": None, "text": None, "rewind": rewind}}


def play(tracker: GroupTracker, decision: dict, chosen: str = "pass") -> None:
    tracker.check(decision)
    tracker.answered(decision, chosen_kind=chosen)


def test_per_seat_counters_advance_independently() -> None:
    tracker = GroupTracker()
    for decision in (sd("p0", 0, 0), sd("p1", 0, 0), sd("p0", 1, 1), sd("p0", 2, 2), sd("p1", 1, 1)):
        play(tracker, decision)
    assert (tracker.answered_steps, tracker.completed_groups) == (5, 5)
    assert (tracker.answered_by("p0"), tracker.answered_by("p1")) == (3, 2)


@pytest.mark.parametrize(
    "decisions",
    [
        [sd("p0", 1, 0)],                                             # seat_step gap
        [sd("p0", 0, 1)],                                             # group_id skip
        [sd("p0", 0, 0, 0, 2), sd("p1", 0, 0)],                       # the other seat during a partial group
        [sd("p0", 0, 0, 0, 2), sd("p0", 1, 0, 1, 3)],                 # substep_count changed mid-group
        [sd("p0", 0, 0, 0, 2), sd("p0", 1, 1, 0, 1)],                 # a partial group abandoned without a rewind
        [sd("p0", 0, 0, rewind=True)],                                # a rewind with no action to undo
        [sd("p0", 0, 0), sd("p0", 1, 1, kind="choice", rewind=True)],  # a rewind that is not a priority decision
    ],
)
def test_v3_violations(decisions: list[dict]) -> None:
    tracker = GroupTracker()
    with pytest.raises(ValidatorViolation) as caught:
        for decision in decisions:
            play(tracker, decision, chosen="cast_spell")
    assert caught.value.rule == "V3"


def test_a_rewind_abandons_the_action_and_the_groups_after_it() -> None:
    tracker = GroupTracker()
    play(tracker, sd("p0", 0, 0), chosen="cast_spell")                   # the action (group 0)
    play(tracker, sd("p0", 1, 1, kind="choice"), chosen="choose_target")  # a completed target group (1)
    play(tracker, sd("p0", 2, 2, 0, 2, kind="choice"), chosen="choose_target")  # group 2 left partial
    rewound = sd("p0", 3, 3, rewind=True)                                 # re-posed priority: group 2 + 1
    play(tracker, rewound, chosen="pass")
    assert tracker.completed_groups == 1   # only the re-posed priority decision counts
    assert tracker.answered_steps == 4     # seat_step keeps counting answered decisions


def test_a_rewind_stops_counting_its_groups_when_posed() -> None:
    tracker = GroupTracker()
    play(tracker, sd("p0", 0, 0), chosen="cast_spell")
    play(tracker, sd("p0", 1, 1, kind="choice"), chosen="choose_target")
    tracker.check(sd("p0", 2, 2, rewind=True))       # validated, not yet answered: a forfeit here records 0 (R2-23)
    assert tracker.completed_groups == 0


def test_a_rewind_also_undoes_the_other_seats_later_action() -> None:
    tracker = GroupTracker()
    play(tracker, sd("p0", 0, 0), chosen="cast_spell")                    # p0's action
    play(tracker, sd("p1", 0, 0), chosen="cast_spell")                    # p1 responds with its own action
    play(tracker, sd("p1", 1, 1, kind="choice"), chosen="choose_target")  # p1's target group
    play(tracker, sd("p0", 1, 1, rewind=True), chosen="pass")             # p0 rewinds: all three groups are abandoned
    assert tracker.completed_groups == 1
    with pytest.raises(ValidatorViolation, match="without a priority action"):
        tracker.check(sd("p1", 2, 2, rewind=True))                        # p1's action was undone with them (R1-11)


def test_a_second_rewind_never_subtracts_a_group_twice() -> None:
    tracker = GroupTracker()
    play(tracker, sd("p1", 0, 0), chosen="cast_spell")                    # p1 acts first
    play(tracker, sd("p0", 0, 0), chosen="cast_spell")                    # then p0
    play(tracker, sd("p0", 1, 1, kind="choice"), chosen="choose_target")
    play(tracker, sd("p0", 2, 2, rewind=True), chosen="pass")             # p0's rewind abandons its two groups
    assert tracker.completed_groups == 2                                  # p1's action and p0's re-posed decision
    play(tracker, sd("p1", 1, 1, rewind=True), chosen="pass")             # p1's rewind abandons everything since its action
    assert tracker.completed_groups == 1                                  # each group subtracted once (R1-11)


def test_the_partial_seat() -> None:
    tracker = GroupTracker()
    assert tracker.partial_seat is None
    play(tracker, sd("p0", 0, 0, 0, 2, kind="choice"), chosen="choose_target")
    assert tracker.partial_seat == "p0"
    play(tracker, sd("p0", 1, 0, 1, 2, kind="choice"), chosen="choose_target")
    assert tracker.partial_seat is None


def test_id_freshness() -> None:
    ids = IdTracker()
    ids.check("p0", {"o-1": "hand", "o-2": "battlefield"})
    ids.check("p1", {"o-1": "graveyard"})                 # per viewer: another seat's stream
    with pytest.raises(ValidatorViolation) as two_zones:
        ids.check("p0", {"o-1": "graveyard", "o-2": "battlefield"})
    assert two_zones.value.rule == "V7"
    ids = IdTracker()
    ids.check("p0", {"o-1": "hand"})
    ids.check("p0", {"o-3": "battlefield"})               # o-1 left
    with pytest.raises(ValidatorViolation, match="returned"):
        ids.check("p0", {"o-1": "hand"})


def test_violations_cross_process_boundaries() -> None:
    violation = pickle.loads(pickle.dumps(ValidatorViolation("V4", "stale reference")))
    assert (violation.rule, violation.detail, str(violation)) == ("V4", "stale reference", "V4: stale reference")


@pytest.mark.parametrize(
    "answers",
    [
        [(sd("p0", 0, 0, 1, 2, kind="choice"), "choose_target")],                                           # a new group past substep 0
        [(sd("p0", 0, 0), "cast_spell"), (sd("p0", 1, 1), "pass"), (sd("p0", 2, 2, rewind=True), "pass")],  # a pass since the action
        [(sd("p1", 0, 0), "cast_spell"), (sd("p0", 0, 0, rewind=True), "pass")],                           # only the other seat acted
    ],
)
def test_more_v3_violations(answers: list[tuple[dict, str]]) -> None:
    tracker = GroupTracker()
    with pytest.raises(ValidatorViolation) as caught:
        for decision, chosen in answers:
            play(tracker, decision, chosen)
    assert caught.value.rule == "V3"


def test_a_rewind_skips_the_abandoned_group_id() -> None:
    tracker = GroupTracker()
    play(tracker, sd("p0", 0, 0), chosen="cast_spell")
    play(tracker, sd("p0", 1, 1, 0, 2, kind="choice"), chosen="choose_target")   # group 1 left partial
    rewound = sd("p0", 2, 2, rewind=True)                                         # group 1 + 1
    tracker.check(rewound)
    assert tracker.partial_seat is None                                           # group 1 is abandoned, not partial
    tracker.answered(rewound, chosen_kind="pass")
    play(tracker, sd("p0", 3, 3))                                                 # neither id 1 nor 2 is reused
    assert (tracker.answered_steps, tracker.completed_groups) == (4, 2)


def test_an_id_keeps_its_owner() -> None:
    ids = IdTracker()
    ids.check("p0", {"o-1": "battlefield"}, owners={"o-1": "p1"})
    ids.check("p0", {"o-1": "battlefield"}, owners={"o-1": "p1"})     # a controller or name may change, an owner never
    with pytest.raises(ValidatorViolation, match="owners p1 and p0") as caught:
        ids.check("p0", {"o-1": "battlefield"}, owners={"o-1": "p0"})
    assert caught.value.rule == "V7"
    ids.check("p1", {"o-1": "battlefield"}, owners={"o-1": "p0"})     # per viewer: another seat's stream


def test_an_id_first_seen_later_never_returns_either() -> None:
    ids = IdTracker()
    ids.check("p0", {"o-1": "hand"})
    ids.check("p0", {"o-1": "hand", "o-2": "stack"})      # o-2 appears
    ids.check("p0", {"o-1": "hand"})                      # and leaves
    with pytest.raises(ValidatorViolation, match="returned"):
        ids.check("p0", {"o-2": "stack"})


def test_a_violation_names_one_of_the_ten_rules() -> None:
    assert RULES == ("V1", "V2", "V3", "V4", "V5", "V6", "V7", "V8", "V9", "V10")
    with pytest.raises(ValueError, match="unknown validator rule"):
        ValidatorViolation("V11", "no such rule")
