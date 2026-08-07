"""Tests for de-vigging and the read-only guarantee on the Betfair client."""

from __future__ import annotations

import pytest

from fantasy_efl.betfair import _ALLOWED_OPERATIONS, BetfairClient, BetfairError
from fantasy_efl.odds import (
    consensus_probabilities,
    devig_power,
    devig_proportional,
    devig_shin,
    exchange_probabilities,
    implied_probabilities,
    overround,
)

# A typical League Two market: modest favourite, five books, ~5% margin.
BOOKS = [
    [2.10, 3.30, 3.60],
    [2.05, 3.40, 3.70],
    [2.15, 3.25, 3.55],
    [2.08, 3.35, 3.75],
    [2.12, 3.30, 3.65],
]


def test_raw_implied_probabilities_carry_the_margin():
    assert overround(BOOKS[0]) > 1.03


def test_odds_at_or_below_evens_are_rejected():
    with pytest.raises(ValueError):
        implied_probabilities([1.0, 3.0, 4.0])


@pytest.mark.parametrize("method", [devig_proportional, devig_power, devig_shin])
def test_every_devig_method_normalises(method):
    probs = method(BOOKS[0])
    assert abs(sum(probs) - 1.0) < 1e-9
    assert all(0.0 < p < 1.0 for p in probs)


@pytest.mark.parametrize("method", [devig_power, devig_shin])
def test_bias_correction_favours_the_favourite(method):
    """Margin is loaded onto outsiders, so correcting it lifts the favourite."""
    proportional = devig_proportional(BOOKS[0])
    corrected = method(BOOKS[0])
    assert corrected[0] > proportional[0]
    assert corrected[2] < proportional[2]


def test_devig_is_a_no_op_on_a_fair_book():
    fair = [3.0, 3.0, 3.0]  # sums to exactly 1.0
    for method in (devig_proportional, devig_power, devig_shin):
        assert all(abs(p - 1 / 3) < 1e-6 for p in method(fair))


def test_consensus_normalises_and_sits_within_the_book_range():
    consensus = consensus_probabilities(BOOKS)
    assert abs(sum(consensus) - 1.0) < 1e-9
    per_book_home = [devig_shin(b)[0] for b in BOOKS]
    assert min(per_book_home) <= consensus[0] <= max(per_book_home)


def test_consensus_rejects_mismatched_books():
    with pytest.raises(ValueError):
        consensus_probabilities([[2.0, 3.0, 4.0], [2.0, 3.0]])


def test_consensus_rejects_empty_input():
    with pytest.raises(ValueError):
        consensus_probabilities([])


def test_exchange_midpoint_beats_using_back_prices_alone():
    """Back prices alone understate probabilities; midpoints are tighter."""
    back_lay = [(2.10, 2.14), (3.30, 3.40), (3.60, 3.75)]
    backs_only = sum(1.0 / b for b, _ in back_lay)
    mids = sum(1.0 / ((b + l) / 2) for b, l in back_lay)
    assert backs_only > mids  # backing every runner would overstate the book
    probs = exchange_probabilities(back_lay)
    assert abs(sum(probs) - 1.0) < 1e-9


def test_exchange_spread_is_tighter_than_bookmaker_margin():
    back_lay = [(2.10, 2.14), (3.30, 3.40), (3.60, 3.75)]
    exchange_book = sum(1.0 / ((b + l) / 2) for b, l in back_lay)
    assert exchange_book < overround(BOOKS[0])


def test_exchange_handles_one_sided_prices():
    probs = exchange_probabilities([(2.10, None), (3.30, 3.40), (None, 3.75)])
    assert abs(sum(probs) - 1.0) < 1e-9


def test_exchange_rejects_a_runner_with_no_price():
    with pytest.raises(ValueError):
        exchange_probabilities([(2.10, 2.14), (None, None)])


def test_betting_operations_are_not_reachable():
    """The client must not be able to stake money, by construction."""
    for forbidden in ("placeOrders", "cancelOrders", "replaceOrders", "updateOrders"):
        assert forbidden not in _ALLOWED_OPERATIONS


def test_rpc_refuses_operations_outside_the_allowlist(monkeypatch):
    monkeypatch.setenv("BETFAIR_APP_KEY", "test-key")
    client = BetfairClient()
    client._session_token = "test-token"
    with pytest.raises(BetfairError, match="not permitted"):
        client._rpc("placeOrders", {})


def test_client_requires_an_app_key(monkeypatch):
    monkeypatch.delenv("BETFAIR_APP_KEY", raising=False)
    with pytest.raises(BetfairError, match="BETFAIR_APP_KEY"):
        BetfairClient()


def test_login_requires_credentials_from_the_environment(monkeypatch):
    monkeypatch.setenv("BETFAIR_APP_KEY", "test-key")
    monkeypatch.delenv("BETFAIR_USERNAME", raising=False)
    monkeypatch.delenv("BETFAIR_PASSWORD", raising=False)
    with pytest.raises(BetfairError, match="BETFAIR_USERNAME"):
        BetfairClient().login()


def test_credentials_are_not_retained_on_the_instance(monkeypatch):
    monkeypatch.setenv("BETFAIR_APP_KEY", "test-key")
    monkeypatch.setenv("BETFAIR_USERNAME", "someone")
    monkeypatch.setenv("BETFAIR_PASSWORD", "hunter2")
    client = BetfairClient()
    assert "hunter2" not in repr(vars(client))
    assert not any("password" in name.lower() for name in vars(client))
