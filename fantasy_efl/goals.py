"""Recovering goal expectations from match-odds prices.

Club scoring needs more than who wins: clean sheets, 2+ goals and 4+ goals are
all worth 2 points each, so the model needs a distribution over scorelines, not
just a 1X2 split.

Under independent Poisson scoring, a scoreline distribution has exactly two
free parameters -- the two teams' scoring rates -- and the 1X2 market supplies
exactly two independent constraints once probabilities are normalised. So the
rates are identified by the match-odds market alone, with no extra API credits
spent on totals.

The solve is reparameterised as (total, supremacy) rather than (home, away)
because those axes are close to independent in their effects: total goals drives
the draw probability, supremacy drives the home/away split. That makes a pair of
nested bisections stable where a naive 2-D search tends to wander.

Independent Poisson slightly understates low-scoring draws -- the Dixon-Coles
correction exists for precisely that -- but the bias is small at EFL scoring
rates and fitting it needs match-level history, which the weekly snapshots are
still accumulating.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

MAX_GOALS = 15  # P(16+ goals) is ~1e-12 at these rates


def poisson_pmf(k: int, rate: float) -> float:
    if rate <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-rate + k * math.log(rate) - math.lgamma(k + 1))


def match_probabilities(home_rate: float, away_rate: float) -> tuple[float, float, float]:
    """(home win, draw, away win) for the given scoring rates."""
    home_pmf = [poisson_pmf(i, home_rate) for i in range(MAX_GOALS + 1)]
    away_pmf = [poisson_pmf(j, away_rate) for j in range(MAX_GOALS + 1)]

    p_home = p_draw = p_away = 0.0
    for i, ph in enumerate(home_pmf):
        for j, pa in enumerate(away_pmf):
            joint = ph * pa
            if i > j:
                p_home += joint
            elif i == j:
                p_draw += joint
            else:
                p_away += joint
    return p_home, p_draw, p_away


def _rates(total: float, supremacy: float) -> tuple[float, float]:
    """Split a total into home and away rates, keeping both non-negative."""
    home = max((total + supremacy) / 2.0, 1e-6)
    away = max((total - supremacy) / 2.0, 1e-6)
    return home, away


def solve_rates(
    p_home: float,
    p_draw: float,
    p_away: float,
    *,
    iterations: int = 60,
) -> tuple[float, float]:
    """Back out (home rate, away rate) from de-vigged 1X2 probabilities.

    Outer bisection on total goals matches the draw probability; inner bisection
    on supremacy matches the home-minus-away margin. Both relationships are
    monotone, so this converges reliably.
    """
    target_margin = p_home - p_away

    def fit_supremacy(total: float) -> float:
        low, high = -total, total
        for _ in range(iterations):
            mid = (low + high) / 2.0
            ph, _, pa = match_probabilities(*_rates(total, mid))
            if ph - pa < target_margin:
                low = mid
            else:
                high = mid
        return (low + high) / 2.0

    # More total goals means fewer draws, so the draw probability is monotone
    # decreasing in the total.
    low_total, high_total = 0.2, 8.0
    for _ in range(iterations):
        total = (low_total + high_total) / 2.0
        supremacy = fit_supremacy(total)
        _, draw, _ = match_probabilities(*_rates(total, supremacy))
        if draw > p_draw:
            low_total = total
        else:
            high_total = total

    total = (low_total + high_total) / 2.0
    return _rates(total, fit_supremacy(total))


@dataclass(frozen=True)
class GoalProfile:
    """Scoring-rate view of one fixture, from one club's perspective."""

    scored_rate: float
    conceded_rate: float

    @property
    def p_clean_sheet(self) -> float:
        """P(opponent fails to score)."""
        return poisson_pmf(0, self.conceded_rate)

    @property
    def p_scores_2_plus(self) -> float:
        return 1.0 - sum(poisson_pmf(k, self.scored_rate) for k in range(2))

    @property
    def p_scores_4_plus(self) -> float:
        return 1.0 - sum(poisson_pmf(k, self.scored_rate) for k in range(4))

    def p_concedes(self, goals: int) -> float:
        return poisson_pmf(goals, self.conceded_rate)


def profiles_from_probabilities(
    p_home: float, p_draw: float, p_away: float
) -> tuple[GoalProfile, GoalProfile]:
    """Goal profiles for (home, away) from de-vigged 1X2 probabilities."""
    home_rate, away_rate = solve_rates(p_home, p_draw, p_away)
    return (
        GoalProfile(scored_rate=home_rate, conceded_rate=away_rate),
        GoalProfile(scored_rate=away_rate, conceded_rate=home_rate),
    )
