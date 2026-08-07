"""Tests for the exact scoring rules and the expected-points engine."""

from __future__ import annotations

import math

from fantasy_efl.expected import (
    ClubOutcome,
    MinutesModel,
    PlayerRates,
    expected_club_points,
    expected_floor_div,
    expected_player_points,
)
from fantasy_efl.scoring import ClubMatch, PlayerMatch, score_club, score_player


def test_unused_player_scores_nothing():
    assert score_player(PlayerMatch("MID", minutes=0, interceptions=5)) == 0


def test_appearance_thresholds():
    assert score_player(PlayerMatch("FWD", minutes=59)) == 1
    assert score_player(PlayerMatch("FWD", minutes=60)) == 2


def test_hat_trick_bonus_awarded_once():
    three = score_player(PlayerMatch("FWD", minutes=90, goals=3))
    four = score_player(PlayerMatch("FWD", minutes=90, goals=4))
    assert three == 2 + 15 + 5
    assert four - three == 5  # the extra goal only, no second bonus


def test_goal_points_vary_by_position():
    for position, expected in (("GK", 10), ("DEF", 7), ("MID", 6), ("FWD", 5)):
        assert score_player(PlayerMatch(position, minutes=90, goals=1)) == 2 + expected


def test_clean_sheet_requires_sixty_minutes():
    assert score_player(PlayerMatch("DEF", minutes=60, clean_sheet=True)) == 7
    assert score_player(PlayerMatch("DEF", minutes=59, clean_sheet=True)) == 1


def test_defender_floor_thresholds():
    # 7 clearances -> 1, 3 blocks -> 1, 5 tackles -> 2
    m = PlayerMatch("DEF", minutes=90, clearances=7, blocks=3, tackles=5)
    assert score_player(m) == 2 + 1 + 1 + 2


def test_goals_conceded_penalty_ignores_odd_goal():
    assert score_player(PlayerMatch("DEF", minutes=90, goals_conceded=3)) == 2 - 1
    assert score_player(PlayerMatch("DEF", minutes=90, goals_conceded=4)) == 2 - 2


def test_keeper_saves_and_penalty_save():
    m = PlayerMatch("GK", minutes=90, saves=5, penalties_saved=1, goals_conceded=1)
    assert score_player(m) == 2 + 2 + 5 + 0


def test_interceptions_are_linear_and_uncapped():
    base = score_player(PlayerMatch("MID", minutes=90))
    assert score_player(PlayerMatch("MID", minutes=90, interceptions=4)) - base == 8


def test_tackles_score_for_defenders_only():
    assert score_player(PlayerMatch("MID", minutes=90, tackles=6)) == 2
    assert score_player(PlayerMatch("DEF", minutes=90, tackles=6)) == 5


def test_interceptions_score_for_midfielders_only():
    assert score_player(PlayerMatch("DEF", minutes=90, interceptions=4)) == 2


def test_club_scoring_maximum():
    assert score_club(ClubMatch(goals_for=4, goals_against=0, away=True)) == 13


def test_club_away_win_bonus_stacks_on_win():
    home = score_club(ClubMatch(goals_for=1, goals_against=0, away=False))
    away = score_club(ClubMatch(goals_for=1, goals_against=0, away=True))
    assert home == 5 + 2
    assert away - home == 2


def test_club_draw_with_clean_sheet():
    assert score_club(ClubMatch(goals_for=0, goals_against=0, away=False)) == 3 + 2


def test_expected_floor_div_is_below_naive_ratio():
    """The whole reason this function exists."""
    mean, k = 4.5, 4
    exact = expected_floor_div(mean, k)
    assert exact < mean / k
    assert 0.5 < exact < 0.95  # naive form would claim 1.125


def test_expected_floor_div_matches_brute_force():
    mean, k = 3.0, 2
    exact = expected_floor_div(mean, k, dispersion=None)
    brute = sum(
        (x // k) * math.exp(-mean + x * math.log(mean) - math.lgamma(x + 1))
        for x in range(200)
    )
    assert abs(exact - brute) < 1e-9


def test_expected_points_never_exceed_certain_appearance_floor():
    r = PlayerRates("MID", MinutesModel(p_60_plus=1.0), interceptions=3.0)
    # 2 for the appearance, plus roughly 3 interceptions scaled to 85 minutes.
    assert 7.5 < expected_player_points(r) < 8.0


def test_rotation_risk_scales_expected_points():
    nailed = PlayerRates("MID", MinutesModel(p_60_plus=1.0), interceptions=3.0)
    rotated = PlayerRates("MID", MinutesModel(p_60_plus=0.5), interceptions=3.0)
    assert expected_player_points(rotated) < expected_player_points(nailed)


def test_expected_club_points_bounded_by_maximum():
    certain_thrashing = ClubOutcome(
        p_win=1.0,
        p_draw=0.0,
        p_clean_sheet=1.0,
        p_scores_2_plus=1.0,
        p_scores_4_plus=1.0,
        away=True,
    )
    assert expected_club_points(certain_thrashing) == 13.0
