"""Reviewed allow-lists of official sources and each domain's state (P2 spec §4.2, P2-D10; R-24, R-71).

The lists are YAML files in `lists/` (or any directory), one per region and family, or per route:

    region: <region code>        # or `route_key: <route>` for a route list; never both
    family: <family>
    bodies:
      - body_ref: <registry id of the body, '' when not in the registry yet>
        tier: regulator | board | admission_body | institution
        domains: [<domain>, ...]
        list_ref: <the official list or page that names the domain>
        reviewed_by: <reviewer>
        preferred_suffixes: [<suffix>, ...]   # R-71: which domain stays when two claim one body
        multiple_domains_ok: false            # true: a reviewer confirmed that the body really has several domains

No domain, region or suffix is written in code (R-58). The state (`active` / `suspect`) is runtime state in
`os_source_domains`; syncing a list never reactivates a suspect domain.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml
from sqlalchemy import Connection, Engine, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from app.os import clock as shared_clock
from app.os import models

LISTS_DIR = Path(__file__).with_name("lists")
D = models.source_domains
_CODE = re.compile(r"^[a-z][a-z0-9_]*$")


class AllowListError(ValueError):
    pass


class NotApproved(PermissionError):
    """Setting a suspect domain back to active needs two different approvers (P2 spec §4.2)."""


@dataclass(frozen=True)
class SourceEntry:
    domain: str
    region: str = ""
    family: str = ""
    route_key: str = ""
    body_ref: str = ""
    tier: str | None = None
    list_ref: str = ""
    reviewed_by: str = ""


@dataclass(frozen=True)
class Scope:
    """Where a page is read for: a region and family, or a route."""
    region: str = ""
    family: str = ""
    route_key: str = ""


@dataclass(frozen=True)
class AllowList:
    entries: tuple[SourceEntry, ...]
    preferred_suffixes: dict[str, tuple[str, ...]]  # body_ref -> suffixes
    multiple_ok: frozenset[str]  # body_refs a reviewer confirmed as having several domains


@dataclass(frozen=True)
class SyncResult:
    added: int
    updated: int
    removed: int
    suspect: tuple[tuple[str, str], ...]  # (domain, reason) this sync set suspect (one-body-one-domain rule)
    tombstoned: int = 0  # suspect rows no longer on a list: kept (tier NULL), never deleted (review I4)


@dataclass(frozen=True)
class DomainState:
    domain: str
    state: str
    reason: str | None
    since: datetime


def clean_domain(value: str) -> str:
    d = str(value).strip().lower().rstrip(".")
    if not d or "/" in d or ":" in d or " " in d or "." not in d:
        raise AllowListError(f"'{value}' is not a bare domain name")
    return d


def person_id(value: str | None) -> str:
    """An approver's identity, normalised (review I7): 'Ann ' and 'ann' are one person."""
    return (value or "").strip().casefold()


def suffix_matches(domain: str, suffix: str) -> bool:
    """A preferred suffix matches on a label boundary only: 'edu.test' matches 'x.edu.test', not 'xedu.test'."""
    s = suffix.lower().strip().lstrip(".")
    return bool(s) and (domain == s or domain.endswith("." + s))


def host_matches(host: str, domain: str) -> bool:
    """A host is on a listed domain when it is that domain or a subdomain of it."""
    h = host.lower().rstrip(".")
    return h == domain or h.endswith("." + domain)


def load_allowlist(directory: Path = LISTS_DIR) -> AllowList:
    entries: list[SourceEntry] = []
    preferred: dict[str, tuple[str, ...]] = {}
    multiple: set[str] = set()
    for path in sorted(Path(directory).glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        region, family, route = data.get("region", ""), data.get("family", ""), data.get("route_key", "")
        if bool(region) == bool(route):
            raise AllowListError(f"{path.name}: give exactly one of `region` and `route_key`")
        for key, value in (("region", region), ("family", family), ("route_key", route)):
            if value and not _CODE.match(str(value)):
                raise AllowListError(f"{path.name}: {key} '{value}' must be snake case")
        if region and not family:
            raise AllowListError(f"{path.name}: a region list needs a `family`")
        for body in data.get("bodies") or []:
            tier = body.get("tier")
            if tier not in models.SOURCE_TIERS:
                raise AllowListError(f"{path.name}: tier '{tier}' is not one of {models.SOURCE_TIERS}")
            if not str(body.get("list_ref", "")).strip():
                raise AllowListError(f"{path.name}: every body names the official list that names its domain (list_ref)")
            if not str(body.get("reviewed_by", "")).strip():
                raise AllowListError(f"{path.name}: every body names who reviewed it (reviewed_by)")
            ref = str(body.get("body_ref", "") or "")
            if ref:
                preferred[ref] = tuple(dict.fromkeys(preferred.get(ref, ()) + tuple(
                    str(s).lower() for s in body.get("preferred_suffixes") or ())))
                if body.get("multiple_domains_ok"):
                    multiple.add(ref)
            for d in body.get("domains") or []:
                entries.append(SourceEntry(clean_domain(d), str(region or ""), str(family or ""), str(route or ""),
                                           ref, tier, str(body["list_ref"]), str(body["reviewed_by"])))
    keys = [(e.domain, e.region, e.family, e.route_key) for e in entries]
    if len(set(keys)) != len(keys):
        raise AllowListError("a domain is listed twice for the same region, family and route")
    return AllowList(tuple(entries), preferred, frozenset(multiple))


def resolve_claims(allow: AllowList) -> dict[str, str]:
    """R-71: when two domains claim one body, the one with a preferred suffix stays; the rest are suspect until a
    person confirms them. With no single preferred domain, all of them are suspect. Returns domain -> reason."""
    by_body: dict[str, set[str]] = {}
    for e in allow.entries:
        if e.body_ref and e.body_ref not in allow.multiple_ok:
            by_body.setdefault(e.body_ref, set()).add(e.domain)
    out: dict[str, str] = {}
    for ref, domains in by_body.items():
        if len(domains) < 2:
            continue
        suffixes = allow.preferred_suffixes.get(ref, ())
        keep = {d for d in domains if any(suffix_matches(d, s) for s in suffixes)}
        if len(keep) == 1:
            for d in domains - keep:
                out[d] = f"duplicate_claim:{ref}"
        else:
            for d in domains:
                out[d] = f"ambiguous_claim:{ref}"
    return out


class SourceDomains:
    def __init__(self, engine: Engine, tenant_id: str, clock: Callable[[], datetime] = shared_clock.now) -> None:
        self.engine, self.tenant_id, self.clock = engine, tenant_id, clock

    # --- load -----------------------------------------------------------------------------------------

    def sync(self, allow: AllowList, *, remove_missing: bool = False,
             payload: Callable[[Connection, str, str], dict] | None = None,
             after_mark: Callable[[str, str, bool], None] | None = None) -> SyncResult:
        """Loads the entries. Existing rows keep their state; a new row for a domain that has a suspect row is
        suspect too (re-adding never reactivates, review I4). The one-body-one-domain rule (R-71) is applied to new
        and existing rows alike, in the same transaction, through `mark_suspect` (an event per domain it changed;
        `payload` adds to it). After the commit `after_mark(domain, reason, changed)` runs for every claimed domain
        (the guard drops the facts there, resumably). Only rows that really changed are counted."""
        claims = resolve_claims(allow)
        added = updated = removed = tombstoned = 0
        changed: list[tuple[str, str]] = []
        now = self.clock()
        with self.engine.begin() as conn:
            for e in allow.entries:
                where = (D.c.tenant_id == self.tenant_id, D.c.domain == e.domain, D.c.region == e.region,
                         D.c.family == e.family, D.c.route_key == e.route_key)
                fields = {"body_ref": e.body_ref, "tier": e.tier, "list_ref": e.list_ref, "reviewed_by": e.reviewed_by}
                if conn.execute(select(D.c.id).where(*where)).first() is None:
                    bad = conn.execute(select(D.c.state_reason).where(
                        D.c.tenant_id == self.tenant_id, D.c.domain == e.domain, D.c.state == "suspect")).first()
                    conn.execute(insert(D).values(
                        tenant_id=self.tenant_id, domain=e.domain, region=e.region, family=e.family,
                        route_key=e.route_key, **fields, state="suspect" if bad else "active",
                        state_reason=bad.state_reason if bad else None, state_since=now))
                    added += 1
                else:
                    differs = or_(*(D.c[k].is_distinct_from(v) for k, v in fields.items()))
                    r = conn.execute(update(D).where(*where, differs).values(**fields, updated_at=func.now()))
                    updated += r.rowcount
            if remove_missing:
                keep = {(e.domain, e.region, e.family, e.route_key) for e in allow.entries}
                rows = conn.execute(select(D.c.id, D.c.domain, D.c.region, D.c.family, D.c.route_key, D.c.state)
                                    .where(D.c.tenant_id == self.tenant_id, D.c.tier.is_not(None))).all()
                gone = [r for r in rows if (r.domain, r.region, r.family, r.route_key) not in keep]
                drop = [r.id for r in gone if r.state != "suspect"]
                tomb = [r.id for r in gone if r.state == "suspect"]
                if drop:
                    removed = conn.execute(delete(D).where(D.c.id.in_(drop))).rowcount
                if tomb:  # a suspect row is evidence: it stays, off the lists, until two approvers clear it
                    tombstoned = conn.execute(update(D).where(D.c.id.in_(tomb))
                                              .values(tier=None, updated_at=func.now())).rowcount
            for domain, reason in sorted(claims.items()):
                extra = payload(conn, domain, reason) if payload else None
                if self._mark(conn, domain, reason, extra):
                    changed.append((domain, reason))
        if after_mark is not None:
            for domain, reason in sorted(claims.items()):
                after_mark(domain, reason, (domain, reason) in changed)
        return SyncResult(added, updated, removed, tuple(changed), tombstoned)

    # --- reads ----------------------------------------------------------------------------------------

    def _rows(self, conn, host: str):
        rows = conn.execute(select(D).where(D.c.tenant_id == self.tenant_id)).all()
        return [r for r in rows if host_matches(host, r.domain)]

    def listed_domains(self) -> list[str]:
        """Domains with an active entry on any list (any scope)."""
        with self.engine.connect() as conn:
            return list(conn.execute(select(D.c.domain).where(
                D.c.tenant_id == self.tenant_id, D.c.state == "active", D.c.tier.is_not(None)).distinct()).scalars())

    def state_of(self, host: str) -> DomainState | None:
        """`suspect` if any row of the host's domain is suspect; else `active` if listed; None if unknown."""
        with self.engine.connect() as conn:
            rows = self._rows(conn, host)
        if not rows:
            return None
        bad = [r for r in rows if r.state == "suspect"]
        r = max(bad or rows, key=lambda x: len(x.domain))
        return DomainState(r.domain, r.state, r.state_reason, r.state_since)

    def is_listed(self, host: str, scope: Scope) -> bool:
        """True when an active entry for the host's domain applies to the scope's route or region and family."""
        with self.engine.connect() as conn:
            rows = self._rows(conn, host)
        if any(r.state == "suspect" for r in rows):  # one suspect row (any scope, or a parent) refuses (review I1)
            return False
        return any(r.state == "active" and r.tier is not None and (
            (scope.route_key and r.route_key == scope.route_key)
            or (scope.region and r.region == scope.region and r.family == scope.family)) for r in rows)

    def domain_for(self, host: str, fallback: str) -> str:
        """The listed domain a host belongs to (the most specific), or `fallback`."""
        with self.engine.connect() as conn:
            rows = self._rows(conn, host)
        return max((r.domain for r in rows), key=len) if rows else fallback

    def domains(self, *, state: str | None = None) -> list[str]:
        q = select(D.c.domain).where(D.c.tenant_id == self.tenant_id).distinct().order_by(D.c.domain)
        if state:
            q = q.where(D.c.state == state)
        with self.engine.connect() as conn:
            return list(conn.execute(q).scalars())

    # --- state changes --------------------------------------------------------------------------------

    def mark_suspect(self, domain: str, reason: str, payload: Callable[[Connection], dict] | None = None) -> bool:
        """Every active row of the domain becomes suspect (a flag row is added for a domain on no list), and the
        `source_suspect` event is written in the same transaction. Race-safe: the caller that changed the state wins
        (True); every other caller, and a domain that was suspect already, gets False (review I2)."""
        with self.engine.begin() as conn:
            return self._mark(conn, domain, reason, payload(conn) if payload else None)

    def _mark(self, conn: Connection, domain: str, reason: str, extra: dict | None) -> bool:
        now = self.clock()
        won = conn.execute(update(D).where(D.c.tenant_id == self.tenant_id, D.c.domain == domain,
                                           D.c.state == "active")
                           .values(state="suspect", state_reason=reason, state_since=now,
                                   updated_at=func.now())).rowcount > 0
        if not won and conn.execute(select(D.c.id).where(D.c.tenant_id == self.tenant_id,
                                                         D.c.domain == domain)).first() is None:
            # the flag row's key is (domain, '', '', ''): unique, so two racing inserts give one row
            won = conn.execute(insert(D).values(
                tenant_id=self.tenant_id, domain=domain, state="suspect", state_reason=reason, state_since=now)
                .on_conflict_do_nothing(constraint="uq_os_source_domains_entry").returning(D.c.id)).first() is not None
        if won:
            conn.execute(insert(models.events).values(tenant_id=self.tenant_id, type="source_suspect", payload={
                "tenant_id": self.tenant_id, "domain": domain, "reason": reason, **(extra or {})}))
        return won

    def reactivate(self, domain: str, *, requested_by: str, approved_by: str,
                   is_approver: Callable[[str], bool]) -> int:
        """Only an approver can set a domain back to active, and two different approvers must agree (two-person
        rule). Ids are normalised (`person_id`) before they are compared or checked; `is_approver` is the
        reviewer-role check (T5's `os_reviewers`). A `source_reactivated` event names both, in the same
        transaction."""
        a, b = person_id(requested_by), person_id(approved_by)
        if not a or not b or a == b:
            raise NotApproved("two different people must approve")
        if not (is_approver(a) and is_approver(b)):
            raise NotApproved("both must be approvers")
        with self.engine.begin() as conn:
            r = conn.execute(update(D).where(D.c.tenant_id == self.tenant_id, D.c.domain == domain,
                                             D.c.state == "suspect")
                             .values(state="active", state_reason=None, state_since=self.clock(),
                                     updated_at=func.now()))
            if r.rowcount and conn.execute(select(D.c.id).where(
                    D.c.tenant_id == self.tenant_id, D.c.domain == domain, D.c.tier.is_(None))).first():
                # a flag row or tombstone has no list entry to return to: it goes away
                conn.execute(delete(D).where(D.c.tenant_id == self.tenant_id, D.c.domain == domain,
                                             D.c.tier.is_(None)))
            if r.rowcount:
                conn.execute(insert(models.events).values(tenant_id=self.tenant_id, type="source_reactivated",
                                                          payload={"tenant_id": self.tenant_id, "domain": domain,
                                                                   "approvers": [a, b]}))
            return r.rowcount


def seed_route_entries(route_key: str, domains: Iterable[str], *, list_ref: str, reviewed_by: str,
                       tier: str = "institution") -> list[SourceEntry]:
    """A route's `official_sources` / a programme's `official_domains` as allow-list entries (P2-D10), so the old
    lists keep working. The caller passes them to `SourceDomains.sync` through an `AllowList`."""
    return [SourceEntry(clean_domain(d), route_key=route_key, tier=tier, list_ref=list_ref, reviewed_by=reviewed_by)
            for d in domains]
