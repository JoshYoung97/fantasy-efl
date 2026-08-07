"""Exact Fantasy EFL scoring: a stat line in, points out.

Encodes the 2026/27 rules. Being deterministic, this doubles as the backtest
oracle for the projection model in `expected.py` -- project a gameweek, then
score the real stat lines with this and compare.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Position = Literal["GK", "DEF", "MID", "FWD"]

#: Points per goal scored, by position (own goals excluded).
GOAL_POINTS: dict[str, int] = {"GK": 10, "DEF": 7, "MID": 6, "FWD": 5}


@dataclass(frozen=True)
class PlayerMatch:
    """One player's stat line from a single fixture.

    Fields are grouped by which positions actually score from them; anything
    irrelevant to the player's position is ignored rather than rejected, so
    a scraped row can be passed through unfiltered.
    """

    position: Position
    minutes: int = 0

    # All positions
    goals: int = 0
    assists: int = 0
    own_goals: int = 0
    penalties_missed: int = 0
    yellow_cards: int = 0
    red_cards: int = 0

    # Goalkeepers
    saves: int = 0
    penalties_saved: int = 0

    # Goalkeepers and defenders
    clean_sheet: bool = False
    goals_conceded: int = 0

    # Defenders
    clearances: int = 0
    blocks: int = 0
    tackles: int = 0

    # Midfielders
    interceptions: int = 0

    # Midfielders and forwards
    key_passes: int = 0
    shots_on_target: int = 0


def score_player(m: PlayerMatch) -> int:
    """Points scored by one player in one fixture."""
    if m.minutes <= 0:
        return 0

    pts = 2 if m.minutes >= 60 else 1

    pts += 3 * m.assists
    pts += GOAL_POINTS[m.position] * m.goals
    if m.goals >= 3:
        pts += 5  # hat-trick bonus, awarded once regardless of goals beyond 3
    pts -= 3 * m.own_goals
    pts -= 3 * m.penalties_missed
    pts -= 1 * m.yellow_cards
    pts -= 3 * m.red_cards

    if m.position == "GK":
        pts += 2 * (m.saves // 3)
        pts += 5 * m.penalties_saved

    if m.position in ("GK", "DEF"):
        # The 60-minute qualifier applies to the clean sheet only; the
        # goals-conceded penalty has no stated minutes threshold.
        if m.clean_sheet and m.minutes >= 60:
            pts += 5
        pts -= m.goals_conceded // 2

    if m.position == "DEF":
        pts += m.clearances // 4
        pts += m.blocks // 2
        pts += m.tackles // 2

    if m.position == "MID":
        # Uncapped and linear -- the highest-leverage stat in the game.
        pts += 2 * m.interceptions

    if m.position in ("MID", "FWD"):
        pts += m.key_passes // 2
        pts += m.shots_on_target

    return pts


@dataclass(frozen=True)
class ClubMatch:
    """One club's result from a single fixture."""

    goals_for: int
    goals_against: int
    away: bool


def score_club(m: ClubMatch) -> int:
    """Points scored by a selected club in one fixture (maximum 13)."""
    pts = 0

    if m.goals_for > m.goals_against:
        pts += 5
        if m.away:
            pts += 2  # away-win bonus, on top of the win
    elif m.goals_for == m.goals_against:
        pts += 3

    if m.goals_against == 0:
        pts += 2
    if m.goals_for >= 2:
        pts += 2
    if m.goals_for >= 4:
        pts += 2

    return pts


def score_gameweek(
    fixtures: list[PlayerMatch],
    *,
    is_captain: bool = False,
) -> int:
    """Total a player's gameweek across all their fixtures.

    Clubs playing twice in a Thursday-Wednesday gameweek score from both, and
    a captain doubles in each -- so the multiplier applies per fixture, not to
    the gameweek total.
    """
    multiplier = 2 if is_captain else 1
    return sum(score_player(m) for m in fixtures) * multiplier
