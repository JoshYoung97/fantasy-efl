"""Read-only Betfair Exchange client for EFL market prices.

Exchange prices are a better model input than a bookmaker average: they are
real money, they update continuously, and the spread between back and lay
brackets the market's true estimate rather than hiding a margin inside it.
The free delayed application key gives 1-180 second snapshots, which is
irrelevant for projections made days ahead of kickoff.

Safety posture, deliberate and load-bearing:

* Credentials are read from the environment only -- never arguments, never
  written to disk, never logged. The caller sets BETFAIR_USERNAME,
  BETFAIR_PASSWORD and BETFAIR_APP_KEY themselves.
* Every session logs in fresh and is discarded on exit, so no token is
  persisted anywhere.
* ``_ALLOWED_OPERATIONS`` is an allowlist of market-data calls. Anything that
  could stake money -- placeOrders, cancelOrders, replaceOrders -- is absent,
  and ``_rpc`` refuses any operation not on the list. This account holds real
  funds; the restriction is structural rather than a matter of care.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

LOGIN_URL = "https://identitysso.betfair.com/api/login"
LOGOUT_URL = "https://identitysso.betfair.com/api/logout"
RPC_URL = "https://api.betfair.com/exchange/betting/json-rpc/v1"

SOCCER_EVENT_TYPE_ID = "1"

#: Read-only operations this client may invoke. Betting operations are
#: intentionally excluded -- see the module docstring.
_ALLOWED_OPERATIONS = frozenset(
    {
        "listCompetitions",
        "listEvents",
        "listMarketCatalogue",
        "listMarketBook",
        "listMarketTypes",
    }
)


class BetfairError(RuntimeError):
    """Login failed, or the exchange rejected a request."""


@dataclass(frozen=True)
class RunnerPrices:
    """Best available back and lay for one runner."""

    selection_id: int
    name: str
    back: float | None
    lay: float | None

    @property
    def midpoint(self) -> float | None:
        """Mid-price between best back and lay.

        The fairest single number the exchange offers: the back price alone
        understates the true probability, the lay price overstates it.
        """
        if self.back and self.lay:
            return (self.back + self.lay) / 2.0
        return self.back or self.lay


class BetfairClient:
    """Minimal read-only Exchange client. Use as a context manager."""

    def __init__(self) -> None:
        self._app_key = os.environ.get("BETFAIR_APP_KEY")
        if not self._app_key:
            raise BetfairError(
                "BETFAIR_APP_KEY is not set. Export your delayed application key "
                "rather than passing it as an argument."
            )
        self._session_token: str | None = None

    def __enter__(self) -> BetfairClient:
        self.login()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.logout()

    def login(self) -> None:
        """Exchange username and password for a session token.

        Credentials are read here and immediately discarded; they are never
        stored on the instance.
        """
        username = os.environ.get("BETFAIR_USERNAME")
        password = os.environ.get("BETFAIR_PASSWORD")
        if not username or not password:
            raise BetfairError(
                "BETFAIR_USERNAME and BETFAIR_PASSWORD must be set in the "
                "environment. They are never read from arguments or files."
            )

        body = urllib.parse.urlencode(
            {"username": username, "password": password}
        ).encode("utf-8")
        request = urllib.request.Request(
            LOGIN_URL,
            data=body,
            headers={
                "X-Application": self._app_key,
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            # Deliberately does not echo the request body.
            raise BetfairError(f"login request failed: {exc}") from exc

        if payload.get("status") != "SUCCESS":
            raise BetfairError(
                f"login rejected: {payload.get('error') or payload.get('status')}"
            )
        self._session_token = payload["token"]

    def logout(self) -> None:
        """Invalidate the session token so it cannot be reused."""
        if not self._session_token:
            return
        request = urllib.request.Request(
            LOGOUT_URL,
            headers={
                "X-Application": self._app_key,
                "X-Authentication": self._session_token,
                "Accept": "application/json",
            },
        )
        try:
            urllib.request.urlopen(request, timeout=15).close()
        except (urllib.error.URLError, OSError):
            pass  # best effort; the token expires on its own regardless
        finally:
            self._session_token = None

    def _rpc(self, operation: str, params: dict[str, Any]) -> Any:
        if operation not in _ALLOWED_OPERATIONS:
            raise BetfairError(
                f"operation {operation!r} is not permitted by this client, which "
                f"is restricted to read-only market data"
            )
        if not self._session_token:
            raise BetfairError("not logged in")

        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "method": f"SportsAPING/v1.0/{operation}",
                "params": params,
                "id": 1,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            RPC_URL,
            data=body,
            headers={
                "X-Application": self._app_key,
                "X-Authentication": self._session_token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            raise BetfairError(f"{operation} failed: {exc}") from exc

        if "error" in payload:
            raise BetfairError(f"{operation} returned an error: {payload['error']}")
        return payload["result"]

    def list_competitions(self, *, text_query: str | None = None) -> list[dict]:
        """Soccer competitions, optionally filtered by a text query."""
        market_filter: dict[str, Any] = {"eventTypeIds": [SOCCER_EVENT_TYPE_ID]}
        if text_query:
            market_filter["textQuery"] = text_query
        return self._rpc("listCompetitions", {"filter": market_filter})

    def list_events(self, competition_ids: list[str]) -> list[dict]:
        """Upcoming events for the given competitions."""
        return self._rpc(
            "listEvents",
            {
                "filter": {
                    "eventTypeIds": [SOCCER_EVENT_TYPE_ID],
                    "competitionIds": competition_ids,
                }
            },
        )

    def list_markets(
        self,
        competition_ids: list[str],
        *,
        market_types: tuple[str, ...] = ("MATCH_ODDS", "OVER_UNDER_25"),
        max_results: int = 200,
    ) -> list[dict]:
        """Market catalogue entries, with event and runner metadata attached."""
        return self._rpc(
            "listMarketCatalogue",
            {
                "filter": {
                    "eventTypeIds": [SOCCER_EVENT_TYPE_ID],
                    "competitionIds": competition_ids,
                    "marketTypeCodes": list(market_types),
                },
                "marketProjection": ["EVENT", "RUNNER_DESCRIPTION", "MARKET_START_TIME"],
                "maxResults": max_results,
                "sort": "FIRST_TO_START",
            },
        )

    def market_prices(self, market_ids: list[str]) -> dict[str, list[RunnerPrices]]:
        """Best back and lay for every runner in the given markets.

        Betfair caps listMarketBook at 40 markets per call, so requests are
        chunked.
        """
        out: dict[str, list[RunnerPrices]] = {}
        for start in range(0, len(market_ids), 40):
            chunk = market_ids[start : start + 40]
            books = self._rpc(
                "listMarketBook",
                {
                    "marketIds": chunk,
                    "priceProjection": {"priceData": ["EX_BEST_OFFERS"]},
                },
            )
            for book in books:
                out[book["marketId"]] = [
                    RunnerPrices(
                        selection_id=runner["selectionId"],
                        name=str(runner["selectionId"]),
                        back=_best(runner, "availableToBack"),
                        lay=_best(runner, "availableToLay"),
                    )
                    for runner in book.get("runners", [])
                    if runner.get("status") == "ACTIVE"
                ]
        return out


def _best(runner: dict, side: str) -> float | None:
    offers = runner.get("ex", {}).get(side) or []
    return offers[0]["price"] if offers else None
