"""The student's chosen route (pai_route_decisions), the decision record PAI OS
reads (spec ROADMAP_ENGINE_SPEC.md §3).

A choice is made against the live engine build, never against client data, so
a student can only choose a field the engine currently says is open or a step
away. The row keeps the verdict and route as they were at choose time; the
page shows the live status beside that snapshot instead of rewriting it.
"""

from datetime import datetime, timezone

from sqlalchemy import select

from app.models import RouteDecision, StudentJourney, Workspace
from app.pai_c.possibilities import PossibilityService
from app.pai_c.roadmap.engine import RoadmapEngine
from app.pai_c.roadmap.steps import step_key_of_legacy

CHOOSABLE = {"open", "step"}
REFUSALS = {"not_open": "This field is not open from your education, so it cannot be chosen",
            "unknown": "PAI cannot check this field yet, so it cannot be chosen"}


class RouteDecisionError(Exception):
    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


def done_keys(row: RouteDecision) -> list[str]:
    """The student's manual ticks as step keys. Decisions saved before steps
    had keys hold one bool per old checklist entry; those map once, by
    position, to the key each entry stands for (the next write stores keys)."""
    done = list(row.steps_done or [])
    if not any(isinstance(item, bool) for item in done):
        return [item for item in done if isinstance(item, str)]
    steps = list(row.steps or [])
    return [key for index, item in enumerate(done) if item is True and index < len(steps)
            and (key := step_key_of_legacy(steps[index]))]


def _snapshot(steps: list[dict]) -> list[dict]:
    """What a step was at choose time: key, copy and colour, not the live
    evidence or calendar wiring."""
    return [{name: step[name] for name in ("key", "label_key", "values", "status")} for step in steps]


def route_of(card: dict, education_line: dict | None) -> dict:
    verdict = card["verdict"]
    return {"now": education_line, "needs": verdict["needs"], "tests": verdict["tests"],
            "degree": {"title": card["title"], "years": verdict["years"]}, "sources": verdict["sources"]}


def serialize(row: RouteDecision, cards: list[dict]) -> dict:
    """The decision with the field's status, steps and time in this same build
    ("unknown" and the choose-time steps when the path is gone), beside the
    snapshot taken at choose time, so the page can say what changed."""
    card = next((card for card in cards if card["field_key"] == row.field_key), None)
    return {"id": row.id, "field_key": row.field_key, "possibility_id": row.possibility_id, "title": row.title,
            "chosen_at": row.chosen_at.isoformat() if row.chosen_at else None,
            "withdrawn_at": row.withdrawn_at.isoformat() if row.withdrawn_at else None,
            "steps": card["steps"] if card else list(row.steps or []),
            "time": card["time"] if card else None,
            "snapshot_steps": list(row.steps or []), "steps_done": done_keys(row),
            "route": row.route, "snapshot_verdict": row.verdict,
            "live_status": card["status"] if card else "unknown"}


# The old confirm-gated research wait (RESEARCHING, ASSESSING, NEEDS_INFO). No
# code enters it any more (migration 121); a journey still there moves on to
# the route decision when the student chooses.
WAITING = {"RESEARCHING", "ASSESSING", "NEEDS_INFO"}


class RouteDecisionService:
    def __init__(self, db):
        self.db = db

    def _journey(self, workspace_id: str) -> StudentJourney | None:
        return self.db.scalar(select(StudentJourney).where(
            StudentJourney.workspace_id == workspace_id, StudentJourney.journey_type == "counselor_decision",
            StudentJourney.status == "active").order_by(StudentJourney.created_at).limit(1))

    def _set_stage(self, journey: StudentJourney, stage: str, actor: str = "human:student", **flags) -> None:
        from app.journey import JourneyService
        JourneyService(self.db).set_counselor_stage(journey.workspace_id, journey.id, stage, actor=actor, **flags)

    def _enter_chosen(self, journey: StudentJourney, row: RouteDecision, actor: str) -> bool:
        """The journey follows the decision: from PROPOSED to CHOSEN, with the
        route as the active goal. Shared by choose and by the first paths
        arriving while a route is already chosen. False when the stage cannot
        move."""
        if journey.current_stage == "PROPOSED":
            self._set_stage(journey, "CHOSEN", actor=actor, validated_choice=True)
        if journey.current_stage != "CHOSEN":
            return False
        journey.current_objective = row.title
        journey.active_goal = {"route_decision_id": row.id, "field_key": row.field_key,
                               "title": row.title, "route": row.route}
        return True

    def follow_active(self, workspace_id: str, actor: str) -> None:
        """Called once the Path engine lands the journey in PROPOSED: an
        active route decision (kept through a rethink, or made before the
        paths) takes it on to CHOSEN."""
        journey, row = self._journey(workspace_id), self.active(workspace_id)
        if journey is not None and row is not None:
            self._enter_chosen(journey, row, actor)

    def _record_choice(self, workspace_id: str, row: RouteDecision, previous: RouteDecision | None) -> None:
        """A student who chooses before the journey reaches PROPOSED keeps
        their stage; the decision itself is still saved, and the first saved
        paths move them to CHOSEN (follow_active)."""
        journey = self._journey(workspace_id)
        if journey is None:
            return
        if previous is not None:
            self._note_withdrawn(journey, previous)
        if journey.current_stage in WAITING:
            self._set_stage(journey, "PROPOSED")
        if not self._enter_chosen(journey, row, "human:student"):
            return
        journey.decisions = [*(journey.decisions or []), {
            "kind": "route_choice", "route_decision_id": row.id, "field_key": row.field_key,
            "chosen_at": row.chosen_at.isoformat()}]

    @staticmethod
    def _note_withdrawn(journey: StudentJourney, row: RouteDecision) -> None:
        journey.decisions = [*(journey.decisions or []), {
            "kind": "route_withdrawn", "route_decision_id": row.id, "field_key": row.field_key,
            "withdrawn_at": row.withdrawn_at.isoformat()}]

    def _record_withdraw(self, workspace_id: str, row: RouteDecision) -> None:
        journey = self._journey(workspace_id)
        if journey is None:
            return
        if journey.current_stage == "CHOSEN":
            self._set_stage(journey, "PROPOSED")
        if (journey.active_goal or {}).get("route_decision_id") == row.id:
            journey.active_goal = None
            journey.current_objective = None
        self._note_withdrawn(journey, row)

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
        row = RouteDecision(workspace_id=workspace_id, field_key=field_key, possibility_id=card["possibility_id"],
                            title=card["title"], verdict=card["verdict"],
                            route=route_of(card, page["education_line"]), steps=_snapshot(card["steps"]),
                            steps_done=[], chosen_at=now)
        self.db.add(row)
        self.db.flush()
        paths.set_chosen(workspace_id, row.possibility_id, True)
        self._record_choice(workspace_id, row, previous)
        self.db.flush()
        from app.pai_c.checkins import schedule
        schedule(self.db, workspace_id, "chosen_path", row.id, at=now)
        return serialize(row, page["fields"])

    def set_step(self, workspace_id: str, done: bool, *, key: str | None = None, index: int | None = None) -> dict:
        """Tick or untick one step of the live route, named by its key (or,
        for older clients, its position in the live steps)."""
        self._lock(workspace_id)
        row = self._active_or_404(workspace_id)
        page = RoadmapEngine(self.db).build(workspace_id)
        card = next((card for card in page["fields"] if card["field_key"] == row.field_key), None)
        steps = card["steps"] if card else list(row.steps or [])
        keys = [step["key"] for step in steps]
        if key is None and index is not None and 0 <= index < len(keys):
            key = keys[index]
        if key not in keys:
            raise RouteDecisionError("No such step on this route", 422)
        # A tick is offered only where the Vault is silent (steps.py _tickable);
        # unticking is always allowed, so an old tick can be cleared.
        if done and not next(step for step in steps if step["key"] == key).get("tickable", False):
            raise RouteDecisionError("PAI reads this step from your Vault, so it cannot be ticked. "
                                     "If it is wrong, update it in your Vault.", 409)
        ticks = [item for item in done_keys(row) if item != key] + ([key] if done else [])
        row.steps_done = ticks  # a new list of keys, so the JSON column is marked changed
        self.db.flush()
        return serialize(row, RoadmapEngine(self.db).build(workspace_id)["fields"])

    def withdraw(self, workspace_id: str) -> dict:
        self._lock(workspace_id)
        row = self._active_or_404(workspace_id)
        row.withdrawn_at = datetime.now(timezone.utc)
        PossibilityService(self.db).set_chosen(workspace_id, row.possibility_id, False)
        self._record_withdraw(workspace_id, row)
        self.db.flush()
        return serialize(row, RoadmapEngine(self.db).build(workspace_id)["fields"])
