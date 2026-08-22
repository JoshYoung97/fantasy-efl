"""Weekly snapshots of the Fantasy EFL public JSON feeds.

The feeds carry season *totals* only -- no per-match rows, no minutes played.
Differencing consecutive snapshots reconstructs what a single gameweek
contained, which is the only route to per-match variance, form, and the
minutes split that dominates projection error. Miss a week and it is gone, so
this is written to be run on a schedule and to fail loudly.

Raw responses are stored verbatim rather than parsed into a schema: we do not
yet know everything we will want from them, and reprocessing is free while
refetching history is impossible.

Stdlib only -- nothing to install on the box that runs the cron job.
"""

from __future__ import annotations

import gzip
import io
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE_URL = "https://fantasy.efl.com/json/fantasy"

#: Feeds worth keeping. `players` is the payload that matters; the rest are
#: small and provide the context needed to interpret it later.
FEEDS = ("players", "squads", "rounds", "competitions")

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "snapshots"

_USER_AGENT = "fantasy-efl-projections/0.1 (personal fantasy tool)"


class SnapshotError(RuntimeError):
    """A feed could not be fetched or did not parse."""


def fetch_feed(name: str, *, timeout: int = 30) -> list | dict:
    """Fetch and parse one feed. Raises SnapshotError on any failure."""
    url = f"{BASE_URL}/{name}.json"
    request = urllib.request.Request(
        url, headers={"User-Agent": _USER_AGENT, "Accept-Encoding": "gzip"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            if response.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
    except (urllib.error.URLError, OSError, gzip.BadGzipFile) as exc:
        raise SnapshotError(f"fetching {url}: {exc}") from exc

    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SnapshotError(f"parsing {url}: {exc}") from exc


def take_snapshot(data_dir: Path | None = None) -> Path:
    """Fetch every feed and write a timestamped, gzipped snapshot directory.

    Returns the directory written. All feeds are fetched before anything is
    written, so a partial failure leaves no half-snapshot behind.
    """
    data_dir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
    taken_at = datetime.now(timezone.utc)

    payloads = {name: fetch_feed(name) for name in FEEDS}

    players = payloads["players"]
    if not isinstance(players, list) or not players:
        raise SnapshotError("players feed was empty or not a list")

    target = data_dir / taken_at.strftime("%Y-%m-%dT%H%M%SZ")
    target.mkdir(parents=True, exist_ok=True)

    for name, payload in payloads.items():
        with gzip.open(target / f"{name}.json.gz", "wt", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"))

    manifest = {
        "taken_at": taken_at.isoformat(),
        "feeds": {name: len(payloads[name]) for name in FEEDS},
        "current_round": _current_round(payloads["rounds"]),
    }
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return target


def is_played(game: dict) -> bool:
    """Whether a fixture has actually happened.

    Read from the data, not from a status string. A recorded score is the
    strongest signal; `isFinalized` is accepted as a fallback in case scores
    arrive later than the flag.
    """
    return game.get("homeScore") is not None or bool(game.get("isFinalized"))


def round_complete(rnd: dict) -> bool:
    """Whether every fixture in a round has been played.

    Deliberately not `status == "complete"`. The feed's own value is
    "completed", and keying off the wrong spelling silently pins the game to
    GW1 forever -- which is exactly what happened: the page kept publishing
    GW1's name, deadline and kickoff times against GW2's fixtures, so every
    player read as already locked.
    """
    games = rnd.get("games") or []
    return bool(games) and all(is_played(g) for g in games)


def _current_round(rounds: list[dict]) -> int | None:
    """The lowest-numbered round that has not been completed."""
    pending = [
        r for r in rounds
        if r.get("gameMode") == "season" and not round_complete(r)
    ]
    return min((r["roundNumber"] for r in pending), default=None)


def load_snapshot(path: Path, feed: str = "players") -> list | dict:
    """Read one feed back out of a stored snapshot."""
    with gzip.open(Path(path) / f"{feed}.json.gz", "rt", encoding="utf-8") as handle:
        return json.load(handle)


#: Stored odds payloads, kept beside the EFL snapshots.
DEFAULT_ODDS_DIR = Path(__file__).resolve().parent.parent / "data" / "odds"


def save_odds(payload: dict, odds_dir: Path | None = None) -> Path:
    """Store a raw odds response so it can be replayed.

    Odds move continuously, so the same code run an hour apart gives different
    projections. Storing the payload is what lets several people work from
    identical numbers, and costs nothing extra -- the fetch has already
    happened. It also builds an archive of what the market expected before
    each match, which is the raw material for checking the model against
    results later.
    """
    odds_dir = Path(odds_dir) if odds_dir else DEFAULT_ODDS_DIR
    odds_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    target = odds_dir / f"{stamp}.json.gz"
    with gzip.open(target, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"))
    return target


def list_odds(odds_dir: Path | None = None) -> list[Path]:
    """Stored odds payloads, oldest first."""
    odds_dir = Path(odds_dir) if odds_dir else DEFAULT_ODDS_DIR
    if not odds_dir.exists():
        return []
    return sorted(p for p in odds_dir.glob("*.json.gz"))


def load_odds(path: Path) -> dict:
    """Read a stored odds payload back."""
    with gzip.open(Path(path), "rt", encoding="utf-8") as handle:
        return json.load(handle)


def list_snapshots(data_dir: Path | None = None) -> list[Path]:
    """Every stored snapshot, oldest first."""
    data_dir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
    if not data_dir.exists():
        return []
    return sorted(p for p in data_dir.iterdir() if (p / "manifest.json").exists())


#: Cumulative stat fields that can be differenced between two snapshots.
CUMULATIVE_FIELDS = (
    "totalPoints",
    "appearances",
    "goalsScored",
    "assists",
    "keyPasses",
    "shotsOnTarget",
    "cleanSheets",
    "clearances",
    "blocks",
    "tackles",
    "interceptions",
    "saves",
)


def diff_snapshots(earlier: Path, later: Path) -> list[dict]:
    """Per-player deltas between two snapshots -- i.e. one gameweek's stat lines.

    Only players whose totals moved are returned. Note the deltas cover whatever
    fixtures fell between the two snapshots, so a club playing twice in a
    Thursday-Wednesday gameweek yields the combined line, not one per match.
    """
    before = {p["id"]: p for p in load_snapshot(earlier)}
    deltas = []

    for player in load_snapshot(later):
        prior = before.get(player["id"])
        if prior is None:
            continue  # new to the game; no baseline to difference against
        delta = {
            field: player.get(field, 0) - prior.get(field, 0)
            for field in CUMULATIVE_FIELDS
        }
        if any(delta.values()):
            delta.update(
                id=player["id"],
                displayName=player["displayName"],
                position=player["position"],
                squadId=player["squadId"],
            )
            deltas.append(delta)

    return deltas


def infer_appearance_points(delta: dict) -> int | None:
    """Recover the appearance component from a single-appearance gameweek delta.

    Everything except the appearance award and cards is directly observable, so
    subtracting the known components leaves a residual of roughly 1 (played
    under 60 minutes) or 2 (played 60 or more), less any card deductions. This
    is the only handle the public feed offers on minutes played, and it only
    works on deltas covering exactly one appearance.
    """
    if delta["appearances"] != 1:
        return None

    from .scoring import GOAL_POINTS

    known = GOAL_POINTS[delta["position"]] * delta["goalsScored"]
    known += 3 * delta["assists"]
    known += 5 * delta["cleanSheets"]
    if delta["position"] in ("MID", "FWD"):
        known += delta["shotsOnTarget"] + delta["keyPasses"] // 2
    if delta["position"] == "MID":
        known += 2 * delta["interceptions"]
    if delta["position"] == "DEF":
        known += delta["clearances"] // 4 + delta["blocks"] // 2 + delta["tackles"] // 2
    if delta["position"] == "GK":
        known += 2 * (delta["saves"] // 3)

    return delta["totalPoints"] - known


if __name__ == "__main__":
    written = take_snapshot()
    manifest = json.loads((written / "manifest.json").read_text(encoding="utf-8"))
    print(f"snapshot written to {written}")
    print(json.dumps(manifest, indent=2))
