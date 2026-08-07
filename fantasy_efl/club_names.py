"""Matching EFL club names to the names bookmakers use.

The two feeds disagree constantly -- "AFC Wimbledon" against "Wimbledon",
"Luton Town" against "Luton" -- so players cannot be joined to their fixture's
odds without a mapping.

The obvious fix, stripping suffixes like Town/City/Rovers and comparing what is
left, is actively unsafe here: it collapses Bristol City into Bristol Rovers and
Sheffield United into Sheffield Wednesday. English football has too many
same-city clubs distinguished *only* by the suffix. So normalisation stays
deliberately light, and the work is done by scoring every candidate and
reporting how close the runner-up came.

A match where the best and second-best candidates score similarly is reported as
ambiguous rather than guessed at. Silently mapping Bristol Rovers' odds onto
Bristol City's players would poison every projection for both clubs, and would
be invisible in the output.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, asdict
from difflib import SequenceMatcher
from pathlib import Path

#: Tokens that carry no distinguishing information on their own.
_NOISE = frozenset({"fc", "afc", "the"})

#: Names no similarity measure can bridge, because they share no tokens with
#: their formal version. Bookmakers use these constantly. Keyed and valued by
#: normalised form; the canonical side matches the EFL feed's spelling.
_ALIASES = {
    "wolves": "wolverhampton wanderers",
    "mk dons": "milton keynes dons",
    "nott m forest": "nottingham forest",
    "notts forest": "nottingham forest",
    "sheff wed": "sheffield wednesday",
    "sheffield weds": "sheffield wednesday",
    "sheff utd": "sheffield united",
    "west brom": "west bromwich albion",
    "wba": "west bromwich albion",
    "qpr": "queens park rangers",
    "spurs": "tottenham hotspur",
    "man utd": "manchester united",
    "man city": "manchester city",
}

#: Below this, even the best candidate is treated as unmatched.
MIN_SCORE = 0.72

#: If the runner-up is within this of the winner, the match is ambiguous.
AMBIGUITY_MARGIN = 0.08


def normalise(name: str) -> str:
    """Lowercase, strip accents and punctuation, drop noise tokens.

    Deliberately does NOT strip Town/City/United/Rovers and friends -- those
    are the only thing separating several pairs of clubs.
    """
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    cleaned = re.sub(r"[^a-z0-9\s]", " ", ascii_only.lower())
    tokens = [t for t in cleaned.split() if t not in _NOISE]
    joined = " ".join(tokens)
    return _ALIASES.get(joined, joined)


def similarity(left: str, right: str) -> float:
    """Score two normalised names between 0 and 1.

    Blends overall string similarity with token overlap so that a name which is
    a clean subset of another ("luton" inside "luton town") scores highly,
    without letting a shared first token alone ("bristol") carry a match.
    """
    if left == right:
        return 1.0

    ratio = SequenceMatcher(None, left, right).ratio()

    left_tokens, right_tokens = set(left.split()), set(right.split())
    if not left_tokens or not right_tokens:
        return ratio

    shared = left_tokens & right_tokens
    overlap = len(shared) / min(len(left_tokens), len(right_tokens))

    # A full subset is strong evidence, but only when the shared tokens carry
    # most of the longer name -- "bristol" alone must not dominate.
    if left_tokens <= right_tokens or right_tokens <= left_tokens:
        coverage = len(shared) / max(len(left_tokens), len(right_tokens))
        return max(ratio, 0.70 + 0.30 * coverage)

    return max(ratio, 0.5 * ratio + 0.5 * overlap)


@dataclass
class Match:
    """One EFL club's best candidate among the bookmaker names."""

    efl_name: str
    odds_name: str | None
    score: float
    runner_up: str | None
    runner_up_score: float

    @property
    def ambiguous(self) -> bool:
        return (
            self.odds_name is not None
            and self.runner_up is not None
            and self.score - self.runner_up_score < AMBIGUITY_MARGIN
        )

    @property
    def needs_review(self) -> bool:
        return self.odds_name is None or self.ambiguous or self.score < 0.90


def match_clubs(efl_names: list[str], odds_names: list[str]) -> list[Match]:
    """Score every EFL club against every bookmaker name.

    Returns one Match per EFL club, ordered worst-first so the entries needing
    attention appear at the top.
    """
    normalised_odds = [(name, normalise(name)) for name in odds_names]
    matches: list[Match] = []

    for efl_name in efl_names:
        target = normalise(efl_name)
        scored = sorted(
            ((similarity(target, norm), name) for name, norm in normalised_odds),
            reverse=True,
        )
        best_score, best_name = scored[0] if scored else (0.0, None)
        runner_score, runner_name = scored[1] if len(scored) > 1 else (0.0, None)

        matches.append(
            Match(
                efl_name=efl_name,
                odds_name=best_name if best_score >= MIN_SCORE else None,
                score=best_score,
                runner_up=runner_name,
                runner_up_score=runner_score,
            )
        )

    matches.sort(key=lambda m: (not m.needs_review, m.score))
    return matches


def save_mapping(matches: list[Match], path: Path) -> None:
    """Write the mapping for hand-editing.

    Entries needing review are kept in the file with their runner-up recorded,
    so a human can see what the alternative was rather than being handed a bare
    guess.
    """
    payload = {
        "mapping": {
            m.efl_name: m.odds_name for m in matches if m.odds_name and not m.needs_review
        },
        "needs_review": [asdict(m) for m in matches if m.needs_review],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def load_mapping(path: Path) -> dict[str, str]:
    """Read a saved mapping, including anything resolved by hand."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    mapping = dict(payload.get("mapping", {}))
    # Reviewed entries can be promoted by filling in `odds_name` and setting
    # `"confirmed": true` in the file.
    for entry in payload.get("needs_review", []):
        if entry.get("confirmed") and entry.get("odds_name"):
            mapping[entry["efl_name"]] = entry["odds_name"]
    return mapping
