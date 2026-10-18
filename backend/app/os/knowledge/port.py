"""The Knowledge port: sourced facts the compiler reads (spec §4.2, parent §3.2 trust rules)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol

FactStatus = Literal["confirmed", "unconfirmed", "stale"]
STATUSES: tuple[str, ...] = ("confirmed", "unconfirmed", "stale")


@dataclass(frozen=True)
class Fact:
    """One sourced value. A confirmed fact must carry its exact quote and URL (invariant 3)."""

    value: Any
    quote: str
    url: str
    checked_at: datetime
    intake_year: int
    status: FactStatus
    conflict_note: str | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"unknown fact status '{self.status}'")
        if self.status == "confirmed" and not (self.quote.strip() and self.url.strip()):
            raise ValueError("confirmed fact needs a quote and url")
        if self.checked_at.tzinfo is None:
            raise ValueError("checked_at must be timezone-aware")

    @property
    def confirmed(self) -> bool:
        return self.status == "confirmed"


class KnowledgePort(Protocol):
    def programme_facts(
        self, refs: Sequence[str], fields: Sequence[str], intake_year: int
    ) -> dict[tuple[str, str], Fact]: ...

    def route_facts(self, route_key: str, fields: Sequence[str], intake_year: int) -> dict[str, Fact]: ...
