"""Converting anytime-goalscorer prices into a player's expected goals.

The market for a player scoring anytime prices something the season-totals
feed cannot see: this player, this fixture, informed by whatever the book
knows about form, fitness and tactical role. Kept manual rather than scraped
-- see the module's own reasoning below -- entries are typed in by hand from
Oddschecker or a single book, one row per player per fixture.

The conversion, in three steps:

1. Poisson invert. `P(scores anytime) = 1 - e^-lambda`, so
   `lambda = -ln(1 - p)`, the same Poisson family `goals.py` already uses for
   clubs. `p` here is the raw, un-devigged implied probability.

2. Reconcile against the team total. Anytime-scorer is not a partition --
   two players can both score -- so the usual "make probabilities sum to 1"
   de-vig does not apply. Instead, the correction *is* rescaling every
   player's raw lambda so they sum to the team's own modelled expected goals
   (from `goals.py`, already de-vigged from the match-odds market), minus a
   small allowance for goals the anytime-scorer market cannot see at all:
   own goals, credited to nobody's own price.

3. Rebase onto a per-90 figure. The anytime-scorer price already reflects
   the market's own view of how long this player is likely to play -- it is
   not a per-90 rate. `export_app_data.py`'s page multiplies every goals
   figure by minutes/90 (see `pointsGivenMinutes` in `build_app.py`), so
   feeding a whole-match figure straight in would discount it a second time.
   Dividing by the same assumed minutes here cancels that out: the page
   recovers exactly the reconciled figure when its own minutes control sits
   at that assumption.

What this deliberately does not attempt:

- **Substitute-scored goals.** Only a problem if entries are limited to the
  starting XI. Price the bench too (bookmakers usually do, once lineups are
  out) and it is not a separate correction at all -- a substitute's own
  anytime price already carries "comes on and scores".
- **A precise own-goal rate.** The feed carries no own-goal field for any
  player (checked directly against `players.json`'s fields), so there is
  nothing to calibrate `OWN_GOAL_ALLOWANCE` against, the way `CARD_COST` was
  calibrated from a real season. It is a placeholder external estimate,
  flagged as such, worth revisiting if a source for real own-goal counts
  ever turns up.
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
1.87 expected goals per 90 and 16.9 points for one match). `build_seeds`
still produces a number below `MIN_PRICED_PER_CLUB` -- a real, incomplete
price is still better than the model's own guess for the players it does
cover -- but flags it via `SeedResult.sparse_clubs`, and
`export_app_data.py` prints a warning for it. Price most of a team's
attacking threat, not just one player, or trust the warning when you cannot.

Only entries with a *confirmed* lineup are used to seed the model. A
predicted lineup's anytime-scorer price is blended: it reflects both this
player's rate if he plays and the market's own uncertainty about whether he
starts at all, and there is no way to cleanly separate those out of a single
price. `player_model.py`'s `MinutesModel` already owns "probability of
playing" -- feeding a blended price into the goals rate would double count
that uncertainty, once from the market price and again from the model's own
estimate. Predicted-but-unconfirmed entries are still matched and reported
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

#: Below this an anytime-scorer price is treated as unpriced. A long-odds
#: line on a fringe bench player is noisy, and division by (1 - p) blows up
#: as p approaches 1 -- not a real risk here, but 1.01 is also just not a
#: price worth trusting to two decimal places either way.
MIN_ODDS = 1.01

#: Below this the best name match is treated as no match at all, and above
#: it but within AMBIGUITY_MARGIN of the runner-up it is flagged rather than
#: guessed at. Same values and reasoning as club_names.py.
MIN_SCORE = 0.72
AMBIGUITY_MARGIN = 0.08

#: Below this many priced players for one club, reconciliation is flagged as
#: sparse rather than trusted quietly.
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
    "player", "club", "anytime_odds", "bookmaker",
    "lineup_status", "confirmed", "captured_at",
)


@dataclass(frozen=True)
class ScorerEntry:
    """One manually-entered anytime-goalscorer price.

    `player` and `club` are written however the odds source spells them --
    matching against the roster is `match_players`'s job, not the entry's.
    `anytime_odds` is the raw decimal price, not a probability: the
    conversion belongs in code, run consistently, not redone by hand for
    every player.
    """

    player: str
    club: str
    anytime_odds: float
    bookmaker: str
    lineup_status: str  # "start" | "bench" | "out"
    confirmed: bool
    captured_at: str = ""


def load_entries(path: Path) -> list[ScorerEntry]:
    """Read a CSV of manually-entered anytime-scorer prices.

    Columns: player, club, anytime_odds, bookmaker, lineup_status, confirmed,
    captured_at. `confirmed` reads any of true/1/yes (case-insensitive) as
    true, everything else as false.
    """
    entries = []
    with Path(path).open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            entries.append(ScorerEntry(
                player=row["player"].strip(),
                club=row["club"].strip(),
                anytime_odds=float(row["anytime_odds"]),
                bookmaker=row.get("bookmaker", "").strip(),
                lineup_status=row["lineup_status"].strip().lower(),
                confirmed=row.get("confirmed", "").strip().lower() in ("true", "1", "yes"),
                captured_at=row.get("captured_at", "").strip(),
            ))
    return entries


def implied_goal_rate(decimal_odds: float) -> float:
    """The raw (not yet reconciled) Poisson lambda behind an anytime price.

    `P(scores anytime) = 1 - e^-lambda`, so `lambda = -ln(1 - p)` for the raw
    implied probability `p = 1 / decimal_odds`. Still carries whatever
    overround the book applies -- `reconcile_team` is the correction, not
    this.
    """
    if decimal_odds < MIN_ODDS:
        raise ValueError(f"odds must be >= {MIN_ODDS}, got {decimal_odds}")
    p = 1.0 / decimal_odds
    return -math.log1p(-p)


def reconcile_team(
    raw_lambdas: dict[int, float], team_expected_goals: float,
    own_goal_allowance: float = OWN_GOAL_ALLOWANCE,
) -> dict[int, float]:
    """Rescale raw per-player lambdas to sum to the team's modelled total.

    Anytime-scorer prices are not a partition (two players can both score),
    so there is no "probabilities sum to 1" de-vig to apply. This rescaling
    *is* the de-vig here: the single correction factor that makes
    `sum(lambda)` agree with a total computed independently, from the
    market-odds solve in `goals.py` rather than from these prices at all --
    the same idea as Shin/proportional de-vigging in `odds.py`, just against
    a different, external target.

    `team_expected_goals` is the team's full expected goals for the match;
    `own_goal_allowance` is subtracted before rescaling, since that portion
    is credited to nobody in `raw_lambdas`.
    """
    target = max(team_expected_goals - own_goal_allowance, 0.0)
    total_raw = sum(raw_lambdas.values())
    if total_raw <= 0:
        return dict(raw_lambdas)
    factor = target / total_raw
    return {player_id: lam * factor for player_id, lam in raw_lambdas.items()}


def seed_rate(reconciled_lambda: float, lineup_status: str) -> float:
    """A reconciled match-total lambda, rebased onto a per-90 figure.

    The anytime-scorer price already reflects the market's own view of how
    long this player plays -- it is a whole-match figure, not a per-90 rate.
    The page multiplies every goals figure by minutes/90 (see
    `pointsGivenMinutes` in `build_app.py`), so dividing by that same assumed
    minutes here cancels the scaling out: the page recovers exactly
    `reconciled_lambda` when its own minutes control sits at this
    assumption. Skipping this step is the double-discount bug this module
    exists to avoid.

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
    """What build_seeds produced, and which clubs it should not be trusted for.

    Kept separate from the seeds themselves so build_seeds stays pure --
    reporting a warning is the caller's job (export_app_data.py prints one),
    not this function's.
    """

    seeds: dict[int, float]
    #: club name -> how many players were actually priced, for any club
    #: below MIN_PRICED_PER_CLUB. Its seeds are still in `seeds` -- this is a
    #: warning, not a rejection -- but they should be treated as unreliable.
    sparse_clubs: dict[str, int]


def build_seeds(
    matches: list[PlayerMatch], team_expected_goals: dict[str, float],
) -> SeedResult:
    """Confirmed, matched, unambiguous entries -> per-player goals90 seeds.

    Reconciliation happens per club, since the target is a club's total
    expected goals for its own fixture. `team_expected_goals` is keyed by
    club name (the same name entries carry) and should already be that
    club's expected goals from `goals.py` for the relevant fixture -- one
    entry's job is to price a player, not to know the match odds.

    Silently drops anything unusable rather than raising: unconfirmed
    lineups (the blended-price problem the module docstring explains),
    unmatched or ambiguous names, and clubs with no expected-goals target
    supplied. A caller that wants to know what got dropped should inspect
    `matches` directly -- `PlayerMatch.player_id` and `.ambiguous` say why.

    Does NOT drop a club for being sparsely priced (see MIN_PRICED_PER_CLUB)
    -- a real but incomplete price is still better than the model's own
    guess for the players it does cover, as long as whoever reads the result
    knows to be suspicious of it. That is what `SeedResult.sparse_clubs` is
    for.
    """
    usable = [
        m for m in matches
        if m.entry.confirmed and m.player_id is not None and not m.ambiguous
    ]

    by_club: dict[str, list[PlayerMatch]] = {}
    for m in usable:
        by_club.setdefault(m.entry.club, []).append(m)

    seeds: dict[int, float] = {}
    sparse_clubs: dict[str, int] = {}
    for club, club_matches in by_club.items():
        target = team_expected_goals.get(club)
        if target is None:
            continue
        if len(club_matches) < MIN_PRICED_PER_CLUB:
            sparse_clubs[club] = len(club_matches)
        raw = {m.player_id: implied_goal_rate(m.entry.anytime_odds) for m in club_matches}
        reconciled = reconcile_team(raw, target)
        for m in club_matches:
            seeds[m.player_id] = seed_rate(reconciled[m.player_id], m.entry.lineup_status)
    return SeedResult(seeds=seeds, sparse_clubs=sparse_clubs)


def apply_seed(rates, goals90: float):
    """A PlayerRates with `goals` replaced by a market-derived seed.

    `rates` is fixture-adjusted per-90 already (see `player_rates` in
    `player_model.py`), which is exactly the basis `goals90` from
    `build_seeds` is on -- so this is a plain substitution, not a rescale.
    Returns a new object; `rates` is frozen and unmodified, so
    `expected_player_points` on the result reflects the seed exactly the way
    it would any other rate, keeping the page's own "recompute from the
    rates" invariant intact.
    """
    return replace(rates, goals=goals90)
