"""What a student chose beyond the field: the route to hand PAI OS (places, intake, countries, level, consent).
Codes and IDs only. Built by the router in a later task; `choose()` works without it (then nothing is handed over)."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ChoiceDetails:
    origin_country: str
    destination_country: str
    level: str
    places: tuple[tuple[str, int], ...]  # (programme_ref, rank)
    intake: tuple[str, int] | None  # (term, year)
    path_ref: str | None = None
    authorized_at: datetime | None = None
    guardian_required: bool = False
    guardian_authorized_at: datetime | None = None
    consent_version: str | None = None  # the consent text version the student agreed to
