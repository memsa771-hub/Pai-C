"""Versioned, program- and intake-scoped research evidence."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from app.models import Opportunity, RequirementSet


class ResearchEvidenceError(ValueError):
    pass


def _https_url(value: str) -> str:
    from urllib.parse import urlparse
    parsed = urlparse(str(value or ""))
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ResearchEvidenceError("A public HTTPS source URL is required")
    return value


class RequirementStore:
    def __init__(self, db):
        self.db = db

    def propose(self, workspace_id: str, *, route: dict, country: str,
                source_url: str, checked_at: datetime, rules: list[dict],
                institution: str | None = None, level: str | None = None,
                intake: str | None = None, fees: dict | None = None,
                deadlines: dict | None = None,
                opportunity_id: str | None = None) -> tuple[Opportunity, RequirementSet]:
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
        if opportunity_id:
            opportunity = self.db.execute(select(Opportunity).where(
                Opportunity.id == opportunity_id,
                Opportunity.workspace_id == workspace_id,
            ).with_for_update()).scalar_one_or_none()
            if opportunity is None:
                raise ResearchEvidenceError("Opportunity not found in student workspace")
            if (opportunity.country, opportunity.level, opportunity.intake) != (country, level, intake):
                raise ResearchEvidenceError("Cannot revise evidence for another route or intake")
            latest = self.db.execute(select(RequirementSet.version).where(
                RequirementSet.opportunity_id == opportunity.id,
            ).order_by(RequirementSet.version.desc()).limit(1)).scalar_one_or_none()
            version = (latest or 0) + 1
        else:
            opportunity = Opportunity(
                id=str(uuid4()), workspace_id=workspace_id, route=route,
                country=country, institution=institution, level=level,
                intake=intake, url=source_url)
            self.db.add(opportunity)
            version = 1
        requirement = RequirementSet(
            id=str(uuid4()), opportunity_id=opportunity.id, rules=rules,
            fees=fees or {}, deadlines=deadlines or {}, source_url=source_url,
            checked_at=checked_at, version=version, status="proposed")
        self.db.add(requirement)
        self.db.flush()
        return opportunity, requirement

    def preferred(self, workspace_id: str, opportunity_id: str) -> RequirementSet | None:
        rows = self.db.execute(select(RequirementSet).join(Opportunity).where(
            Opportunity.workspace_id == workspace_id,
            Opportunity.id == opportunity_id,
            RequirementSet.status.in_(("verified", "proposed")),
        ).order_by(RequirementSet.version.desc())).scalars().all()
        return next((row for row in rows if row.status == "verified"), rows[0] if rows else None)

    def review(self, workspace_id: str, requirement_id: str, *, reviewer: str,
               decision: str) -> RequirementSet:
        if decision not in {"verified", "expired"}:
            raise ResearchEvidenceError("Review decision must be verified or expired")
        row = self.db.execute(select(RequirementSet).join(Opportunity).where(
            Opportunity.workspace_id == workspace_id,
            RequirementSet.id == requirement_id,
        ).with_for_update()).scalar_one_or_none()
        if row is None:
            raise ResearchEvidenceError("Requirement set not found")
        if row.status != "proposed":
            raise ResearchEvidenceError("Only proposed research can be reviewed")
        row.status = decision
        row.reviewed_by = reviewer
        row.reviewed_at = datetime.now(timezone.utc)
        self.db.flush()
        return row
