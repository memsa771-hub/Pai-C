"""Versioned, program- and intake-scoped research evidence."""

from datetime import datetime, timezone
import logging
import time
from uuid import uuid4
import hashlib
import json
from copy import deepcopy
from datetime import timedelta
from urllib.parse import urldefrag, urlsplit

from sqlalchemy import select

from app.models import EventRecord, Institution, InstitutionDomain, Opportunity, RequirementSet
from app.plugins._shared.verification import SourceVerifier, _host, official_url

logger = logging.getLogger(__name__)


class ResearchEvidenceError(ValueError):
    pass


def _public_claim(claim):
    """Copy the evidence schema, never workspace-specific extension metadata."""
    return {key: deepcopy(value) for key, value in claim.items() if key in {
        "field", "value", "quote", "source_url", "checked_at", "kind", "category",
        "comparator", "threshold", "unit", "scale", "decisive_field"}}


def _https_url(value: str) -> str:
    from urllib.parse import urlparse
    parsed = urlparse(str(value or ""))
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ResearchEvidenceError("A public HTTPS source URL is required")
    return value


class RequirementStore:
    def __init__(self, db):
        self.db = db

    def institution_for_url(self, url: str) -> str | None:
        """Resolve an official page to a trusted catalog identity, if unique."""
        candidates = self.db.execute(select(Institution).where(
            Institution.owner_workspace_id.is_(None),
            Institution.provider.isnot(None), Institution.source != "student",
            Institution.website_url.isnot(None),
        )).scalars().all()
        matches = [(len(host), item.name) for item in candidates
                   if (host := _host(item.website_url or "")) and official_url(url, {host})]
        if not matches:
            return None
        best = max(length for length, _ in matches)
        names = {name for length, name in matches if length == best}
        return next(iter(names)) if len(names) == 1 else None

    def register_provider_identity(self, identity: dict) -> str:
        """Record a registry backed website assertion, never a search hit."""
        provider_id = str(identity["provider_id"])
        row = self.db.execute(select(Institution).where(
            Institution.provider == "ror", Institution.provider_id == provider_id,
        ).with_for_update()).scalar_one_or_none()
        if row is None:
            row = Institution(name=identity["name"],
                              normalized_name=identity["name"].strip().casefold(),
                              country_code=identity["country_code"],
                              website_url=identity["website_url"],
                              source="catalog", provider="ror", provider_id=provider_id)
            self.db.add(row)
            self.db.flush()
        for domain in identity["domains"]:
            existing = self.db.execute(select(InstitutionDomain.id).where(
                InstitutionDomain.institution_id == row.id,
                InstitutionDomain.domain == domain)).first()
            if existing is None:
                self.db.add(InstitutionDomain(
                    institution_id=row.id, domain=domain,
                    source_url=provider_id, origin="ror_registry",
                    checked_at=datetime.now(timezone.utc)))
        self.db.flush()
        return row.name

    def propose(self, workspace_id: str, *, route: dict, country: str,
                source_url: str, checked_at: datetime, rules: list[dict],
                institution: str | None = None, level: str | None = None,
                intake: str | None = None, fees: dict | None = None,
                deadlines: dict | None = None,
                opportunity_id: str | None = None, page_text: str = "",
                corroboration: list[dict] | None = None,
                corroborated_at: datetime | None = None,
                public_facts: bool = False) -> tuple[Opportunity, RequirementSet]:
        if not isinstance(route, dict) or not country or not isinstance(rules, list):
            raise ResearchEvidenceError("Route, country and rules are required")
        if not isinstance(checked_at, datetime) or checked_at.tzinfo is None:
            raise ResearchEvidenceError("checked_at must include a timezone")
        source_url = _https_url(source_url)
        for rule in rules:
            if not isinstance(rule, dict) or not rule.get("field") or not rule.get("source_url"):
                raise ResearchEvidenceError("Every rule needs a field and source URL")
            _https_url(rule["source_url"])
        for claims in (fees or {}, deadlines or {}):
            for value in claims.values():
                if not isinstance(value, dict) or not value.get("source_url"):
                    raise ResearchEvidenceError("Every fee or deadline needs a source URL")
                _https_url(value["source_url"])
        if opportunity_id is None:
            possible = self.db.execute(select(Opportunity).where(
                Opportunity.workspace_id == workspace_id,
                Opportunity.url == source_url,
                Opportunity.country == country,
                Opportunity.level == level,
                Opportunity.intake == intake,
            )).scalars().all()
            match = next((item for item in possible if item.route == route and
                          item.institution == institution), None)
            opportunity_id = match.id if match else None
        previous = None
        if opportunity_id:
            opportunity = self.db.execute(select(Opportunity).where(
                Opportunity.id == opportunity_id,
                Opportunity.workspace_id == workspace_id,
            ).with_for_update()).scalar_one_or_none()
            if opportunity is None:
                raise ResearchEvidenceError("Opportunity not found in student workspace")
            if (opportunity.country, opportunity.level, opportunity.intake) != (country, level, intake):
                raise ResearchEvidenceError("Cannot revise evidence for another route or intake")
            previous = self.db.execute(select(RequirementSet).where(
                RequirementSet.opportunity_id == opportunity.id,
            ).order_by(RequirementSet.version.desc()).limit(1)).scalar_one_or_none()
            version = (previous.version if previous else 0) + 1
            institution = opportunity.institution
        else:
            opportunity = Opportunity(
                id=str(uuid4()), workspace_id=workspace_id, route=route,
                country=country, institution=institution, level=level,
                intake=intake, url=source_url)
            self.db.add(opportunity)
            version = 1
        claims = [*rules, *(fees or {}).values(), *(deadlines or {}).values()]
        from app.config import config
        verification_started = time.monotonic()
        verdict = SourceVerifier(
            freshness_days=max(1, config.PAI_RESEARCH_FRESHNESS_DAYS),
            deadline_freshness_days=max(1, config.PAI_RESEARCH_DEADLINE_FRESHNESS_DAYS)).verify(
            claims=claims, source_url=source_url,
            official_domains=self.official_domains(institution), intake=intake,
            page_text=page_text, checked_at=checked_at,
            corroboration=corroboration, corroborated_at=corroborated_at)
        logger.info("research span stage=verifier status=%s duration_ms=%d",
                    verdict.status, round((time.monotonic() - verification_started) * 1000))
        requirement = RequirementSet(
            id=str(uuid4()), opportunity_id=opportunity.id, rules=rules,
            fees=fees or {}, deadlines=deadlines or {}, source_url=source_url,
            checked_at=checked_at, version=version, status=verdict.status,
            verification_checks=verdict.checks, cycle_label=verdict.cycle_label,
            verified_at=datetime.now(timezone.utc) if verdict.status == "verified" else None)
        self.db.add(requirement)
        if (public_facts and not urlsplit(source_url).query
                and official_url(source_url, self.official_domains(institution))):
            requirement.verification_checks = {**requirement.verification_checks,
                "public_cache": {"key": self.cache_key(source_url, country, level, intake,
                    route.get("program_id")), "passed": verdict.status == "verified"}}
        self.db.flush()
        if previous and (previous.rules != rules or previous.fees != (fees or {})
                         or previous.deadlines != (deadlines or {})
                         or previous.status != verdict.status):
            from app.pai_c.roadmaps.service import RoadmapService
            RoadmapService(self.db).mark_stale(
                workspace_id, "Research evidence changed; this route needs a fresh fit check",
                source_url=source_url)
        return opportunity, requirement

    def official_domains(self, institution_name: str | None) -> set[str]:
        """Trust provider-backed catalog identity; student-added URLs never qualify."""
        if not institution_name:
            return set()
        institutions = self.db.execute(select(Institution).where(
            Institution.normalized_name == institution_name.strip().casefold(),
            Institution.owner_workspace_id.is_(None),
            Institution.provider.isnot(None), Institution.source != "student",
        ).with_for_update()).scalars().all()
        domains = set()
        for institution in institutions:
            host = _host(institution.website_url or "")
            if host:
                domains.add(host)
                existing = self.db.execute(select(InstitutionDomain.id).where(
                    InstitutionDomain.institution_id == institution.id,
                    InstitutionDomain.domain == host)).first()
                if existing is None:
                    self.db.add(InstitutionDomain(
                        institution_id=institution.id, domain=host,
                        source_url=institution.website_url, origin="provider_catalog",
                        checked_at=datetime.now(timezone.utc)))
                    self.db.flush()
            domains.update(self.db.execute(select(InstitutionDomain.domain).where(
                InstitutionDomain.institution_id == institution.id)).scalars())
        return domains

    @staticmethod
    def cache_key(url, country, level=None, intake=None, program_id=None):
        scope = [urldefrag(url)[0].rstrip("/"), country, level or "", intake or "", program_id or ""]
        return hashlib.sha256(json.dumps(scope, ensure_ascii=True).encode()).hexdigest()

    @staticmethod
    def is_fresh(row):
        from app.config import config
        from app.research.scheduler import _near_deadline
        now = datetime.now(timezone.utc)
        checked = row.checked_at.replace(tzinfo=timezone.utc) if row.checked_at.tzinfo is None else row.checked_at
        window = (config.PAI_RESEARCH_DEADLINE_FRESHNESS_DAYS if _near_deadline(row, now.date())
                  else config.PAI_RESEARCH_FRESHNESS_DAYS)
        return now - timedelta(days=max(1, window)) <= checked <= now

    def cached(self, workspace_id, payload):
        """Reuse only explicitly public, official facts; clone no private route data."""
        from app.config import config
        from app.research.scheduler import _near_deadline

        url = payload["url"]
        key = self.cache_key(url, payload["country"], payload.get("level"),
                             payload.get("intake"), (payload.get("route") or {}).get("program_id"))
        pairs = self.db.execute(select(RequirementSet, Opportunity).join(Opportunity).where(
            RequirementSet.source_url == url,
            Opportunity.country == payload["country"], Opportunity.level == payload.get("level"),
            Opportunity.intake == payload.get("intake"),
        ).order_by(RequirementSet.checked_at.desc(), RequirementSet.created_at.desc(),
                   RequirementSet.version.desc())).all()
        eligible = [(row, opportunity) for row, opportunity in pairs
                    if ((row.verification_checks or {}).get("public_cache") or {}).get("key") == key]
        if not eligible:
            return None
        own = next((item for item, opportunity in pairs if opportunity.workspace_id == workspace_id
            and (opportunity.route or {}).get("program_id") == (payload.get("route") or {}).get("program_id")), None)
        if own is not None and own.status != "verified":
            return None
        row, opportunity = eligible[0]
        if (row.status != "verified" or not self.is_fresh(row)
                or not ((row.verification_checks or {}).get("public_cache") or {}).get("passed")
                or not official_url(url, self.official_domains(opportunity.institution))):
            return None
        if opportunity.workspace_id == workspace_id:
            return self.payload(opportunity, row, cached=True)
        # Materialize just public evidence into a workspace-owned Opportunity.
        # Student annotations, report text and source workspace IDs never cross.
        local = Opportunity(id=str(uuid4()), workspace_id=workspace_id,
            route={"url": url, **({"program_id": payload["route"]["program_id"]}
                  if (payload.get("route") or {}).get("program_id") else {})},
            country=payload["country"], level=payload.get("level"), intake=payload.get("intake"),
            institution=opportunity.institution, url=url)
        clone = RequirementSet(id=str(uuid4()), opportunity_id=local.id,
            rules=[_public_claim(claim) for claim in row.rules or []],
            fees={key: _public_claim(claim) for key, claim in (row.fees or {}).items()},
            deadlines={key: _public_claim(claim) for key, claim in (row.deadlines or {}).items()},
            source_url=url, checked_at=row.checked_at, status="verified", version=1,
            verified_at=row.verified_at, cycle_label=row.cycle_label,
            verification_checks={"public_cache": {"key": key, "passed": True}})
        self.db.add_all([local, clone])
        self.db.flush()
        return self.payload(local, clone, cached=True)

    @staticmethod
    def payload(opportunity, row, *, cached=False):
        def fact(value, kind, key):
            return {**value, "fact_id": f"{row.id}:{kind}:{key}", "status": row.status,
                    "source_url": value.get("source_url") or row.source_url,
                    "checked_at": value.get("checked_at") or row.checked_at.isoformat()}
        return {"opportunity_id": opportunity.id, "requirement_set_id": row.id,
            "status": row.status, "verification_checks": row.verification_checks,
            "rules": [fact(value, "rule", index) for index, value in enumerate(row.rules or [])],
            "fees": {key: fact(value, "fee", key) for key, value in (row.fees or {}).items()},
            "deadlines": {key: fact(value, "deadline", key) for key, value in (row.deadlines or {}).items()},
            "source_url": row.source_url, "checked_at": row.checked_at.isoformat(),
            "country": opportunity.country, "level": opportunity.level, "intake": opportunity.intake,
            "cached": cached}

    def preferred(self, workspace_id: str, opportunity_id: str) -> RequirementSet | None:
        rows = self.db.execute(select(RequirementSet).join(Opportunity).where(
            Opportunity.workspace_id == workspace_id,
            Opportunity.id == opportunity_id,
            RequirementSet.status.in_(("verified", "unconfirmed")),
        ).order_by(RequirementSet.version.desc())).scalars().all()
        # An older verified version cannot hide newer contradictory evidence.
        return rows[0] if rows else None

    def report_wrong_info(self, workspace_id: str, requirement_id: str) -> RequirementSet:
        row = self.db.execute(select(RequirementSet).join(Opportunity).where(
            Opportunity.workspace_id == workspace_id,
            RequirementSet.id == requirement_id,
        ).with_for_update()).scalar_one_or_none()
        if row is None:
            raise ResearchEvidenceError("Requirement set not found")
        if (row.verification_checks or {}).get("student_report"):
            return row
        row.status = "unconfirmed"
        row.verified_at = None
        checks = dict(row.verification_checks or {})
        checks["student_report"] = {"passed": False, "reason": "Student reported this information may be wrong"}
        row.verification_checks = checks
        from app.pai_c.roadmaps.service import RoadmapService
        RoadmapService(self.db).mark_stale(
            workspace_id, "A student reported a source may be wrong; we are checking it",
            source_url=row.source_url)
        from app.runtime.task_runtime import enqueue
        from app.memory.handlers import JOB_REFRESH_RESEARCH
        enqueue(self.db,
            job_type=JOB_REFRESH_RESEARCH, workspace_id=workspace_id,
            payload={"requirement_id": row.id},
            idempotency_key=f"research-report:{row.id}:{datetime.now(timezone.utc).date()}")
        self.db.add(EventRecord(
            id=str(uuid4()), network_id=workspace_id,
            type="research.requirement.reported", source="human:student",
            target="research", payload={"requirement_id": row.id},
            timestamp=int(datetime.now(timezone.utc).timestamp() * 1000),
            visibility="private"))
        self.db.flush()
        return row
