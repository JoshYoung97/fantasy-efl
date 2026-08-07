"""Build the EFL-to-bookmaker club name mapping.

Matches the 72 clubs in the latest snapshot against the team names the odds
feed uses, writes data/club_mapping.json, and prints anything that needs a
human decision.

Entries under "needs_review" in the output file are NOT used until someone
fills in the right `odds_name` and adds `"confirmed": true`. That is
deliberate -- a wrong mapping between two same-city clubs would silently
corrupt both clubs' projections, and would not show up as an error anywhere.

    python scripts/build_club_mapping.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fantasy_efl.club_names import match_clubs, save_mapping  # noqa: E402
from fantasy_efl.oddsapi import OddsApiError, fetch_all_efl  # noqa: E402
from fantasy_efl.snapshot import list_snapshots, load_snapshot  # noqa: E402

OUTPUT = Path(__file__).resolve().parent.parent / "data" / "club_mapping.json"


def main() -> int:
    snapshots = list_snapshots()
    if not snapshots:
        print("no snapshots yet -- run: python -m fantasy_efl.snapshot", file=sys.stderr)
        return 1

    squads = load_snapshot(snapshots[-1], "squads")
    efl_names = sorted(s["name"] for s in squads)

    try:
        fixtures_by_division, quota = fetch_all_efl()
    except OddsApiError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    odds_names = sorted(
        {t for fixtures in fixtures_by_division.values()
         for f in fixtures for t in (f.home_team, f.away_team)}
    )

    print(f"EFL clubs: {len(efl_names)}   odds feed names: {len(odds_names)}")

    matches = match_clubs(efl_names, odds_names)
    save_mapping(matches, OUTPUT)

    review = [m for m in matches if m.needs_review]
    clean = len(matches) - len(review)

    print(f"matched cleanly: {clean}/{len(matches)}")

    if review:
        print(f"\nneeds review ({len(review)}):")
        print(f"  {'EFL club':<26}{'best candidate':<26}{'score':>6}  runner-up")
        print("  " + "-" * 78)
        for m in review:
            best = m.odds_name or "(no match)"
            runner = f"{m.runner_up} ({m.runner_up_score:.2f})" if m.runner_up else "-"
            flag = " AMBIGUOUS" if m.ambiguous else ""
            print(f"  {m.efl_name:<26}{best:<26}{m.score:>6.2f}  {runner}{flag}")

    unmatched = set(odds_names) - {m.odds_name for m in matches if not m.needs_review}
    if unmatched:
        print(f"\nodds names not claimed by a clean match ({len(unmatched)}):")
        for name in sorted(unmatched):
            print(f"  {name}")

    print(f"\nwritten to {OUTPUT}")
    print(f"quota: {quota}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
