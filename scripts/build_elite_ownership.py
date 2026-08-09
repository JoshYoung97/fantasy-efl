"""Turn collected elite squads into ownership percentages.

    python scripts/build_elite_ownership.py

Reads data/elite_raw.json -- produced by pasting scripts/collect_elite.js into
the browser console while signed in to fantasy.efl.com -- and writes
data/elite_ownership.json, which the page export picks up.

Collection is manual because both endpoints require a session. Copying a
session cookie into a scheduled script would put a credential on disk that
expires silently; a console paste once a gameweek is the smaller cost.

Nothing useful comes back until a gameweek has locked, and this says so rather
than reporting everyone at 0%.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fantasy_efl.elite import DEFAULT_RAW, aggregate, differentials, save  # noqa: E402
from fantasy_efl.snapshot import list_snapshots, load_snapshot  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    if not DEFAULT_RAW.exists():
        print(f"no {DEFAULT_RAW.name} -- collect it first:", file=sys.stderr)
        print("  1. open https://fantasy.efl.com/rankings, signed in", file=sys.stderr)
        print("  2. paste scripts/collect_elite.js into the console", file=sys.stderr)
        print(f"  3. save its output as data/{DEFAULT_RAW.name}", file=sys.stderr)
        return 1

    payload = json.loads(DEFAULT_RAW.read_text(encoding="utf-8"))

    snapshots = list_snapshots()
    squads = players = {}
    if snapshots:
        squads = {s["id"]: s["name"] for s in load_snapshot(snapshots[-1], "squads")}
        players = {p["id"]: p for p in load_snapshot(snapshots[-1], "players")}

    elite = aggregate(payload, squads)
    print(f"round {elite.round_id}, collected {payload.get('collected', '?')} teams")
    print(f"  squads visible: {elite.sample}")

    if not elite.sample:
        print("\n  No squad is visible yet -- teams stay hidden until a gameweek")
        print("  locks. Re-collect after one has.")
        return 0

    save(elite)
    if not elite.usable:
        print(f"  fewer than {20} visible squads, so treat these as indicative")

    named = lambda pid: players.get(pid, {}).get("displayName", str(pid))

    print("\n  most owned among the top managers")
    for pid, share in sorted(elite.players.items(), key=lambda kv: -kv[1])[:10]:
        overall = players.get(pid, {}).get("percentSelected", 0.0)
        print(f"    {named(pid):<22}{share:>6.1f}%   overall {overall:>5.1f}%")

    if elite.captains:
        print("\n  most captained")
        for pid, share in sorted(elite.captains.items(), key=lambda kv: -kv[1])[:5]:
            print(f"    {named(pid):<22}{share:>6.1f}%")

    overall_map = {
        pid: players.get(pid, {}).get("percentSelected", 0.0) for pid in elite.players
    }
    gaps = differentials(elite, overall_map)
    if gaps:
        print("\n  where the top managers disagree with the field")
        for pid, share, overall in gaps[:8]:
            direction = "backing" if share > overall else "avoiding"
            print(f"    {direction:<9}{named(pid):<22}"
                  f"elite {share:>5.1f}%   overall {overall:>5.1f}%")

    if elite.chips:
        print("\n  chips played: " +
              "  ".join(f"{k} {v:.0f}%" for k, v in elite.chips.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
