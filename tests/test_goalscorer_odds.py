"""Tests for player-prop price conversion (goals, assists, shots on target)
and player-name matching."""

from __future__ import annotations

import math

import pytest

from fantasy_efl.expected import PlayerRates
from fantasy_efl.goalscorer_odds import (
    ASSIST_SHARE_OF_GOALS,
    MIN_ODDS,
    MIN_PRICED_PER_CLUB,
    OWN_GOAL_ALLOWANCE,
    PlayerMatch,
    ScorerEntry,
    apply_seed,
    build_assist_seeds,
    build_goal_seeds,
    build_shots_on_target_seeds,
    implied_rate,
    match_players,
    reconcile_team,
    seed_rate,
)
from fantasy_efl.player_model import MINUTES_IF_LONG, MINUTES_IF_SHORT


def entry(player="L. Wing", club="Reading", goal_odds=3.5, assist_odds=None,
          sot_odds=None, status="start", confirmed=True, bookmaker="bet365"):
    return ScorerEntry(
        player=player, club=club, bookmaker=bookmaker,
        lineup_status=status, confirmed=confirmed,
        goal_odds=goal_odds, assist_odds=assist_odds, sot_odds=sot_odds,
    )


def roster_player(player_id, name, club):
    return {"id": player_id, "displayName": name, "club": club}


def test_implied_rate_inverts_the_poisson_probability():
    """P(at least one) = 1 - e^-lambda, so this is the exact inverse, not an approximation."""
    lam = implied_rate(2.0)  # 50% raw implied probability
    assert 1.0 - math.exp(-lam) == pytest.approx(0.5)


def test_implied_rate_rejects_odds_below_the_floor():
    with pytest.raises(ValueError):
        implied_rate(MIN_ODDS - 0.001)


def test_reconcile_team_matches_the_target_exactly():
    """The whole point: summed lambdas equal the given total, not the raw market read."""
    raw = {1: 0.3, 2: 0.5, 3: 0.1}
    reconciled = reconcile_team(raw, target_total=2.0)
    assert sum(reconciled.values()) == pytest.approx(2.0)


def test_reconcile_team_preserves_relative_shares():
    """Rescaling must not change who is more likely to score, only the scale."""
    raw = {1: 0.2, 2: 0.6}
    reconciled = reconcile_team(raw, target_total=1.5)
    assert reconciled[2] / reconciled[1] == pytest.approx(raw[2] / raw[1])


def test_reconcile_team_handles_an_all_zero_market():
    assert reconcile_team({1: 0.0}, target_total=1.5) == {1: 0.0}


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


def full_club_matches(club, id_base=0, target_size=MIN_PRICED_PER_CLUB,
                       goal_odds=2.0, assist_odds=None, sot_odds=None):
    """Enough distinct, confirmed, unambiguous matches to clear the sparse-club floor."""
    return [
        PlayerMatch(
            entry(player=f"Player{i}", club=club, goal_odds=goal_odds,
                  assist_odds=assist_odds, sot_odds=sot_odds),
            player_id=id_base + i, score=1.0, ambiguous=False,
        )
        for i in range(target_size)
    ]


# ---- build_goal_seeds ------------------------------------------------

def test_build_goal_seeds_drops_unconfirmed_lineups():
    """The blended-price problem: a predicted lineup must not seed the model."""
    matches = [PlayerMatch(entry(confirmed=False), player_id=1, score=1.0, ambiguous=False)]
    assert build_goal_seeds(matches, {"Reading": 1.5}).seeds == {}


def test_build_goal_seeds_drops_ambiguous_matches():
    matches = [PlayerMatch(entry(), player_id=1, score=0.8, ambiguous=True)]
    assert build_goal_seeds(matches, {"Reading": 1.5}).seeds == {}


def test_build_goal_seeds_drops_clubs_with_no_target_supplied():
    matches = [PlayerMatch(entry(club="Nowhere Town"), player_id=1, score=1.0, ambiguous=False)]
    assert build_goal_seeds(matches, {"Reading": 1.5}).seeds == {}


def test_build_goal_seeds_drops_entries_with_no_goal_odds_priced():
    """Player Assists-only entries must not accidentally seed goals."""
    matches = [PlayerMatch(entry(goal_odds=None, assist_odds=5.0), player_id=1, score=1.0, ambiguous=False)]
    assert build_goal_seeds(matches, {"Reading": 1.5}).seeds == {}


def test_build_goal_seeds_reconciles_within_each_club_independently():
    matches = full_club_matches("Reading", id_base=0) + full_club_matches("Millwall", id_base=100)
    seeds = build_goal_seeds(matches, {"Reading": 1.5, "Millwall": 2.5}).seeds
    # Different team targets must not leak into each other's reconciliation.
    assert seeds[0] != seeds[100]


def test_build_goal_seeds_flags_a_club_priced_below_the_floor():
    """The trap this exists to catch: a lone priced player silently absorbing

    a whole team's worth of expected goals. Found this by hand -- a single
    test entry for Reading put one midfielder at 16.9 points for one match.
    """
    matches = [PlayerMatch(entry(club="Reading"), player_id=1, score=1.0, ambiguous=False)]
    result = build_goal_seeds(matches, {"Reading": 1.5})
    assert result.sparse_clubs == {"Reading": 1}
    assert 1 in result.seeds  # still produced -- sparse is a warning, not a rejection


def test_build_goal_seeds_does_not_flag_a_club_priced_at_the_floor():
    matches = full_club_matches("Reading")
    result = build_goal_seeds(matches, {"Reading": 1.5})
    assert result.sparse_clubs == {}


def test_a_sparsely_priced_lone_scorer_absorbs_the_whole_team_total():
    """Documents the exact failure mode, not just that it gets flagged.

    Not a bug in the arithmetic -- reconcile_team has nowhere else to put
    the rest of the team's goals -- but the number it produces from one
    entry is not one a real fixture should trust.
    """
    matches = [PlayerMatch(entry(club="Reading", goal_odds=2.75), player_id=1, score=1.0, ambiguous=False)]
    seeds = build_goal_seeds(matches, {"Reading": 1.3}).seeds
    reconciled_lambda = seeds[1] * (MINUTES_IF_LONG / 90.0)
    assert reconciled_lambda == pytest.approx(1.3 - OWN_GOAL_ALLOWANCE)


# ---- build_assist_seeds -----------------------------------------------

def test_build_assist_seeds_targets_the_assist_share_of_goals_not_the_full_total():
    matches = full_club_matches("Reading", assist_odds=3.0)
    seeds = build_assist_seeds(matches, {"Reading": 2.0}).seeds
    reconciled_total = sum(seeds.values()) * (MINUTES_IF_LONG / 90.0)
    assert reconciled_total == pytest.approx(2.0 * ASSIST_SHARE_OF_GOALS)


def test_build_assist_seeds_ignores_goal_only_entries():
    matches = [PlayerMatch(entry(goal_odds=2.0, assist_odds=None), player_id=1, score=1.0, ambiguous=False)]
    assert build_assist_seeds(matches, {"Reading": 1.5}).seeds == {}


def test_build_assist_seeds_and_build_goal_seeds_are_independent():
    """A player priced for both must get two different, correctly-targeted seeds."""
    matches = full_club_matches("Reading", goal_odds=2.0, assist_odds=4.0)
    goal_seeds = build_goal_seeds(matches, {"Reading": 1.5}).seeds
    assist_seeds = build_assist_seeds(matches, {"Reading": 1.5}).seeds
    assert set(goal_seeds) == set(assist_seeds) == {m.player_id for m in matches}
    assert goal_seeds[0] != assist_seeds[0]


# ---- build_shots_on_target_seeds --------------------------------------

def test_build_shots_on_target_seeds_has_no_team_reconciliation():
    """Unlike goals/assists, one player's seed does not depend on any other's."""
    matches = [PlayerMatch(entry(sot_odds=1.8), player_id=1, score=1.0, ambiguous=False)]
    seeds = build_shots_on_target_seeds(matches)
    expected = seed_rate(implied_rate(1.8), "start")
    assert seeds[1] == pytest.approx(expected)


def test_build_shots_on_target_seeds_drops_unconfirmed_and_unpriced():
    matches = [
        PlayerMatch(entry(sot_odds=1.8, confirmed=False), player_id=1, score=1.0, ambiguous=False),
        PlayerMatch(entry(sot_odds=None), player_id=2, score=1.0, ambiguous=False),
    ]
    assert build_shots_on_target_seeds(matches) == {}


# ---- apply_seed ---------------------------------------------------------

def test_apply_seed_only_changes_the_named_field():
    rates = PlayerRates(position="FWD", minutes=None, assists=0.1, key_passes=0.4)
    seeded = apply_seed(rates, "goals", 0.55)
    assert seeded.goals == 0.55
    assert seeded.assists == rates.assists
    assert seeded.key_passes == rates.key_passes
    assert rates.goals == 0.0  # the original is untouched -- PlayerRates is frozen


def test_apply_seed_works_for_assists_and_shots_on_target_too():
    rates = PlayerRates(position="MID", minutes=None, goals=0.2)
    assert apply_seed(rates, "assists", 0.3).assists == 0.3
    assert apply_seed(rates, "shots_on_target", 1.1).shots_on_target == 1.1
