"""Tests for anytime-goalscorer price conversion and player-name matching."""

from __future__ import annotations

import math

import pytest

from fantasy_efl.expected import PlayerRates
from fantasy_efl.goalscorer_odds import (
    MIN_ODDS,
    MIN_PRICED_PER_CLUB,
    OWN_GOAL_ALLOWANCE,
    PlayerMatch,
    ScorerEntry,
    apply_seed,
    build_seeds,
    implied_goal_rate,
    match_players,
    reconcile_team,
    seed_rate,
)
from fantasy_efl.player_model import MINUTES_IF_LONG, MINUTES_IF_SHORT


def entry(player="L. Wing", club="Reading", odds=3.5, status="start",
          confirmed=True, bookmaker="bet365"):
    return ScorerEntry(
        player=player, club=club, anytime_odds=odds, bookmaker=bookmaker,
        lineup_status=status, confirmed=confirmed,
    )


def roster_player(player_id, name, club):
    return {"id": player_id, "displayName": name, "club": club}


def test_implied_goal_rate_inverts_the_poisson_scoring_probability():
    """P(scores) = 1 - e^-lambda, so this is the exact inverse, not an approximation."""
    lam = implied_goal_rate(2.0)  # 50% raw implied probability
    assert 1.0 - math.exp(-lam) == pytest.approx(0.5)


def test_implied_goal_rate_rejects_odds_below_the_floor():
    with pytest.raises(ValueError):
        implied_goal_rate(MIN_ODDS - 0.001)


def test_reconcile_team_matches_the_target_exactly():
    """The whole point: summed lambdas equal the modelled team total, not the raw market read."""
    raw = {1: 0.3, 2: 0.5, 3: 0.1}
    reconciled = reconcile_team(raw, team_expected_goals=2.0)
    assert sum(reconciled.values()) == pytest.approx(2.0 - OWN_GOAL_ALLOWANCE)


def test_reconcile_team_preserves_relative_shares():
    """Rescaling must not change who is more likely to score, only the scale."""
    raw = {1: 0.2, 2: 0.6}
    reconciled = reconcile_team(raw, team_expected_goals=1.5)
    assert reconciled[2] / reconciled[1] == pytest.approx(raw[2] / raw[1])


def test_reconcile_team_handles_an_all_zero_market():
    assert reconcile_team({1: 0.0}, team_expected_goals=1.5) == {1: 0.0}


def test_seed_rate_recovers_the_reconciled_figure_at_its_own_assumed_minutes():
    """The exact property the module exists for: no double-discount.

    If the page's minutes control is set to the same value this seed assumed,
    multiplying back by minutes/90 must return the original reconciled
    lambda unchanged.
    """
    reconciled_lambda = 0.42
    seeded = seed_rate(reconciled_lambda, "start")
    recovered = seeded * (MINUTES_IF_LONG / 90.0)
    assert recovered == pytest.approx(reconciled_lambda)


def test_seed_rate_uses_the_shorter_assumption_for_bench_status():
    same_lambda = 0.3
    assert seed_rate(same_lambda, "bench") > seed_rate(same_lambda, "start")
    # A bench seed, scaled back down by ITS OWN (shorter) assumed minutes,
    # still recovers the original figure.
    seeded = seed_rate(same_lambda, "bench")
    assert seeded * (MINUTES_IF_SHORT / 90.0) == pytest.approx(same_lambda)


def test_match_players_finds_the_initial_and_surname():
    roster = [roster_player(1, "L. Wing", "Reading"), roster_player(2, "J. Smith", "Reading")]
    [match] = match_players([entry(player="Lewis Wing")], roster)
    assert match.player_id == 1
    assert not match.ambiguous


def test_match_players_is_scoped_to_the_entrys_club():
    """A shared surname at a DIFFERENT club must never be a candidate at all."""
    roster = [
        roster_player(1, "L. Wing", "Reading"),
        roster_player(2, "A. Wing", "Millwall"),
    ]
    [match] = match_players([entry(player="Lewis Wing", club="Reading")], roster)
    assert match.player_id == 1


def test_match_players_flags_two_similar_surnames_at_the_same_club():
    """The failure this exists to prevent: guessing between two real candidates."""
    roster = [
        roster_player(1, "J. Evans", "Millwall"),
        roster_player(2, "C. Evans", "Millwall"),
    ]
    [match] = match_players([entry(player="Evans", club="Millwall")], roster)
    assert match.ambiguous


def test_match_players_reports_no_match_rather_than_a_bad_guess():
    roster = [roster_player(1, "L. Wing", "Reading")]
    [match] = match_players([entry(player="Someone Else", club="Reading")], roster)
    assert match.player_id is None


def full_club_matches(club, id_base=0, target_size=MIN_PRICED_PER_CLUB, odds=2.0):
    """Enough distinct, confirmed, unambiguous matches to clear the sparse-club floor."""
    return [
        PlayerMatch(entry(player=f"Player{i}", club=club, odds=odds), player_id=id_base + i,
                    score=1.0, ambiguous=False)
        for i in range(target_size)
    ]


def test_build_seeds_drops_unconfirmed_lineups():
    """The blended-price problem: a predicted lineup must not seed the model."""
    matches = [PlayerMatch(entry(confirmed=False), player_id=1, score=1.0, ambiguous=False)]
    assert build_seeds(matches, {"Reading": 1.5}).seeds == {}


def test_build_seeds_drops_ambiguous_matches():
    matches = [PlayerMatch(entry(), player_id=1, score=0.8, ambiguous=True)]
    assert build_seeds(matches, {"Reading": 1.5}).seeds == {}


def test_build_seeds_drops_clubs_with_no_target_supplied():
    matches = [PlayerMatch(entry(club="Nowhere Town"), player_id=1, score=1.0, ambiguous=False)]
    assert build_seeds(matches, {"Reading": 1.5}).seeds == {}


def test_build_seeds_reconciles_within_each_club_independently():
    matches = full_club_matches("Reading", id_base=0) + full_club_matches("Millwall", id_base=100)
    seeds = build_seeds(matches, {"Reading": 1.5, "Millwall": 2.5}).seeds
    # Different team targets must not leak into each other's reconciliation.
    assert seeds[0] != seeds[100]


def test_build_seeds_flags_a_club_priced_below_the_floor():
    """The trap this exists to catch: a lone priced player silently absorbing

    a whole team's worth of expected goals. Found this by hand -- a single
    test entry for Reading put one midfielder at 16.9 points for one match.
    """
    matches = [PlayerMatch(entry(club="Reading"), player_id=1, score=1.0, ambiguous=False)]
    result = build_seeds(matches, {"Reading": 1.5})
    assert result.sparse_clubs == {"Reading": 1}
    assert 1 in result.seeds  # still produced -- sparse is a warning, not a rejection


def test_build_seeds_does_not_flag_a_club_priced_at_the_floor():
    matches = full_club_matches("Reading")
    result = build_seeds(matches, {"Reading": 1.5})
    assert result.sparse_clubs == {}


def test_a_sparsely_priced_lone_scorer_absorbs_the_whole_team_total():
    """Documents the exact failure mode, not just that it gets flagged.

    Not a bug in the arithmetic -- reconcile_team has nowhere else to put
    the rest of the team's goals -- but the number it produces from one
    entry is not one a real fixture should trust.
    """
    matches = [PlayerMatch(entry(club="Reading", odds=2.75), player_id=1, score=1.0, ambiguous=False)]
    seeds = build_seeds(matches, {"Reading": 1.3}).seeds
    reconciled_lambda = seeds[1] * (MINUTES_IF_LONG / 90.0)
    assert reconciled_lambda == pytest.approx(1.3 - OWN_GOAL_ALLOWANCE)


def test_apply_seed_only_changes_goals():
    rates = PlayerRates(position="FWD", minutes=None, assists=0.1, key_passes=0.4)
    seeded = apply_seed(rates, 0.55)
    assert seeded.goals == 0.55
    assert seeded.assists == rates.assists
    assert seeded.key_passes == rates.key_passes
    assert rates.goals == 0.0  # the original is untouched -- PlayerRates is frozen
