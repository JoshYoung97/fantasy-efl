"""The Odds API client -- primary source of EFL market prices.

Chosen over scraping because it is licensed, stable, and free at this volume:
cost is (markets x regions) credits per request, so all three EFL divisions at
h2h + totals is 6 credits a refresh, or ~180 a month refreshing daily, against
a 500-credit free allowance.

The UK region includes exchange operators alongside traditional bookmakers.
That matters, because exchange prices carry a spread rather than a margin and
are the sharper input -- so they are kept separate here rather than being
averaged into the bookmaker consensus, which would dilute the better signal
with the worse one.

Credentials come from the ODDS_API_KEY environment variable. Stdlib only.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from .odds import consensus_probabilities, exchange_probabilities

BASE_URL = "https://api.the-odds-api.com/v4"

#: EFL sport keys, in division order.
SPORT_KEYS = {
    "Championship": "soccer_efl_champ",
    "League One": "soccer_england_league1",
    "League Two": "soccer_england_league2",
}

#: Operators that run an exchange rather than a book. Their prices reflect a
#: spread, not a margin, so they need `exchange_probabilities`, not de-vigging.
EXCHANGES = frozenset({"betfair_ex_uk", "matchbook", "smarkets"})


class OddsApiError(RuntimeError):
    """The request failed, or the API rejected it."""


@dataclass(frozen=True)
class Quota:
    """Credit usage reported alongside every response."""

    remaining: int | None
    used: int | None
    last_cost: int | None

    def __str__(self) -> str:
        return f"{self.remaining} credits remaining ({self.last_cost} for that call)"


@dataclass(frozen=True)
class Fixture:
    """One match, with every bookmaker's prices attached."""

    id: str
    sport_key: str
    commence_time: str
    home_team: str
    away_team: str
    bookmakers: list[dict] = field(default_factory=list)

    def _h2h(self, bookmaker: dict) -> list[float] | None:
        """That bookmaker's home/draw/away prices, in that order.

        Outcomes come back keyed by team name in no guaranteed order, so they
        are matched by name rather than position.
        """
        for market in bookmaker.get("markets", []):
            if market.get("key") != "h2h":
                continue
            prices = {o["name"]: o["price"] for o in market.get("outcomes", [])}
            triple = [
                prices.get(self.home_team),
                prices.get("Draw"),
                prices.get(self.away_team),
            ]
            if all(p and p > 1.0 for p in triple):
                return triple  # type: ignore[return-value]
        return None

    def bookmaker_books(self, *, limit: int | None = 5) -> list[list[float]]:
        """Home/draw/away prices from traditional bookmakers only.

        `limit` takes the first N, which the API returns in a stable order.
        """
        books = [
            triple
            for bm in self.bookmakers
            if bm.get("key") not in EXCHANGES
            and (triple := self._h2h(bm)) is not None
        ]
        return books[:limit] if limit else books

    def exchange_book(self) -> list[float] | None:
        """Home/draw/away prices from an exchange, if one priced this match."""
        for bm in self.bookmakers:
            if bm.get("key") in EXCHANGES:
                triple = self._h2h(bm)
                if triple:
                    return triple
        return None

    def consensus(self, *, limit: int | None = 5) -> list[float] | None:
        """De-vigged consensus across bookmakers. None if nobody priced it."""
        books = self.bookmaker_books(limit=limit)
        return consensus_probabilities(books) if books else None

    def exchange_consensus(self) -> list[float] | None:
        """Probabilities from exchange prices.

        The API exposes one price per outcome rather than both sides of the
        book, so this normalises those directly. Exchange prices sit close to
        fair already, so the correction is small by construction.
        """
        book = self.exchange_book()
        if not book:
            return None
        return exchange_probabilities([(p, None) for p in book])


def fetch_odds(
    sport_key: str,
    *,
    markets: tuple[str, ...] = ("h2h",),
    regions: str = "uk",
    api_key: str | None = None,
    timeout: int = 30,
) -> tuple[list[Fixture], Quota]:
    """Fetch upcoming odds for one competition.

    Costs len(markets) x len(regions) credits. Returns the fixtures alongside
    the quota headers so callers can log consumption rather than discover the
    limit by hitting it.
    """
    api_key = api_key or os.environ.get("ODDS_API_KEY")
    if not api_key:
        raise OddsApiError(
            "ODDS_API_KEY is not set. Get a free key at https://the-odds-api.com/"
        )

    query = urllib.parse.urlencode(
        {
            "apiKey": api_key,
            "regions": regions,
            "markets": ",".join(markets),
            "oddsFormat": "decimal",
            "dateFormat": "iso",
        }
    )
    url = f"{BASE_URL}/sports/{sport_key}/odds/?{query}"

    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            quota = Quota(
                remaining=_as_int(response.headers.get("x-requests-remaining")),
                used=_as_int(response.headers.get("x-requests-used")),
                last_cost=_as_int(response.headers.get("x-requests-last")),
            )
    except urllib.error.HTTPError as exc:
        # The key appears in the URL, so never surface it in an error message.
        raise OddsApiError(
            f"request for {sport_key} failed: HTTP {exc.code} {exc.reason}"
        ) from None
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        raise OddsApiError(f"request for {sport_key} failed: {exc}") from None

    fixtures = [
        Fixture(
            id=event["id"],
            sport_key=event["sport_key"],
            commence_time=event["commence_time"],
            home_team=event["home_team"],
            away_team=event["away_team"],
            bookmakers=event.get("bookmakers", []),
        )
        for event in payload
    ]
    return fixtures, quota


def fetch_all_efl(
    *,
    markets: tuple[str, ...] = ("h2h",),
    regions: str = "uk",
    api_key: str | None = None,
) -> tuple[dict[str, list[Fixture]], Quota]:
    """Fetch every EFL division. Costs 3 x len(markets) x len(regions) credits."""
    out: dict[str, list[Fixture]] = {}
    quota = Quota(None, None, None)
    for division, key in SPORT_KEYS.items():
        out[division], quota = fetch_odds(
            key, markets=markets, regions=regions, api_key=api_key
        )
    return out, quota


def _as_int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None
