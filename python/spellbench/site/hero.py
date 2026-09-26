"""The Hero table: each bot's Elo above the random bot, across benchmarks.

For bot ``i`` in benchmark ``b``, ``margin(i, b)`` is its Elo display minus
1000 (the anchor, the builtin ``uniform`` bot, is fixed at 1000), with the
interval from ``b``'s leaderboard. The Hero score is the mean margin over
the benchmarks ``i`` entered. One benchmark keeps its own interval; several
combine per-benchmark standard errors (half-width / 1.96) as
``sqrt(sum(se^2)) / n``, an approximation the site labels as such.
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


@dataclass(frozen=True)
class HeroRow:
    name: str
    score: float
    lower: float | None
    upper: float | None
    approximate: bool        # combined from several benchmarks
    reference: bool          # the anchor's row, fixed at 0
    chips: tuple[HeroChip, ...]


@dataclass(frozen=True)
class HeroTable:
    rows: tuple[HeroRow, ...]
    benchmark_ids: tuple[str, ...]   # benchmarks in the chart, input order
    warnings: tuple[str, ...]


def _elo_above_anchor(elo_milli: int) -> float:
    return (elo_milli - _ANCHOR_ELO_MILLI) / 1000


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
    if count == 1:
        return HeroRow(name, score, chips[0].lower, chips[0].upper, False, False, chips)
    if any(chip.lower is None or chip.upper is None for chip in chips):
        return HeroRow(name, score, None, None, True, False, chips)
    se = math.sqrt(math.fsum(((chip.upper - chip.lower) / (2 * Z95)) ** 2 for chip in chips)) / count
    return HeroRow(name, score, score - Z95 * se, score + Z95 * se, True, False, chips)
