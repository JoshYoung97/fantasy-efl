"""Expected Fantasy EFL points from per-90 rates and match context.

The scoring system is full of "every N of X" rules, which are floor functions.
E[floor(X/k)] is NOT E[X]/k -- the naive form overestimates badly, because a
player has to actually reach each threshold. A defender averaging 4.5
clearances earns ~0.75 points from the "every 4 clearances" rule, not
4.5/4 = 1.125, a 33% overstatement. Across the five or six floor rules in this
game that compounds into a materially wrong projection.

So counting stats are modelled as distributions and the expectation taken over
the pmf, via the identity:

    E[floor(X/k)] = sum_{j>=1} P(X >= j*k)

Interceptions and shots on target are the exceptions -- they score linearly, so
their means are used directly.

No third-party dependencies, so this runs anywhere.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import accumulate

from .scoring import GOAL_POINTS, Position

# Defensive counting stats are overdispersed relative to Poisson (form, game
# state and role all vary), so a negative binomial with this dispersion is the
# default. Higher values tend toward Poisson.
DEFAULT_DISPERSION = 5.0


def _poisson_pmf(x: int, mean: float) -> float:
    return math.exp(-mean + x * math.log(mean) - math.lgamma(x + 1))


def _nbinom_pmf(x: int, mean: float, dispersion: float) -> float:
    """Negative binomial with the given mean and var = mean + mean^2/dispersion."""
    p = dispersion / (dispersion + mean)
    return math.exp(
        math.lgamma(x + dispersion)
        - math.lgamma(dispersion)
        - math.lgamma(x + 1)
        + dispersion * math.log(p)
        + x * math.log1p(-p)
    )


def expected_floor_div(
    mean: float,
    k: int,
    *,
    dispersion: float | None = DEFAULT_DISPERSION,
    max_x: int = 200,
) -> float:
    """E[floor(X/k)] for a count X with the given mean.

    Pass ``dispersion=None`` for Poisson. Returns the exact expectation over
    the truncated pmf, not the mean/k approximation.
    """
    if mean <= 0 or k <= 0:
        return 0.0

    if dispersion is None:
        pmf = [_poisson_pmf(x, mean) for x in range(max_x + 1)]
    else:
        pmf = [_nbinom_pmf(x, mean, dispersion) for x in range(max_x + 1)]
    cdf = list(accumulate(pmf))

    total = 0.0
    j = 1
    while j * k <= max_x:
        survival = 1.0 - cdf[j * k - 1]
        if survival < 1e-12:
            break
        total += survival
        j += 1
    return total


@dataclass(frozen=True)
class MinutesModel:
    """How likely the player is to play, and for how long.

    The single biggest driver of projection quality -- rotation risk in the EFL
    swamps most of the finer modelling.
    """

    p_60_plus: float
    p_short: float = 0.0  # P(appears but is withdrawn before 60 minutes)
    mean_minutes_60_plus: float = 85.0
    mean_minutes_short: float = 30.0

    @property
    def p_appears(self) -> float:
        return self.p_60_plus + self.p_short


@dataclass(frozen=True)
class PlayerRates:
    """Per-90 rates for one player, already adjusted for opponent and venue.

    Only the fields relevant to ``position`` are read, so a single row can carry
    everything the scraper found.
    """

    position: Position
    minutes: MinutesModel

    # All positions
    goals: float = 0.0
    assists: float = 0.0
    own_goals: float = 0.0
    penalties_missed: float = 0.0
    yellow_cards: float = 0.0
    red_cards: float = 0.0

    # Goalkeepers
    saves: float = 0.0
    penalties_saved: float = 0.0

    # Goalkeepers and defenders -- clean sheet probability comes from the
    # opposition's expected goals, which is read straight off the betting market.
    p_clean_sheet: float = 0.0
    goals_conceded: float = 0.0

    # Defenders
    clearances: float = 0.0
    blocks: float = 0.0
    tackles: float = 0.0

    # Midfielders
    interceptions: float = 0.0

    # Midfielders and forwards
    key_passes: float = 0.0
    shots_on_target: float = 0.0

    dispersion: float | None = DEFAULT_DISPERSION


def _points_given_minutes(r: PlayerRates, minutes: float, *, sixty_plus: bool) -> float:
    """Expected points conditional on the player lasting `minutes`."""
    scale = minutes / 90.0
    disp = r.dispersion

    pts = 2.0 if sixty_plus else 1.0

    goals = r.goals * scale
    pts += GOAL_POINTS[r.position] * goals
    pts += 3.0 * r.assists * scale

    # Hat-trick bonus needs P(3+ goals), not the mean -- goals are rare enough
    # that Poisson is the right choice here.
    p_hat_trick = 1.0 - sum(_poisson_pmf(x, goals) for x in range(3)) if goals > 0 else 0.0
    pts += 5.0 * p_hat_trick

    pts -= 3.0 * r.own_goals * scale
    pts -= 3.0 * r.penalties_missed * scale
    pts -= 1.0 * r.yellow_cards * scale
    pts -= 3.0 * r.red_cards * scale

    if r.position == "GK":
        pts += 2.0 * expected_floor_div(r.saves * scale, 3, dispersion=disp)
        pts += 5.0 * r.penalties_saved * scale

    if r.position in ("GK", "DEF"):
        if sixty_plus:
            pts += 5.0 * r.p_clean_sheet
        pts -= expected_floor_div(r.goals_conceded * scale, 2, dispersion=disp)

    if r.position == "DEF":
        pts += expected_floor_div(r.clearances * scale, 4, dispersion=disp)
        pts += expected_floor_div(r.blocks * scale, 2, dispersion=disp)
        pts += expected_floor_div(r.tackles * scale, 2, dispersion=disp)

    if r.position == "MID":
        pts += 2.0 * r.interceptions * scale  # linear, no threshold

    if r.position in ("MID", "FWD"):
        pts += expected_floor_div(r.key_passes * scale, 2, dispersion=disp)
        pts += r.shots_on_target * scale  # linear

    return pts


def expected_player_points(r: PlayerRates) -> float:
    """Expected points for one player in one fixture.

    Conditions on the minutes outcome rather than scaling a single projection,
    because the floor thresholds and the 60-minute clean sheet qualifier both
    behave non-linearly in minutes played.
    """
    m = r.minutes
    total = 0.0
    if m.p_60_plus > 0:
        total += m.p_60_plus * _points_given_minutes(
            r, m.mean_minutes_60_plus, sixty_plus=True
        )
    if m.p_short > 0:
        total += m.p_short * _points_given_minutes(
            r, m.mean_minutes_short, sixty_plus=False
        )
    return total


@dataclass(frozen=True)
class ClubOutcome:
    """Match outcome probabilities, de-vigged from the betting market."""

    p_win: float
    p_draw: float
    p_clean_sheet: float
    p_scores_2_plus: float
    p_scores_4_plus: float
    away: bool


def expected_club_points(o: ClubOutcome) -> float:
    """Expected points for a selected club in one fixture.

    Every term is available directly from odds: 1X2 gives win/draw, and a
    bivariate Poisson fitted to the totals and supremacy markets gives the
    clean sheet and team-total probabilities.
    """
    pts = 5.0 * o.p_win + 3.0 * o.p_draw
    if o.away:
        pts += 2.0 * o.p_win
    pts += 2.0 * o.p_clean_sheet
    pts += 2.0 * o.p_scores_2_plus
    pts += 2.0 * o.p_scores_4_plus
    return pts


def expected_gameweek(rates: list[PlayerRates], *, is_captain: bool = False) -> float:
    """Expected points across every fixture a player has in the gameweek."""
    multiplier = 2.0 if is_captain else 1.0
    return sum(expected_player_points(r) for r in rates) * multiplier
