"""The best legal squad for the coming gameweek.

    python scripts/optimal_team.py [--one-club] [--proven-only]

Combines snapshot rates with live market prices, projects every selectable
player, then solves for the highest-scoring legal seven plus two clubs.

Players with no EFL record are included by default, projected from position and
division priors and marked with a dagger. They are estimates rather than
measurements -- use --proven-only to exclude them.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fantasy_efl.optimiser import optimise_gameweek  # noqa: E402
from fantasy_efl.pipeline import load_gameweek, override_fixture  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def parse_odds(spec):
    """Parse CLUB=FOR/AGAINST into (club, scored, conceded).

    Returns None on anything malformed. Expected goals rather than
    probabilities, because that is what the model actually takes -- and a
    scoreline expectation is easier to reason about than a de-vigged
    three-way price.
    """
    club, _, rates = spec.partition("=")
    scored, _, conceded = rates.partition("/")
    if not club or not scored or not conceded:
        return None
    try:
        scored, conceded = float(scored), float(conceded)
    except ValueError:
        return None
    if not (0 <= scored <= 8) or not (0 <= conceded <= 8):
        return None
    return club.strip(), scored, conceded


def resolve_club(gw, needle):
    """Find exactly one club whose name contains `needle`, or report why not."""
    hits = [c for c in gw.clubs if needle.casefold() in c.club.casefold()]
    if not hits:
        print(f"error: no club matched {needle!r}", file=sys.stderr)
        return None
    if len(hits) > 1:
        print(f"error: {needle!r} is ambiguous:", file=sys.stderr)
        for c in hits[:8]:
            print(f"    {c.club}", file=sys.stderr)
        return None
    return hits[0]


def apply_exclusions(players, names):
    """Drop players matching the given names, case-insensitively.

    Matches on any part of the name or club, so "Wing", "l. wing" and "Reading"
    all work -- team news arrives as surnames, not as feed-formatted strings.
    An ambiguous or unmatched name aborts rather than silently dropping the
    wrong player or nobody at all; on the day, a quietly ignored exclusion
    would be worse than an error.
    """
    dropped, remaining = [], list(players)

    for needle in names:
        query = needle.casefold()
        hits = [
            p for p in remaining
            if query in p.name.casefold() or query in p.club.casefold()
        ]
        if not hits:
            print(f"error: nothing matched {needle!r}", file=sys.stderr)
            return None, players
        if len(hits) > 1:
            print(f"error: {needle!r} is ambiguous:", file=sys.stderr)
            for p in sorted(hits, key=lambda p: -p.expected_points)[:8]:
                print(f"    {p.name} ({p.club}, {p.position}) "
                      f"{p.expected_points:.2f}", file=sys.stderr)
            print("  be more specific", file=sys.stderr)
            return None, players

        dropped.append(hits[0])
        remaining = [p for p in remaining if p.id != hits[0].id]

    return dropped, remaining


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--one-club", action="store_true",
                        help="play the One Club chip (lifts the 2-per-club limit)")
    parser.add_argument("--proven-only", action="store_true",
                        help="exclude players with no EFL record")
    parser.add_argument("--fpl", action="store_true",
                        help="attempt the FPL goalkeeper backfill (see fpl_backfill: "
                             "the live API drops relegated clubs, so this finds nobody)")
    parser.add_argument("--exclude", nargs="+", metavar="NAME", default=[],
                        help="drop players before solving, e.g. --exclude Wing Clarke. "
                             "Use once team news confirms someone is benched or injured.")
    parser.add_argument("--odds", nargs="+", metavar="CLUB=FOR/AGAINST", default=[],
                        help="override expected goals for a fixture, e.g. "
                             "--odds Swindon=1.4/0.6. Rebuilds clean sheet, club "
                             "points and both clubs' players from your numbers.")
    args = parser.parse_args()

    try:
        gw = load_gameweek(
            ROOT,
            use_fpl_backfill=args.fpl,
            include_unproven=not args.proven_only,
        )
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    note = [f"{len(gw.players)} players"]
    if gw.backfilled:
        note.append(f"{gw.backfilled} keepers backfilled from FPL")
    if gw.unproven:
        note.append(f"{gw.unproven} unproven (dagger)")
    print("  ".join(note))
    if gw.ambiguous:
        print(f"  {len(gw.ambiguous)} keeper names too ambiguous to match, skipped")
    print()

    # Odds overrides first: they change player projections, so they must land
    # before anything reads the pool.
    for spec in args.odds:
        parsed = parse_odds(spec)
        if parsed is None:
            print(f"error: could not read {spec!r}, expected CLUB=FOR/AGAINST "
                  f"such as Swindon=1.4/0.6", file=sys.stderr)
            return 1
        needle, scored, conceded = parsed
        club = resolve_club(gw, needle)
        if club is None:
            return 1

        was = club.expected_points
        was_cs = club.p_clean_sheet
        rebuilt = override_fixture(gw, club.club, scored, conceded)
        now = rebuilt[0]
        print(f"override: {now.club} v {now.opponent} -- "
              f"{scored:.2f} scored, {conceded:.2f} conceded")
        print(f"          club pts {was:.2f} -> {now.expected_points:.2f}   "
              f"clean sheet {was_cs:.0%} -> {now.p_clean_sheet:.0%}")
    if args.odds:
        print()

    baseline = None
    pool = gw.players
    if args.exclude:
        dropped, pool = apply_exclusions(pool, args.exclude)
        if dropped is None:
            return 1
        # Solve the unrestricted squad too, so the cost of the news is visible.
        baseline = optimise_gameweek(gw.players, gw.clubs, one_club_chip=args.one_club)
        print("excluded: " + ", ".join(f"{p.name} ({p.club})" for p in dropped) + "\n")

    started = time.perf_counter()
    squad = optimise_gameweek(pool, gw.clubs, one_club_chip=args.one_club)
    elapsed = time.perf_counter() - started

    if squad is None:
        print("no legal squad could be built", file=sys.stderr)
        return 1

    chip = "  [ONE CLUB CHIP]" if args.one_club else ""
    print(f"OPTIMAL SQUAD -- formation {squad.formation}{chip}")
    print(f"  {'':<3}{'player':<21}{'club':<25}{'fixture':<22}{'xPts':>6}{'owned':>8}")
    print("  " + "-" * 85)

    order = {"GK": 0, "DEF": 1, "MID": 2, "FWD": 3}
    for p in sorted(squad.players, key=lambda x: (order[x.position], -x.expected_points)):
        mark = "(C)" if p.id == squad.captain.id else (
            "(V)" if squad.vice_captain and p.id == squad.vice_captain.id else "")
        name = p.name + ("" if p.proven else " †")
        print(f"  {mark:<3}{name:<21}{p.club:<25}{p.label:<22}"
              f"{p.expected_points:>6.2f}{p.selected_pct:>7.1f}%")

    print(f"\n  {'':<3}{'CLUBS':<21}")
    for c in squad.clubs:
        venue = "A" if c.away else "H"
        print(f"  {'':<3}{'':<21}{c.club:<25}{c.opponent + ' (' + venue + ')':<22}"
              f"{c.expected_points:>6.2f}")

    players_total = sum(p.expected_points for p in squad.players)
    clubs_total = sum(c.expected_points for c in squad.clubs)
    print(f"\n  players {players_total:>6.2f}"
          f"  + captain {squad.captain.expected_points:>5.2f}"
          f"  + clubs {clubs_total:>5.2f}"
          f"  = {squad.expected_points:.2f}")
    if any(not p.proven for p in squad.players):
        print("  † projected from priors -- no EFL record yet")

    if baseline is not None:
        cost = baseline.expected_points - squad.expected_points
        print(f"\n  cost of the news: {cost:.2f} pts "
              f"(was {baseline.expected_points:.2f})")
        before = {p.id for p in baseline.players}
        now = {p.id for p in squad.players}
        promoted = [p for p in squad.players if p.id not in before]
        if promoted:
            print("  brought in: " + ", ".join(
                f"{p.name} ({p.club}) {p.expected_points:.2f}" for p in promoted))
        lost = [p for p in baseline.players if p.id not in now]
        if lost:
            print("  dropped   : " + ", ".join(f"{p.name}" for p in lost))
        if baseline.captain.id != squad.captain.id:
            print(f"  captain moves to {squad.captain.name}")

    print(f"  solved in {elapsed:.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
