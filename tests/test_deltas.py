"""Tests for reconstructing match data from consecutive snapshots.

No gameweek has been played, so every case here is synthetic: a snapshot pair
built around a match whose facts are known, checked against what the
reconstruction recovers. The point is that this works on the first real
gameweek rather than being debugged during one.
"""

from __future__ import annotations

import gzip
import json

import pytest

from fantasy_efl.deltas import (
    MatchLine,
    build_history,
    calibrate,
    load_history,
    reconstruct,
    save_history,
    summarise,
)
from fantasy_efl.scoring import PlayerMatch, score_player

BLANK = {
    "totalPoints": 0, "appearances": 0, "goalsScored": 0, "assists": 0,
    "cleanSheets": 0, "clearances": 0, "blocks": 0, "tackles": 0,
    "interceptions": 0, "saves": 0, "keyPasses": 0, "shotsOnTarget": 0,
}


def write_snapshot(root, name, players, squads=None):
    """Write a snapshot directory the loader will accept."""
    path = root / name
    path.mkdir(parents=True, exist_ok=True)
    squads = squads or [{"id": 1, "name": "Alpha"}]
    for feed, payload in (("players", players), ("squads", squads)):
        with gzip.open(path / f"{feed}.json.gz", "wt", encoding="utf-8") as fh:
            json.dump(payload, fh)
    (path / "manifest.json").write_text("{}", encoding="utf-8")
    return path


def player(pid=1, position="DEF", **stats):
    row = {"id": pid, "displayName": f"P{pid}", "position": position,
           "squadId": 1, **BLANK}
    row.update(stats)
    return row


def pair(tmp_path, before, after):
    a = write_snapshot(tmp_path, "2026-08-15T060000Z", before)
    b = write_snapshot(tmp_path, "2026-08-16T060000Z", after)
    return reconstruct(a, b)


def test_only_players_whose_totals_moved_are_reported(tmp_path):
    lines = pair(
        tmp_path,
        [player(1), player(2)],
        [player(1, appearances=1, totalPoints=2), player(2)],
    )
    assert [ln.player_id for ln in lines] == [1]


def test_a_new_player_is_skipped_rather_than_counted_from_zero(tmp_path):
    """Without a baseline, their season total would read as one match."""
    lines = pair(tmp_path, [player(1)], [player(1), player(2, appearances=30,
                                                        totalPoints=150)])
    assert [ln.player_id for ln in lines] == []


def test_counting_stats_are_differenced(tmp_path):
    lines = pair(
        tmp_path,
        [player(1, appearances=5, clearances=40, totalPoints=25)],
        [player(1, appearances=6, clearances=47, totalPoints=29)],
    )
    assert lines[0].appearances == 1
    assert lines[0].clearances == 7
    assert lines[0].points == 4


def test_a_full_match_with_no_card_leaves_a_residual_of_two(tmp_path):
    """The whole inference rests on this: everything else is observable."""
    match = PlayerMatch(position="DEF", minutes=90, clearances=8, tackles=4)
    lines = pair(
        tmp_path,
        [player(1)],
        [player(1, appearances=1, clearances=8, tackles=4,
                totalPoints=score_player(match))],
    )
    assert lines[0].residual == 2
    assert lines[0].played_full is True


def test_a_booking_shows_up_as_a_smaller_residual(tmp_path):
    match = PlayerMatch(position="DEF", minutes=90, clearances=8, tackles=4,
                        yellow_cards=1)
    lines = pair(
        tmp_path,
        [player(1)],
        [player(1, appearances=1, clearances=8, tackles=4,
                totalPoints=score_player(match))],
    )
    assert lines[0].residual == 1


def test_a_short_appearance_also_leaves_one(tmp_path):
    """Which is exactly why a residual of 1 cannot be resolved on its own."""
    match = PlayerMatch(position="DEF", minutes=30, clearances=8, tackles=4)
    lines = pair(
        tmp_path,
        [player(1)],
        [player(1, appearances=1, clearances=8, tackles=4,
                totalPoints=score_player(match))],
    )
    assert lines[0].residual == 1
    assert lines[0].played_full is None  # honest about the ambiguity


def test_a_clean_sheet_settles_it_regardless_of_the_residual(tmp_path):
    """A clean sheet needs sixty minutes, so it answers the question outright."""
    match = PlayerMatch(position="DEF", minutes=90, clean_sheet=True,
                        clearances=8, yellow_cards=1)
    lines = pair(
        tmp_path,
        [player(1)],
        [player(1, appearances=1, cleanSheets=1, clearances=8,
                totalPoints=score_player(match))],
    )
    assert lines[0].played_full is True


@pytest.mark.parametrize("position,stats,match", [
    ("MID", {"interceptions": 3, "keyPasses": 4, "shotsOnTarget": 2},
     dict(interceptions=3, key_passes=4, shots_on_target=2)),
    ("FWD", {"goalsScored": 2, "shotsOnTarget": 3},
     dict(goals=2, shots_on_target=3)),
    ("GK", {"saves": 7, "cleanSheets": 1}, dict(saves=7, clean_sheet=True)),
])
def test_observable_points_agree_with_the_scoring_rules(tmp_path, position, stats, match):
    """The reconstruction must read the rules the same way the engine does."""
    full = PlayerMatch(position=position, minutes=90, **match)
    lines = pair(tmp_path, [player(1, position=position)],
                 [player(1, position=position, appearances=1,
                         totalPoints=score_player(full), **stats)])
    assert lines[0].observable_points == score_player(full) - 2


def test_a_hat_trick_bonus_is_accounted_for(tmp_path):
    full = PlayerMatch(position="FWD", minutes=90, goals=3)
    lines = pair(tmp_path, [player(1, position="FWD")],
                 [player(1, position="FWD", appearances=1, goalsScored=3,
                         totalPoints=score_player(full))])
    assert lines[0].residual == 2


def test_a_line_covering_two_fixtures_declines_to_infer_minutes(tmp_path):
    """A double gameweek, or a missed snapshot, merges fixtures."""
    lines = pair(tmp_path, [player(1)],
                 [player(1, appearances=2, clearances=12, totalPoints=8)])
    assert lines[0].appearances == 2
    assert lines[0].played_full is None


def test_history_is_built_across_every_consecutive_pair(tmp_path):
    write_snapshot(tmp_path, "2026-08-15T060000Z", [player(1)])
    write_snapshot(tmp_path, "2026-08-16T060000Z",
                   [player(1, appearances=1, totalPoints=2)])
    write_snapshot(tmp_path, "2026-08-17T060000Z",
                   [player(1, appearances=2, totalPoints=5)])
    lines = build_history(tmp_path)
    assert len(lines) == 2
    assert [ln.points for ln in lines] == [2, 3]


def test_history_round_trips(tmp_path):
    lines = [MatchLine(player_id=1, name="P1", position="DEF", club="Alpha",
                       from_snapshot="a", to_snapshot="b", appearances=1, points=6)]
    path = save_history(lines, tmp_path / "matches.json")
    assert [ln.player_id for ln in load_history(path)] == [1]


def test_loading_a_missing_history_is_empty_not_an_error():
    assert load_history(pytest.importorskip("pathlib").Path("nope.json")) == []


def make_lines(n_full, n_short):
    """Synthetic single-appearance lines with known minutes."""
    lines = []
    for i in range(n_full):
        m = PlayerMatch(position="DEF", minutes=90, clearances=8)
        lines.append(MatchLine(player_id=i, name="x", position="DEF", club="A",
                               from_snapshot="a", to_snapshot="b", appearances=1,
                               points=score_player(m), clearances=8))
    for i in range(n_short):
        m = PlayerMatch(position="DEF", minutes=30, clearances=4)
        lines.append(MatchLine(player_id=1000 + i, name="y", position="DEF", club="A",
                               from_snapshot="a", to_snapshot="b", appearances=1,
                               points=score_player(m), clearances=4))
    return lines


def test_calibration_recovers_the_share_of_full_matches():
    """This is what replaces START_SHARE, the model's largest assumption."""
    result = calibrate(make_lines(n_full=700, n_short=300))
    assert result.start_share == pytest.approx(0.70, abs=0.02)


def test_calibration_reports_when_there_is_too_little_evidence():
    assert not calibrate(make_lines(10, 5)).usable
    assert calibrate(make_lines(700, 300)).usable


def test_calibration_ignores_lines_covering_several_fixtures():
    lines = make_lines(100, 100)
    lines.append(MatchLine(player_id=99, name="z", position="DEF", club="A",
                           from_snapshot="a", to_snapshot="b", appearances=3,
                           points=20))
    assert calibrate(lines).single_appearance_lines == 200


def test_calibration_of_an_empty_history_is_harmless():
    result = calibrate([])
    assert result.start_share is None
    assert not result.usable


def test_summary_describes_what_has_been_reconstructed():
    summary = summarise(make_lines(3, 2))
    assert summary["lines"] == 5
    assert summary["appearances"] == 5
    assert summary["by_position"] == {"DEF": 5}


def test_minutes_and_cards_are_solved_together_not_in_sequence():
    """Counting only unambiguous residuals underestimates both.

    A full match with a booking has residual 1, indistinguishable from a clean
    short appearance. Treating those as short understates the start rate by
    roughly the card rate, and hides the bookings entirely -- on simulated data
    that read 0.64 against a true 0.72, with cards about half their real value.
    """
    from fantasy_efl.deltas import _solve_minutes_and_cards

    lines = []
    pid = 0
    # 720 full matches, 120 of them booked; 280 short, 47 booked.
    for count, minutes, booked in ((600, 90, 0), (120, 90, 1),
                                   (233, 30, 0), (47, 30, 1)):
        for _ in range(count):
            pid += 1
            m = PlayerMatch(position="DEF", minutes=minutes, clearances=6,
                            yellow_cards=booked)
            lines.append(MatchLine(player_id=pid, name="x", position="DEF",
                                   club="A", from_snapshot="a", to_snapshot="b",
                                   appearances=1, points=score_player(m),
                                   clearances=6))

    start_share, card_rate = _solve_minutes_and_cards(lines)
    assert start_share == pytest.approx(0.72, abs=0.04)
    assert card_rate == pytest.approx(0.167, abs=0.05)

    # The naive count is the thing this replaces.
    naive = sum(1 for ln in lines if ln.residual >= 2) / len(lines)
    assert naive < start_share - 0.05


def test_an_unrepresentable_split_falls_back_to_the_boundary():
    """Near the boundary, noise can put the shares outside the model.

    Returning no cards at all would be the worst answer available; the closest
    consistent point is not.
    """
    from fantasy_efl.deltas import _solve_minutes_and_cards

    lines = []
    for i in range(300):
        m = PlayerMatch(position="MID", minutes=90 if i % 3 else 30,
                        interceptions=2, yellow_cards=1 if i % 5 == 0 else 0)
        lines.append(MatchLine(player_id=i, name="x", position="MID", club="A",
                               from_snapshot="a", to_snapshot="b", appearances=1,
                               points=score_player(m), interceptions=2))
    start_share, card_rate = _solve_minutes_and_cards(lines)
    assert 0 < card_rate < 0.9
    assert 0 < start_share <= 1.0


def test_per_position_rates_are_withheld_until_there_is_enough_data():
    """A noisy per-position figure is worse than none: it looks authoritative."""
    from fantasy_efl.deltas import MIN_POSITION_LINES

    small = calibrate(make_lines(60, 40))
    assert small.card_cost == {}
    assert MIN_POSITION_LINES >= 200


def test_dispersion_ignores_positions_that_never_record_the_stat():
    """A midfielder's clearances are structurally zero, not genuinely zero.

    Pooling them in inflates the variance so far that every stat reports a
    dispersion near zero, which would tell the model these counts are wildly
    overdispersed when they are not.
    """
    lines = []
    # Overdispersed, as real counting stats are: mostly low, occasionally high.
    # A negative binomial only exists where variance exceeds the mean.
    for i in range(300):
        lines.append(MatchLine(player_id=i, name="d", position="DEF", club="A",
                               from_snapshot="a", to_snapshot="b", appearances=1,
                               points=4, clearances=30 if i % 10 == 0 else 2))
    for i in range(300):
        lines.append(MatchLine(player_id=1000 + i, name="m", position="MID",
                               club="A", from_snapshot="a", to_snapshot="b",
                               appearances=1, points=4, clearances=0))

    scoped = calibrate(lines).stat_dispersion
    assert "clearances" in scoped

    # Pooling the midfielders in would roughly double the variance while
    # halving the mean, collapsing the dispersion estimate.
    defenders_only = scoped["clearances"]
    pooled_mean = sum(ln.clearances for ln in lines) / len(lines)
    defence_mean = sum(ln.clearances for ln in lines if ln.position == "DEF") / 300
    assert pooled_mean < defence_mean / 1.5
    assert defenders_only > 0.1
