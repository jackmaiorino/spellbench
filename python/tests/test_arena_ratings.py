"""Rating math against hand-derived values (the arena's statistics core)."""

from __future__ import annotations

import math
from fractions import Fraction

import pytest

from spellbench.arena import ratings


def _rating(fit: ratings.BtFit, bot_id: str) -> float:
    return fit.rating(bot_id)


def test_two_bot_fit_is_the_log_score_ratio() -> None:
    fit = ratings.fit_bt_ratings([ratings.PairRecord("alpha", "beta", 3, 1, 0)], "alpha")
    assert _rating(fit, "alpha") == 0.0
    assert _rating(fit, "beta") == pytest.approx(math.log(1 / 3), abs=1e-9)


def test_draws_count_half_a_win_for_each_side() -> None:
    # 1 win + 2 draws = 2.0 points for alpha, 0 wins + 2 draws = 1.0 for beta.
    fit = ratings.fit_bt_ratings([ratings.PairRecord("alpha", "beta", 1, 0, 2)], "alpha")
    assert _rating(fit, "beta") == pytest.approx(math.log(1 / 2), abs=1e-9)


def test_the_anchor_sits_at_zero_and_others_shift_with_it() -> None:
    fit = ratings.fit_bt_ratings([ratings.PairRecord("alpha", "beta", 3, 1, 0)], "beta")
    assert _rating(fit, "beta") == 0.0
    assert _rating(fit, "alpha") == pytest.approx(math.log(3), abs=1e-9)


def test_three_bot_fit_solves_the_likelihood_equations() -> None:
    # At the Bradley-Terry MLE every bot's expected score equals its observed
    # score: sum_j n_ij * s_i / (s_i + s_j) == score_i.
    records = [
        ratings.PairRecord("alpha", "beta", 3, 1, 0),
        ratings.PairRecord("beta", "gamma", 2, 1, 1),
        ratings.PairRecord("alpha", "gamma", 1, 2, 1),
    ]
    fit = ratings.fit_bt_ratings(records, "alpha")
    strength = {bot_id: math.exp(rating) for bot_id, rating in fit.ratings_log_units}
    observed = {"alpha": 3.0 + 1.5, "beta": 1.0 + 2.5, "gamma": 1.5 + 2.5}
    for bot_id, score in observed.items():
        expected = 0.0
        for record in records:
            if bot_id in (record.a_id, record.b_id):
                other = record.b_id if bot_id == record.a_id else record.a_id
                games = record.a_wins + record.b_wins + record.draws
                expected += games * strength[bot_id] / (strength[bot_id] + strength[other])
        assert expected == pytest.approx(score, abs=1e-8), bot_id


def test_a_disconnected_comparison_graph_fails_closed() -> None:
    records = [ratings.PairRecord("alpha", "beta", 1, 1, 0), ratings.PairRecord("gamma", "delta", 1, 1, 0)]
    with pytest.raises(ratings.BtRatingError, match="disconnected"):
        ratings.fit_bt_ratings(records, "alpha")


def test_an_unbeaten_record_has_no_finite_raw_fit() -> None:
    # Why the leaderboard adds a virtual draw per matchup before fitting.
    with pytest.raises(ratings.BtRatingError, match="degenerate"):
        ratings.fit_bt_ratings([ratings.PairRecord("alpha", "beta", 2, 0, 0)], "alpha")


@pytest.mark.parametrize(
    ("pair_totals", "wins", "losses", "ties", "p_value"),
    [
        ([4, 4, 4, 4, 4, 0], 5, 1, 0, Fraction(7, 32)),  # 2 * (C(6,0) + C(6,1)) / 2^6
        ([4] * 10, 10, 0, 0, Fraction(1, 512)),  # 2 / 2^10
        ([2, 2, 4], 1, 0, 2, Fraction(1)),  # ties excluded; |1 - 0| <= 1
    ],
)
def test_exact_sign_test(pair_totals, wins, losses, ties, p_value) -> None:
    result = ratings.exact_two_sided_sign_test(pair_totals)
    assert (result.wins, result.losses, result.ties) == (wins, losses, ties)
    assert Fraction(result.p_value_numerator, result.p_value_denominator) == p_value


def test_bootstrap_of_identical_pairs_collapses_to_the_value() -> None:
    summary = ratings.bootstrap_pair_half_points([3, 3, 3, 3], bootstrap_seed=99, bootstrap_replicates=1000)
    assert (summary.lower_sum, summary.upper_sum, summary.denominator) == (12, 12, 16)


def test_rating_bootstrap_refits_carry_the_virtual_draws() -> None:
    # Every resample of three 4-0 pairs is 12 half-points to 0; one virtual
    # draw per refit makes it 13 to 1, so beta sits at ln(1/13) exactly.
    matchups = [ratings.MatchupPairs("alpha", "beta", (4, 4, 4))]
    boot = ratings.paired_rating_bootstrap(
        matchups, "alpha", bootstrap_seed=5, bootstrap_replicates=1000, virtual_draws=1
    )
    assert boot.failed_replicates == 0
    intervals = {bot_id: (lower, upper) for bot_id, lower, upper in boot.intervals}
    assert intervals["beta"] == pytest.approx((math.log(1 / 13), math.log(1 / 13)), abs=1e-9)
    with pytest.raises(ratings.BtRatingError, match="degenerate"):
        ratings.paired_rating_bootstrap(matchups, "alpha", bootstrap_seed=5, bootstrap_replicates=1000)


def test_elo_display_scale() -> None:
    assert ratings.elo_display(0.0) == 1000.0
    assert ratings.elo_display(math.log(10)) == pytest.approx(1400.0)  # 400 * log10(10)
    assert ratings.elo_milli(math.log(9)) == 1_381_697  # 1000 + 400 * log10(9) = 1381.697...
    assert ratings.rating_e6(-math.log(9)) == -2_197_225
