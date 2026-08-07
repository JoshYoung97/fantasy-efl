"""Tests for the FPL goalkeeper backfill.

The main risks are matching the wrong keeper (which would import another club's
entire record) and overwriting real EFL data once the season starts, so both
are covered explicitly.
"""

from __future__ import annotations

from fantasy_efl.fpl_backfill import (
    EFL_SEASON_GAMES,
    GOALKEEPER,
    PL_SEASON_GAMES,
    apply_backfill,
    match_keepers,
)


def efl_keeper(pid=1, first="James", last="Trafford", appearances=0, position="GK"):
    return {
        "id": pid, "firstName": first, "lastName": last,
        "displayName": f"{first[0]}. {last}", "position": position,
        "appearances": appearances, "saves": 0, "cleanSheets": 0,
        "clearances": 0, "blocks": 0, "tackles": 0, "interceptions": 0,
        "goalsScored": 0, "assists": 0, "keyPasses": 0, "shotsOnTarget": 0,
        "status": "playing",
    }


def fpl_keeper(first="James", last="Trafford", saves=100, clean_sheets=10,
               minutes=3420, starts=38, element_type=GOALKEEPER):
    return {
        "first_name": first, "second_name": last, "web_name": last,
        "element_type": element_type, "saves": saves,
        "clean_sheets": clean_sheets, "minutes": minutes, "starts": starts,
    }


def test_matches_on_surname_and_initial():
    matched, ambiguous = match_keepers([efl_keeper()], [fpl_keeper()])
    assert len(matched) == 1
    assert not ambiguous
    assert matched[0].fpl_name == "Trafford"


def test_different_initial_is_not_matched():
    matched, _ = match_keepers(
        [efl_keeper(first="Alan")], [fpl_keeper(first="James")]
    )
    assert matched == []


def test_shared_initial_resolves_on_the_full_first_name():
    """James, Joe and Jack all share an initial, so it alone is too weak."""
    matched, ambiguous = match_keepers(
        [efl_keeper(first="James", last="Smith")],
        [fpl_keeper(first="James", last="Smith", saves=120),
         fpl_keeper(first="Joe", last="Smith", saves=20)],
    )
    assert len(matched) == 1
    assert matched[0].saves > 0
    assert not ambiguous


def test_genuinely_ambiguous_surnames_are_flagged_not_guessed():
    """Importing the wrong keeper would carry another club's whole record."""
    matched, ambiguous = match_keepers(
        [efl_keeper(first="J", last="Smith")],  # initial only, two J candidates
        [fpl_keeper(first="James", last="Smith", saves=120),
         fpl_keeper(first="Jack", last="Smith", saves=20)],
    )
    assert matched == []
    assert len(ambiguous) == 1
    assert set(ambiguous[0]["candidates"]) == {"Smith"}


def test_outfield_players_are_ignored():
    matched, _ = match_keepers([efl_keeper(position="DEF")], [fpl_keeper()])
    assert matched == []


def test_players_with_existing_efl_history_are_skipped():
    matched, _ = match_keepers([efl_keeper(appearances=20)], [fpl_keeper()])
    assert matched == []


def test_keepers_who_did_not_play_are_skipped():
    matched, _ = match_keepers([efl_keeper()], [fpl_keeper(minutes=0, starts=0)])
    assert matched == []


def test_outfield_fpl_players_are_never_used_as_a_source():
    matched, _ = match_keepers([efl_keeper()], [fpl_keeper(element_type=3)])
    assert matched == []


def test_totals_are_rescaled_to_an_efl_length_season():
    matched, _ = match_keepers([efl_keeper()], [fpl_keeper(starts=38, clean_sheets=10)])
    keeper = matched[0]
    assert keeper.appearances == EFL_SEASON_GAMES
    # Clean sheets scale with the longer season.
    assert keeper.clean_sheets > 10
    assert keeper.clean_sheets == round(10 * EFL_SEASON_GAMES / PL_SEASON_GAMES)


def test_save_rate_is_damped_for_the_easier_division():
    matched, _ = match_keepers([efl_keeper()], [fpl_keeper(saves=100, starts=38)])
    per_game = matched[0].saves / matched[0].appearances
    assert per_game < 100 / PL_SEASON_GAMES  # damped, not transferred raw


def test_backfill_writes_only_the_keeper_fields():
    players = [efl_keeper()]
    matched, _ = match_keepers(players, [fpl_keeper()])
    assert apply_backfill(players, matched) == 1
    assert players[0]["saves"] > 0
    assert players[0]["appearances"] > 0
    assert players[0]["backfilled"] == "fpl"
    # Outfield stats must stay zero -- they cannot be derived from FPL.
    for field in ("clearances", "blocks", "tackles", "interceptions"):
        assert players[0][field] == 0


def test_backfill_never_overwrites_real_efl_data():
    """Re-running mid-season must not replace live stats with stale ones."""
    players = [efl_keeper()]
    matched, _ = match_keepers(players, [fpl_keeper()])

    players[0]["appearances"] = 5
    players[0]["saves"] = 12
    assert apply_backfill(players, matched) == 0
    assert players[0]["saves"] == 12


def test_backfill_ignores_unknown_ids():
    matched, _ = match_keepers([efl_keeper(pid=1)], [fpl_keeper()])
    assert apply_backfill([efl_keeper(pid=99)], matched) == 0
