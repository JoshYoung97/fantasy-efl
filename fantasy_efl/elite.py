"""Ownership among the highest-ranked managers.

The feed's `percentSelected` is ownership across everyone playing, which
answers "is this a popular pick" but not "do the people winning own it". Those
diverge, and the gap is where a differential either is or is not one.

Fantasy EFL exposes what is needed, but only to a signed-in session:
`/api/en/season/rankings/overall_leaderboard` pages the table and carries a
`userId` per row, and `/api/en/season/other-user-team/{userId}/{roundId}`
returns that manager's squad -- lineup, clubs, captain and chips. Both return
401 without a session, so collection runs in the browser
(`scripts/collect_elite.js`) and this module only aggregates what it produced.
Copying a session cookie into a scheduled script would mean a credential on
disk that expires silently, which is worse than a manual step.

Squads stay hidden until a gameweek locks. Before that every lineup is nulls,
and that is reported rather than smoothed over -- an elite ownership of 0%
from an empty sample would look like a differential rather than an absence.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_RAW = Path(__file__).resolve().parent.parent / "data" / "elite_raw.json"
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "data" / "elite_ownership.json"

#: Squads needed before a percentage is worth quoting. With fewer, one manager
#: moves the number by more than a point and it reads far more precisely than
#: it deserves.
MIN_SAMPLE = 20


@dataclass
class EliteOwnership:
    """How often the top managers picked each player and club."""

    round_id: int = 0
    collected_at: str = ""
    sample: int = 0
    #: player id -> percentage of the sample that owns them
    players: dict[int, float] = field(default_factory=dict)
    #: club name -> percentage that picked them
    clubs: dict[str, float] = field(default_factory=dict)
    #: player id -> percentage that captained them
    captains: dict[int, float] = field(default_factory=dict)
    chips: dict[str, float] = field(default_factory=dict)

    @property
    def usable(self) -> bool:
        return self.sample >= MIN_SAMPLE

    def effective(self, player_id: int) -> float:
        """Ownership plus captaincy.

        A captain scores twice, so owning them is worth twice as much to
        everyone who did. Effective ownership is what actually moves you up or
        down the table relative to the field.
        """
        return self.players.get(player_id, 0.0) + self.captains.get(player_id, 0.0)


def aggregate(payload: dict, squads: dict[int, str] | None = None) -> EliteOwnership:
    """Turn collected squads into ownership percentages.

    Only squads with at least one real pick are counted. A team returned as
    all-nulls means that manager's lineup is not visible yet, which is not the
    same as a manager who owns nobody, and averaging the two together would
    understate every percentage.
    """
    teams = payload.get("teams", [])
    picked = [
        team for team in teams
        if any(pid for group in (team.get("players") or {}).values() for pid in group)
    ]

    result = EliteOwnership(
        round_id=payload.get("roundId", 0),
        collected_at=payload.get("collectedAt", ""),
        sample=len(picked),
    )
    if not picked:
        return result

    players: Counter[int] = Counter()
    clubs: Counter[str] = Counter()
    captains: Counter[int] = Counter()
    chips: Counter[str] = Counter()

    for team in picked:
        seen: set[int] = set()
        for group in (team.get("players") or {}).values():
            for pid in group:
                if pid and pid not in seen:
                    seen.add(pid)
                    players[pid] += 1
        for squad_id in team.get("squads") or []:
            if squad_id is None:
                continue
            clubs[(squads or {}).get(squad_id, str(squad_id))] += 1
        if team.get("captainId"):
            captains[team["captainId"]] += 1
        if team.get("maxCaptain"):
            chips["maxCaptain"] += 1
        if team.get("oneClub"):
            chips["oneClub"] += 1

    total = len(picked)
    scale = lambda counter: {k: round(100 * v / total, 1) for k, v in counter.items()}
    result.players = scale(players)
    result.clubs = scale(clubs)
    result.captains = scale(captains)
    result.chips = scale(chips)
    return result


def differentials(
    elite: EliteOwnership, overall: dict[int, float], *, minimum: float = 5.0
) -> list[tuple[int, float, float]]:
    """Players the top managers back far more, or far less, than the field.

    Returns (player id, elite %, overall %) sorted by the gap. This is the
    reason for collecting any of it: a player on 8% overall and 40% among the
    top hundred is not a differential, whatever the headline number says.
    """
    gaps = [
        (pid, share, overall.get(pid, 0.0))
        for pid, share in elite.players.items()
        if abs(share - overall.get(pid, 0.0)) >= minimum
    ]
    return sorted(gaps, key=lambda row: -(row[1] - row[2]))


def save(elite: EliteOwnership, path: Path | None = None) -> Path:
    path = Path(path) if path else DEFAULT_OUT
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(elite), separators=(",", ":")), encoding="utf-8")
    return path


def load(path: Path | None = None) -> EliteOwnership:
    """Read stored elite ownership, or an empty result if none exists yet."""
    path = Path(path) if path else DEFAULT_OUT
    if not path.exists():
        return EliteOwnership()
    raw = json.loads(path.read_text(encoding="utf-8"))
    # JSON object keys are strings; player ids are integers everywhere else.
    return EliteOwnership(
        round_id=raw.get("round_id", 0),
        collected_at=raw.get("collected_at", ""),
        sample=raw.get("sample", 0),
        players={int(k): v for k, v in (raw.get("players") or {}).items()},
        clubs=raw.get("clubs") or {},
        captains={int(k): v for k, v in (raw.get("captains") or {}).items()},
        chips=raw.get("chips") or {},
    )
