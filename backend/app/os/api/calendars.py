"""The admin read API of the official calendars (P2-T11, R-20, R-33): the calendar rows of the registry with their dates
for an intake, each with its trust level as the display rule gives it. Read only."""

from collections.abc import Callable

from fastapi import APIRouter, Depends, Query

from app.os.api.services import Services
from app.os.knowledge.display import display
from app.os.registry.calendars import calendar_dates
from app.os.registry.store import RegistryStore


def add_calendar_routes(router: APIRouter, services: Callable[[], Services], require_admin) -> None:
    @router.get("/admin/registry/calendars", dependencies=[Depends(require_admin)])
    def calendars(intake_year: int = Query(..., ge=2000, le=2200), intake_term: str | None = None,
                  parent_id: str | None = None, svc: Services = Depends(services)) -> dict:
        registry = RegistryStore(svc.engine, svc.settings.tenant_id)
        rows = registry.list(kind="calendar", parent_id=parent_id, status="active", limit=10_000)
        read = {"intake_term": intake_term} if intake_term else {}
        dates = calendar_dates(svc.knowledge, [c.entity_id for c in rows], intake_year, **read)
        out = []
        for c in rows:
            mine = {}
            for (cal, field), fact in sorted(dates.items()):
                if cal != c.entity_id:
                    continue
                d = display(fact, field, intake_year=intake_year, intake_term=intake_term)
                value = fact.value if isinstance(fact.value, dict) else {}
                mine[field] = {"date": value.get("date"), "tz": value.get("tz"), "level": d.level,
                               "other_intake": d.other_intake, "intake_year": fact.intake_year,
                               "intake_term": fact.intake_term, "url": fact.url, "quote": fact.quote}
            out.append({"entity_id": c.entity_id, "name": c.name, "parent_id": c.parent_id,
                        "calendar_type": c.attrs.get("calendar_type"), "source_url": c.source_url, "dates": mine})
        return {"intake_year": intake_year, "intake_term": intake_term, "calendars": out}
