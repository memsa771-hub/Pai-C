"""Profile completion and rollout-aware Counselor policy."""

from datetime import datetime, timezone

from sqlalchemy import select

from app.config import config
from app.models import ProfileFieldResponse, User, Workspace
from .education_journey import EducationJourneyService
from .profile_requirements import ProfileRequirementRegistry, TIERS
from .student_snapshot import StudentSnapshot, StudentSnapshotService


TIER_THRESHOLDS = {"critical": 1.0, "important": 0.80, "enrichment": 0.20}
FOUNDATION_DONE = frozenset({"answered", "valid_unknown", "not_applicable", "declined"})


class ProfileCompletionService:
    def __init__(self, db):
        self.db = db
        self.snapshots = StudentSnapshotService(db)
        self.journeys = EducationJourneyService()
        self.registry = ProfileRequirementRegistry(db)

    def evaluate(self, workspace_id: str, snapshot: StudentSnapshot | None = None) -> dict:
        snapshot = snapshot or self.snapshots.build(workspace_id)
        journey = self.journeys.evaluate(snapshot)
        # Counselor discovery slots have their own progression. They do not
        # change the student's profile-completeness or onboarding gate.
        requirements = self.registry.active(stage="profile")
        responses = {
            row.requirement_key: row for row in self.db.execute(
                select(ProfileFieldResponse).where(ProfileFieldResponse.workspace_id == workspace_id)
            ).scalars()
        }
        counts = {tier: {"filled": 0, "total": 0} for tier in TIERS}
        missing = []
        fields = []

        for requirement in requirements:
            applicable, filled = self.registry.evaluate(requirement, snapshot, journey)
            if not applicable:
                continue
            conflict = any(
                issue.get("type") in {"conflicting_fact", "conflicting_record"}
                and (
                    issue.get("affected_type") in {requirement.source_key, requirement.source_path}
                    or (issue.get("evidence") or {}).get("field_key") == requirement.source_key
                    or (requirement.source_key == "education"
                        and (issue.get("evidence") or {}).get("record_type") == "education")
                )
                for issue in snapshot.issues
            )
            response = responses.get(requirement.key)
            status = ("conflict" if conflict else "answered" if filled else
                      response.status if response else "missing")
            fields.append({
                "key": requirement.key, "tier": requirement.tier,
                "status": status, "question": requirement.question,
                "priority": requirement.priority,
            })
            counts[requirement.tier]["total"] += 1
            if status == "answered":
                counts[requirement.tier]["filled"] += 1
            if status not in FOUNDATION_DONE:
                missing.append({
                    "key": requirement.key, "tier": requirement.tier,
                    "status": status, "question": requirement.question,
                    "priority": requirement.priority,
                })

        tiers = {}
        for tier in TIERS:
            filled, total = counts[tier]["filled"], counts[tier]["total"]
            ratio = 1.0 if total == 0 else filled / total
            tiers[tier] = {
                "filled": filled,
                "total": total,
                "percentage": round(ratio * 100),
                "satisfied": ratio >= TIER_THRESHOLDS[tier],
            }

        order = {tier: index for index, tier in enumerate(TIERS)}
        missing.sort(key=lambda item: (order[item["tier"]], -item["priority"], item["key"]))
        tier_targets_met = all(tiers[tier]["satisfied"] for tier in TIERS)
        critical = [field for field in fields if field["tier"] == "critical"]
        foundation_ready = bool(critical) and all(
            field["status"] in FOUNDATION_DONE for field in critical)
        next_requirement = next((item for item in missing
                                 if item["status"] not in {"pending", "deferred"}), None)
        rollout = self.enforcement(workspace_id)
        return {
            "tiers": tiers,
            "fields": fields,
            "missingRequirements": missing,
            "nextRequirement": next_requirement,
            "foundationReady": foundation_ready,
            "personalizedCounselingEligible": foundation_ready,
            "tierTargetsMet": tier_targets_met,
            "requirementVersion": max((row.version for row in requirements), default=0),
            "enforcementMode": rollout["mode"],
            "enforced": rollout["enforced"],
            "counselorMode": "collection" if rollout["enforced"] and not foundation_ready else "normal",
        }

    def enforcement(self, workspace_id: str) -> dict:
        mode = str(getattr(config, "PAI_PROFILE_COMPLETION_ROLLOUT_MODE", "shadow") or "shadow").strip().lower()
        if mode not in {"off", "shadow", "new", "all"}:
            raise ValueError("PAI_PROFILE_COMPLETION_ROLLOUT_MODE must be off, shadow, new, or all")
        if mode in {"off", "shadow"}:
            return {"mode": mode, "enforced": False}
        if mode == "all":
            return {"mode": mode, "enforced": True}

        cutoff_text = str(getattr(config, "PAI_PROFILE_COMPLETION_ROLLOUT_AT", "") or "").strip()
        if not cutoff_text:
            return {"mode": mode, "enforced": False}
        cutoff = datetime.fromisoformat(cutoff_text.replace("Z", "+00:00"))
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=timezone.utc)
        workspace = self.db.execute(select(Workspace).where(Workspace.id == workspace_id)).scalar_one_or_none()
        if workspace is None:
            return {"mode": mode, "enforced": False}
        created_at = workspace.created_at
        if workspace.owner_user_id:
            user_created = self.db.execute(
                select(User.created_at).where(User.id == workspace.owner_user_id)
            ).scalar_one_or_none()
            created_at = user_created or created_at
        if created_at is None:
            return {"mode": mode, "enforced": False}
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return {"mode": mode, "enforced": created_at >= cutoff}

    def record_response(self, workspace_id: str, key: str, status: str,
                        *, source_event_id: str | None = None) -> dict:
        """Record a non-value answer; a later canonical fact takes precedence."""
        if status not in {"valid_unknown", "not_applicable", "declined", "deferred"}:
            raise ValueError("Unsupported profile response")
        requirement = self.registry.get(key)
        if requirement is None:
            raise ValueError("Unknown profile requirement")
        snapshot = self.snapshots.build(workspace_id)
        journey = self.journeys.evaluate(snapshot)
        applicable, filled = self.registry.evaluate(requirement, snapshot, journey)
        if not applicable or filled:
            raise ValueError("This requirement is already answered or does not apply")
        response = self.db.execute(select(ProfileFieldResponse).where(
            ProfileFieldResponse.workspace_id == workspace_id,
            ProfileFieldResponse.requirement_key == key,
        ).with_for_update()).scalar_one_or_none()
        if response is None:
            response = ProfileFieldResponse(
                workspace_id=workspace_id, requirement_key=key,
                status=status, source_event_id=source_event_id,
            )
            self.db.add(response)
        else:
            response.status = status
            response.source_event_id = source_event_id
        self.db.flush()
        return self.evaluate(workspace_id, snapshot=snapshot)
