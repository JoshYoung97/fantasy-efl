"""Tests for elite ownership.

No gameweek has locked, so nothing can be collected yet. These build the
payload the browser collector produces and check the aggregation handles it --
particularly the pre-lockout case, where every lineup is nulls and a naive
count would report 0% ownership for everyone rather than "no sample".
"""

from __future__ import annotations

import pytest

from fantasy_efl.elite import (
    MIN_SAMPLE,
    EliteOwnership,
    aggregate,
    differentials,
    load,
    save,
)


def team(user_id, gk=None, defs=(), mids=(), fwds=(), squads=(), captain=None, **chips):
    return {
        "userId": user_id,
        "formation": "1-2-3-1",
        "players": {"GK": [gk], "DEF": list(defs), "MID": list(mids), "FWD": list(fwds)},
        "squads": list(squads),
        "captainId": captain,
        "maxCaptain": chips.get("max_captain", False),
        "oneClub": chips.get("one_club", False),
    }


def payload(teams, round_id=1):
    return {"roundId": round_id, "collectedAt": "2026-08-16T06:00:00Z", "teams": teams}


def test_an_unlocked_gameweek_reports_no_sample_not_zero_ownership():
    """Every lineup is nulls until a gameweek locks.

    Counting those as squads owning nobody would give every player 0% elite
    ownership, which reads as "the good managers avoid him" rather than "we
    cannot see yet".
    """
    hidden = [team(i) for i in range(50)]
    result = aggregate(payload(hidden))
    assert result.sample == 0
    assert result.players == {}
    assert not result.usable


def test_ownership_is_a_share_of_the_visible_sample():
    teams = [team(1, gk=10, mids=[20]), team(2, gk=10, mids=[30]),
             team(3, gk=11, mids=[20])]
    result = aggregate(payload(teams))
    assert result.sample == 3
    assert result.players[10] == pytest.approx(66.7, abs=0.1)
    assert result.players[20] == pytest.approx(66.7, abs=0.1)
    assert result.players[30] == pytest.approx(33.3, abs=0.1)


def test_hidden_squads_are_excluded_from_the_denominator():
    """Mixing them in would understate everyone."""
    teams = [team(1, gk=10), team(2, gk=10), team(3), team(4)]
    result = aggregate(payload(teams))
    assert result.sample == 2
    assert result.players[10] == 100.0


def test_a_player_counts_once_per_squad():
    """Guards against a duplicate id inflating a percentage past 100."""
    teams = [team(1, gk=10, mids=[10, 10])]
    assert aggregate(payload(teams)).players[10] == 100.0


def test_club_picks_are_named_where_possible():
    teams = [team(1, gk=10, squads=[44, 12]), team(2, gk=11, squads=[44, 9])]
    result = aggregate(payload(teams), squads={44: "Tranmere Rovers", 12: "Bromley"})
    assert result.clubs["Tranmere Rovers"] == 100.0
    assert result.clubs["Bromley"] == 50.0
    assert result.clubs["9"] == 50.0  # unknown id falls back to the number


def test_captaincy_is_counted_separately_from_ownership():
    teams = [team(1, gk=10, mids=[20], captain=20),
             team(2, gk=10, mids=[20], captain=10)]
    result = aggregate(payload(teams))
    assert result.players[20] == 100.0
    assert result.captains[20] == 50.0


def test_effective_ownership_adds_captaincy():
    """A captain scores twice, so owning them is worth twice as much."""
    teams = [team(1, gk=10, mids=[20], captain=20),
             team(2, gk=11, mids=[20], captain=20)]
    result = aggregate(payload(teams))
    assert result.effective(20) == pytest.approx(200.0)
    assert result.effective(10) == pytest.approx(50.0)


def test_chip_usage_is_reported():
    teams = [team(1, gk=10, max_captain=True), team(2, gk=10), team(3, gk=10),
             team(4, gk=10, one_club=True)]
    result = aggregate(payload(teams))
    assert result.chips["maxCaptain"] == 25.0
    assert result.chips["oneClub"] == 25.0


def test_a_small_sample_is_not_treated_as_usable():
    teams = [team(i, gk=10) for i in range(MIN_SAMPLE - 1)]
    assert not aggregate(payload(teams)).usable
    teams.append(team(999, gk=10))
    assert aggregate(payload(teams)).usable


def test_differentials_surface_where_elite_and_field_disagree():
    """The whole reason for collecting this.

    A player on 8% overall and 40% among the top hundred is not a
    differential, whatever the headline ownership says.
    """
    elite = EliteOwnership(sample=100, players={1: 40.0, 2: 50.0, 3: 12.0})
    gaps = differentials(elite, overall={1: 8.0, 2: 48.0, 3: 45.0})
    assert [row[0] for row in gaps] == [1, 3]   # 2 moves too little to list
    assert gaps[0][1] == 40.0 and gaps[0][2] == 8.0
    assert gaps[-1][1] < gaps[-1][2]            # the field's pick the elite avoid


def test_storage_round_trips_with_integer_player_ids(tmp_path):
    """JSON turns keys into strings; every other module uses integer ids."""
    result = aggregate(payload([team(1, gk=10, mids=[20], captain=20)]))
    path = save(result, tmp_path / "elite.json")
    restored = load(path)
    assert restored.players[10] == 100.0
    assert restored.captains[20] == 100.0
    assert restored.sample == 1


def test_loading_before_anything_is_collected_is_empty_not_an_error(tmp_path):
    result = load(tmp_path / "nothing.json")
    assert result.sample == 0
    assert not result.usable
