"""The Hero table: each bot's Elo above the random bot, across benchmarks.

For bot ``i`` in benchmark ``b``, ``margin(i, b)`` is its Elo display minus
1000 (the anchor, the builtin ``uniform`` bot, is fixed at 1000), with the
interval from ``b``'s leaderboard. The Hero score is the mean margin over
the benchmarks ``i`` entered. One benchmark keeps its own interval; several
combine per-benchmark standard errors (half-width / 1.96) as
``sqrt(sum(se^2)) / n``, an approximation the site labels as such.

A bot that never lost (or never won) a rated game has no finite best-fit
rating: the one virtual draw per matchup keeps it finite, and it grows with
the number of games. ``rating_bound`` marks such a rating as a lower (or
upper) bound. A Hero score is a bound when the benchmarks that bound it all
bound it the same way; mixed bounds bound nothing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

ANCHOR_NAME = "uniform"
Z95 = 1.96
_ANCHOR_ELO_MILLI = 1_000_000


@dataclass(frozen=True)
class HeroChip:
    benchmark_id: str
    margin: float            # Elo above the anchor in that benchmark
    lower: float | None      # interval bounds in the same units; None without an interval
    upper: float | None
    bound: str | None = None  # "lower" or "upper" when that benchmark's rating is only a bound


@dataclass(frozen=True)
class HeroRow:
    name: str
    score: float
    lower: float | None
    upper: float | None
    approximate: bool        # combined from several benchmarks
    reference: bool          # the anchor's row, fixed at 0
    chips: tuple[HeroChip, ...]
    bound: str | None = None  # "lower" or "upper" when the score is only a bound


@dataclass(frozen=True)
class HeroTable:
    rows: tuple[HeroRow, ...]
    benchmark_ids: tuple[str, ...]   # benchmarks in the chart, input order
    warnings: tuple[str, ...]


def _elo_above_anchor(elo_milli: int) -> float:
    return (elo_milli - _ANCHOR_ELO_MILLI) / 1000


def rating_bound(row: Mapping[str, Any]) -> str | None:
    """Whether a leaderboard row's rating is only a bound: ``"lower"``, ``"upper"``, or None.

    A rated row with no losses and at least one win is a lower bound; one with
    no wins and at least one loss is an upper bound. Callers leave out the
    anchor, whose rating is fixed.
    """
    if not row["rated"]:
        return None
    if row["losses"] == 0 and row["wins"] > 0:
        return "lower"
    if row["wins"] == 0 and row["losses"] > 0:
        return "upper"
    return None


def hero_table(
    leaderboards: Sequence[tuple[str, Mapping[str, Any]]], *, anchor_name: str = ANCHOR_NAME
) -> HeroTable:
    """Rank bots by mean Elo above ``anchor_name`` over the benchmarks they entered."""
    chips: dict[str, list[HeroChip]] = {}
    included: list[str] = []
    warnings: list[str] = []
    for benchmark_id, document in leaderboards:
        anchor = document["anchor"]["name"]
        if anchor != anchor_name:
            warnings.append(
                f"{benchmark_id}: anchored on {anchor!r}, not {anchor_name!r}; left out of the Hero chart"
            )
            continue
        if document["status"] != "ok":
            warnings.append(
                f"{benchmark_id}: leaderboard status {document['status']!r}; left out of the Hero chart"
            )
            continue
        included.append(benchmark_id)
        for row in document["rows"]:
            if not row["rated"] or row["name"] == anchor_name:
                continue
            interval = row["ci95_elo_milli"]
            chips.setdefault(row["name"], []).append(
                HeroChip(
                    benchmark_id=benchmark_id,
                    margin=_elo_above_anchor(row["elo_milli"]),
                    lower=None if interval is None else _elo_above_anchor(interval[0]),
                    upper=None if interval is None else _elo_above_anchor(interval[1]),
                    bound=rating_bound(row),
                )
            )
    rows = [_combine(name, tuple(bot_chips)) for name, bot_chips in chips.items()]
    if included:
        rows.append(
            HeroRow(
                name=anchor_name, score=0.0, lower=0.0, upper=0.0, approximate=False, reference=True,
                chips=tuple(HeroChip(benchmark_id, 0.0, 0.0, 0.0) for benchmark_id in included),
            )
        )
    rows.sort(key=lambda row: (-row.score, row.name))
    return HeroTable(rows=tuple(rows), benchmark_ids=tuple(included), warnings=tuple(warnings))


def _combine(name: str, chips: tuple[HeroChip, ...]) -> HeroRow:
    count = len(chips)
    score = math.fsum(chip.margin for chip in chips) / count
    # The mean of lower bounds and estimates is a lower bound (likewise upper); mixed bounds bound nothing.
    bounds = {chip.bound for chip in chips} - {None}
    bound = bounds.pop() if len(bounds) == 1 else None
    if count == 1:
        return HeroRow(
            name=name, score=score, lower=chips[0].lower, upper=chips[0].upper,
            approximate=False, reference=False, chips=chips, bound=bound,
        )
    halves: list[float] = []
    for chip in chips:
        if chip.lower is None or chip.upper is None:
            return HeroRow(
                name=name, score=score, lower=None, upper=None, approximate=True, reference=False, chips=chips,
                bound=bound,
            )
        halves.append((chip.upper - chip.lower) / (2 * Z95))
    # Square by multiplication: h * h is exactly rounded on every OS, while h ** 2
    # calls the C library pow(), which is not (it differs on Windows).
    se = math.sqrt(math.fsum(half * half for half in halves)) / count
    return HeroRow(
        name=name, score=score, lower=score - Z95 * se, upper=score + Z95 * se,
        approximate=True, reference=False, chips=chips, bound=bound,
    )
