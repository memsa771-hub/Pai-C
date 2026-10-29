"""Workspace-owned possibility lifecycle; research still has one gateway."""
from datetime import datetime, timezone
import logging
from sqlalchemy import select
from app.models import PaiPossibility, Workspace
from app.pai_c.policy.controller import load_data
from app.pai_c.possibility_titles import normalized_title

logger = logging.getLogger(__name__)


class PossibilityError(ValueError):
    pass


class PossibilityService:
    def __init__(self, db):
        self.db = db

    def lock(self, workspace_id):
        self.db.scalar(select(Workspace.id).where(Workspace.id == workspace_id).with_for_update())

    def get(self, workspace_id, id):
        row = self.db.scalar(select(PaiPossibility).where(
            PaiPossibility.workspace_id == workspace_id, PaiPossibility.id == id))
        if row is None:
            raise PossibilityError("Possibility not found")
        return row

    def by_title(self, workspace_id, title):
        return self.db.scalar(select(PaiPossibility).where(
            PaiPossibility.workspace_id == workspace_id,
            PaiPossibility.normalized_title == normalized_title(title)))

    def list(self, workspace_id):
        return self.db.scalars(select(PaiPossibility).where(
            PaiPossibility.workspace_id == workspace_id).order_by(PaiPossibility.created_at, PaiPossibility.id)).all()

    @staticmethod
    def serialize(row):
        return {column.name: (value.isoformat() if isinstance(value, datetime) else value)
                for column in row.__table__.columns
                for value in [getattr(row, column.name)]}

    def add(self, workspace_id, journey_id, *, title, why, kind, source, status,
            evidence=(), unknowns=()):
        self.lock(workspace_id)
        existing = self.by_title(workspace_id, title)
        if existing:
            return existing
        row = PaiPossibility(workspace_id=workspace_id, journey_id=journey_id,
            title=title, normalized_title=normalized_title(title), why=why, kind=kind,
            source=source, status=status, evidence=list(evidence), unknowns=list(unknowns),
            mirror_versions=[])
        self.db.add(row)
        self.db.flush()
        logger.info("possibility_stored possibility_id=%s title=%s", row.id, row.title)
        return row

    def transition(self, workspace_id, id, action):
        self.lock(workspace_id)
        row = self.get(workspace_id, id)
        target = load_data("possibilities.json")["transitions"].get(action, {}).get(row.status)
        if target is None:
            raise PossibilityError("This action is not available for this possibility")
        if row.status == target:
            return row, False
        row.status = target
        row.updated_at = datetime.now(timezone.utc)
        self.db.flush()
        return row, True

    def set_chosen(self, workspace_id, id, chosen):
        """The route decision owns 'chosen': choosing a route marks its path
        chosen; withdrawing (or choosing another) puts it back to saved. Kept
        out of the student transition table so the possibilities API cannot
        set it directly."""
        row = self.db.scalar(select(PaiPossibility).where(
            PaiPossibility.workspace_id == workspace_id, PaiPossibility.id == id)) if id else None
        if row is None or row.status == "dismissed":
            return None
        target = "chosen" if chosen else ("saved" if row.status == "chosen" else row.status)
        if row.status != target:
            row.status = target
            row.updated_at = datetime.now(timezone.utc)
            self.db.flush()
        return row

    def mark_mentioned(self, workspace_id, id):
        row = self.get(workspace_id, id)
        if row.mentioned_at is None:
            row.mentioned_at = datetime.now(timezone.utc)
            self.db.flush()

    def research_route(self, row):
        from app.pai_c.memory import MemoryService
        profile = MemoryService(self.db).profile(row.workspace_id)
        goals = profile.records.get("goal", [])
        details = (goals[0].get("details") or {}) if goals else {}
        countries = details.get("target_countries") or []
        return {"field": row.title,
                "level": details.get("degree_level") or "",
                "place_preference": countries[0] if len(countries) == 1 else "", "kind": ""}

