"""Converting manually-entered player-prop prices into expected-points seeds.

The market for a player scoring, assisting or hitting the target anytime
prices something the season-totals feed cannot see: this player, this
fixture, informed by whatever the book knows about form, fitness and
tactical role. Kept manual rather than scraped -- see "What this
deliberately does not attempt" below -- entries are typed in by hand from
Oddschecker or a single book, one row per player per fixture, carrying
whichever of the three markets were priced for them.

All three markets -- Anytime Goalscorer, Player Assists Over 0.5, Player
Shots On Target Over 0.5 -- share the same price structure (an implied
probability of at least one occurrence), so the same conversion applies to
all three:

1. Poisson invert. `P(at least one) = 1 - e^-lambda`, so
   `lambda = -ln(1 - p)`, the same Poisson family `goals.py` already uses
   for clubs. `p` here is the raw, un-devigged implied probability.

2. Reconcile against a team total, for goals and assists only. Anytime
   markets are not a partition -- two players can both score -- so the
   usual "make probabilities sum to 1" de-vig does not apply. Instead, the
   correction *is* rescaling every player's raw lambda so they sum to a
   team total computed independently:
     - goals: the team's own modelled expected goals (from `goals.py`),
       minus a small allowance for goals the market cannot see at all --
       own goals, credited to nobody's own price.
     - assists: the same team expected-goals figure, scaled down by
       `ASSIST_SHARE_OF_GOALS` -- not every goal is assisted (some are
       penalties, own goals, or solo efforts).
   Shots on target has no independent team-level target to reconcile
   against (`goals.py` derives win/draw/clean-sheet/goals from the 1X2
   market alone, not a shots market), so it is a straight, non-reconciled
   read -- see `build_shots_on_target_seeds`.

3. Rebase onto a per-90 figure. The price already reflects the market's own
   view of how long this player is likely to play -- it is not a per-90
   rate. `export_app_data.py`'s page multiplies every rate by minutes/90
   (see `pointsGivenMinutes` in `build_app.py`), so feeding a whole-match
   figure straight in would discount it a second time. Dividing by the same
   assumed minutes here cancels that out.

What this deliberately does not attempt:

- **Cards.** Oddschecker does have a "To Be Shown A Card" market, but its
  price structure wasn't confirmed while building this (the section did not
  render cleanly on inspection). Worth adding once actually verified rather
  than guessed at.
- **Substitute-scored goals/assists.** Only a problem if entries are limited
  to the starting XI. Price the bench too (bookmakers usually do, once
  lineups are out) and it is not a separate correction at all -- a
  substitute's own price already carries "comes on and contributes".
- **A precise own-goal rate or assist share.** The feed carries no own-goal
  or assist-attribution field for any player (checked directly against
  `players.json`'s fields), so there is nothing to calibrate
  `OWN_GOAL_ALLOWANCE` or `ASSIST_SHARE_OF_GOALS` against, the way
  `CARD_COST` was calibrated from a real season. Both are placeholder
  external estimates, flagged as such.
- **Automated collection.** Oddschecker and bet365 both actively resist
  scraping (JS-rendered tables behind bot detection, and their terms
  restrict it), and the volume that actually matters -- a squad plus a
  handful of watchlist players, once a week -- does not come close to
  justifying the fragility. Manual entry is the considered choice here, not
  a placeholder for automation later.

Pricing too few of a team's realistic scorers is a real trap, not a
theoretical one -- found it by hand while testing this module. Reconciliation
attributes the WHOLE team target across however many players are priced, so
one entry for a lone favourite striker makes him absorb his entire team's
worth of expected goals (one real test case: a single midfielder came out at
1.87 expected goals per 90 and 16.9 points for one match). `build_goal_seeds`
and `build_assist_seeds` still produce a number below `MIN_PRICED_PER_CLUB`
-- a real, incomplete price is still better than the model's own guess for
the players it does cover -- but flag it via `SeedResult.sparse_clubs`, and
`export_app_data.py` prints a warning for it. Price most of a team's
attacking threat, not just one player, or trust the warning when you cannot.
Shots on target has no reconciliation step, so this trap does not apply to
it.

Only entries with a *confirmed* lineup are used to seed the model. A
predicted lineup's price is blended: it reflects both this player's rate if
he plays and the market's own uncertainty about whether he starts at all,
and there is no way to cleanly separate those out of a single price.
`player_model.py`'s `MinutesModel` already owns "probability of playing" --
feeding a blended price into a rate would double count that uncertainty,
once from the market price and again from the model's own estimate.
Predicted-but-unconfirmed entries are still matched and reported
(`PlayerMatch.entry.confirmed` says which), so a predicted lineup is visible
without being trusted as a clean rate.
"""

from __future__ import annotations

import csv
import math
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path

from .club_names import similarity
from .player_model import MINUTES_IF_LONG, MINUTES_IF_SHORT

#: Expected goals a team benefits from via an opponent's own goal, per match.
#: See "What this deliberately does not attempt" above -- not measured,
#: because nothing in the feed can measure it against.
OWN_GOAL_ALLOWANCE = 0.03

#: Share of a team's goals that are credited to an assist -- the rest are
#: penalties, own goals (the opponent's, not this team's), or unassisted
#: individual efforts. An external, unmeasured estimate, same basis as
#: OWN_GOAL_ALLOWANCE -- there is no assist field in the feed to calibrate
#: against.
ASSIST_SHARE_OF_GOALS = 0.65

#: Below this a price is treated as unpriced. A long-odds line on a fringe
#: bench player is noisy, and division by (1 - p) blows up as p approaches 1
#: -- not a real risk here, but 1.01 is also just not a price worth trusting
#: to two decimal places either way.
MIN_ODDS = 1.01

#: Below this the best name match is treated as no match at all, and above
#: it but within AMBIGUITY_MARGIN of the runner-up it is flagged rather than
#: guessed at. Same values and reasoning as club_names.py.
MIN_SCORE = 0.72
AMBIGUITY_MARGIN = 0.08

#: Below this many priced players for one club, reconciliation (goals or
#: assists) is flagged as sparse rather than trusted quietly.
#:
#: Reconciliation attributes the ENTIRE team target across however many
#: players are priced -- correct given what it is told, but if that is one
#: favourite striker, he silently absorbs a whole team's worth of expected
#: goals. Found this by feeding the module a single test entry for Reading:
#: one midfielder came out at 1.87 expected goals per 90 and 16.9 points for
#: one match, because reconcile_team had nowhere else to put the rest of
#: Reading's total. Not a bug -- the arithmetic did exactly what a one-player
#: input asked for -- but exactly the trap worth a loud warning rather than a
#: quietly wrong number. Four is a guess at "enough of the realistic scoring
#: threats to not obviously be missing most of them", not a measured figure.
MIN_PRICED_PER_CLUB = 4

CSV_FIELDS = (
    "player", "club", "lineup_status", "confirmed", "captured_at", "bookmaker",
    "goal_odds", "assist_odds", "sot_odds",
)


@dataclass(frozen=True)
class ScorerEntry:
    """One manually-entered player's prices for one fixture.

    `player` and `club` are written however the odds source spells them --
    matching against the roster is `match_players`'s job, not the entry's.
    Each `*_odds` field is the raw decimal price for that market, or `None`
    if that market wasn't priced for this player: not every market covers
    every player (bench options often miss the shots-on-target line, for
    instance), and a row only needs whichever prices were actually found.
    The conversion belongs in code, run consistently, not redone by hand for
    every player.
    """

    player: str
    club: str
    lineup_status: str  # "start" | "bench" | "out"
    confirmed: bool
    captured_at: str = ""
    bookmaker: str = ""
    goal_odds: float | None = None
    assist_odds: float | None = None
    sot_odds: float | None = None


def _parse_odds(raw: str) -> float | None:
    raw = raw.strip()
    return float(raw) if raw else None


def load_entries(path: Path) -> list[ScorerEntry]:
    """Read a CSV of manually-entered player prices.

    Columns: player, club, lineup_status, confirmed, captured_at, bookmaker,
    goal_odds, assist_odds, sot_odds. The three `*_odds` columns may be left
    blank where that market wasn't priced for a player. `confirmed` reads
    any of true/1/yes (case-insensitive) as true, everything else as false.
    """
    entries = []
    with Path(path).open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            entries.append(ScorerEntry(
                player=row["player"].strip(),
                club=row["club"].strip(),
                lineup_status=row["lineup_status"].strip().lower(),
                confirmed=row.get("confirmed", "").strip().lower() in ("true", "1", "yes"),
                captured_at=row.get("captured_at", "").strip(),
                bookmaker=row.get("bookmaker", "").strip(),
                goal_odds=_parse_odds(row.get("goal_odds", "")),
                assist_odds=_parse_odds(row.get("assist_odds", "")),
                sot_odds=_parse_odds(row.get("sot_odds", "")),
            ))
    return entries


def implied_rate(decimal_odds: float) -> float:
    """The raw (not yet reconciled) Poisson lambda behind an "at least one" price.

    `P(at least one) = 1 - e^-lambda`, so `lambda = -ln(1 - p)` for the raw
    implied probability `p = 1 / decimal_odds`. Applies identically to
    anytime-goalscorer, assists-over-0.5 and shots-on-target-over-0.5 --
    all three are "at least one occurrence" prices. Still carries whatever
    overround the book applies; `reconcile_team` is the correction for
    goals and assists, not this.
    """
    if decimal_odds < MIN_ODDS:
        raise ValueError(f"odds must be >= {MIN_ODDS}, got {decimal_odds}")
    p = 1.0 / decimal_odds
    return -math.log1p(-p)


def reconcile_team(raw_lambdas: dict[int, float], target_total: float) -> dict[int, float]:
    """Rescale raw per-player lambdas to sum to an independently-known total.

    Anytime-style prices are not a partition (two players can both score or
    both assist), so there is no "probabilities sum to 1" de-vig to apply.
    This rescaling *is* the de-vig here: the single correction factor that
    makes `sum(lambda)` agree with a total computed independently -- from
    the market-odds solve in `goals.py`, not from these prices at all --
    the same idea as Shin/proportional de-vigging in `odds.py`, just against
    a different, external target.

    `target_total` should already have any allowance (own goals, the
    assist share of goals) applied -- this function just rescales to meet
    whatever total it is given.
    """
    total_raw = sum(raw_lambdas.values())
    if total_raw <= 0:
        return dict(raw_lambdas)
    factor = max(target_total, 0.0) / total_raw
    return {player_id: lam * factor for player_id, lam in raw_lambdas.items()}


def seed_rate(reconciled_lambda: float, lineup_status: str) -> float:
    """A reconciled match-total lambda, rebased onto a per-90 figure.

    The price already reflects the market's own view of how long this
    player plays -- it is a whole-match figure, not a per-90 rate. The page
    multiplies every rate by minutes/90 (see `pointsGivenMinutes` in
    `build_app.py`), so dividing by that same assumed minutes here cancels
    the scaling out: the page recovers exactly `reconciled_lambda` when its
    own minutes control sits at this assumption. Skipping this step is the
    double-discount bug this module exists to avoid.

    Uses the model's own MINUTES_IF_LONG/MINUTES_IF_SHORT so a market-derived
    seed and the model's own estimate agree on what "a starter" means.
    """
    assumed_minutes = MINUTES_IF_LONG if lineup_status == "start" else MINUTES_IF_SHORT
    return reconciled_lambda / (assumed_minutes / 90.0)


def _normalise_player_name(name: str) -> tuple[str, str]:
    """(first_initial, last_name) from a free-form name.

    Handles the formats an odds source or the EFL feed's own `displayName`
    ("L. Wing") might use: "Lewis Wing", "L. Wing", "L Wing", "Wing" alone.
    Accents are stripped (same approach as `club_names.normalise`), so
    "Nunez" typed on an odds source matches "Nunez" however the feed
    accents it.
    """
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    cleaned = ascii_only.replace(".", "").strip()
    parts = cleaned.split()
    if not parts:
        return "", ""
    last = parts[-1].lower()
    first_initial = parts[0][0].lower() if len(parts) > 1 else ""
    return first_initial, last


@dataclass
class PlayerMatch:
    """One entry's best candidate among a club's roster."""

    entry: ScorerEntry
    player_id: int | None
    score: float
    ambiguous: bool


def match_players(entries: list[ScorerEntry], roster: list[dict]) -> list[PlayerMatch]:
    """Match each entry to a roster player id, scoped to the entry's club.

    Scoped to one club (roughly 20-25 players) rather than the whole pool, so
    a shared surname at a *different* club is never in contention -- the
    ambiguity that matters is two players sharing a surname at the same club,
    which is rare but real, and reported rather than guessed at, same
    philosophy as `club_names.py`.
    """
    by_club: dict[str, list[dict]] = {}
    for player in roster:
        by_club.setdefault(player["club"], []).append(player)

    results = []
    for entry in entries:
        candidates = by_club.get(entry.club, [])
        entry_initial, entry_last = _normalise_player_name(entry.player)

        scored = []
        for candidate in candidates:
            cand_initial, cand_last = _normalise_player_name(candidate["displayName"])
            name_score = similarity(entry_last, cand_last)
            if entry_initial and cand_initial and entry_initial != cand_initial:
                name_score *= 0.3  # initials disagree -- probably not this player
            scored.append((name_score, candidate))
        scored.sort(key=lambda pair: -pair[0])

        if not scored or scored[0][0] < MIN_SCORE:
            results.append(PlayerMatch(entry, None, scored[0][0] if scored else 0.0, False))
            continue

        best_score, best_player = scored[0]
        runner_score = scored[1][0] if len(scored) > 1 else 0.0
        results.append(PlayerMatch(
            entry=entry,
            player_id=best_player["id"],
            score=best_score,
            ambiguous=(best_score - runner_score) < AMBIGUITY_MARGIN,
        ))
    return results


@dataclass
class SeedResult:
    """What a build_*_seeds call produced, and which clubs it should not be trusted for.

    Kept separate from the seeds themselves so the build functions stay
    pure -- reporting a warning is the caller's job (export_app_data.py
    prints one), not this one's.
    """

    seeds: dict[int, float]
    #: club name -> how many players were actually priced, for any club
    #: below MIN_PRICED_PER_CLUB. Its seeds are still in `seeds` -- this is a
    #: warning, not a rejection -- but they should be treated as unreliable.
    sparse_clubs: dict[str, int]


def _build_reconciled_seeds(
    matches: list[PlayerMatch], odds_field: str, team_targets: dict[str, float],
) -> SeedResult:
    """Shared machinery behind build_goal_seeds and build_assist_seeds.

    `odds_field` is which of ScorerEntry's `*_odds` attributes to read;
    `team_targets` is keyed by club name and should already have any
    allowance (own goals, assist share) applied.
    """
    usable = [
        m for m in matches
        if m.entry.confirmed and m.player_id is not None and not m.ambiguous
        and getattr(m.entry, odds_field) is not None
    ]

    by_club: dict[str, list[PlayerMatch]] = {}
    for m in usable:
        by_club.setdefault(m.entry.club, []).append(m)

    seeds: dict[int, float] = {}
    sparse_clubs: dict[str, int] = {}
    for club, club_matches in by_club.items():
        target = team_targets.get(club)
        if target is None:
            continue
        if len(club_matches) < MIN_PRICED_PER_CLUB:
            sparse_clubs[club] = len(club_matches)
        raw = {m.player_id: implied_rate(getattr(m.entry, odds_field)) for m in club_matches}
        reconciled = reconcile_team(raw, target)
        for m in club_matches:
            seeds[m.player_id] = seed_rate(reconciled[m.player_id], m.entry.lineup_status)
    return SeedResult(seeds=seeds, sparse_clubs=sparse_clubs)


def build_goal_seeds(
    matches: list[PlayerMatch], team_expected_goals: dict[str, float],
) -> SeedResult:
    """Confirmed, matched, unambiguous entries -> per-player goals90 seeds.

    `team_expected_goals` is keyed by club name and should be that club's
    expected goals from `goals.py` for the relevant fixture -- one entry's
    job is to price a player, not to know the match odds. OWN_GOAL_ALLOWANCE
    is subtracted here before reconciling.

    Silently drops anything unusable rather than raising: unconfirmed
    lineups, unmatched or ambiguous names, players with no goal_odds priced,
    and clubs with no expected-goals target supplied.
    """
    targets = {club: max(g - OWN_GOAL_ALLOWANCE, 0.0) for club, g in team_expected_goals.items()}
    return _build_reconciled_seeds(matches, "goal_odds", targets)


def build_assist_seeds(
    matches: list[PlayerMatch], team_expected_goals: dict[str, float],
) -> SeedResult:
    """Confirmed, matched, unambiguous entries -> per-player assists90 seeds.

    Same shape as build_goal_seeds, reconciled against ASSIST_SHARE_OF_GOALS
    of the same team-expected-goals figure rather than the full total -- not
    every goal has an assist.
    """
    targets = {club: g * ASSIST_SHARE_OF_GOALS for club, g in team_expected_goals.items()}
    return _build_reconciled_seeds(matches, "assist_odds", targets)


def build_shots_on_target_seeds(matches: list[PlayerMatch]) -> dict[int, float]:
    """Confirmed, matched, unambiguous entries -> per-player shotsOnTarget90 seeds.

    Unlike goals and assists, there is no independent team-level "expected
    shots on target" figure to reconcile against -- `goals.py` derives win,
    draw, clean-sheet and goals from the 1X2 market alone, not a shots
    market -- so this is a straight, non-reconciled read of each player's
    own price. The book's overround stays in. Good enough for ranking who is
    likely to register a shot on target; not meant to be read as a precise
    rate the way the goal and assist seeds are.
    """
    seeds: dict[int, float] = {}
    for m in matches:
        if not (m.entry.confirmed and m.player_id is not None and not m.ambiguous):
            continue
        if m.entry.sot_odds is None:
            continue
        raw = implied_rate(m.entry.sot_odds)
        seeds[m.player_id] = seed_rate(raw, m.entry.lineup_status)
    return seeds


def apply_seed(rates, field: str, value: float):
    """A PlayerRates with one field replaced by a market-derived seed.

    `rates` is fixture-adjusted per-90 already (see `player_rates` in
    `player_model.py`), which is exactly the basis a seed from this module
    is on -- so this is a plain substitution, not a rescale. `field` is a
    PlayerRates attribute name (`"goals"`, `"assists"` or
    `"shots_on_target"`). Returns a new object; `rates` is frozen and
    unmodified, so `expected_player_points` on the result reflects the seed
    exactly the way it would any other rate, keeping the page's own
    "recompute from the rates" invariant intact.
    """
    return replace(rates, **{field: value})
