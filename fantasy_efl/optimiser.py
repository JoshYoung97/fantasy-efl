"""Choosing the best legal squad for a gameweek.

Picking greedily by projection does not work: the two-players-per-club limit
means the best seven players are usually an illegal team, and dropping the
third player from a club can cascade into a different formation entirely.

The search is exact rather than heuristic. Because no club can contribute more
than two players, each club's contribution collapses to a handful of options --
take nobody, take the best player in some position, or take the best pair
covering two positions. That makes a dynamic program over clubs tractable:
the state is just how many of each position have been filled, which is bounded
by the formation, so there are only a few thousand states.

The captain is handled by search rather than assumed. Doubling one player makes
the objective sum(squad) + max(squad), which is not separable, so the optimum
is not always "best squad, then captain its best player" -- sometimes a
slightly weaker squad built around a bigger captain wins. Each plausible
captain is therefore forced in and the remainder re-optimised.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations_with_replacement

from .player_model import PlayerProjection

POSITIONS = ("GK", "DEF", "MID", "FWD")
_INDEX = {pos: i for i, pos in enumerate(POSITIONS)}

#: The three formations the game allows, as (GK, DEF, MID, FWD).
FORMATIONS: dict[str, tuple[int, int, int, int]] = {
    "1-2-2-2": (1, 2, 2, 2),
    "1-2-3-1": (1, 2, 3, 1),
    "1-3-2-1": (1, 3, 2, 1),
}

SQUAD_SIZE = 7
MAX_PER_CLUB = 2

#: How many of the top-projected players to test as captain. The captain is
#: almost always among the very best, but not always the single best, so this
#: is set well above the point where the answer stops changing.
CAPTAIN_CANDIDATES = 40


@dataclass(frozen=True)
class Squad:
    """A legal selection with its captain chosen."""

    players: tuple[PlayerProjection, ...]
    captain: PlayerProjection
    vice_captain: PlayerProjection | None
    clubs: tuple
    formation: str

    @property
    def expected_points(self) -> float:
        """Squad total plus the captain's points again, plus both clubs."""
        base = sum(p.expected_points for p in self.players)
        clubs = sum(c.expected_points for c in self.clubs)
        return base + self.captain.expected_points + clubs

    def counts(self) -> dict[str, int]:
        counts = {pos: 0 for pos in POSITIONS}
        for p in self.players:
            counts[p.position] += 1
        return counts


def _club_options(
    players: list[PlayerProjection], limit: int
) -> list[tuple[tuple[int, ...], float, tuple[PlayerProjection, ...]]]:
    """Every way one club can contribute, as (position counts, value, players).

    Only the best player per position and the best pair per position
    combination can ever be optimal, so the rest are discarded.
    """
    by_position: dict[str, list[PlayerProjection]] = {pos: [] for pos in POSITIONS}
    for p in players:
        by_position[p.position].append(p)
    for pos in by_position:
        by_position[pos].sort(key=lambda p: p.expected_points, reverse=True)

    options = [((0, 0, 0, 0), 0.0, ())]

    if limit >= 1:
        for pos, ranked in by_position.items():
            if ranked:
                counts = [0, 0, 0, 0]
                counts[_INDEX[pos]] = 1
                options.append((tuple(counts), ranked[0].expected_points, (ranked[0],)))

    if limit >= 2:
        for first, second in combinations_with_replacement(POSITIONS, 2):
            if first == second:
                ranked = by_position[first]
                if len(ranked) < 2:
                    continue
                pair = (ranked[0], ranked[1])
            else:
                if not by_position[first] or not by_position[second]:
                    continue
                pair = (by_position[first][0], by_position[second][0])

            counts = [0, 0, 0, 0]
            for p in pair:
                counts[_INDEX[p.position]] += 1
            options.append(
                (tuple(counts), sum(p.expected_points for p in pair), pair)
            )

    return options


def _solve(
    players_by_club: dict[str, list[PlayerProjection]],
    target: tuple[int, int, int, int],
    club_limits: dict[str, int],
) -> tuple[float, tuple[PlayerProjection, ...]] | None:
    """Best squad exactly matching `target`, respecting per-club limits.

    Dynamic program over clubs; state is the position counts filled so far.
    """
    # state -> (value, players)
    states: dict[tuple[int, ...], tuple[float, tuple[PlayerProjection, ...]]] = {
        (0, 0, 0, 0): (0.0, ())
    }

    for club, roster in players_by_club.items():
        limit = club_limits.get(club, MAX_PER_CLUB)
        if limit <= 0:
            continue
        options = _club_options(roster, limit)
        if len(options) == 1:
            continue  # nothing this club can offer

        nxt: dict[tuple[int, ...], tuple[float, tuple[PlayerProjection, ...]]] = {}
        for state, (value, chosen) in states.items():
            for counts, gain, picks in options:
                new_state = tuple(a + b for a, b in zip(state, counts))
                if any(n > t for n, t in zip(new_state, target)):
                    continue  # overshot a position; prune
                candidate = value + gain
                best = nxt.get(new_state)
                if best is None or candidate > best[0]:
                    nxt[new_state] = (candidate, chosen + picks)
        states = nxt

    return states.get(target)


def optimise_gameweek(
    projections: list[PlayerProjection],
    clubs: list,
    *,
    formations: dict[str, tuple[int, int, int, int]] | None = None,
    one_club_chip: bool = False,
) -> Squad | None:
    """Best legal squad across every allowed formation and captain choice.

    `one_club_chip` lifts the two-per-club limit for the gameweek.
    """
    playable = [p for p in projections if p.expected_points > 0]
    if not playable:
        return None

    by_club: dict[str, list[PlayerProjection]] = {}
    for p in playable:
        by_club.setdefault(p.club, []).append(p)

    default_limit = SQUAD_SIZE if one_club_chip else MAX_PER_CLUB
    candidates = sorted(playable, key=lambda p: p.expected_points, reverse=True)[
        :CAPTAIN_CANDIDATES
    ]

    best_clubs = tuple(
        sorted(clubs, key=lambda c: c.expected_points, reverse=True)[:2]
    )

    best: Squad | None = None

    for name, target in (formations or FORMATIONS).items():
        for captain in candidates:
            # Force the captain in by pre-filling their slot and charging their
            # club one of its places.
            remaining = list(target)
            remaining[_INDEX[captain.position]] -= 1
            if remaining[_INDEX[captain.position]] < 0:
                continue

            limits = {club: default_limit for club in by_club}
            limits[captain.club] = default_limit - 1

            pool = {
                club: [p for p in roster if p.id != captain.id]
                for club, roster in by_club.items()
            }

            solved = _solve(pool, tuple(remaining), limits)
            if solved is None:
                continue

            value, others = solved
            squad = (captain,) + others
            vice = max(
                (p for p in squad if p.id != captain.id),
                key=lambda p: p.expected_points,
                default=None,
            )
            candidate = Squad(
                players=squad,
                captain=captain,
                vice_captain=vice,
                clubs=best_clubs,
                formation=name,
            )
            if best is None or candidate.expected_points > best.expected_points:
                best = candidate

    return best
