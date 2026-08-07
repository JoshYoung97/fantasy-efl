"""Tests for recovering scoring rates from match-odds probabilities."""

from __future__ import annotations

import pytest

from fantasy_efl.goals import (
    GoalProfile,
    match_probabilities,
    poisson_pmf,
    profiles_from_probabilities,
    solve_rates,
)


def test_match_probabilities_form_a_distribution():
    probs = match_probabilities(1.5, 1.1)
    assert abs(sum(probs) - 1.0) < 1e-9


def test_equal_rates_give_a_symmetric_market():
    p_home, _, p_away = match_probabilities(1.3, 1.3)
    assert abs(p_home - p_away) < 1e-9


def test_higher_rate_means_more_likely_to_win():
    strong, _, weak = match_probabilities(2.2, 0.8)
    assert strong > weak


def test_more_goals_means_fewer_draws():
    _, low_draw, _ = match_probabilities(0.6, 0.6)
    _, high_draw, _ = match_probabilities(2.4, 2.4)
    assert low_draw > high_draw


@pytest.mark.parametrize(
    "rates",
    [(1.5, 1.1), (2.4, 0.7), (0.9, 0.9), (1.2, 1.8), (3.0, 0.5)],
)
def test_solve_rates_inverts_match_probabilities(rates):
    """Round-trip: rates -> probabilities -> rates."""
    probs = match_probabilities(*rates)
    recovered = solve_rates(*probs)
    assert recovered[0] == pytest.approx(rates[0], abs=1e-3)
    assert recovered[1] == pytest.approx(rates[1], abs=1e-3)


def test_solved_rates_reproduce_the_input_market():
    probs = (0.328, 0.272, 0.400)  # a real League Two market
    home_rate, away_rate = solve_rates(*probs)
    assert match_probabilities(home_rate, away_rate) == pytest.approx(probs, abs=1e-3)


def test_clean_sheet_falls_as_the_opponent_improves():
    tight = GoalProfile(scored_rate=1.2, conceded_rate=0.7)
    leaky = GoalProfile(scored_rate=1.2, conceded_rate=2.1)
    assert tight.p_clean_sheet > leaky.p_clean_sheet


def test_goal_thresholds_are_ordered():
    profile = GoalProfile(scored_rate=1.6, conceded_rate=1.1)
    assert profile.p_scores_2_plus > profile.p_scores_4_plus
    assert 0.0 < profile.p_scores_4_plus < profile.p_scores_2_plus < 1.0


def test_profiles_mirror_each_other():
    home, away = profiles_from_probabilities(0.45, 0.28, 0.27)
    assert home.scored_rate == pytest.approx(away.conceded_rate)
    assert home.conceded_rate == pytest.approx(away.scored_rate)


def test_favourite_has_the_better_clean_sheet_chance():
    home, away = profiles_from_probabilities(0.62, 0.22, 0.16)
    assert home.p_clean_sheet > away.p_clean_sheet


def test_poisson_pmf_handles_a_zero_rate():
    assert poisson_pmf(0, 0.0) == 1.0
    assert poisson_pmf(1, 0.0) == 0.0
