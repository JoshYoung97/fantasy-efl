"""Tests for restricting club projections to the round being played.

Club projections are built from whatever the odds feed returns, and bookmakers
price a week or more ahead. That was invisible until the first live gameweek:
run the model before a round and only that round is priced, but run it while
the round is under way and the next one is already listed. Twenty of sixty-six
clubs picked up a fixture from GW2, were treated as having a double, and their
projections roughly doubled -- with the player projections summing over the
same phantom fixture on top.
"""

from __future__ import annotations

from fantasy_efl.goals import GoalProfile
from fantasy_efl.pipeline import _only_this_round, _round_pairs
from fantasy_efl.projections import ClubProjection

SQUADS = {1: "Alpha", 2: "Beta", 3: "Gamma", 4: "Delta"}


def rnd(*pairs):
    return {"games": [{"homeId": h, "awayId": a} for h, a in pairs]}


def proj(club, opponent, away=False, points=4.0):
    return ClubProjection(
        club=club, opponent=opponent, away=away, expected_points=points,
        p_win=0.4, p_draw=0.27,
        profile=GoalProfile(scored_rate=1.4, conceded_rate=1.1),
        source="exchange",
    )


def test_pairs_are_recorded_from_both_sides():
    pairs = _round_pairs(rnd((1, 2)), SQUADS)
    assert ("Alpha", "Beta") in pairs
    assert ("Beta", "Alpha") in pairs


def test_a_next_round_fixture_is_dropped():
    """The bug. Alpha plays Beta this round; Gamma is next round's opponent."""
    pairs = _round_pairs(rnd((1, 2)), SQUADS)
    kept = _only_this_round([proj("Alpha", "Beta"), proj("Alpha", "Gamma")], pairs)
    assert [c.opponent for c in kept] == ["Beta"]


def test_a_genuine_double_keeps_both_fixtures():
    """Matching on the pair, not the club, is what makes this safe."""
    pairs = _round_pairs(rnd((1, 2), (3, 1)), SQUADS)
    kept = _only_this_round([proj("Alpha", "Beta"), proj("Alpha", "Gamma", away=True)], pairs)
    assert sorted(c.opponent for c in kept) == ["Beta", "Gamma"]


def test_both_sides_of_a_fixture_survive():
    pairs = _round_pairs(rnd((1, 2)), SQUADS)
    kept = _only_this_round([proj("Alpha", "Beta"), proj("Beta", "Alpha", away=True)], pairs)
    assert len(kept) == 2


def test_an_unknown_club_is_dropped():
    """A club the snapshot does not name cannot be verified against the round."""
    pairs = _round_pairs(rnd((1, 2)), SQUADS)
    assert _only_this_round([proj("Someone Else", "Beta")], pairs) == []


def test_a_round_with_no_fixtures_keeps_everything():
    """Discarding the whole gameweek would be worse than trusting the feed.

    A round that carries no games gives nothing to check against, so the
    filter has no opinion rather than a destructive one.
    """
    kept = _only_this_round([proj("Alpha", "Beta")], _round_pairs(rnd(), SQUADS))
    assert len(kept) == 1


def test_unnamed_squad_ids_do_not_create_pairs():
    assert _round_pairs(rnd((1, 99)), SQUADS) == set()
