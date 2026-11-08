"""The guard the page gateway calls (P2 spec §4.2): lookup, integrity checks, snapshots and the suspect flow.

A failed check marks the domain `suspect`. The state change and the `source_suspect` event are one transaction, and
only the caller whose UPDATE changed the state runs the rest (race-safe, review I2). Then the domain's facts drop to
`unconfirmed` (through `set_status` and `after_fact_change`, so plans revise; resumable: a re-run on a suspect domain
completes the drop) and the `on_suspect` hook is called once (T5 opens the `suspect_domain` review item there).
Nothing new is taken from a suspect domain: the gateway refuses it before it reads the cache or the network.

The domain flagged is the listed domain the host belongs to or, for a host on no list, the exact host: never a
two-label guess, which would suspend every host under a shared suffix (review C1).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit

from sqlalchemy import Connection, Engine, select, text

from app.os import models
from app.os.knowledge.sources import integrity
from app.os.knowledge.sources.allowlist import (
    AllowList,
    Scope,
    SourceDomains,
    SyncResult,
    host_matches,
)
from app.os.knowledge.sources.snapshots import SnapshotStore
from app.os.knowledge.store import SqlKnowledge

T = models.knowledge_facts
AfterChange = Callable[[str, str, str, int, str, int], None]  # scope, ref, field, fact_id, status, intake_year


@dataclass(frozen=True)
class SuspectCase:
    domain: str
    reason: str
    detail: str
    url: str
    snapshot_id: int | None
    facts_dropped: tuple[int, ...]


@dataclass(frozen=True)
class Inspection:
    findings: tuple[integrity.Finding, ...]
    snapshot_id: int | None


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().rstrip(".")


class SourceGuard:
    def __init__(self, engine: Engine, tenant_id: str, *, domains: SourceDomains | None = None,
                 snapshots: SnapshotStore | None = None, knowledge: SqlKnowledge | None = None,
                 after_change: AfterChange | None = None, on_suspect: Callable[[SuspectCase], None] | None = None,
                 config: dict | None = None) -> None:
        self.engine, self.tenant_id = engine, tenant_id
        self.domains = domains or SourceDomains(engine, tenant_id)
        self.snapshots = snapshots or SnapshotStore(engine, tenant_id)
        self.knowledge = knowledge or SqlKnowledge(engine, tenant_id)
        self.after_change, self.on_suspect, self.config = after_change, on_suspect, config

    # --- lookup (before the cache and the network) ------------------------------------------------------

    def is_suspect(self, url: str) -> bool:
        st = self.domains.state_of(_host(url))
        return st is not None and st.state == "suspect"

    def is_listed(self, url: str, scope: Scope | None) -> bool:
        return scope is not None and self.domains.is_listed(_host(url), scope)

    def domain_of(self, url: str) -> str:
        host = _host(url)
        return self.domains.domain_for(host, host)

    # --- inspection (after a page was read) --------------------------------------------------------------

    def inspect(self, url: str, text: str, links: Sequence[tuple[str, str]], *, content_type: str,
                fetched_at: datetime | None, is_official: Callable[[str], bool], original: bytes | None = None,
                original_type: str | None = None, flag: bool = True) -> Inspection:
        """Runs the integrity checks and stores the snapshot (flagged when a check failed). With `flag` (the
        default) a failure runs the suspect flow at once; the gateway passes False and runs it after its page
        transaction (review M3)."""
        listed = self.domains.listed_domains()
        own = self.domain_of(url)

        def on_list(link: str) -> bool:  # a host listed in any scope is never an off-list link (review C2)
            host = _host(link)
            return host_matches(host, own) or is_official(link) or any(host_matches(host, d) for d in listed)

        too_large = original is not None and len(original) > self.snapshots.max_bytes
        if too_large:
            original = None  # the text is kept; a file over the cap is not, and the snapshot says so (review M5)
        prev = self.snapshots.latest(url)
        previous = integrity.Previous(prev.text, prev.links_total, prev.links_off_list) if prev else None
        findings = integrity.check_page(text, links, on_list, previous, self.config)
        snap = self.snapshots.save(
            url, text, content_type=content_type, links_total=len(links),
            links_off_list=integrity.off_list_links(links, on_list), flagged=findings[0].code if findings else None,
            fetched_at=fetched_at, original=original, original_type=original_type, original_too_large=too_large)
        if findings and flag:
            self.flag(url, findings[0].code, describe(findings), snap.id)
        return Inspection(tuple(findings), snap.id)

    # --- the suspect flow --------------------------------------------------------------------------------

    def flag(self, url: str, reason: str, detail: str = "", snapshot_id: int | None = None) -> SuspectCase | None:
        """Marks the url's domain suspect and runs the flow. Returns the case for the one caller that changed the
        state; None when the domain was suspect already (the drop is completed all the same)."""
        return self.flag_domain(self.domain_of(url), reason, detail, url=url, snapshot_id=snapshot_id)

    def flag_domain(self, domain: str, reason: str, detail: str = "", *, url: str = "",
                    snapshot_id: int | None = None) -> SuspectCase | None:
        def payload(conn: Connection) -> dict:
            return {"detail": detail, "url": url, "snapshot_id": snapshot_id,
                    "facts_dropped": facts_on_domain(conn, self.tenant_id, domain)}
        won = self.domains.mark_suspect(domain, reason, payload)
        return self._finish(domain, reason, detail, url, snapshot_id, won)

    def sync(self, allow: AllowList, *, remove_missing: bool = False) -> SyncResult:
        """`SourceDomains.sync` with the one-body-one-domain rule run through the suspect flow (review I3)."""
        def payload(conn: Connection, domain: str, reason: str) -> dict:
            return {"detail": "allow-list sync", "url": "", "snapshot_id": None,
                    "facts_dropped": facts_on_domain(conn, self.tenant_id, domain)}
        return self.domains.sync(allow, remove_missing=remove_missing, payload=payload,
                                 after_mark=lambda d, r, won: self._finish(d, r, "allow-list sync", "", None, won))

    def complete_drops(self) -> int:
        """Completes the drop for every suspect domain (after a crash between the state change and the drop)."""
        return sum(len(drop_domain_facts(self.engine, self.tenant_id, self.knowledge, d, self.after_change))
                   for d in self.domains.domains(state="suspect"))

    def _finish(self, domain: str, reason: str, detail: str, url: str, snapshot_id: int | None,
                won: bool) -> SuspectCase | None:
        dropped = drop_domain_facts(self.engine, self.tenant_id, self.knowledge, domain, self.after_change)
        if not won:
            return None
        case = SuspectCase(domain, reason, detail, url, snapshot_id, tuple(dropped))
        if self.on_suspect is not None:
            self.on_suspect(case)
        return case


def describe(findings: Sequence[integrity.Finding]) -> str:
    return "; ".join(f"{f.code}: {f.detail}" for f in findings)


def facts_on_domain(conn: Connection, tenant_id: str, domain: str) -> list[int]:
    """Ids of the confirmed, verified or stale facts whose source URL is on the domain (or a subdomain)."""
    rows = conn.execute(select(T.c.id, T.c.url).where(
        T.c.tenant_id == tenant_id, T.c.status != "unconfirmed", T.c.url.ilike(f"%{domain}%")).order_by(T.c.id)).all()
    return [r.id for r in rows if host_matches(_host(r.url or ""), domain)]


def _lock_key(tenant_id: str, domain: str) -> int:
    return int.from_bytes(hashlib.sha256(f"source_drop:{tenant_id}:{domain}".encode()).digest()[:8], "big",
                          signed=True)


def drop_domain_facts(engine: Engine, tenant_id: str, knowledge: SqlKnowledge, domain: str,
                      after_change: AfterChange | None = None) -> list[int]:
    """Every confirmed, verified or stale fact whose source URL is on the domain goes back to `unconfirmed` (spec
    §4.2). Each step is a revision (cause `monitor`, ref `source:<domain>`). Idempotent and resumable: callers for one
    domain are serialised by an advisory lock and each fact's status is read again before it changes, so a fact
    drops once however many callers run. Returns the fact ids this call dropped."""
    dropped: list[int] = []
    with engine.connect() as lock:
        lock.execute(text("SELECT pg_advisory_lock(:k)"), {"k": _lock_key(tenant_id, domain)})
        try:
            with engine.connect() as conn:
                ids = facts_on_domain(conn, tenant_id, domain)
            for fid in ids:
                with engine.connect() as conn:
                    r = conn.execute(select(T.c.scope, T.c.ref, T.c.field, T.c.intake_year, T.c.status).where(
                        T.c.tenant_id == tenant_id, T.c.id == fid)).first()
                if r is None or r.status == "unconfirmed":
                    continue
                knowledge.set_status(fid, "unconfirmed", cause="monitor", cause_ref=f"source:{domain}",
                                     actor="source_guard")
                dropped.append(fid)
                if after_change is not None:
                    after_change(r.scope, r.ref, r.field, fid, "unconfirmed", r.intake_year)
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _lock_key(tenant_id, domain)})
            lock.commit()
    return dropped
