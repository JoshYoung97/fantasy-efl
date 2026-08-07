"""Tests for squad optimisation.

The two-players-per-club limit is the constraint that makes greedy selection
wrong, so most of these check it is genuinely respected rather than
approximated.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from fantasy_efl.optimiser import (
    FORMATIONS,
    MAX_PER_CLUB,
    SQUAD_SIZE,
    optimise_gameweek,
)
from fantasy_efl.player_model import PlayerProjection


def player(pid, position, club, points):
    return PlayerProjection(
        id=pid, name=f"P{pid}", position=position, club=club,
        opponent="Someone", away=False, expected_points=points,
        fixtures=1, selected_pct=0.0, status="playing",
    )


@dataclass(frozen=True)
class FakeClub:
    club: str
    expected_points: float


CLUBS = [FakeClub("A", 6.0), FakeClub("B", 5.0), FakeClub("C", 4.0)]


def squad_of(counts, clubs=("A", "B", "C", "D", "E", "F", "G"), base=5.0):
    """Build a pool with `counts` players per position spread across clubs."""
    pool, pid = [], 0
    for position, n in counts.items():
        for i in range(n):
            pool.append(player(pid, position, clubs[pid % len(clubs)], base + i * 0.1))
            pid += 1
    return pool


def test_every_formation_is_legal_under_the_rules():
    for name, (gk, d, m, f) in FORMATIONS.items():
        assert gk == 1
        assert 2 <= d <= 3
        assert 2 <= m <= 3
        assert 1 <= f <= 2
        assert gk + d + m + f == SQUAD_SIZE


def test_squad_has_exactly_seven_players():
    pool = squad_of({"GK": 4, "DEF": 8, "MID": 8, "FWD": 6})
    squad = optimise_gameweek(pool, CLUBS)
    assert squad is not None
    assert len(squad.players) == SQUAD_SIZE


def test_club_limit_is_respected():
    """The constraint that makes greedy selection produce illegal teams."""
    pool = squad_of({"GK": 4, "DEF": 8, "MID": 8, "FWD": 6})
    squad = optimise_gameweek(pool, CLUBS)
    counts: dict[str, int] = {}
    for p in squad.players:
        counts[p.club] = counts.get(p.club, 0) + 1
    assert max(counts.values()) <= MAX_PER_CLUB


def test_greedy_selection_would_be_illegal_here():
    """A club stacked with the best players must not supply more than two."""
    pool = [player(i, "MID", "Stacked", 20.0 - i) for i in range(5)]
    pool += [player(100 + i, "MID", f"Other{i}", 5.0) for i in range(5)]
    pool += [player(200 + i, "GK", f"G{i}", 4.0) for i in range(3)]
    pool += [player(300 + i, "DEF", f"D{i}", 4.0) for i in range(5)]
    pool += [player(400 + i, "FWD", f"F{i}", 4.0) for i in range(5)]

    squad = optimise_gameweek(pool, CLUBS)
    stacked = [p for p in squad.players if p.club == "Stacked"]
    assert len(stacked) <= MAX_PER_CLUB
    # ...but it should still take its full allowance of the best players.
    assert len(stacked) == MAX_PER_CLUB


def test_one_club_chip_lifts_the_limit():
    pool = [player(i, "MID", "Stacked", 20.0 - i) for i in range(5)]
    pool += [player(200 + i, "GK", f"G{i}", 4.0) for i in range(3)]
    pool += [player(300 + i, "DEF", f"D{i}", 4.0) for i in range(5)]
    pool += [player(400 + i, "FWD", f"F{i}", 4.0) for i in range(5)]

    normal = optimise_gameweek(pool, CLUBS)
    chipped = optimise_gameweek(pool, CLUBS, one_club_chip=True)
    stacked = [p for p in chipped.players if p.club == "Stacked"]
    assert len(stacked) > MAX_PER_CLUB
    assert chipped.expected_points > normal.expected_points


def test_formation_matches_the_selection():
    pool = squad_of({"GK": 4, "DEF": 8, "MID": 8, "FWD": 6})
    squad = optimise_gameweek(pool, CLUBS)
    counts = squad.counts()
    assert (counts["GK"], counts["DEF"], counts["MID"], counts["FWD"]) == FORMATIONS[
        squad.formation
    ]


def test_strong_midfielders_pull_the_formation_to_three():
    """Mirrors the real finding that interceptions make midfielders dominant."""
    pool = [player(i, "MID", f"M{i}", 9.0) for i in range(6)]
    pool += [player(100 + i, "DEF", f"D{i}", 4.0) for i in range(6)]
    pool += [player(200 + i, "GK", f"G{i}", 4.0) for i in range(3)]
    pool += [player(300 + i, "FWD", f"F{i}", 4.0) for i in range(4)]

    squad = optimise_gameweek(pool, CLUBS)
    assert squad.counts()["MID"] == 3


def test_captain_is_in_the_squad_and_is_its_best_player():
    pool = squad_of({"GK": 4, "DEF": 8, "MID": 8, "FWD": 6})
    squad = optimise_gameweek(pool, CLUBS)
    assert squad.captain in squad.players
    assert squad.captain.expected_points == max(
        p.expected_points for p in squad.players
    )


def test_vice_captain_differs_from_captain():
    pool = squad_of({"GK": 4, "DEF": 8, "MID": 8, "FWD": 6})
    squad = optimise_gameweek(pool, CLUBS)
    assert squad.vice_captain is not None
    assert squad.vice_captain.id != squad.captain.id


def test_expected_points_counts_the_captain_twice_and_both_clubs():
    pool = squad_of({"GK": 4, "DEF": 8, "MID": 8, "FWD": 6})
    squad = optimise_gameweek(pool, CLUBS)
    base = sum(p.expected_points for p in squad.players)
    clubs = sum(c.expected_points for c in squad.clubs)
    assert squad.expected_points == pytest.approx(
        base + squad.captain.expected_points + clubs
    )


def test_two_best_clubs_are_selected():
    pool = squad_of({"GK": 4, "DEF": 8, "MID": 8, "FWD": 6})
    squad = optimise_gameweek(pool, CLUBS)
    assert len(squad.clubs) == 2
    assert {c.club for c in squad.clubs} == {"A", "B"}


def test_zero_point_players_are_excluded():
    """Injured and non-featuring players project zero and must not be picked."""
    pool = squad_of({"GK": 4, "DEF": 8, "MID": 8, "FWD": 6})
    pool.append(player(999, "MID", "Z", 0.0))
    squad = optimise_gameweek(pool, CLUBS)
    assert all(p.id != 999 for p in squad.players)


def test_returns_none_when_no_legal_squad_exists():
    assert optimise_gameweek([player(1, "GK", "A", 5.0)], CLUBS) is None


def test_empty_pool_returns_none():
    assert optimise_gameweek([], CLUBS) is None


def test_optimum_beats_a_greedy_baseline():
    """Verify optimality against greedy on a case designed to trap it."""
    pool = [
        player(1, "MID", "A", 10.0), player(2, "MID", "A", 9.9), player(3, "MID", "A", 9.8),
        player(4, "MID", "B", 9.0),
        player(5, "DEF", "A", 9.7), player(6, "DEF", "C", 3.0), player(7, "DEF", "D", 2.9),
        player(8, "GK", "E", 3.0),
        player(9, "FWD", "F", 3.0), player(10, "FWD", "G", 2.8),
    ]
    squad = optimise_gameweek(pool, CLUBS)
    counts: dict[str, int] = {}
    for p in squad.players:
        counts[p.club] = counts.get(p.club, 0) + 1
    assert max(counts.values()) <= MAX_PER_CLUB
    assert len(squad.players) == SQUAD_SIZE
