"""Plan club selections for the whole season.

    python scripts/plan_clubs.py [--from N] [--uses 5]

Two clubs a gameweek, no club more than five times all season, solved exactly
rather than week by week. Taking a club now costs one of only five chances to
use them, and greedy selection cannot see that their best fixture is in March.

What the plan cannot yet weigh is how good each club is. Bookmakers price
three days ahead, and a single round of odds leaves club strength
mathematically unidentifiable -- every club appears exactly once, so only
differences within a fixture are visible, never levels across the division.
Until several gameweeks have accumulated, every club is treated as equal and
the plan maximises fixtures covered.

Re-run it once strength ratings exist and the same solver produces the real
plan.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fantasy_efl.allocation import fixtures_by_club, plan_season  # noqa: E402
from fantasy_efl.snapshot import list_snapshots, load_snapshot  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="start", type=int, default=1,
                        help="first gameweek to plan from")
    parser.add_argument("--uses", type=int, default=5,
                        help="uses allowed per club (the rules say 5)")
    parser.add_argument("--show", type=int, default=12,
                        help="gameweeks to print in full")
    parser.add_argument("--strength", action="store_true",
                        help="weight clubs by their projected points in the "
                             "current round. One noisy observation each, "
                             "confounded with who they happen to be playing, "
                             "but better than treating every club as equal.")
    args = parser.parse_args()

    snapshots = list_snapshots()
    if not snapshots:
        print("no snapshots yet -- run: python -m fantasy_efl.snapshot", file=sys.stderr)
        return 1

    rounds = load_snapshot(snapshots[-1], "rounds")
    squads = {s["id"]: s["name"] for s in load_snapshot(snapshots[-1], "squads")}
    fixtures = fixtures_by_club(rounds, squads)

    strength = None
    if args.strength:
        try:
            from fantasy_efl.pipeline import load_gameweek
            gw = load_gameweek(ROOT, stored_odds=True)
        except RuntimeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        # A club's projected points this round reflect its own quality and its
        # opponent's in equal measure, so this is a proxy rather than a rating.
        # It is one observation per club; a real rating needs several rounds,
        # by which point clubs have met different opposition and their levels
        # separate.
        strength = {c.club: max(c.expected_points, 0.1) for c in gw.clubs}

    weeks = sorted({g for byround in fixtures.values() for g in byround
                    if g >= args.start})
    plan = plan_season(fixtures, strength=strength,
                       max_uses=args.uses, gameweeks=weeks)

    print(f"planning gameweeks {weeks[0]}-{weeks[-1]}, {args.uses} uses per club")
    print(f"  selections needed   {2 * len(weeks)}")
    print(f"  fixtures covered    {plan.fixtures_covered}")
    print(f"  of those, doubles   {plan.doubles_used}")
    print(f"  clubs used          {len(plan.uses)} of {len(fixtures)}")
    if plan.unfilled:
        print(f"  gameweeks left short: {plan.unfilled}")

    if strength:
        print("\n  Clubs weighted by their projected points in the current round.")
        print("  That is one observation each, and it measures the fixture as much")
        print("  as the club -- a modest side drawn against a poor one scores well")
        print("  here and will not sustain it. Treat the ordering as provisional;")
        print("  it separates properly once clubs have met different opponents.")
    else:
        print("\n  Every club weighted equally: one round of odds cannot identify")
        print("  club strength, so this maximises fixtures rather than points.")
        print("  Pass --strength to weight by current projections instead.")
    print("  Doubles are not the constraint -- 744 are available for 84")
    print("  selections -- so which clubs to spend uses on is the whole question.")

    print(f"\n  first {args.show} gameweeks")
    for week in weeks[:args.show]:
        picks = plan.picks.get(week, [])
        detail = "  ".join(
            f"{club} x{fixtures[club][week]}" if fixtures[club][week] > 1 else club
            for club in picks
        )
        print(f"    GW{week:<3} {detail or '-- nothing available'}")

    spread = Counter(plan.uses.values())
    print("\n  how the uses are spread")
    for count in sorted(spread, reverse=True):
        print(f"    {count} use{'s' if count > 1 else ' '}   {spread[count]} clubs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
