"""Swap suggestions (Slice 4 spec S4-D5): other programmes that clear what this one does not. Warn, never block.

Only a `likely_below` line asks for a swap. A line waiting for the student's document (`needs_input`) or for
research (`unknown`) does not: nothing is known to be wrong yet. A candidate must be `likely_meets` on every failing
check; its other lines may still wait for input. Candidates with more confirmed facts come first.
"""

from dataclasses import dataclass

from app.os.eligibility.evaluate import Card

LIMIT = 3


@dataclass(frozen=True)
class Suggestion:
    programme_ref: str
    confirmed_facts: int


def suggest(card: Card, candidates: list[tuple[Card, int]], chosen: set[str], limit: int = LIMIT) -> list[Suggestion]:
    """`candidates`: (a programme's card for the same student, how many of its facts are confirmed), on the same
    route and intake. `chosen`: the programmes already in the student's plan."""
    failing = {ln.check for ln in card.lines if ln.status == "likely_below"}
    if not failing:
        return []
    picks = []
    for other, confirmed in candidates:
        if other.programme_ref == card.programme_ref or other.programme_ref in chosen:
            continue
        status = {ln.check: ln.status for ln in other.lines}
        if all(status.get(check) == "likely_meets" for check in failing):
            picks.append(Suggestion(other.programme_ref, confirmed))
    picks.sort(key=lambda s: (-s.confirmed_facts, s.programme_ref))
    return picks[:limit]
