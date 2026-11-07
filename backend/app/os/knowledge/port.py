"""The Knowledge port: sourced facts the compiler reads (spec §4.2, parent §3.2 trust rules).

P2-T1 (P2 spec P2-D5, P2-D6, P2-D8): a fact is keyed by intake term and year and by the body that owns its value, and
has a third trust level, `verified` (confirmed, then two review records). The new fields default to today's rows."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol

FactStatus = Literal["confirmed", "unconfirmed", "stale", "verified"]
STATUSES: tuple[str, ...] = ("confirmed", "unconfirmed", "stale", "verified")
READ_METHODS: tuple[str, ...] = ("fetch", "render", "ocr", "human", "model")
_SOURCED = ("confirmed", "verified")


@dataclass(frozen=True)
class Fact:
    """One sourced value. A confirmed or verified fact must carry its exact quote and URL (invariant 3)."""

    value: Any
    quote: str
    url: str
    checked_at: datetime
    intake_year: int
    status: FactStatus
    conflict_note: str | None = None
    id: int | None = None
    intake_term: str = ""  # '' = term not recorded (rows before P2; T8 backfills)
    owner_ref: str = ""  # registry id of the body that sets the value; '' = no owner (P2-D8)
    fact_class: str | None = None  # a key of knowledge/fact_classes.yaml; None = look up by field
    read_method: str | None = None
    language: str | None = None

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"unknown fact status '{self.status}'")
        if self.status in _SOURCED and not (self.quote.strip() and self.url.strip()):
            raise ValueError(f"{self.status} fact needs a quote and url")
        if self.checked_at.tzinfo is None:
            raise ValueError("checked_at must be timezone-aware")
        if self.read_method is not None and self.read_method not in READ_METHODS:
            raise ValueError(f"unknown read method '{self.read_method}'")

    @property
    def confirmed(self) -> bool:
        """Confirmed or better: a verified fact is also confirmed (master §8.2)."""
        return self.status in _SOURCED

    @property
    def verified(self) -> bool:
        return self.status == "verified"


class KnowledgePort(Protocol):
    def programme_facts(
        self, refs: Sequence[str], fields: Sequence[str], intake_year: int, *,
        intake_term: str | None = None, owner_ref: str = "", fallback_previous: bool = False,
    ) -> dict[tuple[str, str], Fact]:
        """`fallback_previous` (P2-D24): a key with no fact for `intake_year` gets the newest earlier year's fact. It
        is marked by its own `intake_year`, which differs from the one asked for; the default is today's strict read."""
        ...

    def route_facts(self, route_key: str, fields: Sequence[str], intake_year: int, *,
                    intake_term: str | None = None, owner_ref: str = "",
                    fallback_previous: bool = False) -> dict[str, Fact]: ...
