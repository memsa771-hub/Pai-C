"""Workspace-owned possibility lifecycle; research still has one gateway."""
from datetime import datetime, timezone
import logging
from sqlalchemy import select
from app.models import PaiPossibility, Workspace, StudentJourney
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
        # roadmap_id belongs to the removed roadmap system (dropped by migration 119).
        return {column.name: (value.isoformat() if isinstance(value, datetime) else value)
                for column in row.__table__.columns if column.name != "roadmap_id"
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

    def lane_title(self, journey, lane):
        return (lane.get("title") or (lane.get("route") or {}).get("field")
                or load_data("lane_labels.json")[lane["lane"]])

    def from_mirror(self, journey):
        journey = self.db.scalar(select(StudentJourney).where(
            StudentJourney.workspace_id == journey.workspace_id, StudentJourney.id == journey.id))
        if journey is None:
            return []
        draft = journey.counselor_summary_draft or {}
        if draft.get("status") != "confirmed":
            return []
        self.lock(journey.workspace_id)
        result = []
        bindings = dict(draft.get("possibility_ids") or {})
        for lane in (draft.get("mirror") or {}).get("roadmap_lanes", []):
            row = (self.get(journey.workspace_id, bindings[lane["lane"]]) if lane["lane"] in bindings else
                self.add(journey.workspace_id, journey.id, title=self.lane_title(journey, lane),
                why=lane["why"], kind=lane["lane"], source="mirror", status="exploring",
                evidence=[{"text": text, "item_id": None} for text in lane.get("evidence", [])],
                unknowns=lane.get("unknowns", [])))
            bindings[lane["lane"]] = row.id
            if draft["version"] not in row.mirror_versions:
                if row.status in {"suggested", "saved"}:
                    row.status = "exploring"
                known = {item["text"] for item in row.evidence}
                row.evidence = [*row.evidence, *[{"text": text, "item_id": None}
                    for text in dict.fromkeys(lane.get("evidence", [])) if text not in known]]
                row.mirror_versions = [*row.mirror_versions, draft["version"]]
                row.updated_at = datetime.now(timezone.utc)
            result.append((lane, row))
        if bindings != draft.get("possibility_ids"):
            journey.counselor_summary_draft = {**draft, "possibility_ids": bindings}
        self.db.flush()
        return result

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
        field = row.title
        if row.kind not in {"discovered", "student_added"}:
            journey = self.db.scalar(select(StudentJourney).where(
                StudentJourney.workspace_id == row.workspace_id, StudentJourney.id == row.journey_id))
            draft = (journey.counselor_summary_draft or {}) if journey else {}
            lane = next((lane for lane in (draft.get("mirror") or {}).get("roadmap_lanes", [])
                         if lane.get("lane") == row.kind), {})
            field = (lane.get("route") or {}).get("field") or row.title
        return {"field": field,
                "level": details.get("degree_level") or "",
                "place_preference": countries[0] if len(countries) == 1 else "", "kind": ""}

