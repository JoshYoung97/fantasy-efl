"""Tests for deciding which round is the current one.

The feed's round status reads "completed". Three separate places had grown
their own check against "complete", which never matched -- so the page pinned
itself to GW1 permanently. It published GW1's name, deadline and kickoff
times alongside the pipeline's GW2 fixtures, and because GW1's kickoffs are in
the past the Live view showed every player as already locked.

Played-ness is therefore derived from the fixtures themselves. These pin that,
including against the exact spelling that caused the bug.
"""

from __future__ import annotations

from fantasy_efl.snapshot import _current_round, is_played, round_complete


def game(home=None, away=None, final=False):
    return {"homeScore": home, "awayScore": away, "isFinalized": final}


def rnd(number, games, status="scheduled"):
    return {"roundNumber": number, "gameMode": "season",
            "status": status, "games": games}


def test_a_scoreline_means_played():
    assert is_played(game(2, 2))
    assert is_played(game(0, 0))          # 0-0 is a result, not a missing one


def test_finalized_counts_even_without_a_score():
    assert is_played(game(final=True))


def test_an_unplayed_fixture_is_not_played():
    assert not is_played(game())


def test_a_round_is_complete_only_when_every_game_is():
    assert round_complete(rnd(1, [game(1, 0), game(2, 2)]))
    assert not round_complete(rnd(1, [game(1, 0), game()]))


def test_an_empty_round_is_not_complete():
    """No fixtures is no evidence, and must not advance the gameweek."""
    assert not round_complete(rnd(1, []))


def test_the_feeds_own_spelling_does_not_decide_it():
    """The bug, pinned directly.

    A round the feed calls "completed" whose games have all been played is
    complete; one it calls "completed" whose games have not been played is
    not. Either way the status string is not what decides.
    """
    assert round_complete(rnd(1, [game(1, 0)], status="completed"))
    assert not round_complete(rnd(1, [game()], status="completed"))


def test_current_round_advances_once_a_round_finishes():
    rounds = [rnd(1, [game(2, 2)], status="completed"),
              rnd(2, [game()], status="playing")]
    assert _current_round(rounds) == 2


def test_current_round_stays_put_while_a_round_is_mid_flight():
    rounds = [rnd(1, [game(2, 2), game()], status="playing"),
              rnd(2, [game()])]
    assert _current_round(rounds) == 1


def test_playoff_rounds_do_not_hijack_the_gameweek():
    """Playoffs reuse round numbers and carry no fixtures."""
    rounds = [rnd(1, [game(2, 2)], status="completed"),
              {"roundNumber": 1, "gameMode": "playoff", "status": "scheduled",
               "games": []},
              rnd(2, [game()])]
    assert _current_round(rounds) == 2
