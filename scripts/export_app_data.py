"""Export current projections to data/app_data.json for the mobile page.

    python scripts/export_app_data.py

Costs 3 Odds API credits. Run before each gameweek deadline, then
`build_app.py` to regenerate the page.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fantasy_efl.optimiser import optimise_gameweek  # noqa: E402
from fantasy_efl.pipeline import MINUTES_GRID, load_gameweek  # noqa: E402
from fantasy_efl.snapshot import list_snapshots, load_snapshot  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "data" / "app_data.json"

#: Ownership below which an unrateable player is not worth flagging.
BLIND_SPOT_OWNERSHIP = 5.0

TOP_N = 20

#: How many gameweeks of fixture counts to show alongside each club.
#:
#: Counts only -- not projected points. Odds exist for the coming round only
#: (a three-day horizon), and the obvious substitute, last season's club
#: fantasy points, does not predict current market expectations: r = +0.12
#: overall and -0.16 in League One, wrecked by squad turnover and promotion.
#: Fixture counts, by contrast, are known exactly, and with doubles falling in
#: 20 of 42 gameweeks they are the strongest signal available for planning the
#: five-use club allocation.
OUTLOOK_WEEKS = 5


def _player(p, kickoffs, gw=None, extra=None):
    out = {
        "name": p.name, "club": p.club, "pos": p.position,
        "opp": p.opponent, "away": p.away,
        "xp": round(p.expected_points, 2),
        "own": p.selected_pct, "proven": p.proven,
        # Lockout is rolling: a player locks at their own kickoff, not at a
        # single gameweek deadline. Showing one deadline for everyone would
        # hide hours of usable time -- in GW1, 50 clubs stay open 19 hours
        # after the "deadline" the first fixture implies.
        "kickoff": kickoffs.get(p.club),
        # Projection at each minute, so the page can recalculate when team
        # news lands without reimplementing the scoring maths. Only supplied
        # for the squad, which is where the minutes controls live -- carrying
        # it for the whole pool would triple the page for nothing.
        "curve": gw.minutes_curve(p.id) if gw else [],
        # Where the slider should start: the model's own minutes estimate,
        # which sharpens as the season supplies appearances. Starting at 90
        # would quietly assert every player goes the distance.
        "xmins": round(gw.expected_minutes(p.id)) if gw else None,
    }
    if extra:
        out.update(extra)
    return out


def main() -> int:
    try:
        gw = load_gameweek(ROOT)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    squad = optimise_gameweek(gw.players, gw.clubs)
    if squad is None:
        print("no legal squad could be built", file=sys.stderr)
        return 1

    snapshot = list_snapshots()[-1]
    rounds = load_snapshot(snapshot, "rounds")
    raw = load_snapshot(snapshot, "players")
    squads = {s["id"]: s["name"] for s in load_snapshot(snapshot, "squads")}

    # Playoff rounds reuse the same round numbers as gameweeks and carry no
    # fixtures, so they interleave with the real schedule unless filtered out.
    season_rounds = [r for r in rounds if r.get("gameMode") == "season"]

    upcoming = min(
        (r for r in season_rounds if r["status"] != "complete"),
        key=lambda r: r["roundNumber"],
    )

    # Fixture counts per club for the coming weeks. A club with two fixtures
    # scores from both, so this is the clearest guide to when a club selection
    # is worth spending.
    outlook_rounds = sorted(
        (r for r in season_rounds if r["roundNumber"] >= upcoming["roundNumber"]),
        key=lambda r: r["roundNumber"],
    )[:OUTLOOK_WEEKS]

    fixture_counts: dict[int, list[int]] = {s: [] for s in squads}
    for rnd in outlook_rounds:
        played = {s: 0 for s in squads}
        for game in rnd["games"]:
            for side in ("homeId", "awayId"):
                if game[side] in played:
                    played[game[side]] += 1
        for squad_id, count in played.items():
            fixture_counts[squad_id].append(count)

    # Club projections already carry EFL spellings, courtesy of the pipeline.
    squad_ids = {name: sid for sid, name in squads.items()}

    # Each club's kickoff, which is when its players actually lock.
    kickoffs: dict[str, str] = {}
    for game in upcoming["games"]:
        for side in ("homeId", "awayId"):
            name = squads.get(game[side])
            if name and (name not in kickoffs or game["date"] < kickoffs[name]):
                kickoffs[name] = game["date"]

    ranked = sorted(gw.players, key=lambda p: -p.expected_points)
    positions = {
        pos: [_player(p, kickoffs) for p in ranked if p.position == pos][:TOP_N]
        for pos in ("GK", "DEF", "MID", "FWD")
    }

    # Highly-owned players the model cannot rate -- the gap worth knowing about.
    blind = sorted(
        (
            p for p in raw
            if p.get("status") == "playing"
            and p["appearances"] == 0
            and p.get("percentSelected", 0) >= BLIND_SPOT_OWNERSHIP
        ),
        key=lambda p: -p["percentSelected"],
    )

    payload = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "gameweek": upcoming["name"],
        "deadline": upcoming["lockoutDate"],
        "squad": {
            "formation": squad.formation,
            "players": [
                _player(p, kickoffs, gw, {
                    "captain": p.id == squad.captain.id,
                    "vice": bool(squad.vice_captain and p.id == squad.vice_captain.id),
                })
                for p in squad.players
            ],
            "clubs": [
                {"name": c.club, "opp": c.opponent, "away": c.away,
                 "xp": round(c.expected_points, 2),
                 "kickoff": kickoffs.get(c.club),
                 "fx": c.fixture_count, "sched": c.scheduled_count}
                for c in squad.clubs
            ],
            "total": round(squad.expected_points, 2),
        },
        "positions": positions,
        "clubs": [
            {
                "name": c.club,
                "opp": c.opponent,
                "away": c.away,
                "xp": round(c.expected_points, 2),
                "win": round(c.p_win, 3),
                "cs": round(c.profile.p_clean_sheet, 3),
                "outlook": fixture_counts.get(squad_ids.get(c.club, -1), []),
                "kickoff": kickoffs.get(c.club),
                "fx": c.fixture_count,
                "sched": c.scheduled_count,
            }
            for c in sorted(gw.clubs, key=lambda c: -c.expected_points)
        ],
        "outlook_weeks": [r["shortName"] for r in outlook_rounds],
        "minutes_grid": list(MINUTES_GRID),
        "stats": {"pool": len(gw.players), "unproven": gw.unproven},
        "blindspots": [
            {"name": p["displayName"], "club": squads[p["squadId"]],
             "pos": p["position"], "own": p["percentSelected"]}
            for p in blind[:8]
        ],
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    print(f"exported {upcoming['name']} -- locks {upcoming['lockoutDate']}")
    print(f"  squad {squad.formation}, {payload['squad']['total']} projected")
    print(f"  {len(blind)} unrateable players above {BLIND_SPOT_OWNERSHIP}% ownership")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
