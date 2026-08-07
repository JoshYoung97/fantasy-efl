"""Backfilling relegated Premier League goalkeepers from the FPL API.

*** THIS DOES NOT CURRENTLY WORK AGAINST THE LIVE FPL API, BY DESIGN OF THAT
API RATHER THAN THIS CODE. ***

`bootstrap-static` returns only the twenty clubs currently in the Premier
League. Relegated clubs and their players are removed outright -- so Burnley,
Wolves, West Ham and Leicester players, the precise population this was written
to recover, are absent. Verified August 2026: none of those clubs appear in the
feed.

The module is kept because the conversion logic is correct and tested, and it
would work immediately against a historical FPL dataset (season-by-season
archives exist). It is disabled by default in `pipeline.load_gameweek` so it
does not cost a network round trip for nothing.

Before reviving it, weigh the return: even working perfectly it would fix a
handful of goalkeepers -- the lowest-scoring position in this game, where the
best projection is around 5.3 against 8.2 for the best midfielder -- and only
until those players accumulate their own EFL record, which takes about six
weeks. The position priors in `player_model` already cover them adequately in
the meantime.

Whole squads at recently relegated clubs have no EFL record, so the model
cannot see them. A historical Fantasy Premier League dataset has last season's
stats for exactly those players -- but only goalkeepers can be converted
honestly.

For a goalkeeper, every scoring term Fantasy EFL pays out on has a direct FPL
equivalent: saves, clean sheets, goals conceded, minutes. The mapping is exact.

For every other position it is not, and the gap is not a detail:

* FPL reports ``clearances_blocks_interceptions`` as one number. Fantasy EFL
  pays 0.25 a clearance, 0.5 a block, and 2.0 an interception -- and for
  midfielders the first two score nothing at all, so the entire value of that
  aggregate depends on a split FPL does not provide.
* Nothing can calibrate the split either. The EFL feed records only the stats
  each position scores from, so every midfielder has zero clearances recorded
  and every defender zero interceptions. There is no ground truth anywhere.
* FPL has no key passes or shots on target at all.

So this module is deliberately goalkeepers-only. Guessing a split for
midfielders -- the position that decides this game -- would put an
uncalibrated assumption underneath the most important projections in the model.
Outfield players are better served by the position priors in `player_model`,
which are at least honest about being estimates, and by their own EFL record
once a few gameweeks have been played.
"""

from __future__ import annotations

import gzip
import json
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass

BOOTSTRAP_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"

#: FPL's element_type for goalkeepers.
GOALKEEPER = 1

#: A Premier League season is 38 games against the EFL's 46. Rates are
#: per-appearance, so totals are rescaled to keep the two comparable.
PL_SEASON_GAMES = 38
EFL_SEASON_GAMES = 46

#: Shot volume is higher in the Premier League, so a keeper's saves per game
#: does not transfer unchanged. This damps the difference rather than assuming
#: it away; it is an estimate, flagged as such.
SAVE_RATE_TRANSFER = 0.85


class FplError(RuntimeError):
    """The FPL API could not be reached or returned something unexpected."""


@dataclass(frozen=True)
class BackfilledKeeper:
    """One goalkeeper's EFL-shaped stat line, derived from FPL."""

    efl_id: int
    name: str
    fpl_name: str
    appearances: int
    saves: int
    clean_sheets: int
    minutes: int

    def as_feed_fields(self) -> dict:
        """The subset of EFL feed fields the player model reads."""
        return {
            "appearances": self.appearances,
            "saves": self.saves,
            "cleanSheets": self.clean_sheets,
            "clearances": 0,
            "blocks": 0,
            "tackles": 0,
            "interceptions": 0,
            "goalsScored": 0,
            "assists": 0,
            "keyPasses": 0,
            "shotsOnTarget": 0,
        }


def fetch_fpl_players(timeout: int = 30) -> list[dict]:
    """Every player in the FPL bootstrap feed."""
    request = urllib.request.Request(
        BOOTSTRAP_URL,
        headers={"User-Agent": "fantasy-efl-projections/0.1", "Accept-Encoding": "gzip"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            if response.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
        payload = json.loads(raw.decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError, gzip.BadGzipFile) as exc:
        raise FplError(f"fetching FPL bootstrap: {exc}") from exc

    if "elements" not in payload:
        raise FplError("FPL response did not contain player data")
    return payload["elements"]


def _normalise(name: str) -> str:
    decomposed = unicodedata.normalize("NFKD", name)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower().strip()


def _initial(name: str) -> str:
    cleaned = _normalise(name).replace(".", "").strip()
    return cleaned[0] if cleaned else ""


def match_keepers(
    efl_players: list[dict], fpl_players: list[dict]
) -> tuple[list[BackfilledKeeper], list[dict]]:
    """Match EFL goalkeepers lacking a record to FPL goalkeepers.

    Requires an exact surname match plus a matching first initial. Any surname
    matching more than one candidate is skipped rather than guessed at, and
    returned in the second element for review -- a wrong keeper would carry
    another club's entire save and clean-sheet record.
    """
    fpl_keepers = [p for p in fpl_players if p.get("element_type") == GOALKEEPER]

    by_surname: dict[str, list[dict]] = {}
    for keeper in fpl_keepers:
        by_surname.setdefault(_normalise(keeper.get("second_name", "")), []).append(keeper)

    matched: list[BackfilledKeeper] = []
    ambiguous: list[dict] = []

    for player in efl_players:
        if player.get("position") != "GK" or player.get("appearances", 0) > 0:
            continue

        candidates = by_surname.get(_normalise(player.get("lastName", "")), [])
        first_name = _normalise(player.get("firstName", ""))

        # An initial alone is too weak for common surnames -- James, Joe and
        # Jack all collapse to "j" -- so prefer a full first-name match and
        # only fall back to the initial when that is not decisive.
        exact = [c for c in candidates if _normalise(c.get("first_name", "")) == first_name]
        if len(exact) == 1:
            candidates = exact
        else:
            initial = _initial(first_name)
            candidates = [
                c for c in candidates if _initial(c.get("first_name", "")) == initial
            ]

        if not candidates:
            continue
        if len(candidates) > 1:
            ambiguous.append(
                {
                    "efl_name": player.get("displayName"),
                    "candidates": [c.get("web_name") for c in candidates],
                }
            )
            continue

        source = candidates[0]
        minutes = source.get("minutes", 0)
        if minutes <= 0:
            continue

        # Convert to an EFL-length season so per-appearance rates line up.
        pl_appearances = source.get("starts") or round(minutes / 90)
        scale = EFL_SEASON_GAMES / PL_SEASON_GAMES
        appearances = max(1, round(pl_appearances * scale))

        matched.append(
            BackfilledKeeper(
                efl_id=player["id"],
                name=player.get("displayName", ""),
                fpl_name=source.get("web_name", ""),
                appearances=appearances,
                saves=round(source.get("saves", 0) * scale * SAVE_RATE_TRANSFER),
                clean_sheets=round(source.get("clean_sheets", 0) * scale),
                minutes=minutes,
            )
        )

    return matched, ambiguous


def apply_backfill(efl_players: list[dict], matched: list[BackfilledKeeper]) -> int:
    """Write backfilled stats onto the EFL player records in place.

    Returns how many players were updated. Only touches players who still have
    no appearances, so re-running once the season is underway cannot overwrite
    real EFL data with stale Premier League figures.
    """
    by_id = {p["id"]: p for p in efl_players}
    updated = 0
    for keeper in matched:
        player = by_id.get(keeper.efl_id)
        if player is None or player.get("appearances", 0) > 0:
            continue
        player.update(keeper.as_feed_fields())
        player["backfilled"] = "fpl"
        updated += 1
    return updated
