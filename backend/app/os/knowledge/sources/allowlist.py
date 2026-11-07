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
from sqlalchemy import Engine, delete, func, select, update
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
    suspect: tuple[tuple[str, str], ...]  # (domain, reason) set suspect by the one-body-one-domain rule


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
        keep = {d for d in domains if any(d.endswith(s) for s in suffixes)}
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

    def sync(self, allow: AllowList, *, remove_missing: bool = False) -> SyncResult:
        """Loads the entries. Existing rows keep their state (a suspect domain stays suspect); new rows are
        active, unless the one-body-one-domain rule marks them suspect."""
        claims = resolve_claims(allow)
        added = updated = 0
        now = self.clock()
        with self.engine.begin() as conn:
            for e in allow.entries:
                where = (D.c.tenant_id == self.tenant_id, D.c.domain == e.domain, D.c.region == e.region,
                         D.c.family == e.family, D.c.route_key == e.route_key)
                fields = {"body_ref": e.body_ref, "tier": e.tier, "list_ref": e.list_ref, "reviewed_by": e.reviewed_by}
                if conn.execute(select(D.c.id).where(*where)).first() is None:
                    reason = claims.get(e.domain)
                    conn.execute(insert(D).values(
                        tenant_id=self.tenant_id, domain=e.domain, region=e.region, family=e.family,
                        route_key=e.route_key, **fields, state="suspect" if reason else "active",
                        state_reason=reason, state_since=now))
                    added += 1
                else:
                    r = conn.execute(update(D).where(*where).values(**fields, updated_at=func.now()))
                    updated += r.rowcount
            removed = 0
            if remove_missing:
                keep = {(e.domain, e.region, e.family, e.route_key) for e in allow.entries}
                rows = conn.execute(select(D.c.id, D.c.domain, D.c.region, D.c.family, D.c.route_key).where(
                    D.c.tenant_id == self.tenant_id, D.c.tier.is_not(None))).all()
                gone = [r.id for r in rows if (r.domain, r.region, r.family, r.route_key) not in keep]
                if gone:
                    removed = conn.execute(delete(D).where(D.c.id.in_(gone))).rowcount
        return SyncResult(added, updated, removed, tuple(sorted(claims.items())))

    # --- reads ----------------------------------------------------------------------------------------

    def _rows(self, conn, host: str):
        rows = conn.execute(select(D).where(D.c.tenant_id == self.tenant_id)).all()
        return [r for r in rows if host_matches(host, r.domain)]

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

    def mark_suspect(self, domain: str, reason: str) -> bool:
        """Every row of the domain becomes suspect (a flag row is added for a domain not on any list). False when
        it was suspect already, so the caller opens one review item, not many."""
        now = self.clock()
        with self.engine.begin() as conn:
            rows = [r for r in conn.execute(select(D).where(D.c.tenant_id == self.tenant_id, D.c.domain == domain))]
            if not rows:
                conn.execute(insert(D).values(tenant_id=self.tenant_id, domain=domain, state="suspect",
                                              state_reason=reason, state_since=now))
                return True
            if all(r.state == "suspect" for r in rows):
                return False
            conn.execute(update(D).where(D.c.tenant_id == self.tenant_id, D.c.domain == domain,
                                         D.c.state == "active")
                         .values(state="suspect", state_reason=reason, state_since=now, updated_at=func.now()))
            return True

    def reactivate(self, domain: str, *, requested_by: str, approved_by: str,
                   is_approver: Callable[[str], bool]) -> int:
        """Only an approver can set a domain back to active, and two different approvers must agree (two-person
        rule). `is_approver` is the reviewer-role check (T5's `os_reviewers`)."""
        a, b = (requested_by or "").strip(), (approved_by or "").strip()
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
                # a flag row for a domain on no list has no entry to return to: it goes away
                conn.execute(delete(D).where(D.c.tenant_id == self.tenant_id, D.c.domain == domain,
                                             D.c.tier.is_(None)))
            return r.rowcount


def seed_route_entries(route_key: str, domains: Iterable[str], *, list_ref: str, reviewed_by: str,
                       tier: str = "institution") -> list[SourceEntry]:
    """A route's `official_sources` / a programme's `official_domains` as allow-list entries (P2-D10), so the old
    lists keep working. The caller passes them to `SourceDomains.sync` through an `AllowList`."""
    return [SourceEntry(clean_domain(d), route_key=route_key, tier=tier, list_ref=list_ref, reviewed_by=reviewed_by)
            for d in domains]
