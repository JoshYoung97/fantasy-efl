"""Projected player points for the coming gameweek.

    python scripts/player_projections.py [--top N]

Ranks every selectable player by expected points, grouped by position, using
the latest snapshot for rates and live market prices for fixture context.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fantasy_efl.club_names import load_mapping  # noqa: E402
from fantasy_efl.oddsapi import OddsApiError, fetch_all_efl  # noqa: E402
from fantasy_efl.player_model import (  # noqa: E402
    PlayerProjection,
    build_priors,
    project_player,
)
from fantasy_efl.projections import project_all  # noqa: E402
from fantasy_efl.snapshot import list_snapshots, load_snapshot  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
POSITIONS = ("GK", "DEF", "MID", "FWD")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=8, help="rows per position")
    args = parser.parse_args()

    snapshots = list_snapshots()
    if not snapshots:
        print("no snapshots yet -- run: python -m fantasy_efl.snapshot", file=sys.stderr)
        return 1

    players = load_snapshot(snapshots[-1], "players")
    squads = {s["id"]: s["name"] for s in load_snapshot(snapshots[-1], "squads")}

    mapping_path = ROOT / "data" / "club_mapping.json"
    if not mapping_path.exists():
        print("no club mapping -- run: python scripts/build_club_mapping.py", file=sys.stderr)
        return 1
    mapping = load_mapping(mapping_path)

    try:
        club_projections = project_all(fetch_all_efl()[0])
    except OddsApiError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    fixtures = {p.club: p for ps in club_projections.values() for p in ps}
    priors = build_priors(players)

    # Fixtures carry bookmaker spellings ("Bromley FC"); show EFL ones so the
    # club and opponent columns cannot look like different clubs.
    to_efl_name = {odds: efl for efl, odds in mapping.items()}

    projected: list[PlayerProjection] = []
    for player in players:
        # Only players actually available for selection.
        if player.get("status") != "playing" or player["appearances"] <= 0:
            continue
        club = squads.get(player["squadId"])
        fixture = fixtures.get(mapping.get(club, ""))
        if fixture is None:
            continue

        projected.append(
            PlayerProjection(
                id=player["id"],
                name=player["displayName"],
                position=player["position"],
                club=club,
                opponent=to_efl_name.get(fixture.opponent, fixture.opponent),
                away=fixture.away,
                expected_points=project_player(player, fixture, priors),
                fixtures=1,
                selected_pct=player.get("percentSelected", 0.0),
                status=player["status"],
            )
        )

    print(f"projected {len(projected)} selectable players\n")

    for position in POSITIONS:
        group = sorted(
            (p for p in projected if p.position == position),
            key=lambda p: p.expected_points,
            reverse=True,
        )[: args.top]

        print(f"{position}")
        print(f"  {'player':<20}{'club':<22}{'fixture':<24}{'xPts':>6}{'owned':>8}")
        print("  " + "-" * 78)
        for p in group:
            print(
                f"  {p.name:<20}{p.club:<22}{p.label:<24}"
                f"{p.expected_points:>6.2f}{p.selected_pct:>7.1f}%"
            )
        print()

    best = max(projected, key=lambda p: p.expected_points)
    print(f"captain pick: {best.name} ({best.club}) "
          f"{best.expected_points:.2f} -> {best.expected_points * 2:.2f} doubled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
