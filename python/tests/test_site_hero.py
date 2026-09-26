"""The Hero table: Elo above the random bot, averaged across benchmarks."""

from __future__ import annotations

import math
from typing import Any

import pytest

from spellbench.site.hero import HeroChip, hero_table


def _row(name: str, elo: int, ci: tuple[int, int] | None, rated: bool = True) -> dict[str, Any]:
    return {"name": name, "rated": rated, "elo_milli": elo if rated else None, "ci95_elo_milli": None if ci is None else list(ci)}


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
