"""Planning club selections across the season.

Two clubs each gameweek, and no club more than five times all season. That is
84 selections drawn from 360 club-uses, and it is a genuine optimisation
rather than a weekly greedy choice: taking a strong club this week costs you
one of only five chances to use them, and their best fixture may be in March.

Doubles turn out not to be the constraint. Across 39 scheduled gameweeks there
are 744 club-doubles available for 84 selections, so every pick could be a
double several times over. What actually decides the plan is which clubs are
worth spending a use on -- and how good a club is cannot yet be measured,
because bookmakers price three days ahead and one round of odds leaves club
strength mathematically unidentifiable.

So the solver takes strength as an input rather than inventing one. Fed a
uniform strength it maximises fixtures covered, which is a sound plan and no
worse than guessing. Fed real ratings -- derivable once several gameweeks of
odds have accumulated and clubs have met different opponents -- it becomes the
season plan proper, with no change here.

Solved exactly by min-cost flow rather than by taking the best two clubs each
week, which is not optimal: a club used early on a middling fixture is
unavailable for a better one later, and greedy cannot see that.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

MAX_USES_PER_CLUB = 5
CLUBS_PER_GAMEWEEK = 2


class _Flow:
    """Min-cost max-flow, successive shortest paths with SPFA.

    Costs are negative here -- we are maximising value -- so Dijkstra with
    potentials would need reweighting; SPFA handles negative edges directly and
    the graph is small enough that it does not matter.
    """

    def __init__(self, nodes: int) -> None:
        self.graph: list[list[list]] = [[] for _ in range(nodes)]

    def add(self, u: int, v: int, capacity: int, cost: float) -> None:
        self.graph[u].append([v, capacity, cost, len(self.graph[v])])
        self.graph[v].append([u, 0, -cost, len(self.graph[u]) - 1])

    def solve(self, source: int, sink: int, want: int) -> float:
        total = 0.0
        n = len(self.graph)
        while want > 0:
            dist = [float("inf")] * n
            in_queue = [False] * n
            prev_node = [-1] * n
            prev_edge = [-1] * n
            dist[source] = 0.0
            queue = deque([source])
            in_queue[source] = True

            while queue:
                u = queue.popleft()
                in_queue[u] = False
                for i, (v, cap, cost, _) in enumerate(self.graph[u]):
                    if cap > 0 and dist[u] + cost < dist[v] - 1e-12:
                        dist[v] = dist[u] + cost
                        prev_node[v], prev_edge[v] = u, i
                        if not in_queue[v]:
                            in_queue[v] = True
                            queue.append(v)

            if dist[sink] == float("inf"):
                break  # no augmenting path; the plan is as full as it can be

            # Push as much as the tightest edge on the path allows.
            push, v = want, sink
            while v != source:
                push = min(push, self.graph[prev_node[v]][prev_edge[v]][1])
                v = prev_node[v]
            v = sink
            while v != source:
                edge = self.graph[prev_node[v]][prev_edge[v]]
                edge[1] -= push
                self.graph[v][edge[3]][1] += push
                v = prev_node[v]

            total += push * dist[sink]
            want -= push
        return total

    def used(self, u: int, v: int) -> int:
        """How much flow ran along the edge u -> v."""
        for target, cap, _, rev in self.graph[u]:
            if target == v:
                return self.graph[v][rev][1]
        return 0


@dataclass
class SeasonPlan:
    """Which clubs to use in which gameweeks."""

    picks: dict[int, list[str]]
    value: float
    fixtures_covered: int
    uses: dict[str, int]
    unfilled: list[int]

    @property
    def doubles_used(self) -> int:
        return self.fixtures_covered - sum(len(v) for v in self.picks.values())


def plan_season(
    fixtures: dict[str, dict[int, int]],
    strength: dict[str, float] | None = None,
    *,
    max_uses: int = MAX_USES_PER_CLUB,
    per_gameweek: int = CLUBS_PER_GAMEWEEK,
    gameweeks: list[int] | None = None,
) -> SeasonPlan:
    """Assign clubs to gameweeks, maximising total value.

    `fixtures` maps club name to {gameweek: number of fixtures}. `strength` is
    a per-club multiplier; uniform if omitted, which reduces the objective to
    fixtures covered.

    A club's value in a gameweek is its strength times its fixture count, so a
    double is worth twice a single for the same club -- which is exactly how
    the scoring works.
    """
    strength = strength or {}
    rounds = sorted(gameweeks or {g for byround in fixtures.values() for g in byround})
    clubs = sorted(fixtures)

    source = 0
    club_node = {c: 1 + i for i, c in enumerate(clubs)}
    week_node = {g: 1 + len(clubs) + i for i, g in enumerate(rounds)}
    sink = 1 + len(clubs) + len(rounds)

    flow = _Flow(sink + 1)
    for club in clubs:
        flow.add(source, club_node[club], max_uses, 0.0)
        for week, count in fixtures[club].items():
            if week not in week_node or count <= 0:
                continue
            # Negative because the flow minimises and we want maximum value.
            flow.add(club_node[club], week_node[week], 1,
                     -strength.get(club, 1.0) * count)
    for week in rounds:
        flow.add(week_node[week], sink, per_gameweek, 0.0)

    cost = flow.solve(source, sink, per_gameweek * len(rounds))

    picks: dict[int, list[str]] = {g: [] for g in rounds}
    uses: dict[str, int] = {}
    covered = 0
    for club in clubs:
        for week in fixtures[club]:
            if week in week_node and flow.used(club_node[club], week_node[week]):
                picks[week].append(club)
                uses[club] = uses.get(club, 0) + 1
                covered += fixtures[club][week]

    return SeasonPlan(
        picks={g: sorted(v) for g, v in picks.items()},
        value=-cost,
        fixtures_covered=covered,
        uses=uses,
        unfilled=[g for g in rounds if len(picks[g]) < per_gameweek],
    )


def fixtures_by_club(rounds: list[dict], squads: dict[int, str]) -> dict[str, dict[int, int]]:
    """Fixture counts per club per gameweek, from the stored fixture list."""
    out: dict[str, dict[int, int]] = {name: {} for name in squads.values()}
    for rnd in rounds:
        if rnd.get("gameMode") != "season":
            continue
        week = rnd["roundNumber"]
        for game in rnd.get("games", []):
            for side in ("homeId", "awayId"):
                name = squads.get(game[side])
                if name:
                    out[name][week] = out[name].get(week, 0) + 1
    return {name: weeks for name, weeks in out.items() if weeks}
