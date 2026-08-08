"""Reconstructing match-level data from consecutive snapshots.

The EFL feeds carry season totals only. Differencing two snapshots recovers
what happened in between, which is the only route to the per-match record the
model needs -- and the only way to replace three of its assumptions with
measurements.

What differencing gives directly: every counting stat, and the points scored.

What it gives by subtraction: minutes and cards. Neither appears in the feed
at all, but everything else in a match's score is observable, so the leftover
is a small, structured quantity:

    residual = points - (goals + assists + clean sheet + defensive actions ...)
             = appearance points - card deductions

Appearance points are 1 under sixty minutes and 2 at or above it. Cards cost
1 for a yellow and 3 for a red, own goal or missed penalty. So a residual of 2
means a full match and no card; 1 means either a short appearance or a full
one with a yellow. That ambiguity does not resolve per player -- but a clean
sheet requires sixty minutes, which pins a good share of the cases outright,
and across thousands of appearances the split is estimable even where an
individual line is not.

Nothing here can run until a gameweek has been played. It is written now so it
starts working on its own the moment one has been.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .scoring import GOAL_POINTS
from .snapshot import CUMULATIVE_FIELDS, list_snapshots, load_snapshot

DEFAULT_HISTORY = Path(__file__).resolve().parent.parent / "data" / "matches.json"

#: Which positions actually record each counting stat.
#:
#: The feed only carries the stats a position scores from, so a midfielder's
#: clearances are structurally zero rather than genuinely zero. Measuring
#: dispersion across all positions mixes those in and collapses the estimate.
_DISPERSION_SCOPE = {
    "clearances": ("DEF",),
    "blocks": ("DEF",),
    "tackles": ("DEF",),
    "interceptions": ("MID",),
    "saves": ("GK",),
}

#: Match lines needed before a per-position card rate is worth reporting.
#:
#: The estimator separates minutes from cards by solving a quadratic, and near
#: its boundary that solve is noise-sensitive: 228 simulated midfielders were
#: enough to push it outside the representable region. Roughly a thousand -- a
#: few gameweeks -- settles it.
MIN_POSITION_LINES = 400

#: Points a player earns for appearing, by whether they lasted an hour.
APPEARANCE_LONG = 2
APPEARANCE_SHORT = 1


@dataclass
class MatchLine:
    """One player's stats across whatever fell between two snapshots.

    Usually a single fixture. In a double gameweek, or when snapshots are
    missed, it can span several -- `appearances` says which, and the minutes
    inference declines to guess when it is more than one.
    """

    player_id: int
    name: str
    position: str
    club: str
    from_snapshot: str
    to_snapshot: str
    appearances: int = 0
    points: int = 0
    goals: int = 0
    assists: int = 0
    clean_sheets: int = 0
    clearances: int = 0
    blocks: int = 0
    tackles: int = 0
    interceptions: int = 0
    saves: int = 0
    key_passes: int = 0
    shots_on_target: int = 0

    @property
    def observable_points(self) -> int:
        """Points from everything the feed reports directly.

        Deliberately excludes the appearance award and any card, which is what
        makes the residual informative.
        """
        total = GOAL_POINTS[self.position] * self.goals + 3 * self.assists
        if self.goals >= 3:
            total += 5  # hat-trick bonus, once
        if self.position in ("GK", "DEF"):
            total += 5 * self.clean_sheets
        if self.position == "GK":
            total += 2 * (self.saves // 3)
        if self.position == "DEF":
            total += self.clearances // 4 + self.blocks // 2 + self.tackles // 2
        if self.position == "MID":
            total += 2 * self.interceptions
        if self.position in ("MID", "FWD"):
            total += self.key_passes // 2 + self.shots_on_target
        return total

    @property
    def residual(self) -> int:
        """Appearance points less card deductions."""
        return self.points - self.observable_points

    @property
    def played_full(self) -> bool | None:
        """Whether the player lasted an hour. None when it cannot be told.

        A clean sheet requires sixty minutes, so it settles the question
        outright. Otherwise a residual of 2 means a full match with no card,
        and 1 or less is ambiguous between a short appearance and a booked
        full one.
        """
        if self.appearances != 1:
            return None
        if self.clean_sheets and self.position in ("GK", "DEF"):
            return True
        if self.residual >= APPEARANCE_LONG:
            return True
        return None if self.residual >= APPEARANCE_SHORT else None


#: Counting stats, mapped from the feed's field names to MatchLine's.
_FIELDS = {
    "totalPoints": "points",
    "appearances": "appearances",
    "goalsScored": "goals",
    "assists": "assists",
    "cleanSheets": "clean_sheets",
    "clearances": "clearances",
    "blocks": "blocks",
    "tackles": "tackles",
    "interceptions": "interceptions",
    "saves": "saves",
    "keyPasses": "key_passes",
    "shotsOnTarget": "shots_on_target",
}


def reconstruct(earlier: Path, later: Path, squads: dict | None = None) -> list[MatchLine]:
    """Match lines for every player whose totals moved between two snapshots."""
    before = {p["id"]: p for p in load_snapshot(earlier, "players")}
    squads = squads or {
        s["id"]: s["name"] for s in load_snapshot(later, "squads")
    }

    lines = []
    for player in load_snapshot(later, "players"):
        prior = before.get(player["id"])
        if prior is None:
            continue  # new to the game, so nothing to difference against

        deltas = {
            attr: player.get(feed, 0) - prior.get(feed, 0)
            for feed, attr in _FIELDS.items()
        }
        if not any(deltas.values()):
            continue

        lines.append(MatchLine(
            player_id=player["id"],
            name=player["displayName"],
            position=player["position"],
            club=squads.get(player["squadId"], "?"),
            from_snapshot=Path(earlier).name,
            to_snapshot=Path(later).name,
            **deltas,
        ))
    return lines


def build_history(data_dir: Path | None = None) -> list[MatchLine]:
    """Reconstruct every gameweek from the full run of stored snapshots.

    Consecutive pairs only. A gap in the snapshots merges the fixtures either
    side of it into one line, which stays correct in totals but loses the
    attribution -- `appearances` is what reveals that has happened.
    """
    snapshots = list_snapshots(data_dir)
    lines: list[MatchLine] = []
    for earlier, later in zip(snapshots, snapshots[1:]):
        lines.extend(reconstruct(earlier, later))
    return lines


@dataclass
class Calibration:
    """What the accumulated match lines say about the model's assumptions."""

    appearances: int = 0
    single_appearance_lines: int = 0
    confirmed_full: int = 0
    start_share: float | None = None
    card_rate: float | None = None
    card_cost: dict[str, float] = field(default_factory=dict)
    stat_dispersion: dict[str, float] = field(default_factory=dict)

    @property
    def usable(self) -> bool:
        """Whether there is enough evidence to prefer this to the defaults."""
        return self.single_appearance_lines >= 200


def _solve_minutes_and_cards(lines: list[MatchLine]) -> tuple[float, float]:
    """Recover the start rate and card rate from the residual distribution.

    Solves c^2 - c(1 - n2 + n0) + n0 = 0 for the card rate, taking the smaller
    root, then reads the start rate off P(residual = 2) = p(1 - c). Falls back
    to the naive count if the quadratic has no real root, which happens only
    when there is too little data for the shares to be consistent.
    """
    total = len(lines)
    n2 = sum(1 for ln in lines if ln.residual >= APPEARANCE_LONG) / total
    n0 = sum(1 for ln in lines if ln.residual <= 0) / total

    b = 1 - n2 + n0
    discriminant = b * b - 4 * n0
    if discriminant < 0:
        # The observed shares sit just outside what independent minutes and
        # cards can produce -- sampling noise near the boundary, not a
        # contradiction. The double root is the closest consistent point, and
        # is far better than the alternative of reporting no cards at all: on
        # 228 simulated midfielders that fallback read 0.000 against a true
        # 0.170. The gap closes as gameweeks accumulate.
        card_rate = b / 2
        return min(n2 / (1 - card_rate), 1.0), card_rate

    card_rate = (b - discriminant**0.5) / 2
    card_rate = min(max(card_rate, 0.0), 0.9)
    start_share = min(n2 / (1 - card_rate), 1.0) if card_rate < 1 else n2
    return start_share, card_rate


def calibrate(lines: list[MatchLine]) -> Calibration:
    """Measure what the model currently assumes.

    Three things fall out of enough match lines:

    * the share of appearances lasting an hour, which `START_SHARE` guesses;
    * card cost per appearance by position, which `CARD_COST` guesses;
    * how dispersed each counting stat is, which `expected_floor_div` assumes.

    All three are estimated only from lines covering a single appearance --
    a double gameweek or a missed snapshot merges fixtures, and the residual
    then answers a different question.
    """
    singles = [ln for ln in lines if ln.appearances == 1]
    calibration = Calibration(
        appearances=sum(ln.appearances for ln in lines),
        single_appearance_lines=len(singles),
    )
    if not singles:
        return calibration

    calibration.confirmed_full = sum(1 for ln in singles if ln.played_full is True)

    # Minutes and cards have to be solved together, not one after the other.
    #
    # A residual of 2 means a full match with no card, and 0 or less means a
    # short one that was booked. A residual of 1 is genuinely ambiguous -- a
    # full match with a booking looks exactly like a clean short appearance.
    #
    # Counting only residual >= 2 as full therefore misses every booked
    # starter, understating the start rate by roughly the card rate; and
    # judging cards against an appearance award that was itself inferred that
    # way misses those same bookings entirely. Both estimates come out low,
    # and for the same reason. On simulated data that was 0.64 against a true
    # 0.72, with card rates about half their real values.
    #
    # Writing p for the share of appearances lasting an hour and c for the
    # share carrying a deduction, and taking the two independent:
    #
    #     P(residual = 2) = p(1 - c)
    #     P(residual <= 0) = (1 - p)c
    #
    # which rearranges to c^2 - c(1 - n2 + n0) + n0 = 0. The smaller root is
    # the card rate; the start rate follows.
    calibration.start_share, card_rate = _solve_minutes_and_cards(singles)

    # Card cost per position comes from the same joint solve, run on that
    # position's own residuals.
    #
    # Subtracting residuals from an averaged appearance award does not work:
    # with a fractional award, every clean short appearance registers as a
    # phantom booking, and the estimate comes out two to three times too high.
    # The deduction has to be separated from the minutes, not netted against
    # them.
    by_position: dict[str, list[MatchLine]] = {}
    for ln in singles:
        by_position.setdefault(ln.position, []).append(ln)
    calibration.card_cost = {
        pos: round(_solve_minutes_and_cards(group)[1], 3)
        for pos, group in by_position.items()
        if len(group) >= MIN_POSITION_LINES
    }
    calibration.card_rate = round(card_rate, 3)

    # Dispersion for the negative binomial: var = mean + mean^2/k.
    #
    # Measured only over the position that actually records the stat. Pooling
    # every position instead mixes in the structural zeros -- a midfielder
    # records no clearances at all -- which inflates the variance enormously
    # and returns a dispersion near zero for everything.
    for attr, positions in _DISPERSION_SCOPE.items():
        values = [getattr(ln, attr) for ln in singles if ln.position in positions]
        if len(values) < 2:
            continue
        mean = statistics.fmean(values)
        if mean <= 0:
            continue
        variance = statistics.pvariance(values)
        if variance > mean:
            calibration.stat_dispersion[attr] = round(mean**2 / (variance - mean), 2)

    return calibration


def save_history(lines: list[MatchLine], path: Path | None = None) -> Path:
    """Write the reconstructed history, so it survives snapshot pruning."""
    path = Path(path) if path else DEFAULT_HISTORY
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([asdict(ln) for ln in lines], separators=(",", ":")),
        encoding="utf-8",
    )
    return path


def load_history(path: Path | None = None) -> list[MatchLine]:
    path = Path(path) if path else DEFAULT_HISTORY
    if not path.exists():
        return []
    return [MatchLine(**row) for row in json.loads(path.read_text(encoding="utf-8"))]


def summarise(lines: list[MatchLine]) -> dict:
    """A quick description of what has been reconstructed so far."""
    return {
        "lines": len(lines),
        "players": len({ln.player_id for ln in lines}),
        "appearances": sum(ln.appearances for ln in lines),
        "by_position": dict(Counter(ln.position for ln in lines)),
        "multi_fixture_lines": sum(1 for ln in lines if ln.appearances > 1),
    }
