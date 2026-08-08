"""Tests for planning club selections across a season.

The property worth guarding is optimality. Picking the best two clubs each
week in turn looks reasonable and is not correct: a club used early on a
middling fixture is unavailable for a better one later, and the five-use cap
is what makes that bite.
"""

from __future__ import annotations

import pytest

from fantasy_efl.allocation import fixtures_by_club, plan_season


def test_every_gameweek_gets_its_two_clubs():
    fixtures = {f"C{i}": {g: 1 for g in range(1, 11)} for i in range(8)}
    plan = plan_season(fixtures)
    assert all(len(v) == 2 for v in plan.picks.values())
    assert not plan.unfilled


def test_no_club_exceeds_its_five_uses():
    fixtures = {f"C{i}": {g: 1 for g in range(1, 21)} for i in range(10)}
    plan = plan_season(fixtures)
    assert max(plan.uses.values()) <= 5
    assert sum(plan.uses.values()) == 40  # 20 gameweeks x 2


def test_a_club_is_never_picked_twice_in_one_gameweek():
    fixtures = {f"C{i}": {1: 2, 2: 2} for i in range(4)}
    plan = plan_season(fixtures)
    for clubs in plan.picks.values():
        assert len(clubs) == len(set(clubs))


def test_doubles_are_preferred_when_strength_is_equal():
    """With uniform strength the objective is simply fixtures covered."""
    fixtures = {
        "Doubler": {1: 2, 2: 2},
        "Single1": {1: 1, 2: 1},
        "Single2": {1: 1, 2: 1},
        "Single3": {1: 1, 2: 1},
    }
    plan = plan_season(fixtures)
    assert "Doubler" in plan.picks[1]
    assert "Doubler" in plan.picks[2]


def test_a_stronger_club_is_preferred_over_a_double():
    """Strength multiplies the fixture count, so it can outweigh a second game."""
    fixtures = {"Strong": {1: 1}, "Weak": {1: 2}, "Filler": {1: 1}}
    plan = plan_season(fixtures, strength={"Strong": 5.0, "Weak": 1.0, "Filler": 0.1})
    assert "Strong" in plan.picks[1]


def test_the_cap_is_spent_on_the_best_gameweeks_not_the_earliest():
    """The failure greedy makes: using a club up before their best fixture.

    One strong club, six gameweeks, and only one use available. It must be
    spent on the double, not on gameweek 1.
    """
    fixtures = {
        "Strong": {1: 1, 2: 1, 3: 1, 4: 2, 5: 1, 6: 1},
        **{f"Filler{i}": {g: 1 for g in range(1, 7)} for i in range(4)},
    }
    strength = {"Strong": 10.0, **{f"Filler{i}": 1.0 for i in range(4)}}
    plan = plan_season(fixtures, strength=strength, max_uses=1)
    assert "Strong" in plan.picks[4]
    assert not any("Strong" in plan.picks[g] for g in (1, 2, 3, 5, 6))


def test_the_plan_beats_picking_the_best_two_each_week():
    """Greedy exhausts strong clubs early and pays for it later."""
    fixtures = {
        "A": {g: 2 if g > 6 else 1 for g in range(1, 11)},
        "B": {g: 2 if g > 6 else 1 for g in range(1, 11)},
        **{f"F{i}": {g: 1 for g in range(1, 11)} for i in range(4)},
    }
    strength = {"A": 4.0, "B": 4.0, **{f"F{i}": 1.0 for i in range(4)}}
    plan = plan_season(fixtures, strength=strength)

    greedy_value, used = 0.0, {}
    for week in range(1, 11):
        available = sorted(
            (c for c in fixtures if used.get(c, 0) < 5 and week in fixtures[c]),
            key=lambda c: -strength[c] * fixtures[c][week],
        )[:2]
        for club in available:
            greedy_value += strength[club] * fixtures[club][week]
            used[club] = used.get(club, 0) + 1

    assert plan.value >= greedy_value


def test_an_unplayable_gameweek_is_reported_not_hidden():
    fixtures = {"A": {1: 1}, "B": {1: 1}}
    plan = plan_season(fixtures, gameweeks=[1, 2])
    assert plan.unfilled == [2]


def test_scarce_clubs_still_fill_what_they_can():
    """More gameweeks than the cap can cover, so some go short."""
    fixtures = {f"C{i}": {g: 1 for g in range(1, 21)} for i in range(3)}
    plan = plan_season(fixtures)
    assert sum(plan.uses.values()) == 15  # 3 clubs x 5 uses
    assert len(plan.unfilled) > 0


def test_fixture_counts_are_read_from_the_schedule():
    rounds = [
        {"gameMode": "season", "roundNumber": 1,
         "games": [{"homeId": 1, "awayId": 2}, {"homeId": 1, "awayId": 3}]},
        {"gameMode": "playoff", "roundNumber": 1, "games": []},
    ]
    squads = {1: "Alpha", 2: "Beta", 3: "Gamma"}
    counts = fixtures_by_club(rounds, squads)
    assert counts["Alpha"][1] == 2   # plays twice
    assert counts["Beta"][1] == 1


def test_value_reflects_strength_and_fixture_count():
    fixtures = {"A": {1: 2}, "B": {1: 1}}
    plan = plan_season(fixtures, strength={"A": 3.0, "B": 2.0})
    assert plan.value == pytest.approx(3.0 * 2 + 2.0 * 1)
    assert plan.fixtures_covered == 3
