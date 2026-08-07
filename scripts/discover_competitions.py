"""One-off check: confirm the exchange prices all three EFL divisions.

Run once after setting the Betfair environment variables. Prints the
competition ids needed to fetch markets, plus how many events and match-odds
markets are currently listed for each -- League Two is the division most likely
to be thin, so it is worth seeing the numbers before building on them.

    python scripts/discover_competitions.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fantasy_efl.betfair import BetfairClient, BetfairError  # noqa: E402
from fantasy_efl.odds import exchange_probabilities  # noqa: E402

WANTED = ("Championship", "League 1", "League One", "League 2", "League Two")


def main() -> int:
    try:
        with BetfairClient() as client:
            competitions = client.list_competitions(text_query="English")
            matches = [
                c
                for c in competitions
                if any(w.lower() in c["competition"]["name"].lower() for w in WANTED)
            ]

            if not matches:
                print("No EFL competitions matched. All English competitions found:")
                for c in competitions:
                    print(f"  {c['competition']['id']:>8}  {c['competition']['name']}")
                return 1

            print(f"{'id':>8}  {'competition':<28} {'events':>6}  {'markets':>7}")
            print("-" * 56)
            for c in matches:
                cid = c["competition"]["id"]
                name = c["competition"]["name"]
                events = client.list_events([cid])
                markets = client.list_markets([cid], market_types=("MATCH_ODDS",))
                print(f"{cid:>8}  {name:<28} {len(events):>6}  {len(markets):>7}")

            # Sanity-check liquidity on the thinnest division we found.
            thinnest = matches[-1]["competition"]
            markets = client.list_markets(
                [thinnest["id"]], market_types=("MATCH_ODDS",), max_results=1
            )
            if markets:
                book = client.market_prices([markets[0]["marketId"]])
                runners = next(iter(book.values()))
                pairs = [(r.back, r.lay) for r in runners]
                print()
                print(f"sample market from {thinnest['name']}:")
                for r in runners:
                    print(f"  {r.selection_id}  back {r.back}  lay {r.lay}")
                if all(any(p) for p in pairs):
                    probs = exchange_probabilities(pairs)
                    print("  implied:", " ".join(f"{p:.3f}" for p in probs))

    except BetfairError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
