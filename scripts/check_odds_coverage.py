"""One-off check of EFL odds coverage and credit cost.

Run once ODDS_API_KEY is set. Reports how many fixtures each division has
priced, how many bookmakers are quoting, whether an exchange is among them,
and what the call actually cost against the free allowance.

League Two is the division to watch: markets there are sometimes not posted
until close to kickoff, which would mean projecting those clubs from ratings
rather than from the market.

    python scripts/check_odds_coverage.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fantasy_efl.expected import ClubOutcome, expected_club_points  # noqa: E402
from fantasy_efl.oddsapi import (  # noqa: E402
    EXCHANGES,
    SPORT_KEYS,
    OddsApiError,
    fetch_odds,
)


def main() -> int:
    total_cost = 0
    quota = None

    for division, sport_key in SPORT_KEYS.items():
        try:
            fixtures, quota = fetch_odds(sport_key, markets=("h2h",), regions="uk")
        except OddsApiError as exc:
            print(f"{division}: {exc}", file=sys.stderr)
            return 1

        total_cost += quota.last_cost or 0
        priced = [f for f in fixtures if f.bookmaker_books()]
        with_exchange = [f for f in fixtures if f.exchange_book()]

        print(f"\n{division}  ({sport_key})")
        print(f"  fixtures returned : {len(fixtures)}")
        print(f"  with bookmakers   : {len(priced)}")
        print(f"  with an exchange  : {len(with_exchange)}")

        if not priced:
            print("  no priced fixtures yet -- markets may not be open")
            continue

        sample = priced[0]
        books = sample.bookmaker_books(limit=None)
        print(f"  sample            : {sample.home_team} v {sample.away_team}")
        print(f"    bookmakers quoting: {len(books)}")

        consensus = sample.consensus(limit=5)
        print(f"    consensus (top 5) : {_fmt(consensus)}")

        exchange = sample.exchange_consensus()
        if exchange:
            print(f"    exchange          : {_fmt(exchange)}")
            drift = max(abs(a - b) for a, b in zip(consensus, exchange))
            print(f"    largest gap       : {drift * 100:.2f} pts of probability")
        else:
            names = {bm.get("key") for bm in sample.bookmakers}
            print(f"    exchange          : none quoting ({len(names & EXCHANGES)} found)")

        # What the club side of the model would project, ignoring the goals
        # markets for now -- those need a separate totals request.
        home = ClubOutcome(
            p_win=consensus[0], p_draw=consensus[1],
            p_clean_sheet=0.0, p_scores_2_plus=0.0, p_scores_4_plus=0.0, away=False,
        )
        away = ClubOutcome(
            p_win=consensus[2], p_draw=consensus[1],
            p_clean_sheet=0.0, p_scores_2_plus=0.0, p_scores_4_plus=0.0, away=True,
        )
        print(f"    club pts (W/D only): {sample.home_team} {expected_club_points(home):.2f}"
              f" | {sample.away_team} {expected_club_points(away):.2f}")

    print(f"\ncost of this check: {total_cost} credits")
    if quota:
        print(f"quota: {quota}")
        if quota.remaining is not None:
            daily = total_cost * 2  # h2h + totals in the real refresh
            print(f"at {daily} credits/day a 500-credit month allows "
                  f"{500 // daily if daily else 0} refreshes -- "
                  f"{'comfortable' if daily * 30 < 500 else 'TIGHT, reduce frequency'}")
    return 0


def _fmt(probs) -> str:
    return "  ".join(f"{p:.3f}" for p in probs) if probs else "n/a"


if __name__ == "__main__":
    raise SystemExit(main())
