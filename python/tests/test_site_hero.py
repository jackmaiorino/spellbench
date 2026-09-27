"""The Hero table: Elo above the random bot, averaged across benchmarks."""

from __future__ import annotations

import math
from typing import Any

import pytest

from spellbench.site.hero import HeroChip, hero_table, rating_bound


def _row(
    name: str, elo: int, ci: tuple[int, int] | None, rated: bool = True, record: tuple[int, int, int] = (5, 0, 5)
) -> dict[str, Any]:
    """A leaderboard row reduced to the fields the Hero table reads; ``record`` is (wins, draws, losses)."""
    wins, draws, losses = record
    return {
        "name": name, "rated": rated, "elo_milli": elo if rated else None, "ci95_elo_milli": None if ci is None else list(ci),
        "wins": wins, "draws": draws, "losses": losses, "games": wins + draws + losses,
    }


def _board(*rows: dict[str, Any], anchor: str = "uniform", status: str = "ok") -> dict[str, Any]:
    """A leaderboard document reduced to the fields the Hero table reads."""
    anchor_row = _row(anchor, 1_000_000, (1_000_000, 1_000_000))
    return {"status": status, "anchor": {"bot_id": "a" * 64, "name": anchor, "version": "1.0.0"}, "rows": [anchor_row, *rows]}


def _by_name(table) -> dict[str, Any]:
    return {row.name: row for row in table.rows}


def test_one_benchmark_uses_its_own_interval() -> None:
    table = hero_table([("pauper", _board(_row("heuristic", 1_101_000, (1_052_000, 1_150_500))))])
    row = _by_name(table)["heuristic"]
    assert (row.score, row.lower, row.upper, row.approximate, row.reference) == (101.0, 52.0, 150.5, False, False)
    assert row.chips == (HeroChip("pauper", 101.0, 52.0, 150.5),)
    assert table.benchmark_ids == ("pauper",) and table.warnings == ()


def test_random_is_the_reference_row_at_zero_and_rows_rank_by_score() -> None:
    table = hero_table(
        [("pauper", _board(_row("first", 985_000, (950_000, 1_020_000)), _row("heuristic", 1_101_000, (1_050_000, 1_150_000))))]
    )
    assert [row.name for row in table.rows] == ["heuristic", "uniform", "first"]
    reference = _by_name(table)["uniform"]
    assert (reference.score, reference.lower, reference.upper, reference.reference) == (0.0, 0.0, 0.0, True)
    assert reference.chips == (HeroChip("pauper", 0.0, 0.0, 0.0),)


def test_two_benchmarks_average_and_combine_standard_errors() -> None:
    # Half-widths 39.2 and 58.8 Elo are standard errors of 20 and 30.
    table = hero_table(
        [
            ("a", _board(_row("heuristic", 1_100_000, (1_060_800, 1_139_200)))),
            ("b", _board(_row("heuristic", 1_200_000, (1_141_200, 1_258_800)))),
        ]
    )
    row = _by_name(table)["heuristic"]
    se = math.sqrt(20.0**2 + 30.0**2) / 2
    assert row.score == pytest.approx(150.0)
    assert row.lower == pytest.approx(150.0 - 1.96 * se)
    assert row.upper == pytest.approx(150.0 + 1.96 * se)
    assert row.approximate is True
    assert [chip.benchmark_id for chip in row.chips] == ["a", "b"]


def test_combined_interval_squares_half_widths_exactly() -> None:
    # h * h is exactly rounded on every OS; h ** 2 calls the C library pow(),
    # which on Windows is one ulp off for benchmark a's half-width here.
    table = hero_table(
        [
            ("a", _board(_row("heuristic", 1_100_000, (1_061_188, 1_138_812)))),
            ("b", _board(_row("heuristic", 1_200_000, (1_141_200, 1_258_800)))),
        ]
    )
    row = _by_name(table)["heuristic"]
    half_a = (138.812 - 61.188) / (2 * 1.96)
    half_b = (258.8 - 141.2) / (2 * 1.96)
    se = math.sqrt(half_a * half_a + half_b * half_b) / 2
    assert (row.lower, row.upper) == (150.0 - 1.96 * se, 150.0 + 1.96 * se)


def test_a_bot_in_one_of_two_benchmarks_keeps_that_interval() -> None:
    table = hero_table(
        [
            ("a", _board(_row("heuristic", 1_100_000, (1_060_800, 1_139_200)))),
            ("b", _board(_row("g115", 1_420_000, (1_380_000, 1_470_000)))),
        ]
    )
    row = _by_name(table)["g115"]
    assert (row.score, row.lower, row.upper, row.approximate) == (420.0, 380.0, 470.0, False)


def test_an_unanchored_benchmark_is_left_out_with_a_warning() -> None:
    table = hero_table(
        [
            ("a", _board(_row("heuristic", 1_100_000, (1_060_800, 1_139_200)))),
            ("x", _board(_row("uniform", 900_000, (850_000, 950_000)), anchor="heuristic")),
        ]
    )
    assert table.benchmark_ids == ("a",)
    assert len(table.warnings) == 1 and "x" in table.warnings[0] and "heuristic" in table.warnings[0]
    assert all(chip.benchmark_id == "a" for row in table.rows for chip in row.chips)


def test_a_benchmark_whose_fit_failed_is_left_out_with_a_warning() -> None:
    table = hero_table([("a", _board(status="fit_failed"))])
    assert table.rows == () and table.benchmark_ids == ()
    assert "fit_failed" in table.warnings[0]


def test_missing_intervals_propagate() -> None:
    single = _by_name(hero_table([("a", _board(_row("heuristic", 1_100_000, None)))]))["heuristic"]
    assert (single.lower, single.upper, single.approximate) == (None, None, False)
    double = _by_name(
        hero_table(
            [
                ("a", _board(_row("heuristic", 1_100_000, None))),
                ("b", _board(_row("heuristic", 1_200_000, (1_141_200, 1_258_800)))),
            ]
        )
    )["heuristic"]
    assert (double.lower, double.upper, double.approximate) == (None, None, True)


def test_unrated_rows_are_skipped_and_ties_break_by_name() -> None:
    table = hero_table(
        [
            (
                "a",
                _board(
                    _row("zeta", 1_050_000, (1_000_000, 1_100_000)),
                    _row("alpha", 1_050_000, (1_000_000, 1_100_000)),
                    _row("ghost", 0, None, rated=False),
                ),
            )
        ]
    )
    assert [row.name for row in table.rows] == ["alpha", "zeta", "uniform"]


@pytest.mark.parametrize(
    ("record", "rated", "bound"),
    [
        ((6, 0, 0), True, "lower"),
        ((0, 0, 6), True, "upper"),
        ((5, 0, 1), True, None),
        ((0, 4, 0), True, None),      # only draws: neither a win nor a loss
        ((6, 0, 0), False, None),     # no rating to bound
    ],
)
def test_a_rating_is_a_bound_when_the_bot_won_or_lost_every_game(
    record: tuple[int, int, int], rated: bool, bound: str | None
) -> None:
    assert rating_bound(_row("bot", 1_100_000, None, rated=rated, record=record)) == bound


@pytest.mark.parametrize("record", [(6, 2, 0), (6, 1, 0), (0, 1, 6), (0, 2, 6)])
def test_draws_make_a_rating_finite_so_it_is_not_a_bound(record: tuple[int, int, int]) -> None:
    # A draw gives each side half a point, so a bot that never lost but drew (or never won but drew)
    # has a finite best-fit rating that does not lean on the prior.
    assert rating_bound(_row("bot", 1_100_000, None, record=record)) is None
    table = hero_table([("pauper", _board(_row("drawer", 1_300_000, (1_250_000, 1_350_000), record=record)))])
    row = _by_name(table)["drawer"]
    assert row.bound is None and row.chips[0].bound is None


def test_a_bot_that_never_lost_is_a_lower_bound_and_one_that_never_won_an_upper_bound() -> None:
    table = hero_table(
        [
            (
                "pauper",
                _board(
                    _row("strong", 1_864_000, (1_817_000, 1_920_000), record=(64, 0, 0)),
                    _row("weak", 700_000, (690_000, 710_000), record=(0, 0, 64)),
                ),
            )
        ]
    )
    rows = _by_name(table)
    strong = rows["strong"]
    assert strong.bound == "lower" and strong.chips == (HeroChip("pauper", 864.0, 817.0, 920.0, "lower"),)
    assert (strong.score, strong.lower, strong.upper, strong.approximate) == (864.0, 817.0, 920.0, False)  # otherwise unchanged
    assert rows["weak"].bound == "upper" and rows["weak"].chips[0].bound == "upper"
    assert rows["uniform"].bound is None and rows["uniform"].chips[0].bound is None  # the reference is exact


@pytest.mark.parametrize(
    ("first", "second", "bound"),
    [
        ((64, 0, 0), (5, 0, 5), "lower"),   # the mean of a lower bound and an estimate is a lower bound
        ((64, 0, 0), (40, 0, 0), "lower"),
        ((0, 0, 64), (0, 0, 9), "upper"),
        ((5, 0, 5), (0, 0, 9), "upper"),
        ((64, 0, 0), (0, 0, 9), None),      # mixed bounds bound nothing
        ((5, 0, 5), (5, 0, 5), None),
    ],
)
def test_a_combined_row_is_a_bound_when_its_bounded_chips_agree(
    first: tuple[int, int, int], second: tuple[int, int, int], bound: str | None
) -> None:
    table = hero_table(
        [
            ("a", _board(_row("bot", 1_100_000, (1_060_800, 1_139_200), record=first))),
            ("b", _board(_row("bot", 1_200_000, (1_141_200, 1_258_800), record=second))),
        ]
    )
    row = _by_name(table)["bot"]
    assert row.bound == bound
    assert row.approximate is True and row.score == pytest.approx(150.0)
