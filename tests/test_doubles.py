"""Tests for double gameweeks.

A club playing twice in a Thursday-to-Wednesday window scores from both
fixtures. Mapping clubs to fixtures through a plain dict kept only the last
one, silently halving the projection for 20 of 42 gameweeks -- and, because a
club then appeared twice in the club list, the optimiser could also pick the
same club as both of your two selections.
"""

from __future__ import annotations

import pytest

from fantasy_efl.goals import GoalProfile
from fantasy_efl.pipeline import _combine, _is_played, _round_complete
from fantasy_efl.projections import ClubProjection


def fixture(club, opponent, away=False, points=4.0, scored=1.4, conceded=1.1):
    return ClubProjection(
        club=club, opponent=opponent, away=away, expected_points=points,
        p_win=0.4, p_draw=0.27,
        profile=GoalProfile(scored_rate=scored, conceded_rate=conceded),
        source="exchange",
    )


def test_a_single_fixture_is_unchanged():
    c = _combine("Alpha", [fixture("Alpha", "Beta")], scheduled=1)
    assert c.expected_points == 4.0
    assert c.fixture_count == 1
    assert not c.is_double
    assert c.missing_fixtures == 0


def test_a_double_sums_both_fixtures():
    """The bug: one of these used to vanish entirely."""
    c = _combine(
        "Alpha",
        [fixture("Alpha", "Beta", points=4.0), fixture("Alpha", "Gamma", points=3.5)],
        scheduled=2,
    )
    assert c.expected_points == pytest.approx(7.5)
    assert c.fixture_count == 2
    assert c.is_double


def test_a_double_names_both_opponents():
    c = _combine(
        "Alpha", [fixture("Alpha", "Beta"), fixture("Alpha", "Gamma")], scheduled=2
    )
    assert "Beta" in c.opponent and "Gamma" in c.opponent


def test_a_partly_priced_double_reports_the_shortfall():
    """Odds run three days ahead, so a double's second game is often unpriced.

    Projecting one fixture while the schedule says two must be visible, not
    passed off as a complete gameweek.
    """
    c = _combine("Alpha", [fixture("Alpha", "Beta")], scheduled=2)
    assert c.fixture_count == 1
    assert c.scheduled_count == 2
    assert c.missing_fixtures == 1
    assert c.is_double


def test_more_priced_than_scheduled_never_reports_negative():
    c = _combine(
        "Alpha", [fixture("Alpha", "Beta"), fixture("Alpha", "Gamma")], scheduled=1
    )
    assert c.missing_fixtures == 0
    assert c.scheduled_count == 2


def test_a_round_is_complete_only_when_every_game_is_played():
    played = {"homeScore": 1, "awayScore": 0}
    pending = {"homeScore": None, "isFinalized": False}
    assert _round_complete({"games": [played, played]})
    assert not _round_complete({"games": [played, pending]})
    assert not _round_complete({"games": []})


def test_a_goalless_draw_counts_as_played():
    assert _is_played({"homeScore": 0, "awayScore": 0})


def test_fixture_lookup_uses_the_same_names_it_was_keyed_with():
    """Guards a silent, total data loss.

    Club projections are renamed to EFL spellings, so the fixture store is
    keyed by EFL name. Looking it up by the bookmaker name instead dropped
    every club whose two names differ -- seven of them, and all 183 of their
    players -- with no error anywhere. The optimiser simply never saw them.
    """
    import inspect

    from fantasy_efl import pipeline

    source = inspect.getsource(pipeline.load_gameweek)
    assert "fixtures.get(mapping.get(" not in source, (
        "fixture lookups must use the EFL club name, matching how per_fixture "
        "is keyed, not the bookmaker name"
    )
