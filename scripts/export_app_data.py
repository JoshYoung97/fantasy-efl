"""Export current projections to data/app_data.json for the web page.

    python scripts/export_app_data.py [--stored-odds] [--ags-all]

Costs 3 Odds API credits, unless --stored-odds replays the most recently
saved odds payload instead -- no key needed, and it's how a group works from
the same numbers rather than everyone fetching an hour apart and getting
different projections from identical code. Run before each gameweek
deadline, then `build_app.py` to regenerate the page.

--ags-all seeds every matched, priced anytime-goalscorer entry regardless of
`confirmed` status, using each player's own raw price with no team-level
reconciliation (see build_goal_seeds_unreconciled in goalscorer_odds.py).
Default (off) is the safer per-player-confirmed, team-reconciled path
(build_goal_seeds) -- wait for real lineups, same as every other gameweek.
Turn it on to sanity-check a wider pool of players against their bookmaker
price ahead of lineups being announced.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fantasy_efl.elite import load as load_elite  # noqa: E402
from fantasy_efl.expected import (  # noqa: E402
    DEFAULT_DISPERSION,
    expected_player_points,
)
from fantasy_efl.goalscorer_odds import (  # noqa: E402
    apply_seed,
    build_assist_seeds,
    build_goal_seeds,
    build_goal_seeds_unreconciled,
    build_shots_on_target_seeds,
    load_entries,
    match_players,
)
from fantasy_efl.optimiser import optimise_gameweek  # noqa: E402
from fantasy_efl.pipeline import load_gameweek  # noqa: E402
from fantasy_efl.player_model import player_rates  # noqa: E402
from fantasy_efl.snapshot import (  # noqa: E402
    list_snapshots,
    load_snapshot,
    round_complete,
)

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "data" / "app_data.json"

#: Manually-entered player-prop prices (goals, assists, shots on target),
#: read if present. Absent by default -- this is a manual, occasional input
#: (see goalscorer_odds.py for why it stays that way), not something every
#: run needs.
SCORER_ODDS = ROOT / "data" / "scorer_odds.csv"

#: PlayerRates field name for each seed, keyed by the same short names used
#: in the pool row's `seeds` dict and log output.
SEED_FIELDS = {"goals": "goals", "assists": "assists", "sot": "shots_on_target"}

#: Ownership below which an unrateable player is not worth flagging.
BLIND_SPOT_OWNERSHIP = 5.0

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

#: Division codes, from the EFL's own competition ids. The page colours rows
#: by these using the palette taken from the official division marks: gold for
#: the Championship, silver for League One, red for League Two.
DIVISION_CODE = {10: "CH", 11: "L1", 12: "L2"}

#: Rate fields, in a fixed order, sent as a positional array rather than an
#: object per fixture.
#:
#: Naming every field on every fixture spent 38% of the pool payload on
#: repeated keys alone. A shared key list plus arrays of numbers carries the
#: same information for a fraction of the bytes, which is what lets every
#: player stay in the export -- cutting the pool to the highest-projected few
#: shrinks the file but makes most of the game unsearchable, and being unable
#: to look up a player is worse than a larger download.
RATE_KEYS = (
    "goals", "assists", "ownGoals", "penaltiesMissed", "yellowCards",
    "redCards", "saves", "penaltiesSaved", "pCleanSheet", "goalsConceded",
    "clearances", "blocks", "tackles", "interceptions", "keyPasses",
    "shotsOnTarget",
)


def _rate_fields(rates) -> dict:
    """A PlayerRates as a JSON-safe dict of just the scoring inputs.

    Ships the fixture-adjusted rate the model actually used for every stat
    the scoring engine reads, so a page can let someone override any one of
    them individually -- not just expected minutes -- and recompute
    correctly. `xp` is the model's own total for this fixture at these
    rates, included so the page's ported scoring logic can be checked
    against it: if nothing has been overridden, they must match exactly.
    """
    return {
        "goals": round(rates.goals, 4),
        "assists": round(rates.assists, 4),
        "ownGoals": round(rates.own_goals, 4),
        "penaltiesMissed": round(rates.penalties_missed, 4),
        "yellowCards": round(rates.yellow_cards, 4),
        "redCards": round(rates.red_cards, 4),
        "saves": round(rates.saves, 4),
        "penaltiesSaved": round(rates.penalties_saved, 4),
        "pCleanSheet": round(rates.p_clean_sheet, 4),
        "goalsConceded": round(rates.goals_conceded, 4),
        "clearances": round(rates.clearances, 4),
        "blocks": round(rates.blocks, 4),
        "tackles": round(rates.tackles, 4),
        "interceptions": round(rates.interceptions, 4),
        "keyPasses": round(rates.key_passes, 4),
        "shotsOnTarget": round(rates.shots_on_target, 4),
        "xp": round(expected_player_points(rates), 4),
    }


def _rate_values(rates) -> list[float]:
    """The same rates as a positional array, ordered by RATE_KEYS.

    Three decimals, and exact zeros as integers. Rates only matter to this
    precision once something is overridden -- an untouched player shows the
    model's own figure -- and 37% of these values are zero, because a defender
    records no saves and a forward no clearances.
    """
    fields = _rate_fields(rates)
    out = []
    for key in RATE_KEYS:
        value = round(fields[key], 3)
        out.append(0 if value == 0 else value)
    return out


def _pool(gw, kickoffs, divisions: dict[int, str], elite=None, scorer_seeds=None) -> list[dict]:
    """Every selectable player, with fixture-adjusted rates for each fixture.

    `gw.players` is restricted to status == "playing" because the optimiser
    must never pick an injured or suspended player -- but a page that lets
    someone override "the club say he's actually fit" needs that player's
    row and rates to override, not an absence. Only "eliminated" (no longer
    in Fantasy EFL's pool at all -- retired, dropped out of the EFL) is left
    out here.

    One row per player, each carrying a list of fixtures rather than one
    rate set, so a club playing twice in the gameweek is represented
    completely: the page sums across a player's fixtures the same way
    `project_player` does.

    `scorer_seeds` is {"goals": {player_id: goals90}, "assists": {...},
    "sot": {...}}, from build_goal_seeds/build_assist_seeds/
    build_shots_on_target_seeds in goalscorer_odds.py -- each replaces the
    model's own rate for that one stat where a confirmed, matched price
    exists, independently of the other two. Applied to every fixture a
    player has this gameweek alike -- a real simplification for the rare
    case of a double gameweek priced from a single-fixture entry, on the
    same "loose is fine here" basis as the rest of that module.
    """
    scorer_seeds = scorer_seeds or {}
    rows = []
    for player in gw.raw_by_id.values():
        if player.get("status") == "eliminated":
            continue
        club_fixtures = gw.fixtures_by_club.get(player["squadId"])
        if not club_fixtures:
            continue

        games_played = gw.games_played.get(player["squadId"], 0)
        player_seeds = {
            SEED_FIELDS[key]: seeds[player["id"]]
            for key, seeds in scorer_seeds.items()
            if player["id"] in seeds
        }
        fixtures = []
        for f in club_fixtures:
            rates = player_rates(player, f, gw.priors, games_played=games_played)
            for field, value in player_seeds.items():
                rates = apply_seed(rates, field, value)
            fixtures.append({
                "opp": f.opponent,
                "away": f.away,
                "kickoff": kickoffs.get(f.club),
                "tier": f.difficulty,
                "xp": _rate_fields(rates)["xp"],
                "r": _rate_values(rates),
            })

        rows.append({
            "id": player["id"],
            "div": divisions.get(player["squadId"], ""),
            # Ownership among the top-ranked managers, where it has been
            # collected. Absent rather than zero when it has not, so the
            # page can tell "they avoid him" from "we cannot see yet".
            "elite": (elite.players.get(player["id"]) if elite and elite.usable else None),
            "eliteC": (elite.captains.get(player["id"]) if elite and elite.usable else None),
            "name": player["displayName"],
            "pos": player["position"],
            "club": club_fixtures[0].club,
            "status": player.get("status", "playing"),
            "proven": player["appearances"] > 0 or player.get("backfilled") == "fpl",
            "own": player.get("percentSelected", 0.0),
            # Where the minutes control should start: the model's own
            # estimate, which sharpens as the season supplies appearances.
            # Starting at 90 would quietly assert every player goes the
            # distance; injured/suspended players correctly start at 0 but
            # remain fully overridable.
            "xmins": round(gw.expected_minutes(player["id"])),
            "fixtures": fixtures,
        })
    return rows


def main() -> int:
    stored_odds = "--stored-odds" in sys.argv
    ags_all = "--ags-all" in sys.argv
    try:
        gw = load_gameweek(ROOT, stored_odds=stored_odds)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    squad = optimise_gameweek(gw.players, gw.clubs)
    if squad is None:
        print("no legal squad could be built", file=sys.stderr)
        return 1

    snapshot = list_snapshots()[-1]
    rounds = load_snapshot(snapshot, "rounds")
    squad_rows = load_snapshot(snapshot, "squads")
    squads = {s["id"]: s["name"] for s in squad_rows}
    divisions = {
        s["id"]: DIVISION_CODE.get(s.get("competitionId"), "")
        for s in squad_rows
    }
    division_by_name = {s["name"]: divisions[s["id"]] for s in squad_rows}

    # Playoff rounds reuse the same round numbers as gameweeks and carry no
    # fixtures, so they interleave with the real schedule unless filtered out.
    season_rounds = [r for r in rounds if r.get("gameMode") == "season"]

    # Played-ness from the data, never from the status string. The feed says
    # "completed", not "complete", so this comparison never matched and the
    # page stayed on GW1 permanently -- publishing GW1's name, deadline and
    # kickoff times against the pipeline's GW2 fixtures. Every player then
    # read as locked, because GW1's kickoffs are in the past.
    upcoming = min(
        (r for r in season_rounds if not round_complete(r)),
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

    elite = load_elite()

    scorer_seeds = {}
    if SCORER_ODDS.exists():
        roster = [
            {"id": p["id"], "displayName": p["displayName"], "club": squads.get(p["squadId"], "")}
            for p in gw.raw_by_id.values()
        ]
        entries = load_entries(SCORER_ODDS)
        matches = match_players(entries, roster)
        team_expected_goals = {c.club: c.profile.scored_rate for c in gw.clubs}

        # Goals: --ags-all seeds every matched, priced entry regardless of
        # confirmed status, unreconciled against the team total (see
        # build_goal_seeds_unreconciled's docstring for why those two go
        # together). Default is the normal confirmed+reconciled path --
        # wait for real lineups, same as any other gameweek.
        sparse_goal_clubs: dict[str, int] = {}
        if ags_all:
            goal_seeds = build_goal_seeds_unreconciled(matches, require_confirmed=False)
        else:
            goal_result = build_goal_seeds(matches, team_expected_goals)
            goal_seeds = goal_result.seeds
            sparse_goal_clubs = goal_result.sparse_clubs
        assist_result = build_assist_seeds(matches, team_expected_goals)
        sot_seeds = build_shots_on_target_seeds(matches)
        scorer_seeds = {"goals": goal_seeds, "assists": assist_result.seeds, "sot": sot_seeds}

        unusable = [m for m in matches if m.player_id is None or m.ambiguous]
        if unusable:
            print(f"  {len(unusable)} of {len(entries)} scorer-odds entries unmatched or "
                  f"ambiguous -- see goalscorer_odds.match_players")
        unconfirmed = [m for m in matches if m.player_id is not None and not m.ambiguous and not m.entry.confirmed]
        if unconfirmed and not ags_all:
            print(f"  {len(unconfirmed)} matched entries not yet confirmed -- predicted lineups "
                  f"aren't used to seed the model (see goalscorer_odds.py)")
        if ags_all:
            print(f"  --ags-all: goals seeded from every matched priced entry, "
                  f"ignoring confirmed status and team reconciliation")
        print(f"  seeded: {len(goal_seeds)} goals, {len(assist_result.seeds)} assists, "
              f"{len(sot_seeds)} shots on target")
        for stat, sparse in (("goals", sparse_goal_clubs), ("assists", assist_result.sparse_clubs)):
            for club, count in sparse.items():
                print(f"  WARNING: only {count} priced player(s) for {club} ({stat}) -- "
                      f"reconciliation attributes the whole team's total across just them, "
                      f"which overstates their share. Price more of the likely contributors.")

    pool = _pool(gw, kickoffs, divisions, elite, scorer_seeds)

    # Highly-owned players the model cannot rate -- the gap worth knowing about.
    blind = sorted(
        (row for row in pool if not row["proven"] and row["own"] >= BLIND_SPOT_OWNERSHIP),
        key=lambda row: -row["own"],
    )

    payload = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "gameweek": upcoming["name"],
        "deadline": upcoming["lockoutDate"],
        "squad": {
            "formation": squad.formation,
            # ids into `pool`, not copies -- the page looks the row up so a
            # squad member's edits and their pool-row edits are the same edit.
            "playerIds": [p.id for p in squad.players],
            "captain": squad.captain.id,
            "vice": squad.vice_captain.id if squad.vice_captain else None,
            "clubs": [
                {"name": c.club, "opp": c.opponent, "away": c.away,
                 "xp": round(c.expected_points, 2),
                 "kickoff": kickoffs.get(c.club),
                 "tier": c.difficulty,
                "div": division_by_name.get(c.club, ""),
                "fx": c.fixture_count, "sched": c.scheduled_count}
                for c in squad.clubs
            ],
            "total": round(squad.expected_points, 2),
        },
        "pool": pool,
        "rateKeys": list(RATE_KEYS),
        "elite": {"sample": elite.sample, "roundId": elite.round_id,
                  "collectedAt": elite.collected_at,
                  "usable": elite.usable},
        "dispersion": DEFAULT_DISPERSION,
        "clubs": [
            {
                "name": c.club,
                "opp": c.opponent,
                "away": c.away,
                "xp": round(c.expected_points, 2),
                "win": round(c.p_win, 3),
                "draw": round(c.p_draw, 3),
                "cs": round(c.profile.p_clean_sheet, 3),
                # Over 1.5 goals is the 2+ term; over 3.5 is the 4+ term.
                "o15": round(c.profile.p_scores_2_plus, 3),
                "o35": round(c.profile.p_scores_4_plus, 3),
                "outlook": fixture_counts.get(squad_ids.get(c.club, -1), []),
                "kickoff": kickoffs.get(c.club),
                "tier": c.difficulty,
                "div": division_by_name.get(c.club, ""),
                "fx": c.fixture_count,
                "sched": c.scheduled_count,
            }
            for c in sorted(gw.clubs, key=lambda c: -c.expected_points)
        ],
        "outlook_weeks": [r["shortName"] for r in outlook_rounds],
        "stats": {"pool": len(pool), "selectable": len(gw.players),
                  "unproven": gw.unproven},
        "blindspots": [
            {"name": row["name"], "club": row["club"], "pos": row["pos"], "own": row["own"]}
            for row in blind[:8]
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
