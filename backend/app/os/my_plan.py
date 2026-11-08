"""My plan (P1-T9, R-51, R-53, R-54): what the student's plan shows on screen, built on every read, never stored.
The pages and every word on them come from the pinned playbook (R-52); the dates come from Knowledge facts and from
the playbook's own dated source list. Nothing here names a country."""

from datetime import date
from typing import Any

from sqlalchemy import select

from app.os import models
from app.os.kernel.states import PLAN_OPEN
from app.os.playbooks.loader import PlaybookError, select_playbook
from app.os.plan_view import build_plan_view
from app.os.replan.store import OverrideStore

K, P, PIN = models.knowledge_facts, models.plans, models.playbook_pins


def _empty() -> dict:
    return {"state": "empty", "source": None, "plan_id": None, "route_key": None, "abroad": None, "pages": [],
            "sources": {}}


def _pin(conn, tenant_id: str, plan_id: int):
    return conn.execute(select(PIN.c.playbook_key, PIN.c.version).where(
        PIN.c.tenant_id == tenant_id, PIN.c.plan_id == plan_id)
        .order_by(PIN.c.version.desc(), PIN.c.id.desc()).limit(1)).first()


def _self_serve(svc: Any, student_ref: str) -> dict | None:
    """The student's newest open self-serve plan (the same choice as `ports.plan_query.self_serve_plan`)."""
    tenant_id = svc.settings.tenant_id
    with svc.engine.connect() as conn:
        row = conn.execute(select(P.c.id, P.c.status, P.c.contract).where(
            P.c.tenant_id == tenant_id, P.c.student_ref == student_ref, P.c.source == "self_serve",
            P.c.status.in_(PLAN_OPEN)).order_by(P.c.id.desc()).limit(1)).first()
        if row is None:
            return None
        pin = _pin(conn, tenant_id, row.id)
    return {"plan_id": row.id, "state": "paused" if row.status == "paused" else "active", "contract": row.contract,
            "pin": pin}


def _counsellor(svc: Any, student_ref: str) -> dict | None:
    view = build_plan_view(svc, student_ref)
    if view.state == "empty":
        return None
    with svc.engine.connect() as conn:
        row = conn.execute(select(P.c.contract).where(P.c.tenant_id == svc.settings.tenant_id,
                                                      P.c.id == view.plan_id)).first()
        pin = _pin(conn, svc.settings.tenant_id, view.plan_id)
    return {"plan_id": view.plan_id, "state": view.state, "contract": row.contract, "pin": pin}


def _book(svc: Any, chosen: dict):
    pin, c = chosen["pin"], chosen["contract"]
    books = svc.plans.playbooks
    if pin is not None:
        return books.get((pin.playbook_key, pin.version))
    try:  # no pin: the playbook this route runs on
        return select_playbook(books, c["origin_country"], c["destination_country"], c["level"])
    except PlaybookError:
        return None


def _note(found: dict, url: str, day: date, confirmed: bool) -> None:
    """Keeps, for a url, the oldest day any fact or source with it was checked; it is confirmed only if all are."""
    old = found.get(url)
    if old is None:
        found[url] = {"checked_at": day.isoformat(), "confirmed": confirmed}
        return
    found[url] = {"checked_at": min(day, date.fromisoformat(old["checked_at"])).isoformat(),
                  "confirmed": old["confirmed"] and confirmed}


def _facts_of(svc: Any, route_key: str, refs: list[str], year: int | None) -> list:
    """The Knowledge facts behind a plan's route and programmes for its intake year."""
    if year is None:
        return []
    # every field the Knowledge has for these, not a list of ours. Any owner's rows count (P2-T2): the port read below
    # takes owner_ref=None (the general row first, else a body's), so a source an owner set is dated like any other.
    with svc.engine.connect() as conn:
        rows = conn.execute(select(K.c.scope, K.c.ref, K.c.field).where(
            K.c.tenant_id == svc.settings.tenant_id, K.c.intake_year == year,
            ((K.c.scope == "route") & (K.c.ref == route_key)) | ((K.c.scope == "programme") & K.c.ref.in_(refs))
        )).all()
    route_fields = sorted({r.field for r in rows if r.scope == "route"})
    programme_fields = sorted({r.field for r in rows if r.scope == "programme"})
    facts = list(svc.knowledge.route_facts(route_key, route_fields, year).values())
    facts += list(svc.knowledge.programme_facts(refs, programme_fields, year).values())
    return facts


def _knowledge_sources(svc: Any, route_key: str, refs: list[str], year: int | None, found: dict) -> None:
    for f in _facts_of(svc, route_key, refs, year):
        if not f.url.strip():  # an unconfirmed fact may have no source yet: nothing to date
            continue
        _note(found, f.url, f.checked_at.date(), f.confirmed)


def _playbook_sources(book: Any, found: dict) -> None:
    cited = [c for t in book.tasks for c in t.citations] + [c for k in book.constants.values() for c in k.citations]
    for c in cited:
        check = book.sources.get(c.source)
        if check is not None:
            _note(found, str(c.url), check.checked, check.confirmed)


def _choose(svc: Any, student_ref: str) -> tuple[dict | None, str]:
    chosen = _counsellor(svc, student_ref)
    source = "counsellor"
    if chosen is None or chosen["state"] in ("stopped", "finished"):
        # a Counsellor plan that is over gives way to the student's open plan of their own; alone, it is shown
        own = _self_serve(svc, student_ref)
        if own is not None and (chosen is None or own["plan_id"] != chosen["plan_id"]):  # not the adopted plan itself
            chosen, source = own, "self_serve"
    return chosen, source


def _plan_refs(svc: Any, chosen: dict) -> tuple[Any, dict, str | None, list[str]]:
    book = _book(svc, chosen)
    c = chosen["contract"]
    route_key = chosen["pin"].playbook_key if chosen["pin"] is not None else (book.key if book else None)
    cancelled = OverrideStore(svc.engine, svc.settings.tenant_id).cancelled(chosen["plan_id"])
    return book, c, route_key, [p["programme_ref"] for p in c.get("programmes") or [] if p["programme_ref"] not in cancelled]


def plan_facts(svc: Any, student_ref: str) -> list:
    """The Knowledge facts the student's plan shows (what a student may report as wrong, P2-T7, R-28)."""
    chosen, _ = _choose(svc, student_ref)
    if chosen is None:
        return []
    _, c, route_key, refs = _plan_refs(svc, chosen)
    return [] if route_key is None else _facts_of(svc, route_key, refs, (c.get("target_intake") or {}).get("year"))


def build_my_plan(svc: Any, student_ref: str) -> dict:
    chosen, source = _choose(svc, student_ref)
    if chosen is None:
        return _empty()
    book, c, route_key, refs = _plan_refs(svc, chosen)
    found: dict[str, dict] = {}
    if route_key is not None:
        year = (c.get("target_intake") or {}).get("year")
        _knowledge_sources(svc, route_key, refs, year, found)
    if book is not None:
        _playbook_sources(book, found)
    # null: the playbook declares no pages (the screens keep today's page list); [] is a route with none to show
    pages = None if book is None or book.pages is None else [p.model_dump() for p in book.pages]
    return {"state": chosen["state"], "source": source, "plan_id": chosen["plan_id"], "route_key": route_key,
            "abroad": c["origin_country"] != c["destination_country"], "pages": pages,
            "sources": dict(sorted(found.items()))}
