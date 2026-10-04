"""Validated cross-domain edges over canonical student records.

Containment (for example Course.education_id) remains an ordinary FK. This
read model only records cross-domain relations that are supported by accepted
canonical records, and can be rebuilt when those records change.
"""

from sqlalchemy import select

from app.models import MemoryCandidate, VaultAssertion, VaultRelation, Workspace
from .errors import MemoryDataError
from .student_records import ENTITY_MODELS, StudentRecordService


def _identity(value: str) -> str:
    return " ".join(value.casefold().split())


class VaultRelationService:
    def __init__(self, db):
        self.db = db
        self.records = StudentRecordService(db)

    def link(self, workspace_id: str, subject_type: str, subject_id: str,
             predicate: str, object_type: str, object_id: str,
             assertion_id: str | None = None, confidence: float = 1.0) -> VaultRelation:
        """Create or reactivate an edge only between this student's live records."""
        if (subject_type not in ENTITY_MODELS or object_type not in ENTITY_MODELS
                or not isinstance(predicate, str) or not predicate.strip()
                or not 0 <= confidence <= 1):
            raise MemoryDataError("Invalid Vault relationship")
        predicate = predicate.strip()
        owner = self.db.execute(select(Workspace.id).where(
            Workspace.id == workspace_id).with_for_update()).scalar_one_or_none()
        if owner is None:
            raise MemoryDataError("Student workspace does not exist")
        if (self.records.get(workspace_id, subject_type, subject_id) is None
                or self.records.get(workspace_id, object_type, object_id) is None):
            raise MemoryDataError("Vault relationship endpoints must belong to this student")
        if assertion_id is not None:
            source = self.db.execute(select(VaultAssertion).join(
                MemoryCandidate, MemoryCandidate.id == VaultAssertion.candidate_id,
            ).where(VaultAssertion.id == assertion_id,
                    VaultAssertion.workspace_id == workspace_id,
                    MemoryCandidate.status == "accepted")).scalar_one_or_none()
            if source is None:
                raise MemoryDataError("Vault relationship requires an accepted assertion from this student")
        existing = self.db.execute(select(VaultRelation).where(
            VaultRelation.workspace_id == workspace_id,
            VaultRelation.subject_type == subject_type,
            VaultRelation.subject_id == subject_id,
            VaultRelation.predicate == predicate,
            VaultRelation.object_type == object_type,
            VaultRelation.object_id == object_id,
        )).scalar_one_or_none()
        if existing is not None:
            existing.status = "active"
            self.db.flush()
            return existing
        row = VaultRelation(
            workspace_id=workspace_id, subject_type=subject_type, subject_id=subject_id,
            predicate=predicate, object_type=object_type, object_id=object_id,
            assertion_id=assertion_id, confidence=confidence, status="active",
        )
        self.db.add(row)
        self.db.flush()
        return row

    def sync_demonstrations(self, workspace_id: str, assertion_id: str | None = None) -> None:
        """Project details can demonstrate an already known skill by exact name.

        Ambiguous or missing skills create no edge. This is an index over
        canonical records, never a reason to create a new skill assertion.
        """
        skills_by_name: dict[str, list] = {}
        for skill in self.records.list(workspace_id, "skill"):
            skills_by_name.setdefault(_identity(skill.name), []).append(skill)
        expected: set[tuple[str, str]] = set()
        for project in self.records.list(workspace_id, "project"):
            names = (project.details or {}).get("skills") or []
            for name in names:
                if not isinstance(name, str):
                    continue
                matches = skills_by_name.get(_identity(name), [])
                if len(matches) == 1:
                    expected.add((project.id, matches[0].id))
        existing = list(self.db.execute(select(VaultRelation).where(
            VaultRelation.workspace_id == workspace_id,
            VaultRelation.subject_type == "project",
            VaultRelation.predicate == "demonstrates",
            VaultRelation.object_type == "skill",
        )).scalars())
        by_edge = {(row.subject_id, row.object_id): row for row in existing}
        for edge, row in by_edge.items():
            row.status = "active" if edge in expected else "superseded"
        for project_id, skill_id in expected - by_edge.keys():
            self.link(workspace_id, "project", project_id, "demonstrates", "skill", skill_id,
                      assertion_id=assertion_id)
        self.db.flush()

    def list(self, workspace_id: str) -> list[VaultRelation]:
        return list(self.db.execute(select(VaultRelation).where(
            VaultRelation.workspace_id == workspace_id,
            VaultRelation.status == "active",
        )).scalars())
