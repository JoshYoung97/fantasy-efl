"""The full projection pipeline, assembled once.

Snapshot -> goalkeeper backfill -> market prices -> club projections ->
player projections. Both the ranking script and the optimiser need exactly
this, so it lives here rather than being duplicated and drifting apart.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from .club_names import load_mapping
from .expected import ClubOutcome, expected_club_points
from .goals import GoalProfile, match_probabilities
from .fpl_backfill import FplError, apply_backfill, fetch_fpl_players, match_keepers
from .oddsapi import fetch_all_efl
from .player_model import (
    PlayerProjection,
    build_priors,
    expected_minutes,
    project_player,
)
from .projections import ClubProjection, project_all
from .snapshot import list_snapshots, load_snapshot


#: Minutes sampled when building a per-player projection curve.
#:
#: Every minute, rather than a coarser grid, because the curve has two genuine
#: discontinuities and interpolation would smear both: at 0->1 an appearance
#: point appears from nothing, and at 59->60 the appearance doubles and the
#: clean sheet becomes payable. Sampling exhaustively also means the page needs
#: no interpolation logic at all -- the slider value is the index.
#:
#: Costs 91 projections per player at roughly 0.1 ms each, so this is only
#: worth doing for players actually shown with a control.
MINUTES_GRID = tuple(range(91))


@dataclass
class Gameweek:
    """Everything needed to rank or optimise a gameweek."""

    players: list[PlayerProjection]
    clubs: list[ClubProjection]
    backfilled: int
    unproven: int
    ambiguous: list[dict]
    #: Kept so callers can re-project a player at chosen minutes without
    #: rebuilding the whole pipeline.
    raw_by_id: dict = None
    fixtures_by_club: dict = None
    priors: dict = None
    games_played: dict = None

    def expected_minutes(self, player_id: int) -> float:
        """The model's own view of how long a player will be on the pitch."""
        raw = (self.raw_by_id or {}).get(player_id)
        if raw is None:
            return 0.0
        return expected_minutes(raw, (self.games_played or {}).get(raw["squadId"], 0))

    def minutes_curve(self, player_id: int) -> list[float]:
        """Projected points across MINUTES_GRID for one player.

        Lets the published page recalculate when team news lands, without
        reimplementing the scoring distributions in the browser.
        """
        raw = (self.raw_by_id or {}).get(player_id)
        if raw is None:
            return []
        fixture = (self.fixtures_by_club or {}).get(raw["squadId"])
        if fixture is None:
            return []
        played = (self.games_played or {}).get(raw["squadId"], 0)
        return [
            round(
                project_player(
                    raw, fixture, self.priors,
                    minutes_override=m, games_played=played,
                ),
                2,
            )
            for m in MINUTES_GRID
        ]


def override_fixture(
    gw: Gameweek, club_name: str, scored: float, conceded: float
) -> list[ClubProjection]:
    """Replace the market's goal expectations for one fixture.

    `scored` and `conceded` are expected goals for the named club. Everything
    downstream is rebuilt from them: win and draw probabilities, clean sheet,
    the goal thresholds, and the pressure and attacking multipliers applied to
    every player at both clubs.

    Both sides are updated, because a fixture has one scoreline. Saying a club
    is expected to score 2.2 necessarily says its opponent concedes 2.2, and
    leaving the opponent on the market's numbers would let the two disagree
    about the same match.

    Returns the two rebuilt club projections. Raises KeyError if the club is
    not playing this gameweek.
    """
    target = next((c for c in gw.clubs if c.club == club_name), None)
    if target is None:
        raise KeyError(club_name)
    opponent = next(
        (c for c in gw.clubs if c.club == target.opponent and c.opponent == club_name),
        None,
    )
    if opponent is None:
        raise KeyError(f"no opponent found for {club_name}")

    home_rate = conceded if target.away else scored
    away_rate = scored if target.away else conceded
    p_home, p_draw, p_away = match_probabilities(home_rate, away_rate)

    rebuilt = []
    for side, rate_for, rate_against, p_win in (
        (target, scored, conceded, p_away if target.away else p_home),
        (opponent, conceded, scored, p_home if target.away else p_away),
    ):
        profile = GoalProfile(scored_rate=rate_for, conceded_rate=rate_against)
        outcome = ClubOutcome(
            p_win=p_win,
            p_draw=p_draw,
            p_clean_sheet=profile.p_clean_sheet,
            p_scores_2_plus=profile.p_scores_2_plus,
            p_scores_4_plus=profile.p_scores_4_plus,
            away=side.away,
        )
        updated = ClubProjection(
            club=side.club,
            opponent=side.opponent,
            away=side.away,
            expected_points=expected_club_points(outcome),
            p_win=p_win,
            p_draw=p_draw,
            profile=profile,
            source="manual",
        )
        gw.clubs[gw.clubs.index(side)] = updated
        if gw.fixtures_by_club:
            for sid, fixture in gw.fixtures_by_club.items():
                if fixture is side:
                    gw.fixtures_by_club[sid] = updated
        rebuilt.append(updated)

    # Re-project every player whose fixture just changed.
    affected = {c.club for c in rebuilt}
    for index, projection in enumerate(gw.players):
        if projection.club not in affected:
            continue
        raw = (gw.raw_by_id or {}).get(projection.id)
        fixture = next(c for c in rebuilt if c.club == projection.club)
        if raw is None:
            continue
        gw.players[index] = replace(
            projection,
            opponent=fixture.opponent,
            away=fixture.away,
            expected_points=project_player(raw, fixture, gw.priors),
        )

    return rebuilt


def load_gameweek(
    root: Path,
    *,
    use_fpl_backfill: bool = False,
    include_unproven: bool = True,
) -> Gameweek:
    """Build projections for every selectable player and club.

    `include_unproven` keeps players with no EFL record in the pool, projected
    from position and division priors. They are flagged rather than hidden --
    excluding them entirely would drop a third of the selectable squad.

    `use_fpl_backfill` is off because the live FPL API drops relegated clubs
    entirely, so it recovers nobody. See `fpl_backfill` for the detail.
    """
    snapshots = list_snapshots()
    if not snapshots:
        raise RuntimeError("no snapshots yet -- run: python -m fantasy_efl.snapshot")

    raw_players = load_snapshot(snapshots[-1], "players")
    squads = {s["id"]: s["name"] for s in load_snapshot(snapshots[-1], "squads")}

    mapping_path = root / "data" / "club_mapping.json"
    if not mapping_path.exists():
        raise RuntimeError(
            "no club mapping -- run: python scripts/build_club_mapping.py"
        )
    mapping = load_mapping(mapping_path)
    to_efl_name = {odds: efl for efl, odds in mapping.items()}

    backfilled, ambiguous = 0, []
    if use_fpl_backfill:
        try:
            matched, ambiguous = match_keepers(raw_players, fetch_fpl_players())
            backfilled = apply_backfill(raw_players, matched)
        except FplError:
            # The backfill is an enhancement, not a dependency. Losing it costs
            # a handful of goalkeepers, not the run.
            pass

    # How many fixtures each club has completed. The feed shows last
    # season's totals until the new one starts, then rolls over -- so the
    # appearance yardstick has to follow, or every player reads as a fringe
    # squad member until spring.
    games_played: dict[int, int] = {sid: 0 for sid in squads}
    for rnd in load_snapshot(snapshots[-1], "rounds"):
        if rnd.get("gameMode") != "season":
            continue
        for game in rnd.get("games", []):
            if game.get("homeScore") is None:
                continue
            for side in ("homeId", "awayId"):
                if game[side] in games_played:
                    games_played[game[side]] += 1

    club_projections = project_all(fetch_all_efl()[0])
    clubs = [c for cs in club_projections.values() for c in cs]
    # Both sides of the fixture need EFL spellings, or a club and its
    # opponent can appear under different names for the same team.
    for club in clubs:
        object.__setattr__(club, "club", to_efl_name.get(club.club, club.club))
        object.__setattr__(club, "opponent", to_efl_name.get(club.opponent, club.opponent))

    fixtures = {p.club: p for p in clubs}
    # Priors must come from players who actually have a record.
    priors = build_priors([p for p in raw_players if p["appearances"] > 0])

    projected: list[PlayerProjection] = []
    unproven = 0
    for player in raw_players:
        if player.get("status") != "playing":
            continue
        proven = player["appearances"] > 0
        if not proven and not include_unproven:
            continue

        club = squads.get(player["squadId"])
        fixture = fixtures.get(mapping.get(club, ""))
        if fixture is None:
            continue

        if not proven:
            unproven += 1

        projected.append(
            PlayerProjection(
                id=player["id"],
                name=player["displayName"],
                position=player["position"],
                club=club,
                opponent=to_efl_name.get(fixture.opponent, fixture.opponent),
                away=fixture.away,
                expected_points=project_player(
                    player, fixture, priors,
                    games_played=games_played.get(player["squadId"], 0),
                ),
                fixtures=1,
                selected_pct=player.get("percentSelected", 0.0),
                status=player["status"],
                proven=proven or player.get("backfilled") == "fpl",
            )
        )

    return Gameweek(
        players=projected,
        clubs=clubs,
        backfilled=backfilled,
        unproven=unproven,
        ambiguous=ambiguous,
        raw_by_id={p["id"]: p for p in raw_players},
        fixtures_by_club={
            sid: fixtures.get(mapping.get(name, ""))
            for sid, name in squads.items()
            if fixtures.get(mapping.get(name, ""))
        },
        priors=priors,
        games_played=games_played,
    )
