"""The student's chosen route (pai_route_decisions), the decision record PAI OS
reads (spec ROADMAP_ENGINE_SPEC.md §3).

A choice is made against the live engine build, never against client data, so
a student can only choose a field the engine currently says is open or a step
away. The row keeps the verdict and route as they were at choose time; the
page shows the live status beside that snapshot instead of rewriting it.
"""

from datetime import datetime, timezone

from sqlalchemy import select

from app.models import RouteDecision, Workspace
from app.pai_c.possibilities import PossibilityService
from app.pai_c.roadmap.engine import RoadmapEngine

CHOOSABLE = {"open", "step"}
REFUSALS = {"not_open": "This field is not open from your education, so it cannot be chosen",
            "unknown": "PAI cannot check this field yet, so it cannot be chosen"}


class RouteDecisionError(Exception):
    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


def _need_step(need: dict) -> dict:
    kind, detail = need["kind"], need.get("detail") or {}
    if kind == "marks":
        return {"key": "step_marks", "min": detail["min"], "have": detail["have"]}
    if kind == "bridge":
        return {"key": "step_bridge", "text": detail["text"], "source": detail.get("source")}
    if kind == "check":
        return {"key": "step_check", "note": detail.get("note")}
    if detail.get("groups"):
        return {"key": "step_group", "groups": detail["groups"]}
    return {"key": "step_any_group"}


def route_steps(card: dict) -> list[dict]:
    """The route checklist: each need, each entry test, then applying for the
    degree. Copy keys with values, rendered by policy/roadmap.json like reasons."""
    verdict = card["verdict"]
    return ([_need_step(need) for need in verdict["needs"]]
            + [{"key": "step_test", "name": test["name"]} for test in verdict["tests"]]
            + [{"key": "step_apply", "degree": card["title"]}])


def route_of(card: dict, education_line: dict | None) -> dict:
    verdict = card["verdict"]
    return {"now": education_line, "needs": verdict["needs"], "tests": verdict["tests"],
            "degree": {"title": card["title"], "years": verdict["years"]}, "sources": verdict["sources"]}


def serialize(row: RouteDecision, cards: list[dict]) -> dict:
    """The decision with the field's status in this same build ("unknown" when
    the path is gone), so the page can say the route changed since choosing."""
    live = next((card["status"] for card in cards if card["field_key"] == row.field_key), "unknown")
    return {"id": row.id, "field_key": row.field_key, "possibility_id": row.possibility_id, "title": row.title,
            "chosen_at": row.chosen_at.isoformat() if row.chosen_at else None,
            "withdrawn_at": row.withdrawn_at.isoformat() if row.withdrawn_at else None,
            "steps": list(row.steps or []), "steps_done": list(row.steps_done or []),
            "route": row.route, "snapshot_verdict": row.verdict, "live_status": live}


class RouteDecisionService:
    def __init__(self, db):
        self.db = db

    def active(self, workspace_id: str) -> RouteDecision | None:
        return self.db.scalar(select(RouteDecision).where(
            RouteDecision.workspace_id == workspace_id, RouteDecision.withdrawn_at.is_(None)))

    def _lock(self, workspace_id: str):
        # Serializes choose/tick/withdraw per workspace; the partial unique
        # index is the final guard.
        self.db.scalar(select(Workspace.id).where(Workspace.id == workspace_id).with_for_update())

    def _active_or_404(self, workspace_id: str) -> RouteDecision:
        row = self.active(workspace_id)
        if row is None:
            raise RouteDecisionError("No route is chosen", 404)
        return row

    def current(self, workspace_id: str) -> dict | None:
        row = self.active(workspace_id)
        if row is None:
            return None
        cards = RoadmapEngine(self.db).build(workspace_id)["fields"]
        return {**serialize(row, cards), "workspace_id": row.workspace_id}

    def choose(self, workspace_id: str, field_key: str) -> dict:
        self._lock(workspace_id)
        page = RoadmapEngine(self.db).build(workspace_id)
        card = next((card for card in page["fields"] if field_key and card["field_key"] == field_key), None)
        if card is None:
            raise RouteDecisionError("This field is not one of your paths", 404)
        if card["status"] not in CHOOSABLE:
            raise RouteDecisionError(REFUSALS[card["status"]], 409)
        now = datetime.now(timezone.utc)
        previous = self.active(workspace_id)
        paths = PossibilityService(self.db)
        if previous is not None:
            previous.withdrawn_at = now
            paths.set_chosen(workspace_id, previous.possibility_id, False)
            self.db.flush()  # the old row leaves the partial unique index before the new one enters
        steps = route_steps(card)
        row = RouteDecision(workspace_id=workspace_id, field_key=field_key, possibility_id=card["possibility_id"],
                            title=card["title"], verdict=card["verdict"],
                            route=route_of(card, page["education_line"]), steps=steps,
                            steps_done=[False] * len(steps), chosen_at=now)
        self.db.add(row)
        self.db.flush()
        paths.set_chosen(workspace_id, row.possibility_id, True)
        from app.pai_c.checkins import schedule
        schedule(self.db, workspace_id, "chosen_path", row.id, at=now)
        return serialize(row, page["fields"])

    def set_step(self, workspace_id: str, index: int, done: bool) -> dict:
        self._lock(workspace_id)
        row = self._active_or_404(workspace_id)
        if not 0 <= index < len(row.steps or []):
            raise RouteDecisionError("No such step on this route", 422)
        steps_done = list(row.steps_done or [])
        steps_done[index] = done
        row.steps_done = steps_done  # a new list, so the JSON column is marked changed
        self.db.flush()
        return serialize(row, RoadmapEngine(self.db).build(workspace_id)["fields"])

    def withdraw(self, workspace_id: str) -> dict:
        self._lock(workspace_id)
        row = self._active_or_404(workspace_id)
        row.withdrawn_at = datetime.now(timezone.utc)
        PossibilityService(self.db).set_chosen(workspace_id, row.possibility_id, False)
        self.db.flush()
        return serialize(row, RoadmapEngine(self.db).build(workspace_id)["fields"])
