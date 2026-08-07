"""Tests for player rate estimation, minutes and fixture adjustment."""

from __future__ import annotations

import pytest

import fantasy_efl.player_model as pm
from fantasy_efl.goals import GoalProfile
from fantasy_efl.player_model import (
    SHRINKAGE_WEIGHT,
    build_priors,
    estimate_minutes,
    project_player,
    shrunk_rate,
)
from fantasy_efl.projections import ClubProjection


def make_player(**overrides):
    base = {
        "id": 1,
        "displayName": "A. Player",
        "position": "DEF",
        "competitionId": 12,
        "squadId": 44,
        "status": "playing",
        "appearances": 46,
        "goalsScored": 0,
        "assists": 0,
        "keyPasses": 0,
        "shotsOnTarget": 0,
        "cleanSheets": 8,
        "clearances": 406,
        "blocks": 48,
        "tackles": 33,
        "interceptions": 0,
        "saves": 0,
        "percentSelected": 1.0,
    }
    base.update(overrides)
    return base


def make_fixture(scored=1.3, conceded=1.3, away=False):
    profile = GoalProfile(scored_rate=scored, conceded_rate=conceded)
    return ClubProjection(
        club="Tranmere Rovers",
        opponent="Shrewsbury Town",
        away=away,
        expected_points=4.0,
        p_win=0.35,
        p_draw=0.28,
        profile=profile,
        source="exchange",
    )


PRIORS = {(12, "DEF"): {
    "clearances": 4.0, "blocks": 1.0, "tackles": 1.2, "interceptions": 0.0,
    "saves": 0.0, "goalsScored": 0.05, "assists": 0.04, "keyPasses": 0.2,
    "shotsOnTarget": 0.15, "cleanSheets": 0.25,
}}


def test_shrinkage_pulls_small_samples_toward_the_prior():
    """Four blocks in six games is not a 0.67-per-game player."""
    raw, prior = 4 / 6, 1.0
    shrunk = shrunk_rate(4, 6, prior=prior)
    assert raw < shrunk < prior
    # With this little evidence the prior should carry more than half the weight.
    assert shrunk > (raw + prior) / 2


def test_shrinkage_defers_to_a_large_sample():
    """A full season of a high-frequency stat should stay close to observed."""
    raw, prior = 400 / 46, 4.0
    shrunk = shrunk_rate(400, 46, prior=prior)
    assert abs(shrunk - raw) < abs(shrunk - prior)
    assert shrunk == pytest.approx(raw, rel=0.12)


def test_shrinkage_returns_the_prior_with_no_evidence():
    assert shrunk_rate(0, 0, prior=2.5) == 2.5


def test_shrinkage_weight_is_the_halfway_point():
    """At exactly SHRINKAGE_WEIGHT appearances, evidence and prior weigh equally."""
    blended = shrunk_rate(SHRINKAGE_WEIGHT * 4.0, int(SHRINKAGE_WEIGHT), prior=2.0)
    assert blended == pytest.approx(3.0)


def test_priors_ignore_tiny_samples():
    players = [
        make_player(id=1, appearances=40, clearances=200),
        make_player(id=2, appearances=2, clearances=40),  # 20/game, must be excluded
    ]
    priors = build_priors(players)
    assert priors[(12, "DEF")]["clearances"] == pytest.approx(5.0)


def test_injured_and_suspended_players_are_zeroed():
    for status in ("injured", "suspended", "eliminated"):
        assert estimate_minutes(make_player(status=status)).p_appears == 0.0


def test_minutes_reflect_last_season_availability():
    nailed = estimate_minutes(make_player(appearances=46))
    fringe = estimate_minutes(make_player(appearances=12))
    assert nailed.p_appears > fringe.p_appears
    assert nailed.p_60_plus > fringe.p_60_plus


def test_not_every_appearance_counts_as_a_full_match():
    """The conflation that costs ~0.5 points per appearance if ignored."""
    minutes = estimate_minutes(make_player(appearances=46))
    assert minutes.p_short > 0.0
    assert minutes.p_60_plus < minutes.p_appears


def test_a_player_with_no_history_projects_from_priors_not_zero():
    """A third of the pool has no EFL record; zero makes them invisible."""
    unknown = project_player(make_player(appearances=0), make_fixture(), PRIORS)
    assert unknown > 0.0


def test_an_unknown_player_does_not_outrank_a_proven_starter():
    """The prior keeps them in contention without letting a guess win."""
    proven = project_player(make_player(appearances=46), make_fixture(), PRIORS)
    unknown = project_player(make_player(appearances=0), make_fixture(), PRIORS)
    assert unknown < proven


def test_injured_players_with_no_history_still_project_zero():
    assert project_player(
        make_player(appearances=0, status="injured"), make_fixture(), PRIORS
    ) == 0.0


def test_defensive_output_rises_under_pressure():
    """The core insight: pressure creates the stats this game pays for.

    Tested on a midfielder because they earn no clean sheet points, so the
    pressure effect is unopposed and the direction holds at any adjustment
    strength. For defenders the clean sheet term pulls the other way -- see
    the sensitivity test below.
    """
    priors = {(12, "MID"): dict(PRIORS[(12, "DEF")])}
    player = make_player(position="MID", interceptions=60, clearances=0,
                         blocks=0, tackles=0)
    sheltered = project_player(player, make_fixture(scored=1.8, conceded=0.7), priors)
    besieged = project_player(player, make_fixture(scored=0.7, conceded=1.8), priors)
    assert besieged > sheltered


def test_defender_fixture_preference_flips_with_adjustment_strength():
    """Documents the model's least certain behaviour, so it cannot drift silently.

    Whether a defender is better off in a hard or easy fixture depends entirely
    on ADJUSTMENT_STRENGTH: at full strength the defensive-volume boost wins, at
    half strength the undamped clean sheet term does. The sign of this effect is
    unresolved until match-level data can fit the real relationship.
    """
    player = make_player()
    easy = make_fixture(scored=1.3, conceded=0.6)
    hard = make_fixture(scored=1.3, conceded=2.2)

    original = pm.ADJUSTMENT_STRENGTH
    try:
        pm.ADJUSTMENT_STRENGTH = 1.0
        assert project_player(player, hard, PRIORS) > project_player(player, easy, PRIORS)

        pm.ADJUSTMENT_STRENGTH = 0.5
        assert project_player(player, easy, PRIORS) > project_player(player, hard, PRIORS)
    finally:
        pm.ADJUSTMENT_STRENGTH = original


def test_adjustment_strength_defaults_to_the_damped_midpoint():
    assert pm.ADJUSTMENT_STRENGTH == 0.5


def test_zero_adjustment_strength_ignores_the_fixture():
    player = make_player(position="MID", interceptions=60)
    priors = {(12, "MID"): dict(PRIORS[(12, "DEF")])}
    original = pm.ADJUSTMENT_STRENGTH
    try:
        pm.ADJUSTMENT_STRENGTH = 0.0
        easy = project_player(player, make_fixture(scored=1.3, conceded=0.6), priors)
        hard = project_player(player, make_fixture(scored=1.3, conceded=2.2), priors)
        # Only the clean sheet term should differ, and midfielders have none.
        assert easy == pytest.approx(hard)
    finally:
        pm.ADJUSTMENT_STRENGTH = original


def test_clean_sheet_probability_comes_from_the_fixture_not_history():
    player = make_player()
    easy = make_fixture(conceded=0.5)
    hard = make_fixture(conceded=2.2)
    assert project_player(player, easy, PRIORS) > 0
    assert easy.p_clean_sheet > hard.p_clean_sheet


def test_interceptions_dominate_midfield_scoring():
    """+2 each, uncapped -- the highest-leverage stat in the game."""
    priors = {(12, "MID"): dict(PRIORS[(12, "DEF")])}
    quiet = make_player(position="MID", interceptions=20, clearances=0, blocks=0, tackles=0)
    ballwinner = make_player(position="MID", interceptions=140, clearances=0, blocks=0, tackles=0)
    gap = project_player(ballwinner, make_fixture(), priors) - project_player(
        quiet, make_fixture(), priors
    )
    assert gap > 3.0


def test_fixture_multipliers_are_bounded():
    """No fixture should triple a player's output."""
    player = make_player()
    extreme = project_player(player, make_fixture(scored=0.1, conceded=6.0), PRIORS)
    normal = project_player(player, make_fixture(), PRIORS)
    assert extreme < normal * 2.0


def test_missing_prior_falls_back_to_the_same_position_elsewhere():
    player = make_player(competitionId=10)  # no (10, DEF) prior exists
    assert project_player(player, make_fixture(), PRIORS) > 0


def keeper(appearances=0, shirt=None, **kw):
    return make_player(position="GK", appearances=appearances, jerseyNum=shirt, **kw)


GK_PRIORS = {(12, "GK"): {
    "saves": 2.6, "clearances": 0.0, "blocks": 0.0, "tackles": 0.0,
    "interceptions": 0.0, "goalsScored": 0.0, "assists": 0.0,
    "keyPasses": 0.0, "shotsOnTarget": 0.0, "cleanSheets": 0.27,
}}


def test_first_choice_keeper_is_inferred_from_shirt_number():
    """Number 1 keepers made a median 32 appearances against 8 for others."""
    first = estimate_minutes(keeper(shirt=1))
    backup = estimate_minutes(keeper(shirt=13))
    assert first.p_60_plus > backup.p_60_plus
    assert first.p_60_plus >= 0.8


def test_keepers_are_not_modelled_as_substitutes():
    assert estimate_minutes(keeper(shirt=1)).p_short == 0.0


def test_an_unknown_first_choice_keeper_beats_the_flat_prior():
    """The flat prior rates a first-choice keeper at roughly half his worth."""
    fixture = make_fixture(scored=1.4, conceded=0.9)
    first = project_player(keeper(shirt=1), fixture, GK_PRIORS)
    backup = project_player(keeper(shirt=13), fixture, GK_PRIORS)
    assert first > 2 * backup


def test_keeper_projection_tracks_clean_sheet_odds():
    """Two of a keeper's four scoring terms come straight from the market."""
    easy = project_player(keeper(shirt=1), make_fixture(conceded=0.6), GK_PRIORS)
    hard = project_player(keeper(shirt=1), make_fixture(conceded=2.4), GK_PRIORS)
    assert easy > hard


def test_keepers_with_a_record_use_it_rather_than_the_shirt():
    played = estimate_minutes(keeper(appearances=46, shirt=13))
    assert played.p_60_plus > estimate_minutes(keeper(shirt=1)).p_60_plus


def test_injured_keepers_still_project_zero():
    assert estimate_minutes(keeper(shirt=1, status="injured")).p_appears == 0.0


def test_minutes_override_scales_the_projection():
    """The whole point: your team news beats the model's estimate."""
    p = make_player()
    full = project_player(p, make_fixture(), PRIORS, minutes_override=90)
    half = project_player(p, make_fixture(), PRIORS, minutes_override=45)
    assert full > half > 0


def test_zero_minutes_scores_nothing():
    assert project_player(
        make_player(), make_fixture(), PRIORS, minutes_override=0
    ) == 0.0


def test_the_sixty_minute_mark_is_a_step_not_a_slope():
    """Below 60 the appearance is worth 1 and no clean sheet can be earned."""
    p = make_player()
    just_under = project_player(p, make_fixture(), PRIORS, minutes_override=59)
    just_over = project_player(p, make_fixture(), PRIORS, minutes_override=60)
    # One extra minute buys an appearance point plus clean sheet eligibility.
    assert just_over - just_under > 1.0


def test_override_does_not_inflate_per_90_rates():
    """A player told to play 20 minutes is not thereby a higher-rate player."""
    p = make_player()
    short = project_player(p, make_fixture(), PRIORS, minutes_override=20)
    natural = project_player(p, make_fixture(), PRIORS)
    assert short < natural


def test_override_revives_a_player_the_estimate_wrote_off():
    """An injured player who is passed fit must project sensibly, not absurdly."""
    injured = make_player(status="injured")
    assert project_player(injured, make_fixture(), PRIORS) == 0.0
    revived = project_player(injured, make_fixture(), PRIORS, minutes_override=90)
    healthy = project_player(make_player(), make_fixture(), PRIORS, minutes_override=90)
    assert revived == pytest.approx(healthy, rel=0.02)


def test_override_of_a_no_history_player_stays_bounded():
    unknown = make_player(appearances=0)
    known = make_player(appearances=46)
    assert project_player(unknown, make_fixture(), PRIORS, minutes_override=90) < (
        project_player(known, make_fixture(), PRIORS, minutes_override=90) * 2
    )
