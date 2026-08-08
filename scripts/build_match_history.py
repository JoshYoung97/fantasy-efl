"""Reconstruct match-level history from the stored snapshots.

    python scripts/build_match_history.py

Differences every consecutive pair of snapshots into per-player match lines,
writes them to data/matches.json, and reports what they say about the three
assumptions the model currently guesses at.

Nothing happens until a gameweek has been played. Run it after each one; the
history accumulates, and the measurements sharpen with it.

It deliberately reports rather than applies. A measured value is only better
than an assumption if the reconstruction behind it is sound, and that cannot
be known until there is enough of it to look at.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fantasy_efl.deltas import (  # noqa: E402
    build_history,
    calibrate,
    save_history,
    summarise,
)
from fantasy_efl.player_model import CARD_COST, START_SHARE  # noqa: E402
from fantasy_efl.snapshot import list_snapshots  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    snapshots = list_snapshots()
    if len(snapshots) < 2:
        print(f"need at least two snapshots to difference, found {len(snapshots)}",
              file=sys.stderr)
        return 1

    lines = build_history()
    summary = summarise(lines)

    print(f"snapshots      {len(snapshots)}")
    print(f"match lines    {summary['lines']}")
    print(f"players        {summary['players']}")
    print(f"appearances    {summary['appearances']}")
    if summary["by_position"]:
        print("  by position  " + "  ".join(
            f"{k} {v}" for k, v in sorted(summary["by_position"].items())))
    if summary["multi_fixture_lines"]:
        print(f"  {summary['multi_fixture_lines']} lines cover more than one fixture "
              f"(a double gameweek, or a missed snapshot)")

    if not lines:
        print("\nNo player's totals have moved yet, so no gameweek has been played.")
        print("Run this again once one has; the machinery is ready.")
        return 0

    path = save_history(lines)
    print(f"\nwritten to {path}")

    result = calibrate(lines)
    print(f"\nsingle-appearance lines usable for calibration: "
          f"{result.single_appearance_lines}")
    if not result.usable:
        print("  not enough yet to prefer measurement over assumption "
              "(want 200+, roughly two gameweeks)")

    print("\n  what the model assumes, against what the data says:")
    if result.start_share is not None:
        print(f"    share of appearances lasting 60+ min   "
              f"assumed {START_SHARE[0][1]:.2f}   measured {result.start_share:.2f}")
    if result.card_rate is not None:
        print(f"    cards per appearance, pooled           "
              f"measured {result.card_rate:.3f}")

    if result.card_cost:
        print("    card cost per appearance, by position")
        for position in ("GK", "DEF", "MID", "FWD"):
            if position in result.card_cost:
                print(f"      {position}   assumed {CARD_COST[position]:.2f}   "
                      f"measured {result.card_cost[position]:.3f}")
    else:
        print("    card cost by position: not enough lines per position yet")

    if result.stat_dispersion:
        print("    negative binomial dispersion (model assumes 5.0 throughout)")
        for stat, k in sorted(result.stat_dispersion.items()):
            print(f"      {stat:<14} {k}")

    if result.usable:
        print("\n  Enough evidence to act on. Replacing START_SHARE and CARD_COST")
        print("  with these is the single largest improvement available to the")
        print("  model -- but read the numbers first; a reconstruction bug would")
        print("  show up here as a plausible-looking measurement.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
