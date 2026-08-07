"""Tests for parsing The Odds API payloads.

Uses a fixture shaped like a real v4 response, so no network or key is needed.
"""

from __future__ import annotations

import pytest

from fantasy_efl.oddsapi import EXCHANGES, SPORT_KEYS, Fixture, OddsApiError, fetch_odds


def make_fixture(bookmakers):
    return Fixture(
        id="abc123",
        sport_key="soccer_england_league2",
        commence_time="2026-08-15T14:00:00Z",
        home_team="Tranmere Rovers",
        away_team="Shrewsbury Town",
        bookmakers=bookmakers,
    )


def h2h(key, home, draw, away):
    return {
        "key": key,
        "title": key,
        "markets": [
            {
                "key": "h2h",
                "outcomes": [
                    # Deliberately out of order: the parser must match by name.
                    {"name": "Shrewsbury Town", "price": away},
                    {"name": "Tranmere Rovers", "price": home},
                    {"name": "Draw", "price": draw},
                ],
            }
        ],
    }


BOOKS = [
    h2h("williamhill", 2.10, 3.30, 3.60),
    h2h("skybet", 2.05, 3.40, 3.70),
    h2h("ladbrokes", 2.15, 3.25, 3.55),
    h2h("paddypower", 2.08, 3.35, 3.75),
    h2h("unibet", 2.12, 3.30, 3.65),
    h2h("betvictor", 2.11, 3.32, 3.62),
]


def test_all_three_efl_divisions_are_configured():
    assert set(SPORT_KEYS) == {"Championship", "League One", "League Two"}
    assert SPORT_KEYS["League Two"] == "soccer_england_league2"


def test_outcomes_are_matched_by_name_not_position():
    """The API does not guarantee outcome ordering."""
    triple = make_fixture([BOOKS[0]]).bookmaker_books()[0]
    assert triple == [2.10, 3.30, 3.60]


def test_bookmaker_limit_takes_the_top_five():
    fixture = make_fixture(BOOKS)
    assert len(fixture.bookmaker_books(limit=5)) == 5
    assert len(fixture.bookmaker_books(limit=None)) == 6


def test_exchanges_are_excluded_from_the_bookmaker_consensus():
    fixture = make_fixture(BOOKS + [h2h("betfair_ex_uk", 2.20, 3.45, 3.80)])
    assert len(fixture.bookmaker_books(limit=None)) == 6  # exchange not counted
    assert fixture.exchange_book() == [2.20, 3.45, 3.80]


def test_exchange_prices_are_recognised():
    assert "betfair_ex_uk" in EXCHANGES
    fixture = make_fixture([h2h("betfair_ex_uk", 2.20, 3.45, 3.80)])
    probs = fixture.exchange_consensus()
    assert probs is not None
    assert abs(sum(probs) - 1.0) < 1e-9


def test_exchange_implies_a_tighter_book_than_bookmakers():
    """The whole reason exchange prices are kept separate."""
    fixture = make_fixture(BOOKS + [h2h("betfair_ex_uk", 2.20, 3.45, 3.80)])
    book_margin = sum(1 / p for p in fixture.bookmaker_books()[0])
    exchange_margin = sum(1 / p for p in fixture.exchange_book())
    assert exchange_margin < book_margin


def test_consensus_normalises():
    probs = make_fixture(BOOKS).consensus()
    assert probs is not None
    assert abs(sum(probs) - 1.0) < 1e-9
    assert probs[0] > probs[1] > probs[2]  # favourite, draw, outsider


def test_unpriced_fixture_returns_none_rather_than_raising():
    """League Two markets are sometimes not posted until close to kickoff."""
    fixture = make_fixture([])
    assert fixture.consensus() is None
    assert fixture.exchange_consensus() is None


def test_incomplete_market_is_skipped():
    broken = {
        "key": "williamhill",
        "markets": [
            {"key": "h2h", "outcomes": [{"name": "Tranmere Rovers", "price": 2.1}]}
        ],
    }
    assert make_fixture([broken]).bookmaker_books() == []


def test_non_h2h_markets_are_ignored_by_the_h2h_parser():
    totals = {
        "key": "williamhill",
        "markets": [
            {
                "key": "totals",
                "outcomes": [
                    {"name": "Over", "price": 1.9, "point": 2.5},
                    {"name": "Under", "price": 1.9, "point": 2.5},
                ],
            }
        ],
    }
    assert make_fixture([totals]).bookmaker_books() == []


def test_missing_api_key_is_reported_clearly(monkeypatch):
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    with pytest.raises(OddsApiError, match="ODDS_API_KEY"):
        fetch_odds("soccer_efl_champ")
