"""Turning bookmaker prices into the probabilities the club model needs.

Two things trip up the obvious approach of "average the top five books":

1. Bookmaker odds embed a margin (the overround). Raw implied probabilities
   sum to ~105-107%, not 100%, so they are not probabilities until de-vigged.
2. Averaging *odds* is not averaging *probabilities* -- 1/x is convex, so the
   mean of the odds and the mean of the implied probabilities disagree. The
   right order is: de-vig each book independently, then average the results.

Proportional de-vigging (just dividing by the overround) assumes every runner
carries the margin equally. Bookmakers do not price that way: the
favourite-longshot bias means margin is loaded onto outsiders. The power and
Shin methods below correct for that, and matter most in exactly the spread of
near-coinflip fixtures that fills League One and League Two.
"""

from __future__ import annotations

from statistics import fmean

from .expected import ClubOutcome


def implied_probabilities(decimal_odds: list[float]) -> list[float]:
    """Raw implied probabilities. These sum to the overround, not to 1."""
    if any(o <= 1.0 for o in decimal_odds):
        raise ValueError("decimal odds must exceed 1.0")
    return [1.0 / o for o in decimal_odds]


def overround(decimal_odds: list[float]) -> float:
    """Bookmaker margin, e.g. 1.06 for a 6% book."""
    return sum(implied_probabilities(decimal_odds))


def devig_proportional(decimal_odds: list[float]) -> list[float]:
    """Scale implied probabilities to sum to 1.

    Simple and unbiased only if margin is spread evenly across runners, which
    it generally is not. Included as a baseline to compare against.
    """
    raw = implied_probabilities(decimal_odds)
    total = sum(raw)
    return [p / total for p in raw]


def devig_power(decimal_odds: list[float], *, tolerance: float = 1e-10) -> list[float]:
    """De-vig by solving for k in p_i = raw_i ** k such that the sum is 1.

    Because k > 1, this shrinks long prices harder than short ones, which is
    the direction the favourite-longshot bias actually runs.
    """
    raw = implied_probabilities(decimal_odds)

    low, high = 0.5, 3.0
    for _ in range(200):
        k = (low + high) / 2.0
        total = sum(p**k for p in raw)
        if abs(total - 1.0) < tolerance:
            break
        # Larger k lowers the sum, since every raw probability is below 1.
        if total > 1.0:
            low = k
        else:
            high = k

    scaled = [p**k for p in raw]
    total = sum(scaled)
    return [p / total for p in scaled]


def devig_shin(decimal_odds: list[float], *, tolerance: float = 1e-10) -> list[float]:
    """Shin's method, which models margin as protection against insider betting.

    Usually the best-behaved of the three on football 1X2 markets, and the
    standard choice when the de-vigged prices feed a model rather than a bet.
    """
    raw = implied_probabilities(decimal_odds)
    book = sum(raw)

    low, high = 0.0, 0.2  # z is the assumed insider fraction
    for _ in range(200):
        z = (low + high) / 2.0
        probs = _shin_probabilities(raw, book, z)
        total = sum(probs)
        if abs(total - 1.0) < tolerance:
            break
        if total > 1.0:
            low = z
        else:
            high = z

    probs = _shin_probabilities(raw, book, z)
    total = sum(probs)
    return [p / total for p in probs]


def _shin_probabilities(raw: list[float], book: float, z: float) -> list[float]:
    if z <= 0:
        return [p / book for p in raw]
    return [
        ((z**2 + 4 * (1 - z) * (p**2) / book) ** 0.5 - z) / (2 * (1 - z))
        for p in raw
    ]


def exchange_probabilities(
    back_lay: list[tuple[float | None, float | None]],
) -> list[float]:
    """Probabilities from exchange back/lay pairs.

    An exchange carries no bookmaker margin, so the heavier de-vig methods are
    the wrong tool here. What it has instead is a spread: backing at the best
    back price understates a runner's probability and laying at the best lay
    price overstates it, so the midpoint is the fair estimate. Midpoints
    normalise to roughly 100.5-101%, against 105-107% for a bookmaker, which is
    precisely why exchange prices are the better model input.

    Runners with no price on either side are dropped by the caller; a ``None``
    pair here raises rather than silently distorting the normalisation.
    """
    if not back_lay:
        raise ValueError("no exchange prices supplied")

    mids = []
    for back, lay in back_lay:
        if back and lay:
            mids.append((back + lay) / 2.0)
        elif back or lay:
            mids.append(back or lay)  # one-sided book; better than nothing
        else:
            raise ValueError("runner has neither a back nor a lay price")

    raw = [1.0 / m for m in mids]
    total = sum(raw)
    return [p / total for p in raw]


def consensus_probabilities(
    books: list[list[float]],
    *,
    method=devig_shin,
) -> list[float]:
    """Average several bookmakers into one set of probabilities.

    Each book is de-vigged on its own before averaging -- pooling the raw
    prices first would carry every book's margin straight through into the
    result.
    """
    if not books:
        raise ValueError("no bookmaker prices supplied")
    widths = {len(b) for b in books}
    if len(widths) != 1:
        raise ValueError("all books must price the same set of outcomes")

    devigged = [method(b) for b in books]
    averaged = [fmean(col) for col in zip(*devigged)]
    total = sum(averaged)
    return [p / total for p in averaged]


def club_outcome_from_odds(
    *,
    home_draw_away: list[list[float]],
    team_totals: dict[str, float] | None = None,
    away: bool,
    method=devig_shin,
) -> ClubOutcome:
    """Build a ClubOutcome for one side from market prices.

    `home_draw_away` is one list of three decimal prices per bookmaker.
    `team_totals` optionally supplies P(clean sheet) and the team-total
    probabilities where those markets are priced; where they are not, a
    Poisson fit to the supremacy and totals lines fills the gap.
    """
    probs = consensus_probabilities(home_draw_away, method=method)
    p_home, p_draw, p_away = probs

    p_win = p_away if away else p_home
    totals = team_totals or {}

    return ClubOutcome(
        p_win=p_win,
        p_draw=p_draw,
        p_clean_sheet=totals.get("clean_sheet", 0.0),
        p_scores_2_plus=totals.get("scores_2_plus", 0.0),
        p_scores_4_plus=totals.get("scores_4_plus", 0.0),
        away=away,
    )
