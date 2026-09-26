"""Tournament ratings: anchored Bradley-Terry MM fit, paired bootstrap, sign test.

The Bradley-Terry MM iteration is ported from mtg-kernel
``scripts/experiments/population_v2_cycle4_v1/bt_rating_v1.py``
(``fit_bt_ratings``), with Jack's attribution: draws count half (the standard
Davidson-free reduction), one declared anchor identity is fixed at 0.0 log
units, and the fit fails closed on schema violations, a disconnected
comparison graph, degenerate records, or non-convergence.

The paired bootstrap (percentile 95% CI over resampled pair totals) and the
exact two-sided sign test are ported from mtg-kernel
``python/mtg_kernel_rl/evaluation_stats.py`` (``bootstrap_pair_half_points``,
``exact_two_sided_sign_test`` and their private helpers, including the
private ``_SplitMix64``), with Jack's attribution.

Elo-scale display conversion: ``rating * 400 / ln(10) + 1000``; the anchor
displays at exactly 1000.0. Artifacts store fixed-point integers: log-unit
ratings times 1e6 (``*_e6``) and Elo displays times 1e3 (``*_milli``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Callable, Iterable, Mapping, Sequence, Set

# ---------------------------------------------------------------------------
# Anchored Bradley-Terry MM fit (ported from bt_rating_v1.py)
# ---------------------------------------------------------------------------

# Convergence is judged in LOG space (max |log(updated) - log(old)|), exactly
# as in the mtg-kernel source; see the attribution note above.
MAX_ITERATIONS = 200_000
LOG_CONVERGENCE_EPSILON = 1e-10

ELO_DISPLAY_BASE = 1000.0
ELO_DISPLAY_SCALE = 400.0 / math.log(10.0)


class BtRatingError(ValueError):
    pass


@dataclass(frozen=True)
class PairRecord:
    """Aggregated terminal W/D/L for one ordered pair of distinct identities."""

    a_id: str
    b_id: str
    a_wins: int
    b_wins: int
    draws: int

    def __post_init__(self) -> None:
        if type(self.a_id) is not str or not self.a_id or type(self.b_id) is not str or not self.b_id:
            raise BtRatingError("invalid pair ids")
        if self.a_id == self.b_id:
            raise BtRatingError("pair ids must differ (mirror matchups cannot be rated)")
        for count in (self.a_wins, self.b_wins, self.draws):
            if type(count) is not int or count < 0:
                raise BtRatingError("invalid pair counts")
        if self.a_wins + self.b_wins + self.draws == 0:
            raise BtRatingError(f"empty pair {self.a_id} vs {self.b_id}")


@dataclass(frozen=True)
class _ScorePair:
    a_id: str
    b_id: str
    a_score: float
    b_score: float


@dataclass(frozen=True)
class BtFit:
    reference_id: str
    iterations: int
    ratings_log_units: tuple[tuple[str, float], ...]  # sorted by id
    strengths: tuple[tuple[str, float], ...]  # sorted by id

    def rating(self, bot_id: str) -> float:
        return dict(self.ratings_log_units)[bot_id]


def _connected(ids: list[str], pairs: Sequence[_ScorePair]) -> bool:
    adjacency: dict[str, set[str]] = {model_id: set() for model_id in ids}
    for pair in pairs:
        adjacency[pair.a_id].add(pair.b_id)
        adjacency[pair.b_id].add(pair.a_id)
    seen = {ids[0]}
    frontier = [ids[0]]
    while frontier:
        for neighbor in adjacency[frontier.pop()]:
            if neighbor not in seen:
                seen.add(neighbor)
                frontier.append(neighbor)
    return len(seen) == len(ids)


def _fit_score_pairs(pairs: Sequence[_ScorePair], reference_id: str) -> BtFit:
    """The MM iteration proper; shared by the public fit and bootstrap refits."""
    if not pairs:
        raise BtRatingError("missing pairs")
    if type(reference_id) is not str or not reference_id:
        raise BtRatingError("missing reference_id")
    ids = sorted({pair.a_id for pair in pairs} | {pair.b_id for pair in pairs})
    if reference_id not in ids:
        raise BtRatingError("reference_id has no games")
    if not _connected(ids, pairs):
        raise BtRatingError("comparison graph is disconnected")
    score: dict[str, float] = {model_id: 0.0 for model_id in ids}
    counter: dict[str, float] = {model_id: 0.0 for model_id in ids}
    for pair in pairs:
        score[pair.a_id] += pair.a_score
        counter[pair.a_id] += pair.b_score
        score[pair.b_id] += pair.b_score
        counter[pair.b_id] += pair.a_score
    for model_id in ids:
        if score[model_id] == 0.0 or counter[model_id] == 0.0:
            raise BtRatingError(f"degenerate record for {model_id}")

    strengths = {model_id: 1.0 for model_id in ids}
    iterations = 0
    for iteration in range(1, MAX_ITERATIONS + 1):
        iterations = iteration
        updated: dict[str, float] = {}
        for model_id in ids:
            denominator = 0.0
            for pair in pairs:
                if model_id == pair.a_id:
                    other = pair.b_id
                elif model_id == pair.b_id:
                    other = pair.a_id
                else:
                    continue
                games = pair.a_score + pair.b_score
                denominator += games / (strengths[model_id] + strengths[other])
            updated[model_id] = score[model_id] / denominator
        normalizer = updated[reference_id]
        updated = {model_id: value / normalizer for model_id, value in updated.items()}
        delta = max(abs(math.log(updated[model_id]) - math.log(strengths[model_id])) for model_id in ids)
        strengths = updated
        if delta < LOG_CONVERGENCE_EPSILON:
            break
    else:
        raise BtRatingError("MM iteration did not converge")

    ratings = {model_id: math.log(strengths[model_id]) for model_id in ids}
    return BtFit(
        reference_id=reference_id,
        iterations=iterations,
        ratings_log_units=tuple((model_id, ratings[model_id]) for model_id in sorted(ratings)),
        strengths=tuple((model_id, strengths[model_id]) for model_id in sorted(strengths)),
    )


def fit_bt_ratings(pairs: Sequence[PairRecord], reference_id: str) -> BtFit:
    """Fit anchored Bradley-Terry ratings; draws count half a win per side.

    Fails closed on: invalid records, a reference id absent from the pairs, a
    disconnected comparison graph, any model with zero total score or zero
    total counter-score (its rating would diverge to +/- infinity), or
    non-convergence within MAX_ITERATIONS.
    """
    score_pairs = [
        _ScorePair(
            a_id=pair.a_id,
            b_id=pair.b_id,
            a_score=pair.a_wins + pair.draws / 2.0,
            b_score=pair.b_wins + pair.draws / 2.0,
        )
        for pair in pairs
    ]
    return _fit_score_pairs(score_pairs, reference_id)


def elo_display(rating_log_units: float) -> float:
    """Elo-scale display: the anchor (0.0 log units) shows exactly 1000."""
    return rating_log_units * ELO_DISPLAY_SCALE + ELO_DISPLAY_BASE


def rating_e6(rating_log_units: float) -> int:
    """Fixed-point log-unit rating for canonical artifacts (round-half-even)."""
    return int(round(rating_log_units * 1_000_000))


def elo_milli(rating_log_units: float) -> int:
    """Fixed-point Elo display for canonical artifacts (round-half-even)."""
    return int(round(elo_display(rating_log_units) * 1000))


# ---------------------------------------------------------------------------
# Paired bootstrap and exact sign test (ported from evaluation_stats.py)
# ---------------------------------------------------------------------------

_MASK64 = 0xFFFF_FFFF_FFFF_FFFF
_UINT64_CARDINALITY = 1 << 64
_GOLDEN_RATIO_64 = 0x9E37_79B9_7F4A_7C15
_MAX_PAIR_COUNT = 50_000
_MIN_BOOTSTRAP_REPLICATES = 1_000
_MAX_BOOTSTRAP_REPLICATES = 100_000
_MAX_BOOTSTRAP_DRAWS = 50_000_000


class _SplitMix64:
    """Ported from mtg-kernel evaluation_stats.py (private _SplitMix64)."""

    def __init__(self, seed: int) -> None:
        self._state = _validate_uint64(seed, "seed")

    def next_u64(self) -> int:
        self._state = (self._state + _GOLDEN_RATIO_64) & _MASK64
        value = self._state
        value = ((value ^ (value >> 30)) * 0xBF58_476D_1CE4_E5B9) & _MASK64
        value = ((value ^ (value >> 27)) * 0x94D0_49BB_1331_11EB) & _MASK64
        return (value ^ (value >> 31)) & _MASK64


def _validate_uint64(value: Any, name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer and not bool")
    if value < 0 or value > _MASK64:
        raise ValueError(f"{name} must be in [0, 2**64 - 1]")
    return value


def _validate_pair_half_points(pair_half_points: Iterable[int]) -> tuple[int, ...]:
    """Materialize one ordered observation stream exactly once."""
    if isinstance(pair_half_points, (Set, Mapping)):
        raise TypeError("pair_half_points must be ordered; sets and mappings are not supported")
    values: list[int] = []
    for index, value in enumerate(iter(pair_half_points)):
        if index >= _MAX_PAIR_COUNT:
            raise ValueError(f"pair_half_points must contain at most {_MAX_PAIR_COUNT} pairs")
        if type(value) is not int:
            raise TypeError(f"pair_half_points[{index}] must be an integer and not bool")
        if value < 0 or value > 4:
            raise ValueError(f"pair_half_points[{index}] must be in [0, 4]")
        values.append(value)
    if not values:
        raise ValueError("pair_half_points must contain at least one pair")
    return tuple(values)


def _validate_bootstrap_replicates(bootstrap_replicates: Any, pair_count: int) -> int:
    if type(bootstrap_replicates) is not int:
        raise TypeError("bootstrap_replicates must be an integer and not bool")
    if bootstrap_replicates < _MIN_BOOTSTRAP_REPLICATES or bootstrap_replicates > _MAX_BOOTSTRAP_REPLICATES:
        raise ValueError(
            f"bootstrap_replicates must be in [{_MIN_BOOTSTRAP_REPLICATES}, {_MAX_BOOTSTRAP_REPLICATES}]"
        )
    if pair_count * bootstrap_replicates > _MAX_BOOTSTRAP_DRAWS:
        raise ValueError(f"pair_count * bootstrap_replicates must be at most {_MAX_BOOTSTRAP_DRAWS}")
    return bootstrap_replicates


def _unbiased_index(population_size: int, next_u64: Callable[[], int]) -> int:
    """Draw an unbiased index, rejecting the incomplete upper modulo bucket."""
    if type(population_size) is not int or population_size <= 0 or population_size > _MAX_PAIR_COUNT:
        raise ValueError("population_size out of range")
    limit = (_UINT64_CARDINALITY // population_size) * population_size
    while True:
        value = next_u64()
        if type(value) is not int or value < 0 or value > _MASK64:
            raise ValueError("next_u64 must return an integer in [0, 2**64 - 1]")
        if value < limit:
            return value % population_size


def splitmix64_next(seed: int) -> int:
    """One SplitMix64 draw from a raw seed; used for deterministic subseed derivation."""
    return _SplitMix64(seed).next_u64()


@dataclass(frozen=True)
class BootstrapSummary:
    """Observed paired score and its deterministic percentile bootstrap."""

    pair_count: int
    total_half_points: int
    bootstrap_seed: int
    bootstrap_replicates: int
    lower_sum: int
    upper_sum: int

    @property
    def denominator(self) -> int:
        return 4 * self.pair_count

    @property
    def estimate(self) -> float:
        return self.total_half_points / self.denominator

    @property
    def lower(self) -> float:
        return self.lower_sum / self.denominator

    @property
    def upper(self) -> float:
        return self.upper_sum / self.denominator


def bootstrap_pair_half_points(
    pair_half_points: Iterable[int],
    bootstrap_seed: int,
    bootstrap_replicates: int,
) -> BootstrapSummary:
    """Bootstrap complete pair totals and return a fixed 95% interval.

    Ported from mtg-kernel evaluation_stats.py (``bootstrap_pair_half_points``
    and helpers). The resample order of the input is part of the determinism
    contract; sets and mappings are rejected. Percentile indexes follow the
    source: ``(R-1)//40`` and ``(39*(R-1)+39)//40`` over the sorted replicate
    sums.
    """
    values = _validate_pair_half_points(pair_half_points)
    pair_count = len(values)
    bootstrap_seed = _validate_uint64(bootstrap_seed, "bootstrap_seed")
    bootstrap_replicates = _validate_bootstrap_replicates(bootstrap_replicates, pair_count)
    rng = _SplitMix64(bootstrap_seed)
    replicate_sums: list[int] = []
    for _ in range(bootstrap_replicates):
        replicate_sum = 0
        for _ in range(pair_count):
            replicate_sum += values[_unbiased_index(pair_count, rng.next_u64)]
        replicate_sums.append(replicate_sum)
    ordered_sums = sorted(replicate_sums)
    lower_index = (bootstrap_replicates - 1) // 40
    upper_index = (39 * (bootstrap_replicates - 1) + 39) // 40
    return BootstrapSummary(
        pair_count=pair_count,
        total_half_points=sum(values),
        bootstrap_seed=bootstrap_seed,
        bootstrap_replicates=bootstrap_replicates,
        lower_sum=ordered_sums[lower_index],
        upper_sum=ordered_sums[upper_index],
    )


def _sum_binomial_range(trials: int, start: int, end: int) -> int:
    if start > end:
        return 0
    term = math.comb(trials, start)
    total = term
    for successes in range(start + 1, end + 1):
        term = term * (trials - successes + 1) // successes
        total += term
    return total


@dataclass(frozen=True)
class SignTestResult:
    """Exact two-sided sign test over better, worse, and tied pairs.

    ``p_value_numerator / p_value_denominator`` is authoritative.
    """

    wins: int
    losses: int
    ties: int
    non_ties: int
    p_value_numerator: int
    p_value_denominator: int

    @property
    def p_value(self) -> float:
        return self.p_value_numerator / self.p_value_denominator


def exact_two_sided_sign_test(pair_half_points: Iterable[int]) -> SignTestResult:
    """Test pair totals around two half-points, excluding exact pair ties.

    Ported from mtg-kernel evaluation_stats.py (``exact_two_sided_sign_test``
    and helpers).
    """
    values = _validate_pair_half_points(pair_half_points)
    wins = sum(value > 2 for value in values)
    losses = sum(value < 2 for value in values)
    ties = len(values) - wins - losses
    non_ties = wins + losses
    if non_ties == 0 or abs(wins - losses) <= 1:
        exact_p_value = Fraction(1, 1)
    else:
        smaller_count = min(wins, losses)
        denominator = 1 << non_ties
        central_start = smaller_count + 1
        central_end = non_ties - smaller_count - 1
        lower_tail_terms = smaller_count + 1
        central_terms = central_end - central_start + 1
        if lower_tail_terms <= central_terms:
            numerator = 2 * _sum_binomial_range(non_ties, 0, smaller_count)
        else:
            numerator = denominator - _sum_binomial_range(non_ties, central_start, central_end)
        exact_p_value = Fraction(numerator, denominator)
    return SignTestResult(
        wins=wins,
        losses=losses,
        ties=ties,
        non_ties=non_ties,
        p_value_numerator=exact_p_value.numerator,
        p_value_denominator=exact_p_value.denominator,
    )


# ---------------------------------------------------------------------------
# Tournament-level paired rating bootstrap
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MatchupPairs:
    """Per-pair half-point totals (0..4) for one non-mirror matchup.

    ``pair_totals[i]`` is ``a_id``'s half-point sum over the two seat-swapped
    games of pair ``i``; only pairs whose two games both terminated naturally
    enter (the CRN unit is the pair).
    """

    a_id: str
    b_id: str
    pair_totals: tuple[int, ...]

    def __post_init__(self) -> None:
        if self.a_id == self.b_id:
            raise BtRatingError("MatchupPairs must join distinct identities")
        _validate_pair_half_points(self.pair_totals)


@dataclass(frozen=True)
class RatingBootstrap:
    """Per-bot paired-bootstrap 95% CI over refitted anchored BT ratings."""

    replicates: int
    failed_replicates: int
    intervals: tuple[tuple[str, float, float], ...]  # (bot_id, lower, upper), sorted


def paired_rating_bootstrap(
    matchups: Sequence[MatchupPairs],
    reference_id: str,
    *,
    bootstrap_seed: int,
    bootstrap_replicates: int,
) -> RatingBootstrap:
    """Resample pair units per matchup, refit BT, and take percentile CIs.

    The resampling unit is the seat-swapped pair, preserving the CRN design.
    Draw order is fixed (matchup order, then pair slot), so an identical
    ledger and seed reproduce identical intervals. Replicate fits that fail
    closed (a degenerate or disconnected resample) are skipped and counted;
    if more than half fail, the whole bootstrap fails closed.
    """
    _validate_uint64(bootstrap_seed, "bootstrap_seed")
    total_pairs = sum(len(matchup.pair_totals) for matchup in matchups)
    _validate_bootstrap_replicates(bootstrap_replicates, max(total_pairs, 1))
    rng = _SplitMix64(bootstrap_seed)
    samples: dict[str, list[float]] = {}
    failed = 0
    for _ in range(bootstrap_replicates):
        score_pairs: list[_ScorePair] = []
        for matchup in matchups:
            totals = matchup.pair_totals
            a_score = 0.0
            for _ in range(len(totals)):
                a_score += totals[_unbiased_index(len(totals), rng.next_u64)]
            score_pairs.append(
                _ScorePair(
                    a_id=matchup.a_id,
                    b_id=matchup.b_id,
                    a_score=a_score,
                    b_score=4.0 * len(totals) - a_score,
                )
            )
        try:
            fit = _fit_score_pairs(score_pairs, reference_id)
        except BtRatingError:
            failed += 1
            continue
        for model_id, rating in fit.ratings_log_units:
            samples.setdefault(model_id, []).append(rating)
    if failed * 2 > bootstrap_replicates:
        raise BtRatingError(
            f"paired rating bootstrap degenerate: {failed}/{bootstrap_replicates} replicate fits failed"
        )
    successful = bootstrap_replicates - failed
    lower_index = (successful - 1) // 40
    upper_index = (39 * (successful - 1) + 39) // 40
    intervals = []
    for model_id in sorted(samples):
        ordered = sorted(samples[model_id])
        if len(ordered) != successful:
            raise BtRatingError(f"bootstrap produced no fit covering {model_id!r}")
        intervals.append((model_id, ordered[lower_index], ordered[upper_index]))
    return RatingBootstrap(
        replicates=bootstrap_replicates,
        failed_replicates=failed,
        intervals=tuple(intervals),
    )
