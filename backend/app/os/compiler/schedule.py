"""Date helpers and the backward/forward pass (spec §4.3 step 5). Everything is timezone-aware."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def end_of_day(d: date, tz: str) -> datetime:
    """Deadlines are end of day in the anchor's timezone (invariant 13)."""
    return datetime.combine(d, time(23, 59, 59), tzinfo=ZoneInfo(tz))


def start_of_day(d: date, tz: str) -> datetime:
    return datetime.combine(d, time(0, 0), tzinfo=ZoneInfo(tz))


@dataclass
class Node:
    key: str
    duration_days: int
    tz: str
    deadline: datetime | None  # anchor end-of-day minus lead time, if the anchor is usable
    hard_preds: list[str]
    hard_succs: list[str]
    latest_finish: datetime | None = None
    latest_start: datetime | None = None
    earliest_start: datetime | None = None
    slack_days: int | None = None


def schedule(nodes: Mapping[str, Node], order: Sequence[str], today: date) -> None:
    """Fills latest/earliest dates and slack in place. `order` is a topological order of all edges."""
    for key in reversed(order):
        n = nodes[key]
        cands = [n.deadline] if n.deadline is not None else []
        cands += [nodes[s].latest_start for s in n.hard_succs if nodes[s].latest_start is not None]
        n.latest_finish = min(cands) if cands else None
        n.latest_start = n.latest_finish - timedelta(days=n.duration_days) if n.latest_finish else None
    for key in order:
        n = nodes[key]
        starts = [start_of_day(today, n.tz)]
        starts += [nodes[p].earliest_start + timedelta(days=nodes[p].duration_days) for p in n.hard_preds]
        n.earliest_start = max(starts)
        n.slack_days = (n.latest_start - n.earliest_start).days if n.latest_start is not None else None
