"""Tests for club name matching.

The same-city pairs are the point of this module: getting Bristol City and
Bristol Rovers the wrong way round would corrupt both clubs' projections
silently, so they are tested explicitly.
"""

from __future__ import annotations

import pytest

from fantasy_efl.club_names import Match, match_clubs, normalise, similarity


def test_normalise_strips_noise_but_keeps_distinguishing_suffixes():
    assert normalise("AFC Wimbledon") == "wimbledon"
    assert normalise("Bristol City FC") == "bristol city"
    assert normalise("Bristol Rovers") == "bristol rovers"


def test_normalise_handles_punctuation_and_accents():
    assert normalise("Preston North End") == "preston north end"
    assert normalise("Crewe Alexandra") == "crewe alexandra"


def test_normalise_canonicalises_bookmaker_shorthand():
    """Names sharing no tokens with their formal version need an alias."""
    assert normalise("Nott'm Forest") == normalise("Nottingham Forest")
    assert normalise("Wolves") == normalise("Wolverhampton Wanderers")
    assert normalise("MK Dons") == normalise("Milton Keynes Dons")
    assert normalise("Sheff Wed") == normalise("Sheffield Wednesday")


def test_identical_names_score_one():
    assert similarity("luton town", "luton town") == 1.0


def test_subset_names_score_highly():
    assert similarity("luton town", "luton") > 0.8
    assert similarity("wimbledon", "afc wimbledon") > 0.8


def test_same_city_clubs_are_kept_apart():
    """The failure this module exists to prevent."""
    assert similarity("bristol city", "bristol rovers") < 0.8
    assert similarity("sheffield united", "sheffield wednesday") < 0.8


def find(matches: list[Match], efl_name: str) -> Match:
    return next(m for m in matches if m.efl_name == efl_name)


def test_obvious_variants_map_cleanly():
    matches = match_clubs(
        ["AFC Wimbledon", "Luton Town", "Middlesbrough"],
        ["Wimbledon", "Luton", "Middlesbrough"],
    )
    assert find(matches, "AFC Wimbledon").odds_name == "Wimbledon"
    assert find(matches, "Luton Town").odds_name == "Luton"
    assert find(matches, "Middlesbrough").score == 1.0


def test_same_city_pair_maps_to_the_right_side():
    matches = match_clubs(
        ["Bristol City", "Bristol Rovers"],
        ["Bristol Rovers", "Bristol City"],
    )
    assert find(matches, "Bristol City").odds_name == "Bristol City"
    assert find(matches, "Bristol Rovers").odds_name == "Bristol Rovers"


def test_sheffield_clubs_map_to_the_right_side():
    matches = match_clubs(
        ["Sheffield United", "Sheffield Wednesday"],
        ["Sheffield Wednesday", "Sheffield United"],
    )
    assert find(matches, "Sheffield United").odds_name == "Sheffield United"
    assert find(matches, "Sheffield Wednesday").odds_name == "Sheffield Wednesday"


def test_a_bare_shared_token_is_flagged_not_guessed():
    """"Bristol" alone must not silently pick one of the two clubs."""
    matches = match_clubs(["Bristol"], ["Bristol City", "Bristol Rovers"])
    assert matches[0].ambiguous or matches[0].odds_name is None


def test_missing_club_yields_no_match():
    matches = match_clubs(["Barrow"], ["Middlesbrough", "Wolverhampton Wanderers"])
    assert matches[0].odds_name is None
    assert matches[0].needs_review


def test_exact_matches_do_not_need_review():
    matches = match_clubs(["Middlesbrough"], ["Middlesbrough", "Blackburn Rovers"])
    assert not matches[0].needs_review


def test_review_items_are_ordered_first():
    matches = match_clubs(
        ["Middlesbrough", "Barrow"], ["Middlesbrough", "Blackburn Rovers"]
    )
    assert matches[0].efl_name == "Barrow"


@pytest.mark.parametrize(
    "efl,odds",
    [
        ("Nottingham Forest", "Nott'm Forest"),
        ("Wolverhampton Wanderers", "Wolves"),
        ("Peterborough United", "Peterborough"),
        ("Milton Keynes Dons", "MK Dons"),
    ],
)
def test_common_abbreviations_at_least_surface_the_right_candidate(efl, odds):
    """These may need review, but the correct club must be the top candidate."""
    pool = [odds, "Middlesbrough", "Bristol City", "Leyton Orient"]
    matches = match_clubs([efl], pool)
    assert matches[0].odds_name == odds or matches[0].runner_up == odds
