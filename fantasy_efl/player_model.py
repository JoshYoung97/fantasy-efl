"""Projecting individual players for a gameweek.

Three things have to happen between a player's season totals and a projection:

1. **Shrink the rates.** A defender with six appearances and four blocks is not
   a 0.67-blocks-per-game player. Rates are pulled toward the mean for their
   position and division, weighted by how much evidence there is.

2. **Adjust for the fixture.** Defensive actions rise when a team is under
   pressure and attacking output rises when it is on top, so counting stats are
   scaled by what the market expects of the fixture. This is why the model can
   like a defensive midfielder at a poor club: the same player facing more shots
   accumulates more of the stats this game pays for.

3. **Model the minutes.** The public feed reports appearances, not minutes, and
   counts a five-minute cameo the same as a full match. That conflation is the
   single largest error source in the whole model -- around 0.5 points per
   appearance. It is calibrated here against observed season totals, and can be
   replaced with directly measured splits once weekly snapshot deltas
   accumulate.

Cards are not in the feed at all, so a position-level allowance is subtracted.
That is an assumption, flagged as such, and worth roughly a point a month.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean

from .expected import MinutesModel, PlayerRates, expected_player_points
from .goals import GoalProfile
from .projections import ClubProjection

#: Appearances of evidence needed before a player's own rate outweighs the
#: prior. Low enough to let genuine outliers through by midseason, high enough
#: that a handful of games cannot manufacture one.
#:
#: A single weight for every stat is a simplification. Evidence really
#: accumulates on the count scale, not the appearance scale: 406 clearances
#: pins a rate far more tightly than 5 goals over the same 46 games, so this
#: over-shrinks high-frequency defensive stats and under-shrinks goals. A
#: per-stat weight derived from each stat's dispersion would be better, and is
#: worth revisiting once snapshot deltas give match-level variance to fit it
#: against.
SHRINKAGE_WEIGHT = 8.0

#: Counting stats, split by what drives them. Defensive actions scale with how
#: much pressure a team is under; attacking output with how much it creates.
PRESSURE_STATS = ("clearances", "blocks", "tackles", "interceptions", "saves")
ATTACKING_STATS = ("goalsScored", "assists", "keyPasses", "shotsOnTarget")

#: Yellow and red cards are absent from the feed. These are per-appearance
#: allowances by position, inferred from the gap between predicted and actual
#: season totals. Replace with measured values once deltas allow.
CARD_COST = {"GK": 0.04, "DEF": 0.14, "MID": 0.16, "FWD": 0.10}

#: Share of appearances lasting 60+ minutes, by how established the player is.
#: Calibrated against season totals: assuming every appearance is a full match
#: overstates points by ~0.5 each, and the gap narrows for nailed starters.
START_SHARE = ((40, 0.86), (30, 0.74), (20, 0.66), (0, 0.55))

#: Typical minutes in each branch, used to convert per-appearance rates to
#: the per-90 basis the scoring engine expects.
MINUTES_IF_LONG = 85.0
MINUTES_IF_SHORT = 30.0

SEASON_GAMES = 46

#: Chance a player with no EFL history features at all in a given gameweek.
#:
#: Excluding these players entirely is worse than guessing: a third of the
#: selectable pool has no EFL record -- whole squads at relegated clubs like
#: Burnley and Wolves, and at promoted ones like York City -- and scoring them
#: zero makes them invisible rather than uncertain. Projecting them from their
#: position and division prior at a modest appearance probability keeps them in
#: contention without letting an unknown outrank a proven starter.
#:
#: Self-corrects: once a player has a few appearances, shrinkage hands the
#: weight over to their own record, so this matters for roughly the first two
#: months of the season and then stops mattering at all.
NO_HISTORY_APPEARANCE_PRIOR = 0.45

#: Goalkeepers are far more projectable without a record than outfielders, and
#: the flat prior above badly understates them.
#:
#: Two of a keeper's four scoring terms -- clean sheet and goals conceded --
#: come from the market rather than from the player, so no history is needed
#: for either. The third, save rate, barely varies: across 79 EFL keepers it
#: runs 2.60 per appearance with a standard deviation of 0.41, and correlates
#: only -0.32 with defensive strength. Assuming the league mean therefore costs
#: about a quarter of a point.
#:
#: That leaves only "will they play", and shirt number answers it. Keepers
#: wearing 1 made a median of 32 appearances last season against 8 for every
#: other number. Ignoring that signal projects a first-choice keeper with no
#: EFL record at roughly 2 points when the market-derived figure is nearer 4.7.
FIRST_CHOICE_KEEPER_SHIRT = 1
FIRST_CHOICE_KEEPER_START_PRIOR = 0.85
BACKUP_KEEPER_START_PRIOR = 0.20


def build_priors(players: list[dict]) -> dict[tuple[int, str], dict[str, float]]:
    """Mean per-appearance rate for each (division, position) group.

    Only players with a meaningful sample contribute, so the prior is not
    dragged down by squad players with two appearances.
    """
    groups: dict[tuple[int, str], list[dict]] = {}
    for p in players:
        if p["appearances"] >= 10:
            groups.setdefault((p["competitionId"], p["position"]), []).append(p)

    priors: dict[tuple[int, str], dict[str, float]] = {}
    for key, members in groups.items():
        priors[key] = {
            stat: fmean(m[stat] / m["appearances"] for m in members)
            for stat in PRESSURE_STATS + ATTACKING_STATS + ("cleanSheets",)
        }
    return priors


def _prior_for(player: dict, priors: dict) -> dict[str, float]:
    key = (player["competitionId"], player["position"])
    if key in priors:
        return priors[key]
    # Fall back to the same position in any division -- better than nothing for
    # a player who has just changed level.
    same_position = [v for (_, pos), v in priors.items() if pos == player["position"]]
    if not same_position:
        return {}
    return {
        stat: fmean(p[stat] for p in same_position if stat in p)
        for stat in same_position[0]
    }


def shrunk_rate(total: float, appearances: int, prior: float) -> float:
    """Per-appearance rate pulled toward the prior by the weight of evidence."""
    if appearances <= 0:
        return prior
    return (total + SHRINKAGE_WEIGHT * prior) / (appearances + SHRINKAGE_WEIGHT)


def estimate_minutes(player: dict) -> MinutesModel:
    """How likely the player is to feature, and for how long.

    Availability comes from last season's appearance rate; the split between
    full matches and cameos from the calibrated start share. Injured and
    suspended players are zeroed -- the feed marks them explicitly. Players with
    no EFL record fall back to NO_HISTORY_APPEARANCE_PRIOR rather than zero.
    """
    if player.get("status") in ("injured", "suspended", "eliminated"):
        return MinutesModel(p_60_plus=0.0, p_short=0.0)

    appearances = player["appearances"]

    if not appearances and player.get("position") == "GK":
        # Shirt number is a strong first-choice signal for keepers, and a
        # keeper who plays is projectable almost entirely from the market.
        first_choice = player.get("jerseyNum") == FIRST_CHOICE_KEEPER_SHIRT
        share = (
            FIRST_CHOICE_KEEPER_START_PRIOR if first_choice
            else BACKUP_KEEPER_START_PRIOR
        )
        return MinutesModel(
            p_60_plus=share,
            p_short=0.0,  # keepers are rarely substituted
            mean_minutes_60_plus=90.0,
        )

    p_features = (
        min(appearances / SEASON_GAMES, 1.0)
        if appearances
        else NO_HISTORY_APPEARANCE_PRIOR
    )

    start_share = next(share for threshold, share in START_SHARE if appearances >= threshold)

    return MinutesModel(
        p_60_plus=p_features * start_share,
        p_short=p_features * (1.0 - start_share),
        mean_minutes_60_plus=MINUTES_IF_LONG,
        mean_minutes_short=MINUTES_IF_SHORT,
    )


#: How strongly fixture context is allowed to move a player's rates.
#: 0.0 ignores the fixture entirely; 1.0 scales rates in direct proportion to
#: expected goals.
#:
#: This is the most consequential unvalidated assumption in the model. That
#: defensive actions rise under pressure is well established; the *size* of the
#: effect here is a choice, and it is load-bearing -- at full strength it
#: changes four of the seven optimal picks and the formation compared with
#: switching it off. Half strength is used as the honest midpoint until the
#: relationship can be fitted, which needs match-level data: regress each
#: player's per-match defensive actions on their fixture's expected goals
#: against, once weekly snapshot deltas have accumulated enough gameweeks.
ADJUSTMENT_STRENGTH = 0.5


def _fixture_multipliers(
    profile: GoalProfile, league_average_goals: float
) -> tuple[float, float]:
    """(pressure, attacking) multipliers for this fixture.

    Pressure tracks what the opponent is expected to score, attacking what the
    club itself is. Both are capped -- a heavy favourite still has to defend
    sometimes, and no fixture triples a player's output -- then damped toward 1
    by ADJUSTMENT_STRENGTH.
    """
    if league_average_goals <= 0:
        return 1.0, 1.0
    pressure = _clamp(profile.conceded_rate / league_average_goals)
    attacking = _clamp(profile.scored_rate / league_average_goals)
    return (
        1.0 + (pressure - 1.0) * ADJUSTMENT_STRENGTH,
        1.0 + (attacking - 1.0) * ADJUSTMENT_STRENGTH,
    )


def _clamp(value: float, low: float = 0.6, high: float = 1.6) -> float:
    return max(low, min(high, value))


def deterministic_minutes(minutes: float) -> MinutesModel:
    """A MinutesModel for a player known to play exactly `minutes`.

    Used when team news replaces the estimate. The 60-minute mark is a genuine
    step, not a slope: below it the appearance is worth 1 point and no clean
    sheet can be earned, at or above it the appearance is worth 2 and the clean
    sheet counts. Interpolating across that boundary would be wrong, so callers
    sampling a curve should place points either side of it.
    """
    if minutes <= 0:
        return MinutesModel(p_60_plus=0.0, p_short=0.0)
    if minutes >= 60:
        return MinutesModel(p_60_plus=1.0, p_short=0.0,
                            mean_minutes_60_plus=minutes)
    return MinutesModel(p_60_plus=0.0, p_short=1.0, mean_minutes_short=minutes)


def project_player(
    player: dict,
    fixture: ClubProjection,
    priors: dict,
    *,
    minutes_override: float | None = None,
    league_average_goals: float = 1.3,
) -> float:
    """Expected Fantasy EFL points for one player in one fixture.

    `minutes_override` replaces the estimated minutes with a known figure, for
    when team news is out. Note that the player's own rates are still converted
    to a per-90 basis using their *normal* appearance length -- a player told to
    play 20 minutes does not thereby become a higher-rate player, he simply has
    less time to accumulate.
    """
    minutes = (
        estimate_minutes(player)
        if minutes_override is None
        else deterministic_minutes(minutes_override)
    )
    if minutes.p_appears <= 0:
        return 0.0

    # How long one of this player's appearances typically runs. Derived with
    # availability forced on, because appearance length is a property of the
    # player, not of whether he happens to be fit this week -- otherwise
    # overriding a player who has just been passed fit would use a different
    # basis from an identical team-mate who was never injured.
    natural = estimate_minutes({**player, "status": "playing"})

    prior = _prior_for(player, priors)
    appearances = player["appearances"]
    pressure, attacking = _fixture_multipliers(fixture.profile, league_average_goals)

    # How long this player normally lasts, used to put per-appearance rates on
    # a per-90 basis. Deliberately taken from the natural estimate rather than
    # any override: being told a player starts on the bench for 20 minutes must
    # not silently treble his per-90 rates. A player the estimate says never
    # features has no basis of his own, so a full match is assumed -- otherwise
    # overriding an injured player who has recovered would inflate every rate.
    basis_minutes = MINUTES_IF_LONG
    if natural.p_appears > 0:
        basis_minutes = max(
            (natural.p_60_plus * MINUTES_IF_LONG + natural.p_short * MINUTES_IF_SHORT)
            / natural.p_appears,
            1.0,
        )

    def rate(stat: str, multiplier: float) -> float:
        """Per-90 rate, fixture-adjusted.

        Season totals are per *appearance*, and appearances average well under
        90 minutes, so they are converted to a per-90 basis before the scoring
        engine scales them back down by actual minutes. Skipping this would
        double-count the minutes discount.
        """
        per_appearance = shrunk_rate(
            player.get(stat, 0), appearances, prior.get(stat, 0.0)
        )
        per_90 = per_appearance * 90.0 / basis_minutes
        return per_90 * multiplier

    rates = PlayerRates(
        position=player["position"],
        minutes=minutes,
        goals=rate("goalsScored", attacking),
        assists=rate("assists", attacking),
        key_passes=rate("keyPasses", attacking),
        shots_on_target=rate("shotsOnTarget", attacking),
        clearances=rate("clearances", pressure),
        blocks=rate("blocks", pressure),
        tackles=rate("tackles", pressure),
        interceptions=rate("interceptions", pressure),
        saves=rate("saves", pressure),
        # Straight from the market rather than from the player's history.
        p_clean_sheet=fixture.p_clean_sheet,
        goals_conceded=fixture.profile.conceded_rate,
        yellow_cards=CARD_COST.get(player["position"], 0.12) * 90.0 / MINUTES_IF_LONG,
    )

    return expected_player_points(rates)


@dataclass(frozen=True)
class PlayerProjection:
    """A projected player, with the context needed to explain the number."""

    id: int
    name: str
    position: str
    club: str
    opponent: str
    away: bool
    expected_points: float
    fixtures: int
    selected_pct: float
    status: str
    #: False when the player has no EFL record and is projected from priors
    #: alone -- the number is a placeholder, not a measurement.
    proven: bool = True

    @property
    def label(self) -> str:
        venue = "A" if self.away else "H"
        double = f" x{self.fixtures}" if self.fixtures > 1 else ""
        return f"{self.opponent} ({venue}){double}"
