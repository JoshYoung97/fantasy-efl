"""Tests for carrying a player's record across a season rollover.

The EFL feed reports season totals and zeroes them when a new season starts.
On the morning of the 2026/27 opener every one of 3,453 players read as having
no EFL record, the model fell back to position priors for the entire pool, and
a 6.61-point midfielder projected 1.96. Nothing errored -- the numbers were
simply wrong, and would have been published.

The dangerous failure here is the opposite one: mistaking something else for a
rollover and adding a season to itself. These pin both directions.
"""

from __future__ import annotations

from fantasy_efl.pipeline import (
    CARRIED_STATS,
    _appearance_total,
    _find_season_baseline,
    _merge_history,
)


def player(pid, apps, goals=0, interceptions=0, **extra):
    row = {
        "id": pid, "appearances": apps, "goalsScored": goals,
        "interceptions": interceptions, "assists": 0, "cleanSheets": 0,
        "saves": 0, "clearances": 0, "blocks": 0, "tackles": 0,
        "keyPasses": 0, "shotsOnTarget": 0,
    }
    row.update(extra)
    return row


# ---- merging -------------------------------------------------------------

def test_totals_are_summed_across_the_boundary():
    current = [player(1, 3, goals=1, interceptions=4)]
    previous = [player(1, 46, goals=11, interceptions=61)]
    merged, carried = _merge_history(current, previous)
    assert carried == 1
    assert merged[0]["appearances"] == 49
    assert merged[0]["goalsScored"] == 12
    assert merged[0]["interceptions"] == 65


def test_a_reset_player_recovers_the_previous_seasons_record():
    """The actual case: the new season has not started for him yet."""
    merged, _ = _merge_history([player(1, 0)], [player(1, 46, goals=11)])
    assert merged[0]["appearances"] == 46
    assert merged[0]["goalsScored"] == 11


def test_a_new_signing_is_left_alone():
    """Nobody to carry forward, and inventing a record would be worse."""
    merged, carried = _merge_history([player(9, 2, goals=1)], [player(1, 46)])
    assert carried == 0
    assert merged[0]["appearances"] == 2


def test_current_state_fields_are_not_added_up():
    """Ownership and status describe now, not an accumulated total."""
    current = [player(1, 0, percentSelected=28.4, status="playing", jerseyNum=8)]
    previous = [player(1, 46, percentSelected=30.1, status="injured", jerseyNum=8)]
    merged, _ = _merge_history(current, previous)
    assert merged[0]["percentSelected"] == 28.4
    assert merged[0]["status"] == "playing"


def test_merging_does_not_mutate_the_input():
    current = [player(1, 0)]
    _merge_history(current, [player(1, 46)])
    assert current[0]["appearances"] == 0


def test_every_carried_stat_is_a_counting_stat():
    """A guard on the list itself: nothing current-state may creep in."""
    for field in ("percentSelected", "status", "jerseyNum", "averagePoints",
                  "roundPoints", "position", "squadId"):
        assert field not in CARRIED_STATS


# ---- detection -----------------------------------------------------------

def test_a_fall_in_appearances_finds_the_baseline():
    snaps = ["a", "b", "c"]
    data = {"a": [player(1, 46)], "b": [player(1, 46)], "c": [player(1, 0)]}
    found = _find_season_baseline(snaps, data["c"], load=data.get)
    assert found is not None
    assert found[0] == "b"


def test_no_rollover_while_totals_only_grow():
    """Every run until the day a season turns over."""
    snaps = ["a", "b", "c"]
    data = {"a": [player(1, 3)], "b": [player(1, 5)], "c": [player(1, 9)]}
    assert _find_season_baseline(snaps, data["c"], load=data.get) is None


def test_a_small_dip_is_not_treated_as_a_new_season():
    """A truncated capture must not cause a season to be added to itself."""
    snaps = ["a", "b"]
    data = {"a": [player(1, 46), player(2, 40)], "b": [player(1, 46)]}
    assert _find_season_baseline(snaps, data["b"], load=data.get) is None


def test_the_most_recent_pre_reset_snapshot_wins():
    """The freshest view of the old season, not the oldest."""
    snaps = ["old", "newer", "current"]
    data = {"old": [player(1, 40)], "newer": [player(1, 46)], "current": [player(1, 1)]}
    assert _find_season_baseline(snaps, data["current"], load=data.get)[0] == "newer"


def test_a_single_snapshot_cannot_roll_over():
    assert _find_season_baseline(["only"], [player(1, 0)], load=lambda s: []) is None


def test_appearance_total_tolerates_missing_and_null_fields():
    assert _appearance_total([{"id": 1}, {"id": 2, "appearances": None},
                              {"id": 3, "appearances": 4}]) == 4
