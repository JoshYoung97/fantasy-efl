"""Tests for dropping players by name after team news.

Used under time pressure on matchday, so the important property is that a name
which does not resolve cleanly stops the run rather than quietly doing nothing.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from fantasy_efl.player_model import PlayerProjection

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "optimal_team", ROOT / "scripts" / "optimal_team.py"
)
optimal_team = importlib.util.module_from_spec(_spec)
sys.modules["optimal_team"] = optimal_team
_spec.loader.exec_module(optimal_team)
apply_exclusions = optimal_team.apply_exclusions


def player(pid, name, club, position="MID", points=5.0):
    return PlayerProjection(
        id=pid, name=name, position=position, club=club,
        opponent="Someone", away=False, expected_points=points,
        fixtures=1, selected_pct=0.0, status="playing",
    )


POOL = [
    player(1, "L. Wing", "Reading"),
    player(2, "N. Smith", "Tranmere Rovers", "DEF"),
    player(3, "R. Smith", "Walsall"),
    player(4, "C. Ripley", "Swindon Town", "GK"),
]


def test_surname_match_drops_the_right_player():
    """Team news arrives as surnames, not feed-formatted names."""
    dropped, remaining = apply_exclusions(POOL, ["Wing"])
    assert [p.id for p in dropped] == [1]
    assert 1 not in {p.id for p in remaining}
    assert len(remaining) == 3


def test_match_is_case_insensitive():
    dropped, _ = apply_exclusions(POOL, ["l. wing"])
    assert dropped[0].id == 1


def test_club_name_also_matches():
    dropped, _ = apply_exclusions(POOL, ["Reading"])
    assert dropped[0].id == 1


def test_ambiguous_name_aborts_without_dropping_anyone():
    """Guessing between two Smiths would silently field the wrong team."""
    dropped, remaining = apply_exclusions(POOL, ["Smith"])
    assert dropped is None
    assert len(remaining) == len(POOL)


def test_unmatched_name_aborts():
    """A typo must not pass silently -- the player would still be selected."""
    dropped, remaining = apply_exclusions(POOL, ["Ronaldo"])
    assert dropped is None
    assert len(remaining) == len(POOL)


def test_several_exclusions_apply_together():
    dropped, remaining = apply_exclusions(POOL, ["Wing", "Ripley"])
    assert {p.id for p in dropped} == {1, 4}
    assert {p.id for p in remaining} == {2, 3}


def test_one_bad_name_aborts_the_whole_request():
    """Partial application would field a team the user never approved."""
    dropped, remaining = apply_exclusions(POOL, ["Wing", "Nobody"])
    assert dropped is None
    assert len(remaining) == len(POOL)


def test_no_exclusions_leaves_the_pool_intact():
    dropped, remaining = apply_exclusions(POOL, [])
    assert dropped == []
    assert len(remaining) == len(POOL)


def test_ambiguity_resolves_with_a_fuller_name():
    dropped, _ = apply_exclusions(POOL, ["N. Smith"])
    assert dropped[0].club == "Tranmere Rovers"


@pytest.mark.parametrize("needle", ["Tranmere", "tranmere rovers", "N. SMITH"])
def test_various_ways_of_naming_the_same_player(needle):
    dropped, _ = apply_exclusions(POOL, [needle])
    assert dropped[0].id == 2
