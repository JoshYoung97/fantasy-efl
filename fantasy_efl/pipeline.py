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
from .oddsapi import fetch_all_efl_raw, parse_fixtures
from .player_model import (
    SEASON_GAMES,
    PlayerProjection,
    build_priors,
    expected_minutes,
    project_player,
)
from .projections import ClubProjection, project_all
from .snapshot import list_odds, list_snapshots, load_odds, load_snapshot, save_odds


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
    per_fixture: dict = None

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
        club_fixtures = (self.fixtures_by_club or {}).get(raw["squadId"]) or []
        if not club_fixtures:
            return []
        played = (self.games_played or {}).get(raw["squadId"], 0)
        return [
            round(
                sum(
                    project_player(
                        raw, f, self.priors,
                        minutes_override=m, games_played=played,
                    )
                    for f in club_fixtures
                ),
                2,
            )
            for m in MINUTES_GRID
        ]


def _round_complete(rnd: dict) -> bool:
    """Whether every fixture in a round has been played."""
    games = rnd.get("games") or []
    return bool(games) and all(_is_played(g) for g in games)


#: Counting stats that accumulate through a season and reset with it. Every
#: one of these feeds a scoring rate; the rest of a player record (ownership,
#: status, shirt number) is current-state and must not be added up.
CARRIED_STATS = (
    "appearances", "goalsScored", "assists", "cleanSheets", "saves",
    "clearances", "blocks", "tackles", "interceptions", "keyPasses",
    "shotsOnTarget",
)


def _appearance_total(players: list[dict]) -> int:
    return sum(p.get("appearances") or 0 for p in players)


#: How far total appearances must fall before a drop is read as a new season
#: rather than a bad capture. A real rollover takes every total to zero, so the
#: fall is near-total; requiring at least half guards against a truncated or
#: partially-written snapshot being mistaken for one, which would double-count
#: every stat it did contain.
ROLLOVER_RATIO = 0.5


def _find_season_baseline(snapshots: list, current: list[dict], load=None):
    """The last snapshot taken before the feed rolled over to a new season.

    Season totals only ever grow within a season, so a *fall* in total
    appearances is evidence that the feed has reset. Walking back from the
    newest snapshot, the first one holding substantially more appearances than
    the current feed is the last view of the previous season.

    Returns None when no reset has happened, which is every run until the day
    one does.
    """
    load = load or (lambda s: load_snapshot(s, "players"))
    now = _appearance_total(current)
    for snapshot in reversed(snapshots[:-1]):
        previous = load(snapshot)
        if _appearance_total(previous) * ROLLOVER_RATIO > now:
            return snapshot, previous
    return None


def _merge_history(current: list[dict], previous: list[dict]) -> tuple[list[dict], int]:
    """Add the previous season's totals back onto a reset feed.

    The EFL feed zeroes every counting stat when a new season starts. Taken at
    face value that erases the entire evidence base: on the morning of the
    2026/27 opener every one of 3,453 players read as having no record, so the
    model fell back to position priors for all of them and a 6.61-point
    midfielder projected 1.96.

    Summing the two seasons is the honest default rather than a choice of
    weighting: rates are per-appearance, so a player with 46 previous
    appearances and 3 new ones is simply a player with 49 appearances of
    evidence. Current form takes over as it accumulates, through the same
    shrinkage that already handles a thin sample, with no new parameter to
    guess at.

    The limitation is that it has no notion of recency -- a full new season
    weighs the same as the old one, and a player whose role has changed carries
    the old rate longer than he should. Fixing that needs a decay fitted to
    real data, which is what the delta pipeline is accumulating.
    """
    by_id = {p["id"]: p for p in previous}
    merged, carried = [], 0
    for player in current:
        before = by_id.get(player["id"])
        if not before:
            merged.append(player)
            continue
        combined = dict(player)
        for stat in CARRIED_STATS:
            combined[stat] = (player.get(stat) or 0) + (before.get(stat) or 0)
        merged.append(combined)
        carried += 1
    return merged, carried


def _round_pairs(rnd: dict, squads: dict[int, str]) -> set[tuple[str, str]]:
    """Every (club, opponent) ordered pair the round actually schedules.

    Both directions, so a projection can be checked from either side.
    """
    pairs: set[tuple[str, str]] = set()
    for game in rnd.get("games") or []:
        home = squads.get(game.get("homeId"))
        away = squads.get(game.get("awayId"))
        if home and away:
            pairs.add((home, away))
            pairs.add((away, home))
    return pairs


def _only_this_round(
    clubs: list[ClubProjection], pairs: set[tuple[str, str]]
) -> list[ClubProjection]:
    """Drop projections for fixtures that belong to a later round.

    Club projections are built from every event the odds feed returns, and
    bookmakers price a week or more ahead. Before a round starts that is
    harmless, because only that round is listed. Once a round is under way the
    next one is already priced, and those matches would otherwise be counted as
    extra fixtures in the current gameweek -- on the first live gameweek 20 of
    66 clubs gained a phantom double and their projections roughly doubled.

    Matched on the pair rather than the club, so a genuine double keeps both of
    its fixtures while a next-round match is dropped. An empty `pairs` means
    the round carries no fixtures to check against, and everything is kept
    rather than silently discarding the whole gameweek.
    """
    if not pairs:
        return clubs
    return [c for c in clubs if (c.club, c.opponent) in pairs]


def _combine(name: str, group: list[ClubProjection], scheduled: int) -> ClubProjection:
    """Fold a club's fixtures into one entry for the gameweek.

    Points sum, because a club playing twice scores from both. The remaining
    fields come from the first fixture and are indicative only for a double --
    `fixture_count` is what tells you to read them that way.
    """
    first = group[0]
    if len(group) == 1 and scheduled <= 1:
        return replace(first, fixture_count=1, scheduled_count=max(1, scheduled))
    return replace(
        first,
        opponent=" + ".join(f.opponent for f in group),
        expected_points=sum(f.expected_points for f in group),
        fixture_count=len(group),
        scheduled_count=max(scheduled, len(group)),
    )


def _is_played(game: dict) -> bool:
    """Whether a fixture has actually happened.

    Read from the data, not from a status string. A recorded score is the
    strongest signal; `isFinalized` is accepted as a fallback in case scores
    arrive later than the flag.
    """
    return game.get("homeScore") is not None or bool(game.get("isFinalized"))


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
    if target.fixture_count > 1:
        # Which of the two fixtures the numbers refer to is genuinely
        # ambiguous, and guessing would silently reprice the wrong match.
        raise ValueError(
            f"{club_name} plays {target.fixture_count} times this gameweek; "
            f"overriding a single fixture is not supported"
        )
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
        # Fixture lists are keyed by squad id and by club name; both hold the
        # same objects, so both need the replacement.
        for store in (gw.fixtures_by_club, gw.per_fixture):
            for key, group in (store or {}).items():
                if group and any(f is side for f in group):
                    store[key] = [updated if f is side else f for f in group]
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
        played = (gw.games_played or {}).get(raw["squadId"], 0)
        gw.players[index] = replace(
            projection,
            opponent=fixture.opponent,
            away=fixture.away,
            expected_points=project_player(
                raw, fixture, gw.priors, games_played=played
            ),
        )

    return rebuilt


def load_gameweek(
    root: Path,
    *,
    use_fpl_backfill: bool = False,
    include_unproven: bool = True,
    stored_odds: bool = False,
) -> Gameweek:
    """Build projections for every selectable player and club.

    `include_unproven` keeps players with no EFL record in the pool, projected
    from position and division priors. They are flagged rather than hidden --
    excluding them entirely would drop a third of the selectable squad.

    `use_fpl_backfill` is off because the live FPL API drops relegated clubs
    entirely, so it recovers nobody. See `fpl_backfill` for the detail.

    `stored_odds` replays the most recent saved odds payload instead of
    fetching. Odds move continuously, so two people fetching an hour apart get
    different projections from identical code -- replaying a stored response is
    how a group works from the same numbers, and it needs no API key at all.
    """
    snapshots = list_snapshots()
    if not snapshots:
        raise RuntimeError("no snapshots yet -- run: python -m fantasy_efl.snapshot")

    raw_players = load_snapshot(snapshots[-1], "players")
    squads = {s["id"]: s["name"] for s in load_snapshot(snapshots[-1], "squads")}

    # Carry the previous season's record across a rollover. Without this every
    # player reads as having no history the moment a new season starts, and
    # the whole pool collapses onto position priors.
    carried_players = 0
    baseline = _find_season_baseline(snapshots, raw_players)
    if baseline is not None:
        _, previous_players = baseline
        raw_players, carried_players = _merge_history(raw_players, previous_players)

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
    #
    # Played-ness is derived from the data rather than from a status string.
    # Pre-season every round reads "scheduled" and no other value has ever been
    # observed, so keying off status == "complete" would be guessing at a
    # string that may never appear -- and if it never appears, the gameweek
    # never advances and the season silently freezes on GW1.
    games_played: dict[int, int] = {sid: 0 for sid in squads}
    for rnd in load_snapshot(snapshots[-1], "rounds"):
        if rnd.get("gameMode") != "season":
            continue
        for game in rnd.get("games", []):
            if not _is_played(game):
                continue
            for side in ("homeId", "awayId"):
                if game[side] in games_played:
                    games_played[game[side]] += 1

    # The appearance yardstick has to cover the same span as the appearances.
    # Having merged a full previous campaign into every total, a club that has
    # played once this season has 47 games behind it, not 1 -- otherwise a
    # regular reads as having featured 46 times in 1 game.
    if carried_players:
        games_played = {sid: n + SEASON_GAMES for sid, n in games_played.items()}

    if stored_odds:
        stored = list_odds()
        if not stored:
            raise RuntimeError(
                "no stored odds -- run once with live odds first, or pull them "
                "from the repo"
            )
        raw = load_odds(stored[-1])
    else:
        raw, _ = fetch_all_efl_raw()
        save_odds(raw)
    club_projections = project_all(
        {division: parse_fixtures(payload) for division, payload in raw.items()}
    )
    clubs = [c for cs in club_projections.values() for c in cs]
    # Both sides of the fixture need EFL spellings, or a club and its
    # opponent can appear under different names for the same team.
    for club in clubs:
        object.__setattr__(club, "club", to_efl_name.get(club.club, club.club))
        object.__setattr__(club, "opponent", to_efl_name.get(club.opponent, club.opponent))

    # How many fixtures each club is scheduled for this gameweek. A club
    # playing twice scores from both, so the projection has to cover both --
    # and where the market has priced only one, that shortfall is reported
    # rather than passed off as a complete gameweek.
    upcoming = min(
        (r for r in load_snapshot(snapshots[-1], "rounds")
         if r.get("gameMode") == "season" and not _round_complete(r)),
        key=lambda r: r["roundNumber"],
        default=None,
    )
    scheduled: dict[str, int] = {}
    if upcoming:
        for game in upcoming.get("games", []):
            for side in ("homeId", "awayId"):
                name = squads.get(game[side])
                if name:
                    scheduled[name] = scheduled.get(name, 0) + 1

    if upcoming:
        clubs = _only_this_round(clubs, _round_pairs(upcoming, squads))

    # Per-fixture projections, grouped by club. Mapping straight into a dict
    # keyed on club name would keep only the last fixture and silently drop
    # the other half of a double gameweek.
    per_fixture: dict[str, list[ClubProjection]] = {}
    for projection in clubs:
        per_fixture.setdefault(projection.club, []).append(projection)

    clubs = [
        _combine(name, group, scheduled.get(name, len(group)))
        for name, group in per_fixture.items()
    ]
    fixtures = per_fixture
    # Priors must come from players who actually have a record.
    played_so_far = max(games_played.values(), default=0)
    priors = build_priors(
        [p for p in raw_players if p["appearances"] > 0], played_so_far
    )

    projected: list[PlayerProjection] = []
    unproven = 0
    for player in raw_players:
        if player.get("status") != "playing":
            continue
        proven = player["appearances"] > 0
        if not proven and not include_unproven:
            continue

        club = squads.get(player["squadId"])
        # Keyed by EFL name, because the projections were renamed to EFL
        # spellings above. Looking up by the bookmaker name silently drops
        # every club whose two names differ -- seven of them, and all of
        # their players with them.
        club_fixtures = fixtures.get(club)
        if not club_fixtures:
            continue

        if not proven:
            unproven += 1

        projected.append(
            PlayerProjection(
                id=player["id"],
                name=player["displayName"],
                position=player["position"],
                club=club,
                # Already EFL spellings, renamed with the club above.
                opponent=" + ".join(f.opponent for f in club_fixtures),
                away=club_fixtures[0].away,
                # A player whose club plays twice accumulates from both.
                expected_points=sum(
                    project_player(
                        player, f, priors,
                        games_played=games_played.get(player["squadId"], 0),
                    )
                    for f in club_fixtures
                ),
                fixtures=len(club_fixtures),
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
            sid: fixtures.get(name)
            for sid, name in squads.items()
            if fixtures.get(name)
        },
        per_fixture=per_fixture,
        priors=priors,
        games_played=games_played,
    )
