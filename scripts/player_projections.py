"""Projected player points for the coming gameweek, ranked by position.

    python scripts/player_projections.py [--top N] [--proven-only]

Uses the shared pipeline rather than assembling its own. An earlier version
duplicated that assembly and drifted: it applied different filters, missed
double gameweeks, and carried none of the later corrections to the minutes
model. Two implementations of the same thing will always diverge, and the
divergence is silent -- both produce plausible numbers.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fantasy_efl.pipeline import load_gameweek  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
POSITIONS = ("GK", "DEF", "MID", "FWD")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=8, help="rows per position")
    parser.add_argument("--proven-only", action="store_true",
                        help="exclude players with no EFL record")
    args = parser.parse_args()

    try:
        gw = load_gameweek(ROOT, include_unproven=not args.proven_only)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    note = f"{len(gw.players)} players"
    if gw.unproven:
        note += f", {gw.unproven} with no EFL record (dagger)"
    print(f"{note}\n")

    for position in POSITIONS:
        group = sorted(
            (p for p in gw.players if p.position == position),
            key=lambda p: -p.expected_points,
        )[: args.top]
        if not group:
            continue

        print(position)
        print(f"  {'player':<21}{'club':<25}{'fixture':<24}{'xPts':>6}{'owned':>8}")
        print("  " + "-" * 84)
        for p in group:
            name = p.name + ("" if p.proven else " †")
            print(f"  {name:<21}{p.club:<25}{p.label:<24}"
                  f"{p.expected_points:>6.2f}{p.selected_pct:>7.1f}%")
        print()

    if any(not p.proven for p in gw.players):
        print("  † projected from position priors -- no EFL record yet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
