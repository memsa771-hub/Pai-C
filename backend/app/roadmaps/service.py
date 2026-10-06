"""Versioned roadmap content and isolated student actions."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select, update

from app.models import ExecutionRun, NotificationRecord, Roadmap, RoadmapStudentState, StudentJourney
from app.plugins._shared.sources import public_https


class RoadmapError(ValueError):
    pass


def _now():
    return datetime.now(timezone.utc)


class RoadmapService:
    def __init__(self, db):
        self.db = db

    def _require(self, workspace_id: str, roadmap_id: str, *, lock=False) -> tuple[Roadmap, RoadmapStudentState]:
        query = select(Roadmap, RoadmapStudentState).join(
            RoadmapStudentState, RoadmapStudentState.roadmap_id == Roadmap.id).where(
            Roadmap.workspace_id == workspace_id, Roadmap.id == roadmap_id)
        if lock:
            query = query.with_for_update()
        pair = self.db.execute(query).one_or_none()
        if pair is None:
            raise RoadmapError("Roadmap not found")
        return pair

    def list(self, workspace_id: str, filter_by: str = "all", *, presented=False) -> list[dict]:
        if filter_by not in {"all", "favorites", "exploring", "dismissed"}:
            raise RoadmapError("Invalid roadmap filter")
        pairs = self.db.execute(select(Roadmap, RoadmapStudentState).join(
            RoadmapStudentState, RoadmapStudentState.roadmap_id == Roadmap.id).where(
            Roadmap.workspace_id == workspace_id).order_by(Roadmap.created_at.desc())).all()
        now = _now()
        rows = []
        for roadmap, state in pairs:
            if filter_by == "dismissed":
                if state.dismissed_at is None:
                    continue
            elif state.dismissed_at is not None:
                continue
            if filter_by == "favorites" and not state.favorite:
                continue
            if filter_by == "exploring" and not state.exploring:
                continue
            newly_presented = state.presented_at is None
            if presented and newly_presented:
                state.presented_at = now
            rows.append(self.serialize(roadmap, state) | {"new": newly_presented})
        rows.sort(key=lambda item: (
            0 if item["chosen_at"] else 1,
            0 if item["favorite"] else 1,
            0 if item["origin"] == "stated_goal" else 1,
        ))
        return rows

    def get(self, workspace_id: str, roadmap_id: str, *, presented=False) -> dict:
        roadmap, state = self._require(workspace_id, roadmap_id)
        if presented and state.presented_at is None:
            state.presented_at = _now()
        return self.serialize(roadmap, state)

    def for_run(self, workspace_id: str, run_id: str, *, presented=False) -> list[dict]:
        pairs = self.db.execute(select(Roadmap, RoadmapStudentState).join(
            RoadmapStudentState, RoadmapStudentState.roadmap_id == Roadmap.id).where(
            Roadmap.workspace_id == workspace_id,
            Roadmap.execution_run_id == run_id,
        ).order_by(Roadmap.created_at.asc())).all()
        if presented:
            for _, state in pairs:
                if state.presented_at is None:
                    state.presented_at = _now()
        return [self.serialize(*pair) for pair in pairs]

    @staticmethod
    def serialize(roadmap: Roadmap, state: RoadmapStudentState) -> dict:
        return {key: getattr(roadmap, key) for key in (
            "id", "workspace_id", "journey_id", "goal_id", "origin", "title", "route",
            "fit_level", "fit_dimensions", "gaps", "steps", "total_cost", "time_to_start",
            "risks", "sources", "generation_status", "execution_run_id", "version",
            "stale_reason",
        )} | {
            "favorite": state.favorite, "exploring": state.exploring,
            "dismissed_at": state.dismissed_at.isoformat() if state.dismissed_at else None,
            "chosen_at": state.chosen_at.isoformat() if state.chosen_at else None,
            "focused_at": state.focused_at.isoformat() if state.focused_at else None,
            "created_at": roadmap.created_at.isoformat() if roadmap.created_at else None,
            "updated_at": roadmap.updated_at.isoformat() if roadmap.updated_at else None,
        }

    def publish_from_run(self, run: ExecutionRun) -> list[str]:
        """Only the registered builder calls this from its status hook."""
        if run.task_type != "roadmap_research":
            raise RoadmapError("Run does not own roadmap research")
        artifact = ((run.result or {}).get("capability_result") or {})
        candidates = artifact.get("roadmaps") or []
        journey_id = str((run.constraints or {}).get("research_key") or "").split(":", 1)[0]
        journey = self.db.execute(select(StudentJourney).where(
            StudentJourney.id == journey_id,
            StudentJourney.workspace_id == run.workspace_id,
            StudentJourney.journey_type == "counselor_decision",
        )).scalar_one_or_none()
        if journey is None:
            raise RoadmapError("Counselor journey not found for research run")
        custom_id = (run.constraints or {}).get("roadmap_id")
        changed = []
        for position, candidate in enumerate(candidates):
            if not isinstance(candidate, dict) or not candidate.get("title"):
                continue
            sources = candidate.get("sources") or []
            if not sources or any(not isinstance(item, dict) or not public_https(item.get("url"))
                                  or not item.get("checked_at") for item in sources):
                continue
            for gap in candidate.get("gaps") or []:
                if not isinstance(gap, dict) or not public_https(gap.get("source_url")):
                    raise RoadmapError("Each published gap needs a source URL")
            origin = candidate.get("origin")
            if origin not in {"stated_goal", "alternative"}:
                continue
            if custom_id and position == 0:
                roadmap = self.db.get(Roadmap, custom_id)
                if roadmap is None or roadmap.workspace_id != run.workspace_id:
                    raise RoadmapError("Custom roadmap placeholder missing")
                origin = "student_added"
            else:
                route_key = json.dumps(candidate.get("route") or {}, sort_keys=True, default=str)
                roadmap_id = str(uuid5(NAMESPACE_URL, f"pai-roadmap:{journey_id}:{origin}:{route_key}"))
                roadmap = self.db.get(Roadmap, roadmap_id)
                if roadmap is None:
                    roadmap = Roadmap(id=roadmap_id, workspace_id=run.workspace_id,
                                      journey_id=journey_id, goal_id=((run.constraints or {}).get("capability_input") or {}).get("brief", {}).get("goal_id"),
                                      origin=origin, title=candidate["title"], execution_run_id=run.id)
                    self.db.add(roadmap)
                    self.db.add(RoadmapStudentState(roadmap_id=roadmap_id, journey_id=journey_id))
            previous_status = roadmap.generation_status
            next_status = "ready" if run.status == "completed" else "needs_info"
            content = {
                "title": candidate["title"], "route": candidate.get("route") or {},
                "fit_level": candidate.get("fit_level") or "unconfirmed",
                "fit_dimensions": candidate.get("fit_dimensions") or {},
                "gaps": candidate.get("gaps") or [], "steps": candidate.get("steps") or [],
                "total_cost": candidate.get("total_cost"),
                "time_to_start": candidate.get("time_to_start"),
                "risks": candidate.get("risks") or [], "sources": sources,
                "generation_status": next_status,
                "stale_reason": None,
            }
            changed_content = any(getattr(roadmap, key) != value for key, value in content.items())
            for key, value in content.items():
                setattr(roadmap, key, value)
            roadmap.execution_run_id = run.id
            if changed_content:
                roadmap.version = (roadmap.version or 1) + (1 if roadmap.created_at else 0)
                roadmap.updated_at = _now()
            changed.append(roadmap.id)
            if next_status == "ready" and previous_status != "ready":
                self._notify_ready(run.workspace_id, roadmap)
        if custom_id and custom_id not in changed and run.status in {"failed", "needs_user_action"}:
            placeholder = self.db.get(Roadmap, custom_id)
            if placeholder and placeholder.workspace_id == run.workspace_id:
                placeholder.generation_status = "needs_info" if run.status == "needs_user_action" else "failed"
                changed.append(placeholder.id)
        self.db.flush()
        return changed

    def mark_stale(self, workspace_id: str, reason: str, *, source_url: str | None = None) -> int:
        """Invalidate old fit without replacing a student's choices or annotations."""
        rows = self.db.execute(select(Roadmap).where(
            Roadmap.workspace_id == workspace_id,
            Roadmap.generation_status.in_(("ready", "needs_info")),
        )).scalars().all()
        affected = 0
        for row in rows:
            if source_url and not any(item.get("url") == source_url for item in row.sources or []):
                continue
            row.generation_status = "stale"
            row.stale_reason = reason[:240]
            row.updated_at = _now()
            affected += 1
        return affected

    def _notify_ready(self, workspace_id: str, roadmap: Roadmap):
        from app.services.notify import notify
        key = f"roadmap-ready:{roadmap.id}:{roadmap.version}"
        exists = self.db.execute(select(NotificationRecord.id).where(
            NotificationRecord.workspace_id == workspace_id,
            NotificationRecord.dedupe_key == key)).first()
        if exists is None:
            notify(self.db, workspace_id, source="system:roadmaps", title="A roadmap is ready",
                   message=roadmap.title, link_url="/roadmaps", dedupe_key=key)

    def set_flag(self, workspace_id: str, roadmap_id: str, field: str, value: bool) -> dict:
        if field not in {"favorite", "exploring"}:
            raise RoadmapError("Unknown student action")
        roadmap, state = self._require(workspace_id, roadmap_id, lock=True)
        setattr(state, field, bool(value))
        self.db.flush()
        return self.serialize(roadmap, state)

    def dismiss(self, workspace_id: str, roadmap_id: str, dismissed: bool) -> dict:
        roadmap, state = self._require(workspace_id, roadmap_id, lock=True)
        if state.chosen_at and dismissed:
            raise RoadmapError("Chosen roadmap cannot be dismissed")
        state.dismissed_at = _now() if dismissed else None
        if dismissed:
            state.focused_at = None
        self.db.flush()
        return self.serialize(roadmap, state)

    def create_custom(self, workspace_id: str, journey_id: str, goal_id: str,
                      title: str, route: dict) -> dict:
        existing = self.db.execute(select(Roadmap, RoadmapStudentState).join(
            RoadmapStudentState, RoadmapStudentState.roadmap_id == Roadmap.id).where(
            Roadmap.workspace_id == workspace_id,
            Roadmap.journey_id == journey_id,
            Roadmap.goal_id == goal_id,
            Roadmap.origin == "student_added",
        ).limit(1)).one_or_none()
        if existing:
            return self.serialize(*existing)
        roadmap = Roadmap(workspace_id=workspace_id, journey_id=journey_id,
                          goal_id=goal_id, origin="student_added", title=title,
                          route=route, generation_status="generating")
        self.db.add(roadmap)
        self.db.flush()
        state = RoadmapStudentState(roadmap_id=roadmap.id, journey_id=journey_id)
        self.db.add(state)
        self.db.flush()
        return self.serialize(roadmap, state)

    def focus(self, workspace_id: str, roadmap_id: str) -> dict:
        roadmap, state = self._require(workspace_id, roadmap_id, lock=True)
        if state.dismissed_at or roadmap.generation_status not in {"ready", "needs_info", "stale"}:
            raise RoadmapError("Roadmap is unavailable for discussion")
        self.db.execute(update(RoadmapStudentState).where(
            RoadmapStudentState.journey_id == roadmap.journey_id,
            RoadmapStudentState.roadmap_id != roadmap.id,
        ).values(focused_at=None))
        state.focused_at = _now()
        self.db.flush()
        return self.serialize(roadmap, state)

    def rethink(self, workspace_id: str, roadmap_id: str) -> dict:
        """An explicit 'not yet' returns to discovery and keeps the old route."""
        roadmap, state = self._require(workspace_id, roadmap_id, lock=True)
        journey = self.db.execute(select(StudentJourney).where(
            StudentJourney.id == roadmap.journey_id,
            StudentJourney.workspace_id == workspace_id,
        ).with_for_update()).scalar_one_or_none()
        if journey is None or journey.current_stage != "PROPOSED":
            raise RoadmapError("Only a proposed direction can be reconsidered")
        from app.journey import JourneyService
        JourneyService(self.db).set_counselor_stage(
            workspace_id, journey.id, "DIRECTION", actor="human:student")
        decisions = list(journey.decisions or [])
        decisions.append({"kind": "roadmap_rethink", "roadmap_id": roadmap.id,
                          "at": _now().isoformat()})
        journey.decisions = decisions
        self.db.flush()
        return self.serialize(roadmap, state)

    def focused(self, workspace_id: str) -> dict | None:
        pair = self.db.execute(select(Roadmap, RoadmapStudentState).join(
            RoadmapStudentState, RoadmapStudentState.roadmap_id == Roadmap.id).where(
            Roadmap.workspace_id == workspace_id,
            RoadmapStudentState.focused_at.isnot(None),
        ).order_by(RoadmapStudentState.focused_at.desc()).limit(1)).one_or_none()
        return self.serialize(*pair) if pair else None

    @staticmethod
    def choice_token(roadmap: Roadmap, workspace_secret: str) -> str:
        expiry = int(time.time()) + 600
        body = f"{roadmap.workspace_id}:{roadmap.id}:{roadmap.version}:{expiry}"
        signature = hmac.new(workspace_secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        return f"{expiry}.{signature}"

    def choose(self, workspace_id: str, roadmap_id: str, token: str, workspace_secret: str) -> dict:
        roadmap, state = self._require(workspace_id, roadmap_id, lock=True)
        journey = self.db.execute(select(StudentJourney).where(
            StudentJourney.id == roadmap.journey_id,
            StudentJourney.workspace_id == workspace_id,
        ).with_for_update()).scalar_one_or_none()
        if journey is None or journey.current_stage != "PROPOSED":
            raise RoadmapError("Counselor has not presented a route for choice")
        if state.presented_at is None or state.dismissed_at or roadmap.generation_status != "ready":
            raise RoadmapError("Only a presented, ready roadmap can be chosen")
        try:
            expiry_text, signature = token.split(".", 1)
            expiry = int(expiry_text)
        except (ValueError, AttributeError):
            raise RoadmapError("Invalid choice confirmation") from None
        if expiry < int(time.time()) or expiry > int(time.time()) + 600:
            raise RoadmapError("Choice confirmation expired")
        body = f"{workspace_id}:{roadmap.id}:{roadmap.version}:{expiry}"
        expected = hmac.new(workspace_secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        if not secrets.compare_digest(expected, signature):
            raise RoadmapError("Invalid choice confirmation")
        from app.journey import JourneyService
        JourneyService(self.db).set_counselor_stage(
            workspace_id, journey.id, "CHOSEN", actor="human:student", validated_choice=True)
        state.chosen_at = _now()
        journey.current_objective = roadmap.title
        journey.active_goal = {"roadmap_id": roadmap.id, "goal_id": roadmap.goal_id,
                               "route": roadmap.route, "title": roadmap.title}
        decisions = list(journey.decisions or [])
        decisions.append({"kind": "roadmap_choice", "roadmap_id": roadmap.id,
                          "chosen_at": state.chosen_at.isoformat(), "version": roadmap.version})
        journey.decisions = decisions
        self.db.flush()
        return self.serialize(roadmap, state)
