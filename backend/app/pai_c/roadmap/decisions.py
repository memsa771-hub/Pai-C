"""The student's chosen route (pai_route_decisions), the decision record PAI OS
reads (spec ROADMAP_ENGINE_SPEC.md §3).

A choice is made against the live engine build, never against client data, so
a student can only choose a field the engine currently says is open or a step
away. The row keeps the verdict and route as they were at choose time; the
page shows the live status beside that snapshot instead of rewriting it.
"""

import hashlib
import json
from datetime import datetime, timezone
from types import EllipsisType
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.models import RouteDecision, StudentJourney, Workspace
from app.pai_c.connect import outbox
from app.pai_c.possibilities import PossibilityService
from app import pai_os_bridge
from app.pai_c.roadmap import plan_adapter
from app.pai_c.roadmap.engine import RoadmapEngine
from app.pai_c.roadmap.steps import is_tickable, step_key_of_legacy

if TYPE_CHECKING:
    from app.pai_c.connect.choice import ChoiceDetails

CHOOSABLE = {"open", "step"}
REFUSALS = {"not_open": "This field is not open from your education, so it cannot be chosen",
            "unknown": "PAI cannot check this field yet, so it cannot be chosen"}


STEP_REFUSALS = {  # PAI OS refusals of a tick: (words for the student, HTTP status)
    "not_found": ("No such step on this route", 404), "not_yours": ("No such step on this route", 404),
    "not_waiting": ("This step is not waiting for you, so it cannot be ticked.", 409),
    "review_required": ("Approve the file to finish this step; it cannot be ticked.", 409),
    "unavailable": ("PAI could not update your plan just now; try again later.", 503)}


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


def _instant(moment: datetime | None) -> datetime | None:
    """A datetime as an aware UTC instant (SQLite returns them without a zone), so equal moments compare equal."""
    return moment if moment is None or moment.tzinfo else moment.replace(tzinfo=timezone.utc)


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


def choice_of(row: RouteDecision) -> tuple:
    """What the student chose, apart from consent: field, route, places in order, intake."""
    intake = row.intake or None
    return (row.field_key, row.origin_country, row.destination_country, row.level,
            tuple((p["programme_ref"], p["rank"]) for p in sorted(row.places or [], key=lambda p: p["rank"])),
            None if intake is None else (intake.get("term"), intake.get("year")))


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
        """Called by the stage sync once the journey is in PROPOSED: an
        active route decision (made before the paths) takes it on to CHOSEN."""
        journey, row = self._journey(workspace_id), self.active(workspace_id)
        if journey is not None and row is not None and not self._escalated(journey, row):
            self._enter_chosen(journey, row, actor)

    def _escalated(self, journey: StudentJourney, row: RouteDecision) -> bool:
        """PAI OS sent the student back to choosing (D-x9): the newest route entry is an escalation with a decision
        version (a legacy entry has none), made for this decision or for an earlier version of the same choice. A
        new choice, or a choice request that changed the places, ends it."""
        newest = next((d for d in reversed(journey.decisions or [])
                       if str(d.get("kind", "")).startswith("route_")), None)
        if newest is None or newest["kind"] != "route_escalation" or newest.get("decision_version") is None:
            return False
        version = newest["decision_version"]
        if version >= row.decision_version:
            return True
        then = self.db.scalar(select(RouteDecision).where(
            RouteDecision.workspace_id == row.workspace_id, RouteDecision.decision_version == version))
        return then is not None and choice_of(then) == choice_of(row)

    def _record_choice(self, workspace_id: str, row: RouteDecision, previous: RouteDecision | None) -> None:
        """The choice syncs the stage (journey_sync, reason "chosen"): it is
        the student's act, so it also ends a re-plan, and a journey lagging in
        MIRROR or the old research wait moves on with it. A student who
        chooses before the Mirror keeps their stage; the decision itself is
        still saved, and the first saved paths move them to CHOSEN
        (follow_active)."""
        from app.pai_c.journey_sync import sync_counselor_stage
        journey = self._journey(workspace_id)
        if journey is None:
            return
        if previous is not None:
            self._note_withdrawn(journey, previous)
        sync_counselor_stage(self.db, workspace_id, reason="chosen", actor="human:student")
        if not self._enter_chosen(journey, row, "human:student"):
            return
        journey.decisions = [*(journey.decisions or []), {
            "kind": "route_choice", "route_decision_id": row.id, "field_key": row.field_key,
            "chosen_at": row.chosen_at.isoformat(), "decision_version": row.decision_version}]

    @staticmethod
    def _note_withdrawn(journey: StudentJourney, row: RouteDecision, version: int | None = None) -> None:
        journey.decisions = [*(journey.decisions or []), {
            "kind": "route_withdrawn", "route_decision_id": row.id, "field_key": row.field_key,
            "withdrawn_at": row.withdrawn_at.isoformat(),
            "decision_version": version if version is not None else row.decision_version}]

    def _record_withdraw(self, workspace_id: str, row: RouteDecision, version: int) -> None:
        journey = self._journey(workspace_id)
        if journey is None:
            return
        if journey.current_stage == "CHOSEN":
            self._set_stage(journey, "PROPOSED")
        goal = journey.active_goal or {}
        # A consent change supersedes the row without touching the journey, so the goal may name an older version
        # of the same choice: match by field as well.
        if goal.get("route_decision_id") == row.id or (goal and goal.get("field_key") == row.field_key):
            journey.active_goal = None
            journey.current_objective = None
        self._note_withdrawn(journey, row, version)

    def active(self, workspace_id: str) -> RouteDecision | None:
        return self.db.scalar(select(RouteDecision).where(
            RouteDecision.workspace_id == workspace_id, RouteDecision.withdrawn_at.is_(None)))

    def _lock(self, workspace_id: str):
        # Serializes choose/tick/withdraw per workspace; the partial unique
        # index is the final guard.
        self.db.scalar(select(Workspace.id).where(Workspace.id == workspace_id).with_for_update())

    def _next_version(self, workspace_id: str) -> int:
        """The next decision version of the student (1 when there is none). Call under `_lock`."""
        newest = self.db.scalar(select(func.max(RouteDecision.decision_version)).where(
            RouteDecision.workspace_id == workspace_id))
        return (newest or 0) + 1

    def newest(self, workspace_id: str) -> RouteDecision | None:
        """The student's highest-version row: a choice, or the withdrawal that followed it."""
        return self.db.scalar(select(RouteDecision).where(RouteDecision.workspace_id == workspace_id)
                              .order_by(RouteDecision.decision_version.desc()).limit(1))

    def _active_or_404(self, workspace_id: str) -> RouteDecision:
        row = self.active(workspace_id)
        if row is None:
            raise RouteDecisionError("No route is chosen", 404)
        return row

    def current(self, workspace_id: str) -> dict | None:
        row = self.active(workspace_id)
        if row is None:
            return None
        with plan_adapter.pinned_read(row):
            cards = RoadmapEngine(self.db).build(workspace_id)["fields"]
            return {**plan_adapter.chosen(row, cards), "workspace_id": row.workspace_id}

    def choose(self, workspace_id: str, field_key: str, details: "ChoiceDetails | None" = None) -> dict:
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
        extra = {}
        if details is not None:
            extra = {"origin_country": details.origin_country, "destination_country": details.destination_country,
                     "level": details.level, "path_ref": details.path_ref,
                     "places": [{"programme_ref": ref, "rank": rank} for ref, rank in details.places],
                     "intake": {"term": details.intake[0], "year": details.intake[1]} if details.intake else None,
                     "os_supported": pai_os_bridge.route_supported(
                         details.origin_country, details.destination_country, details.level),
                     "authorized_at": details.authorized_at, "guardian_required": details.guardian_required,
                     "guardian_authorized_at": details.guardian_authorized_at,
                     "consent_version": details.consent_version if details.authorized_at else None}
        row = RouteDecision(workspace_id=workspace_id, decision_version=self._next_version(workspace_id),
                            status="chosen", field_key=field_key,
                            possibility_id=card["possibility_id"], title=card["title"], verdict=card["verdict"],
                            route=route_of(card, page["education_line"]), steps=_snapshot(card["steps"]),
                            steps_done=[], chosen_at=now, **extra)
        self.db.add(row)
        self.db.flush()
        paths.set_chosen(workspace_id, row.possibility_id, True)
        self._record_choice(workspace_id, row, previous)
        self.db.flush()
        from app.pai_c.checkins import schedule
        schedule(self.db, workspace_id, "chosen_path", row.id, at=now)
        outbox.record(self.db, row)
        return plan_adapter.chosen(row, page["fields"])

    # Every column a consent change carries over unchanged into its new version.
    _COPIED = ("field_key", "possibility_id", "title", "verdict", "route", "steps", "steps_done", "chosen_at",
               "origin_country", "destination_country", "level", "path_ref", "places", "intake", "os_supported",
               "authorized_at", "guardian_authorized_at", "guardian_required", "consent_version")

    def update_consent(self, workspace_id: str, *, authorized_at: "datetime | None | EllipsisType" = ...,
                       guardian_authorized_at: "datetime | None | EllipsisType" = ...,
                       consent_version: "str | None | EllipsisType" = ...) -> dict:
        """A consent change is a new decision version: the active row is superseded by a copy of itself with the
        named consent fields changed (`...` leaves a field as it is, None clears it). The choice, places and
        intake stay; check-ins are not rescheduled and the journey and the possibility are not touched.
        `consent_version` goes with the student's own consent: it is cleared when `authorized_at` is."""
        self._lock(workspace_id)
        row = self._active_or_404(workspace_id)
        values = {name: getattr(row, name) for name in self._COPIED}
        changes = {name: value for name, value in (("authorized_at", authorized_at),
                                                   ("guardian_authorized_at", guardian_authorized_at))
                   if value is not ... and _instant(value) != _instant(values[name])}
        if not changes:  # nothing to change: no version, no outbox row
            with plan_adapter.pinned_read(row):
                return plan_adapter.chosen(row, RoadmapEngine(self.db).build(workspace_id)["fields"])
        values.update(changes)
        if "authorized_at" in changes:
            values["consent_version"] = None if changes["authorized_at"] is None else (
                values["consent_version"] if consent_version is ... else consent_version)
        row.withdrawn_at = datetime.now(timezone.utc)
        self.db.flush()  # the old row leaves the partial unique index before the new one enters
        new = RouteDecision(workspace_id=workspace_id, decision_version=self._next_version(workspace_id),
                            status="chosen", **values)
        self.db.add(new)
        self.db.flush()
        outbox.record(self.db, new, consent_only=True)
        with plan_adapter.pinned_read(new):
            return plan_adapter.chosen(new, RoadmapEngine(self.db).build(workspace_id)["fields"])

    @staticmethod
    def _choice_of(row: RouteDecision) -> tuple:
        """What a choice request is checked against: refs in order, intake, destination, level and field."""
        refs = tuple(p["programme_ref"] for p in sorted(row.places or [], key=lambda p: p["rank"]))
        intake = (row.intake["term"], row.intake["year"]) if row.intake else None
        return refs, intake, row.destination_country, row.level, row.field_key

    def apply_choice_request(self, workspace_id: str, request: dict) -> tuple[str, "int | None | str"]:
        """Writes an accepted PAI OS choice request (`choice_request.v1`, R-07) as the next decision version, once, and
        only while the choice it was made against is still the newest. Returns `("written", n+1)`,
        `("duplicate", version)` for a request already written (its key is on a row; asked FIRST, so a repeat after
        n+1 never reads as stale), `("stale", None)` and `("refused", code)` (`no_decision`, `not_supported`).
        A consent copy in between does not make a request stale. Like `update_consent` it makes no journey,
        possibility or check-in change. No commit: the caller commits, then delivers the outbox row."""
        self._lock(workspace_id)
        key = request["key"]
        done = self.db.scalar(select(RouteDecision).where(RouteDecision.workspace_id == workspace_id,
                                                          RouteDecision.request_key == key))
        if done is not None:
            return "duplicate", done.decision_version
        newest = self.newest(workspace_id)
        if newest is None:
            return "refused", "no_decision"
        base = self.db.scalar(select(RouteDecision).where(
            RouteDecision.workspace_id == workspace_id, RouteDecision.decision_version == request["based_on_version"]))
        if (base is None or newest.status != "chosen" or newest.withdrawn_at is not None
                or self._choice_of(base) != self._choice_of(newest)):
            return "stale", None
        if not newest.os_supported:
            return "refused", "not_supported"
        values = {name: getattr(newest, name) for name in self._COPIED}
        # D-x4: recomputed, never copied. A route PAI OS no longer runs is still written (the student's choice stands);
        # the hand-off then closes the old plan through the unsupported path.
        values["os_supported"] = pai_os_bridge.route_supported(
            values["origin_country"], values["destination_country"], values["level"])
        if request.get("programmes"):
            ordered = sorted(request["programmes"], key=lambda p: p["rank"])
            values["places"] = [{"programme_ref": p["programme_ref"], "rank": i + 1} for i, p in enumerate(ordered)]
        if request.get("target_intake"):
            values["intake"] = {"term": request["target_intake"]["term"], "year": request["target_intake"]["year"]}
        newest.withdrawn_at = datetime.now(timezone.utc)
        self.db.flush()  # the old row leaves the partial unique index before the new one enters
        new = RouteDecision(workspace_id=workspace_id, decision_version=self._next_version(workspace_id),
                            status="chosen", request_key=key, **values)
        self.db.add(new)
        self.db.flush()
        outbox.record(self.db, new)
        return "written", new.decision_version

    MAX_PLACES = 5  # decision_record.v2 holds at most five places

    def request_from_builder(self, workspace_id: str, origin: str, destination: str, level: str, intake: dict,
                             places: list[dict]) -> tuple[str, "int | None", "str | None"]:
        """The OS route builder's choice (R-09), written as the next decision version. Returns `(outcome, version,
        code)`: `("written", n+1, None)`, `("unchanged", n, None)` when the active row already has this route, these
        places in this order and this intake (or this exact request was written), or `("refused", None, code)` with
        `choose_field_first` (no active decision: the builder knows no field, D-x4) or `too_many_places`. The new
        version copies everything else from the active row, field and consent included. The key is
        `builder:{sha256 of the base version, route, intake and places}`: the base version keeps a student who goes back
        to an earlier choice from being read as a repeat. The key lookup is only a backstop (the unique index is the
        final guard); the "unchanged" comparison with the active row is the real guard against a repeat. No commit: the caller commits, then delivers the outbox row."""
        self._lock(workspace_id)
        active = self.active(workspace_id)
        if active is None:
            return "refused", None, "choose_field_first"
        if len(places) > self.MAX_PLACES:
            return "refused", None, "too_many_places"
        ordered = sorted(places, key=lambda p: p["rank"])
        wanted = [{"programme_ref": p["programme_ref"], "rank": i + 1} for i, p in enumerate(ordered)]
        want_intake = {"term": intake["term"], "year": intake["year"]}
        have = [{"programme_ref": p["programme_ref"], "rank": i + 1}
                for i, p in enumerate(sorted(active.places or [], key=lambda p: p["rank"]))]
        if ((active.origin_country, active.destination_country, active.level, have, active.intake)
                == (origin, destination, level, wanted, want_intake)):
            return "unchanged", active.decision_version, None
        key = "builder:" + hashlib.sha256(json.dumps(
            [active.decision_version, origin, destination, level, want_intake, wanted], sort_keys=True).encode()
        ).hexdigest()
        done = self.db.scalar(select(RouteDecision).where(RouteDecision.workspace_id == workspace_id,
                                                          RouteDecision.request_key == key))
        if done is not None:
            return "unchanged", done.decision_version, None
        values = {name: getattr(active, name) for name in self._COPIED}
        same_path = (active.destination_country, active.level) == (destination, level)
        values.update(origin_country=origin, destination_country=destination, level=level, places=wanted,
                      intake=want_intake, path_ref=values["path_ref"] if same_path else None,
                      os_supported=pai_os_bridge.route_supported(origin, destination, level))
        active.withdrawn_at = datetime.now(timezone.utc)
        self.db.flush()  # the old row leaves the partial unique index before the new one enters
        new = RouteDecision(workspace_id=workspace_id, decision_version=self._next_version(workspace_id),
                            status="chosen", request_key=key, **values)
        self.db.add(new)
        self.db.flush()
        outbox.record(self.db, new)
        return "written", new.decision_version, None

    def set_step(self, workspace_id: str, done: bool, *, key: str | None = None, index: int | None = None,
                 is_human=None) -> dict:
        """Tick or untick one step of the live route, named by its key (or,
        for older clients, its position in the live steps). A step of the OS
        plan is completed through PAI OS and only by a signed-in student
        (`is_human()` is asked then, and only then)."""
        self._lock(workspace_id)
        row = self._active_or_404(workspace_id)
        try:
            view = plan_adapter.read(row)
        except plan_adapter.PlanUnavailable:  # an OS route whose plan cannot be read must not fall back to local ticks
            raise RouteDecisionError(*STEP_REFUSALS["unavailable"]) from None
        with plan_adapter.pinned(view):  # the plan is read once for this request
            if view is not None and view["state"] != "empty" and plan_adapter.applied(row, view):
                return self._set_plan_step(row, view, done, key, index, is_human)
            return self._set_local_step(row, workspace_id, done, key, index)

    def _set_local_step(self, row: RouteDecision, workspace_id: str, done: bool, key: str | None,
                        index: int | None) -> dict:
        page = RoadmapEngine(self.db).build(workspace_id)
        card = next((card for card in page["fields"] if card["field_key"] == row.field_key), None)
        # The field card is gone (the route is stale): its stored steps carry no
        # `tickable`, so the same rule is read from them rather than refusing
        # every tick.
        steps = card["steps"] if card else [{**step, "tickable": is_tickable(step)} for step in row.steps or []]
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
        return plan_adapter.chosen(row, RoadmapEngine(self.db).build(workspace_id)["fields"])

    def _set_plan_step(self, row: RouteDecision, view: dict, done: bool, key: str | None, index: int | None,
                       is_human) -> dict:
        """A tick on a step of the OS plan: PAI OS completes the task (the tick is its state, not a Counsellor tick)."""
        steps = plan_adapter.steps_of(view)
        if key is None and index is not None and 0 <= index < len(steps):
            key = steps[index]["key"]
        step = next((s for s in steps if s["key"] == key), None)
        if step is None:
            raise RouteDecisionError("No such step on this route", 422)
        if is_human is None or not is_human():  # first, so a token-only caller is refused for every OS step
            raise RouteDecisionError("Sign in to your PAI account to tick a step of your plan.", 403)
        if not done:
            raise RouteDecisionError("A step of your plan cannot be undone here. If something changed, "
                                     "tell PAI and the plan will be updated.", 409)
        if step["status"] == "done":  # a repeat tick (a double click) changes nothing and is no error
            return plan_adapter.chosen(row, RoadmapEngine(self.db).build(row.workspace_id)["fields"])
        if step["review"]:
            raise RouteDecisionError("Approve the file to finish this step; it cannot be ticked.", 409)
        if not step["tickable"]:
            raise RouteDecisionError("This step is not waiting for you, so it cannot be ticked.", 409)
        try:
            pai_os_bridge.complete_step(str(row.workspace_id), step["task_id"])
        except pai_os_bridge.StepError as exc:
            raise RouteDecisionError(*STEP_REFUSALS[exc.code]) from None
        try:  # the tick changed the plan: read it again, once, for the answer
            fresh = plan_adapter.read(row, fresh=True)
        except plan_adapter.PlanUnavailable:
            fresh = {**view, "steps": [{**s, "status": "done"} if s["task_id"] == step["task_id"] else s
                                       for s in view["steps"]]}  # the OS took the tick: show it done
        with plan_adapter.pinned(fresh):
            return plan_adapter.chosen(row, RoadmapEngine(self.db).build(row.workspace_id)["fields"])

    def withdraw(self, workspace_id: str) -> dict:
        self._lock(workspace_id)
        row = self._active_or_404(workspace_id)
        now = datetime.now(timezone.utc)
        row.withdrawn_at = now
        PossibilityService(self.db).set_chosen(workspace_id, row.possibility_id, False)
        self.db.flush()
        # The withdrawal is a version of its own, born withdrawn so it is never the active row (rule D-a).
        marker = RouteDecision(
            workspace_id=workspace_id, decision_version=self._next_version(workspace_id), status="withdrawn",
            field_key=row.field_key, possibility_id=row.possibility_id, title=row.title, verdict=row.verdict,
            route=row.route, steps=list(row.steps or []), steps_done=[], origin_country=row.origin_country,
            destination_country=row.destination_country, level=row.level, path_ref=row.path_ref, places=[],
            intake=None, os_supported=row.os_supported, chosen_at=now, withdrawn_at=now)
        self.db.add(marker)
        self.db.flush()
        self._record_withdraw(workspace_id, row, marker.decision_version)
        outbox.record(self.db, marker)
        self.db.flush()
        return serialize(row, RoadmapEngine(self.db).build(workspace_id)["fields"])
