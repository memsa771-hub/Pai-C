"""The guard the page gateway calls (P2 spec §4.2): lookup, integrity checks, snapshots and the suspect flow.

A failed check marks the domain `suspect`. Then, in this order: the domain's facts drop to `unconfirmed` (through
`set_status` and `after_fact_change`, so plans revise), an `os_events` row `source_suspect` is written and the
`on_suspect` hook is called (T5 opens the `suspect_domain` review item there). Nothing new is taken from a suspect
domain: the gateway refuses it before it reads the cache or the network.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit

from sqlalchemy import Engine, insert, select

from app.os import models
from app.os.knowledge.research.links import registrable
from app.os.knowledge.sources import integrity
from app.os.knowledge.sources.allowlist import Scope, SourceDomains, host_matches
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
        st = self.domains.state_of(urlsplit(url).hostname or "")
        return st is not None and st.state == "suspect"

    def is_listed(self, url: str, scope: Scope | None) -> bool:
        return scope is not None and self.domains.is_listed(urlsplit(url).hostname or "", scope)

    # --- inspection (after a page was read) --------------------------------------------------------------

    def inspect(self, url: str, text: str, links: Sequence[tuple[str, str]], *, content_type: str,
                fetched_at: datetime, is_official: Callable[[str], bool], original: bytes | None = None,
                original_type: str | None = None) -> Inspection:
        """Runs the integrity checks, stores the snapshot (flagged when a check failed) and, on a failure, runs the
        suspect flow for the page's domain."""
        known = [d for d in self.domains.domains()]
        own = registrable(urlsplit(url).hostname or "")

        def on_list(link: str) -> bool:
            host = urlsplit(link).hostname or ""
            return registrable(host) == own or is_official(link) or any(host_matches(host, d) for d in known)

        if original is not None and len(original) > self.snapshots.max_bytes:
            original = None  # the text is kept; a file over the cap is not
        prev = self.snapshots.latest(url)
        previous = integrity.Previous(prev.text, prev.links_total, prev.links_off_list) if prev else None
        findings = integrity.check_page(text, links, on_list, previous, self.config)
        snap = self.snapshots.save(
            url, text, content_type=content_type, links_total=len(links),
            links_off_list=integrity.off_list_links(links, on_list), flagged=findings[0].code if findings else None,
            fetched_at=fetched_at, original=original, original_type=original_type)
        if findings:
            self.flag(url, findings[0].code, "; ".join(f"{f.code}: {f.detail}" for f in findings), snap.id)
        return Inspection(tuple(findings), snap.id)

    # --- the suspect flow --------------------------------------------------------------------------------

    def flag(self, url: str, reason: str, detail: str = "", snapshot_id: int | None = None) -> SuspectCase | None:
        """Marks the url's domain suspect and runs the flow once (None when it was suspect already)."""
        host = urlsplit(url).hostname or ""
        domain = self.domains.domain_for(host, registrable(host))
        if not self.domains.mark_suspect(domain, reason):
            return None
        dropped = drop_domain_facts(self.engine, self.tenant_id, self.knowledge, domain, self.after_change)
        case = SuspectCase(domain, reason, detail, url, snapshot_id, tuple(dropped))
        with self.engine.begin() as conn:
            conn.execute(insert(models.events).values(
                tenant_id=self.tenant_id, type="source_suspect",
                payload={"tenant_id": self.tenant_id, "domain": domain, "reason": reason, "detail": detail,
                         "url": url, "snapshot_id": snapshot_id, "facts_dropped": list(dropped)}))
        if self.on_suspect is not None:
            self.on_suspect(case)
        return case


def drop_domain_facts(engine: Engine, tenant_id: str, knowledge: SqlKnowledge, domain: str,
                      after_change: AfterChange | None = None) -> list[int]:
    """Every confirmed, verified or stale fact whose source URL is on the domain goes back to `unconfirmed` (spec
    §4.2). Each step is a revision (cause `monitor`, ref `source:<domain>`). Returns the fact ids."""
    with engine.connect() as conn:
        rows = conn.execute(select(T.c.id, T.c.scope, T.c.ref, T.c.field, T.c.intake_year, T.c.url).where(
            T.c.tenant_id == tenant_id, T.c.status != "unconfirmed", T.c.url.ilike(f"%{domain}%")).order_by(T.c.id)).all()
    dropped: list[int] = []
    for r in rows:
        if not host_matches(urlsplit(r.url or "").hostname or "", domain):
            continue
        knowledge.set_status(r.id, "unconfirmed", cause="monitor", cause_ref=f"source:{domain}", actor="source_guard")
        dropped.append(r.id)
        if after_change is not None:
            after_change(r.scope, r.ref, r.field, r.id, "unconfirmed", r.intake_year)
    return dropped
