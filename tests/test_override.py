"""Tests for overriding a fixture's goal expectations.

The property that matters most is that both sides stay consistent: a fixture
has one scoreline, so a club's expected goals for must equal its opponent's
expected goals against. Letting the two drift apart would produce a model that
disagrees with itself about the same match.
"""

from __future__ import annotations

import pytest

from fantasy_efl.goals import GoalProfile
from fantasy_efl.pipeline import Gameweek, override_fixture
from fantasy_efl.player_model import PlayerProjection
from fantasy_efl.projections import ClubProjection


def club(name, opponent, away, scored, conceded, points=4.0):
    return ClubProjection(
        club=name, opponent=opponent, away=away, expected_points=points,
        p_win=0.35, p_draw=0.28,
        profile=GoalProfile(scored_rate=scored, conceded_rate=conceded),
        source="exchange",
    )


def raw(pid, squad_id, position="DEF"):
    return {
        "id": pid, "displayName": f"P{pid}", "position": position,
        "competitionId": 12, "squadId": squad_id, "status": "playing",
        "appearances": 40, "goalsScored": 2, "assists": 1, "keyPasses": 10,
        "shotsOnTarget": 8, "cleanSheets": 10, "clearances": 300, "blocks": 40,
        "tackles": 30, "interceptions": 0, "saves": 0, "percentSelected": 1.0,
    }


PRIORS = {(12, "DEF"): {
    "clearances": 4.0, "blocks": 1.0, "tackles": 1.2, "interceptions": 0.0,
    "saves": 0.0, "goalsScored": 0.05, "assists": 0.04, "keyPasses": 0.2,
    "shotsOnTarget": 0.15, "cleanSheets": 0.25,
}}


def make_gameweek():
    home = club("Alpha", "Beta", away=False, scored=1.4, conceded=1.1)
    away = club("Beta", "Alpha", away=True, scored=1.1, conceded=1.4)
    players = [
        PlayerProjection(1, "P1", "DEF", "Alpha", "Beta", False, 5.0, 1, 0.0, "playing"),
        PlayerProjection(2, "P2", "DEF", "Beta", "Alpha", True, 4.0, 1, 0.0, "playing"),
    ]
    # Fixture stores hold a list per club, because a club can play twice.
    return Gameweek(
        players=players, clubs=[home, away], backfilled=0, unproven=0, ambiguous=[],
        raw_by_id={1: raw(1, 10), 2: raw(2, 20)},
        fixtures_by_club={10: [home], 20: [away]},
        per_fixture={"Alpha": [home], "Beta": [away]},
        priors=PRIORS,
    )


def find(gw, name):
    return next(c for c in gw.clubs if c.club == name)


def test_both_sides_are_updated_consistently():
    """A fixture has one scoreline -- the two sides must agree about it."""
    gw = make_gameweek()
    override_fixture(gw, "Alpha", scored=2.2, conceded=0.4)

    alpha, beta = find(gw, "Alpha"), find(gw, "Beta")
    assert alpha.profile.scored_rate == pytest.approx(2.2)
    assert alpha.profile.conceded_rate == pytest.approx(0.4)
    assert beta.profile.scored_rate == pytest.approx(0.4)
    assert beta.profile.conceded_rate == pytest.approx(2.2)


def test_win_probabilities_are_recomputed_and_valid():
    gw = make_gameweek()
    override_fixture(gw, "Alpha", scored=2.2, conceded=0.4)
    alpha, beta = find(gw, "Alpha"), find(gw, "Beta")
    assert alpha.p_draw == pytest.approx(beta.p_draw)
    assert alpha.p_win + alpha.p_draw + beta.p_win == pytest.approx(1.0, abs=1e-6)
    assert alpha.p_win > beta.p_win  # the stronger side


def test_a_dominant_override_lifts_club_points():
    gw = make_gameweek()
    before = find(gw, "Alpha").expected_points
    override_fixture(gw, "Alpha", scored=2.6, conceded=0.3)
    assert find(gw, "Alpha").expected_points > before


def test_clean_sheet_follows_the_new_conceded_rate():
    gw = make_gameweek()
    override_fixture(gw, "Alpha", scored=1.4, conceded=0.2)
    assert find(gw, "Alpha").p_clean_sheet > 0.75


def test_players_at_both_clubs_are_reprojected():
    gw = make_gameweek()
    before = {p.id: p.expected_points for p in gw.players}
    override_fixture(gw, "Alpha", scored=2.4, conceded=0.3)
    after = {p.id: p.expected_points for p in gw.players}
    assert after[1] != before[1]
    assert after[2] != before[2]


def test_a_stronger_defence_helps_that_club_s_defenders():
    gw = make_gameweek()
    before = next(p for p in gw.players if p.club == "Alpha").expected_points
    override_fixture(gw, "Alpha", scored=1.4, conceded=0.3)
    after = next(p for p in gw.players if p.club == "Alpha").expected_points
    assert after > before


def test_the_override_is_marked_as_manual():
    """So a projection built on a guess is never mistaken for the market's."""
    gw = make_gameweek()
    override_fixture(gw, "Alpha", scored=1.5, conceded=1.0)
    assert find(gw, "Alpha").source == "manual"
    assert find(gw, "Beta").source == "manual"


def test_venue_is_preserved():
    gw = make_gameweek()
    override_fixture(gw, "Alpha", scored=1.5, conceded=1.0)
    assert find(gw, "Alpha").away is False
    assert find(gw, "Beta").away is True


def test_overriding_the_away_side_mirrors_correctly():
    gw = make_gameweek()
    override_fixture(gw, "Beta", scored=2.0, conceded=0.5)
    alpha, beta = find(gw, "Alpha"), find(gw, "Beta")
    assert beta.profile.scored_rate == pytest.approx(2.0)
    assert alpha.profile.conceded_rate == pytest.approx(2.0)
    assert beta.p_win > alpha.p_win


def test_unknown_club_raises():
    with pytest.raises(KeyError):
        override_fixture(make_gameweek(), "Gamma", 1.0, 1.0)


def test_overrides_compose():
    """Two overrides in one run must not undo each other."""
    gw = make_gameweek()
    override_fixture(gw, "Alpha", scored=2.0, conceded=0.5)
    override_fixture(gw, "Alpha", scored=1.0, conceded=1.5)
    alpha = find(gw, "Alpha")
    assert alpha.profile.scored_rate == pytest.approx(1.0)
    assert alpha.profile.conceded_rate == pytest.approx(1.5)


def test_played_fixtures_are_read_from_data_not_a_status_string():
    """No completed-round status has ever been observed in the feed.

    Keying off status == "complete" risks guessing a string that never
    appears, in which case the gameweek never advances and the season freezes
    on GW1. A recorded score is the reliable signal.
    """
    from fantasy_efl.pipeline import _is_played

    assert _is_played({"homeScore": 2, "awayScore": 1})
    assert _is_played({"homeScore": 0, "awayScore": 0})   # 0-0 is still played
    assert _is_played({"homeScore": None, "isFinalized": True})
    assert not _is_played({"homeScore": None, "isFinalized": False})
    assert not _is_played({"status": "scheduled"})


def test_overriding_a_double_gameweek_is_refused():
    """Which of the two fixtures the numbers refer to is genuinely ambiguous.

    Guessing would silently reprice the wrong match, so this errors instead.
    """
    from dataclasses import replace

    gw = make_gameweek()
    gw.clubs[0] = replace(gw.clubs[0], fixture_count=2, scheduled_count=2)
    with pytest.raises(ValueError, match="plays 2 times"):
        override_fixture(gw, "Alpha", 1.5, 1.0)
