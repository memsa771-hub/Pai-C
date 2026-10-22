"""Programme requests: a student asks for a programme that is not in the registry (Slice 4 spec S4-D8, Q1).

A request adds the programme to the shared registry with status `requested` and enqueues its research **once**.
When research has found facts, every student sees it (labelled "requested by a student" until an admin reviews it),
and no later request researches it again: it is shared like the seeded programmes. At most REQUESTS_PER_DAY per
student (S4-D11).
"""

import hashlib
from collections.abc import Callable
from datetime import datetime, timedelta
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import Engine, exists, func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.os import models
from app.os.knowledge.programmes import Programme, _programme

REQUESTS_PER_DAY = 3
REQUESTED_NOTE = "requested by a student"

P, R, F = models.programmes, models.programme_requests, models.knowledge_facts


class RequestLimit(Exception):
    """The student asked for REQUESTS_PER_DAY programmes in the last 24 hours."""


def _normalise(url: str) -> tuple[str, str]:
    """(the URL in one canonical form, its host without www.) Only https URLs with a host are accepted."""
    parts = urlsplit(url.strip())
    if parts.scheme.lower() != "https" or not parts.hostname:
        raise ValueError("the programme's page must be an https:// address")
    host = parts.hostname.lower()
    path = parts.path.rstrip("/").lower()
    return urlunsplit(("https", host, path, "", "")), host.removeprefix("www.")


def _same(a: str, b: str) -> bool:
    return " ".join(a.casefold().split()) == " ".join(b.casefold().split())


def _existing(conn, tenant_id: str, route_key: str, url: str, university: str, name: str) -> str | None:
    rows = conn.execute(select(P.c.ref, P.c.university, P.c.name, P.c.start_urls).where(
        P.c.tenant_id == tenant_id, P.c.route_key == route_key)).all()
    for r in rows:
        urls = set()
        for u in r.start_urls:
            try:
                urls.add(_normalise(u)[0])
            except ValueError:
                continue
        if url in urls or (_same(r.university, university) and _same(r.name, name)):
            return r.ref
    return None


def request_programme(engine: Engine, tenant_id: str, student_ref: str, route_key: str, university: str, name: str,
                      url: str, *, now: datetime, enqueue: Callable[[str], object],
                      intake_year: int | None = None) -> tuple[str, bool]:
    """(programme_ref, created). `enqueue(ref)` starts its research (for the request's year): for a new programme,
    and for a known one with no facts for `intake_year` yet (another year, or an enqueue that was lost).
    Research is idempotent per programme, year and day, so a repeat is harmless."""
    canon, host = _normalise(url)
    university, name = university.strip(), name.strip()
    if not university or not name:
        raise ValueError("the university and the programme name are both needed")
    with engine.begin() as conn:
        asked = conn.execute(select(func.count()).select_from(R).where(
            R.c.tenant_id == tenant_id, R.c.student_ref == student_ref,
            R.c.created_at > now - timedelta(hours=24))).scalar()
        if asked >= REQUESTS_PER_DAY:
            raise RequestLimit(f"at most {REQUESTS_PER_DAY} programme requests a day")
        ref = _existing(conn, tenant_id, route_key, canon, university, name)
        created = False
        if ref is None:
            ref = "req-" + hashlib.sha256(canon.encode()).hexdigest()[:12]
            created = conn.execute(pg_insert(P).values(
                tenant_id=tenant_id, ref=ref, route_key=route_key, university=university, name=name,
                aliases=[name], start_urls=[url.strip()], official_domains=[host], status="requested",
                notes=REQUESTED_NOTE,
            ).on_conflict_do_nothing(constraint="uq_os_programmes_ref").returning(P.c.id)).scalar() is not None
        conn.execute(insert(R).values(tenant_id=tenant_id, student_ref=student_ref, route_key=route_key, url=canon,
                                      programme_ref=ref, created_at=now))
    if created or (intake_year is not None and not _facts_for(engine, tenant_id, ref, intake_year)):
        enqueue(ref)  # after the commit: research reads the registry row
    return ref, created


def _facts_for(engine: Engine, tenant_id: str, ref: str, intake_year: int) -> bool:
    with engine.connect() as conn:
        return conn.execute(select(exists(select(F.c.id).where(
            F.c.tenant_id == tenant_id, F.c.scope == "programme", F.c.ref == ref,
            F.c.intake_year == intake_year)))).scalar()


def _has_facts(tenant_id: str, intake_year: int | None = None):
    q = select(F.c.id).where(F.c.tenant_id == tenant_id, F.c.scope == "programme", F.c.ref == P.c.ref)
    return exists(q.where(F.c.intake_year == intake_year) if intake_year is not None else q)


def visible_programmes(engine: Engine, tenant_id: str, route_key: str, intake_year: int) -> list[Programme]:
    """The route's programmes a student can choose: active ones, and requested ones with facts for the year."""
    with engine.connect() as conn:
        rows = conn.execute(select(P).where(
            P.c.tenant_id == tenant_id, P.c.route_key == route_key,
            (P.c.status == "active") | ((P.c.status == "requested") & _has_facts(tenant_id, intake_year)),
        ).order_by(P.c.ref)).all()
    return [_programme(r) for r in rows]


def requested_without_facts(engine: Engine, tenant_id: str) -> list[Programme]:
    """Requested programmes research has found nothing for yet (the admin's open-facts view, Q1)."""
    with engine.connect() as conn:
        rows = conn.execute(select(P).where(
            P.c.tenant_id == tenant_id, P.c.status == "requested", ~_has_facts(tenant_id)).order_by(P.c.ref)).all()
    return [_programme(r) for r in rows]
