"""Fischer clock, per-seat caps and stalling adjudication (spec 11.4)."""

from __future__ import annotations

from spellbench.host.clock import CapRuling, SeatCaps, SeatClock, StallingWindow, is_real_choice


def test_the_clock_charges_then_adds_the_increment() -> None:
    clock = SeatClock(bank_ms=1000, increment_ms=200, max_decision_ms=600)
    assert clock.budget_ms() == 600
    assert clock.charge(500) and clock.remaining_ms == 700
    assert clock.charge(600) and clock.remaining_ms == 300   # exactly the cap is allowed
    assert clock.budget_ms() == 300                          # the bank is now the tighter limit
    assert not clock.charge(301)                             # over the remaining bank: a timeout
    assert not SeatClock(bank_ms=10_000, increment_ms=0, max_decision_ms=100).charge(101)
    assert SeatClock(bank_ms=100, increment_ms=0, max_decision_ms=600).charge(100)   # exactly the bank is allowed


def test_each_cap_is_reached_at_equality() -> None:
    caps = SeatCaps(per_turn=3, groups_per_game=100, steps_per_game=100)
    assert [caps.record("p0", turn=1, completed_group=True) for _ in range(2)] == [None, None]
    assert caps.record("p0", turn=1, completed_group=True) == "max_seat_decisions_per_turn"
    fresh = SeatCaps(per_turn=3, groups_per_game=100, steps_per_game=100)
    assert fresh.record("p0", turn=1, completed_group=True) is None
    assert fresh.record("p0", turn=2, completed_group=True) is None   # a new turn resets the per-turn count
    assert fresh.record("p1", turn=2, completed_group=True) is None   # seats count separately
    assert fresh.record("p1", turn=2, completed_group=True) is None
    assert fresh.record("p0", turn=2, completed_group=True) is None   # p0's second decision of turn 2
    assert fresh.record("p0", turn=2, completed_group=True) == "max_seat_decisions_per_turn"


def test_game_caps_count_groups_and_steps_separately() -> None:
    caps = SeatCaps(per_turn=1000, groups_per_game=2, steps_per_game=5)
    assert caps.record("p1", turn=1, completed_group=False) is None
    assert caps.record("p1", turn=2, completed_group=True) is None
    assert caps.record("p1", turn=3, completed_group=True) == "max_seat_decisions_per_game"
    steps = SeatCaps(per_turn=1000, groups_per_game=1000, steps_per_game=2)
    steps.record("p0", turn=1, completed_group=False)
    assert steps.record("p0", turn=1, completed_group=False) == "max_seat_steps_per_game"


def test_real_choices_are_non_pass_selections_among_several() -> None:
    assert is_real_choice(2, "activate_ability")
    assert not is_real_choice(2, "pass")
    assert not is_real_choice(1, "cast_spell")


def test_stalling_rulings() -> None:
    window = StallingWindow()
    for _ in range(10):
        window.record("p0", real_choice=False)
        window.record("p1", real_choice=False)
    assert window.ruling("p0") == CapRuling(kind="draw", loser_seat=None)   # a mandatory loop
    window.record("p1", real_choice=True)
    assert window.ruling("p0") == CapRuling(kind="forfeit", loser_seat="p1")
    window.record("p0", real_choice=True)
    assert window.ruling("p0") == CapRuling(kind="forfeit", loser_seat="p0")  # a tie: the capped seat
    assert window.ruling("p1") == CapRuling(kind="forfeit", loser_seat="p1")


def test_the_window_is_the_last_250_decisions_of_either_seat() -> None:
    window = StallingWindow()
    window.record("p1", real_choice=True)
    for _ in range(250):
        window.record("p0", real_choice=False)
    assert window.ruling("p0").kind == "draw"   # p1's real choice fell out of the window
    window.record("p1", real_choice=True)
    for _ in range(249):
        window.record("p0", real_choice=False)
    assert window.ruling("p0") == CapRuling(kind="forfeit", loser_seat="p1")   # the 250th most recent still counts


def test_the_window_counts_each_seats_real_choices() -> None:
    window = StallingWindow()
    assert window.counts() == {"p0": 0, "p1": 0}
    window.record("p0", real_choice=True)
    window.record("p1", real_choice=False)
    window.record("p1", real_choice=True)
    assert window.counts() == {"p0": 1, "p1": 1}
    for _ in range(247):
        window.record("p1", real_choice=False)
    assert window.counts() == {"p0": 1, "p1": 1}   # 250 decisions: p0's real choice is the oldest still counted
    window.record("p1", real_choice=False)
    assert window.counts() == {"p0": 0, "p1": 1}   # the 251st pushes it out, as it does for the ruling
    assert window.ruling("p0") == CapRuling(kind="forfeit", loser_seat="p1")
