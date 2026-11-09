"""The admin read API of the registry (P2-T2, R-32, R-33, R-34): entities, official lists with their loaded count, and
coverage levels. Read only: the registry is written by the import and the review queue, never by this API."""

from collections.abc import Callable
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query

from app.os import models
from app.os.api.services import Services
from app.os.registry.coverage import coverage_map, summarise
from app.os.registry.model import RegistryEntry, known_region
from app.os.registry.store import ListProgress, RegistryStore


def entity_out(e: RegistryEntry) -> dict:
    return {"entity_id": e.entity_id, "kind": e.kind, "name": e.name, "parent_id": e.parent_id, "region": e.region,
            "institution_type": e.institution_type, "aliases": list(e.aliases),
            "official_domains": list(e.official_domains), "status": e.status, "successor_id": e.successor_id,
            "list_ids": list(e.list_ids), "source_url": e.source_url, "quote": e.quote,
            "checked_at": e.checked_at.isoformat(), "attrs": e.attrs}


def progress_out(p: ListProgress) -> dict:
    return {"list_id": p.list_id, "name": p.name, "region": p.region, "published": p.published, "loaded": p.loaded,
            "ratio": p.ratio, "complete": p.complete, "over": p.over, "count_confirmed": p.count_confirmed,
            "status": p.status}


def add_registry_routes(router: APIRouter, services: Callable[[], Services], require_admin) -> None:
    def store(svc: Services) -> RegistryStore:
        return RegistryStore(svc.engine, svc.settings.tenant_id)

    @router.get("/admin/registry/entities", dependencies=[Depends(require_admin)])
    def entities(kind: str | None = None, region: str | None = None, parent_id: str | None = None,
                 status: str | None = None, list_id: str | None = None, q: str | None = None,
                 limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
                 svc: Services = Depends(services)) -> dict:
        if kind is not None and kind not in models.REGISTRY_KINDS:
            raise HTTPException(status_code=422, detail=f"kind must be one of {list(models.REGISTRY_KINDS)}")
        if status is not None and status not in models.REGISTRY_STATUSES:
            raise HTTPException(status_code=422, detail=f"status must be one of {list(models.REGISTRY_STATUSES)}")
        if region is not None and not known_region(region):
            raise HTTPException(status_code=422, detail="unknown region code")
        found = store(svc).list(kind=kind, region=region, parent_id=parent_id, status=status, list_id=list_id, q=q,
                                limit=limit, offset=offset)
        return {"entities": [entity_out(e) for e in found]}

    @router.get("/admin/registry/entities/{entity_id}", dependencies=[Depends(require_admin)])
    def entity(entity_id: str, svc: Services = Depends(services)) -> dict:
        s = store(svc)
        e = s.get(entity_id)
        if e is None:
            raise HTTPException(status_code=404, detail="entity not found")
        return {
            "entity": entity_out(e),
            "children": [entity_out(c) for c in s.children(entity_id)],
            "links_out": [asdict(link) for link in s.links_from(entity_id)],
            "links_in": [asdict(link) for link in s.links_to(entity_id)],
            "programmes": s.programmes_of(entity_id) if e.kind == "institution" else [],
            "revisions": [{"id": r.id, "kind": r.kind, "subject": r.subject, "action": r.action, "cause": r.cause, "cause_ref": r.cause_ref,
                           "actor": r.actor, "at": r.at.isoformat(), "before": r.before, "after": r.after}
                          for r in s.revisions(entity_id)],
        }

    @router.get("/admin/registry/lists", dependencies=[Depends(require_admin)])
    def lists(region: str | None = None, svc: Services = Depends(services)) -> dict:
        if region is not None and not known_region(region):
            raise HTTPException(status_code=422, detail="unknown region code")
        return {"lists": [progress_out(p) for p in store(svc).list_progresses(region)]}

    @router.get("/admin/registry/coverage", dependencies=[Depends(require_admin)])
    def coverage(intake_year: int = Query(..., ge=2000, le=2200), intake_term: str | None = None,
                 region: str | None = None, svc: Services = Depends(services)) -> dict:
        if region is not None and not known_region(region):
            raise HTTPException(status_code=422, detail="unknown region code")
        cov = coverage_map(svc.engine, svc.settings.tenant_id, intake_year, intake_term=intake_term, region=region)
        return {"intake_year": intake_year, "intake_term": intake_term, "region": region, "summary": summarise(cov),
                "institutions": [asdict(c) for c in cov.values()]}
