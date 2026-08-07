"""Joining market prices to expected Fantasy EFL points.

The chain is: bookmaker or exchange prices -> de-vigged 1X2 probabilities ->
Poisson scoring rates -> the clean sheet and goal-threshold probabilities that
club scoring actually pays out on.

Exchange prices are preferred where available. They disagree with the
bookmaker consensus most in League One and League Two -- the divisions holding
most of this game's player pool -- and the exchange is the sharper of the two.
"""

from __future__ import annotations

from dataclasses import dataclass

from .expected import ClubOutcome, expected_club_points
from .goals import GoalProfile, profiles_from_probabilities
from .oddsapi import Fixture


@dataclass(frozen=True)
class ClubProjection:
    """One club's projected points for a gameweek.

    Usually one fixture, but a club playing twice in a Thursday-to-Wednesday
    window scores from both, so `expected_points` may cover several. The
    per-fixture detail stays in `fixtures`.
    """

    club: str
    opponent: str
    away: bool
    expected_points: float
    p_win: float
    p_draw: float
    profile: GoalProfile
    source: str  # "exchange", "bookmakers" or "manual"

    #: How many of this club's fixtures the market has priced, and how many the
    #: schedule says it has. These differ when a double gameweek's second
    #: fixture is beyond the three-day horizon bookmakers price to -- in which
    #: case the projection covers only part of the gameweek and says so, rather
    #: than passing a partial total off as complete.
    fixture_count: int = 1
    scheduled_count: int = 1

    @property
    def p_clean_sheet(self) -> float:
        return self.profile.p_clean_sheet

    @property
    def is_double(self) -> bool:
        return self.scheduled_count > 1

    @property
    def missing_fixtures(self) -> int:
        return max(0, self.scheduled_count - self.fixture_count)


def project_fixture(
    fixture: Fixture,
    *,
    prefer_exchange: bool = True,
    bookmaker_limit: int | None = 5,
) -> tuple[ClubProjection, ClubProjection] | None:
    """Project both clubs in a fixture. None if nobody has priced it."""
    probabilities = None
    source = ""

    if prefer_exchange:
        probabilities = fixture.exchange_consensus()
        source = "exchange"
    if probabilities is None:
        probabilities = fixture.consensus(limit=bookmaker_limit)
        source = "bookmakers"
    if probabilities is None:
        return None

    p_home, p_draw, p_away = probabilities
    home_profile, away_profile = profiles_from_probabilities(p_home, p_draw, p_away)

    def build(club, opponent, p_win, profile, away):
        outcome = ClubOutcome(
            p_win=p_win,
            p_draw=p_draw,
            p_clean_sheet=profile.p_clean_sheet,
            p_scores_2_plus=profile.p_scores_2_plus,
            p_scores_4_plus=profile.p_scores_4_plus,
            away=away,
        )
        return ClubProjection(
            club=club,
            opponent=opponent,
            away=away,
            expected_points=expected_club_points(outcome),
            p_win=p_win,
            p_draw=p_draw,
            profile=profile,
            source=source,
        )

    return (
        build(fixture.home_team, fixture.away_team, p_home, home_profile, False),
        build(fixture.away_team, fixture.home_team, p_away, away_profile, True),
    )


def project_all(
    fixtures_by_division: dict[str, list[Fixture]],
    **kwargs,
) -> dict[str, list[ClubProjection]]:
    """Project every priced fixture, keyed by division and ranked by points."""
    out: dict[str, list[ClubProjection]] = {}
    for division, fixtures in fixtures_by_division.items():
        projections: list[ClubProjection] = []
        for fixture in fixtures:
            pair = project_fixture(fixture, **kwargs)
            if pair:
                projections.extend(pair)
        projections.sort(key=lambda p: p.expected_points, reverse=True)
        out[division] = projections
    return out
