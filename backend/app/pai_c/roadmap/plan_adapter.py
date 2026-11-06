"""The Counsellor adapter for the OS plan (P1-T5, R-01, R-04, R-44). With CONNECT_ROADMAP_FROM_PLANVIEW on, the chosen
route of a route PAI OS runs is filled from the OS plan view, in today's `RoadmapPage.chosen` shape; a tick on an OS step
completes the OS task. Only a row with `os_supported` true whose plan view is not `empty` uses it: everything else, and
every flag-off call, is today's `serialize`, so the page stays as it was. All OS reads go through `pai_os_bridge`."""

from contextlib import contextmanager
from contextvars import ContextVar

from app import pai_os_bridge
from app.pai_c.connect.flags import part_on
from app.pai_c.roadmap.engine import roadmap_policy

STATUS = {"done": "done", "running": "half", "ready": "half", "waiting_student": "half", "waiting_review": "half",
          "pending": "not", "blocked": "not", "failed": "not"}  # skipped and cancelled steps are not shown
TICK_KINDS = ("act", "provide")
STEP_FIELDS = ("due_at", "due_tz", "owner", "provisional", "estimated")


class PlanUnavailable(Exception):
    """The row is one the OS runs and the flag is on, but the plan view could not be read (PAI OS is not mounted or
    failed). Not the same as an empty plan."""


_MISSING = object()
_PINNED: ContextVar = ContextVar("plan_view_pinned", default=_MISSING)


def applicable(row) -> bool:
    """True when the plan view decides what this row shows: the flag is on (read before anything is asked of the OS),
    the row is the active choice and PAI OS runs its route."""
    return row.withdrawn_at is None and bool(row.os_supported) and part_on("CONNECT_ROADMAP_FROM_PLANVIEW")


def read(row, *, fresh: bool = False) -> dict | None:
    """The OS plan view of an applicable row, or None when the adapter does not apply (flag off, withdrawn row, route
    the OS does not run): today's path then runs. Raises PlanUnavailable when the OS cannot answer. Inside `pinned`, the
    pinned view is returned (one read per request) unless `fresh`."""
    if not applicable(row):
        return None
    pinned = _PINNED.get()
    if pinned is not _MISSING and not fresh:
        return pinned
    view = pai_os_bridge.plan_view(str(row.workspace_id))
    if view is None:
        raise PlanUnavailable()
    return view


@contextmanager
def pinned(view: dict | None):
    """Every `read` inside answers `view`, so one request reads the plan once."""
    token = _PINNED.set(view)
    try:
        yield
    finally:
        _PINNED.reset(token)


@contextmanager
def pinned_read(row):
    """Reads the row's plan view once (an unavailable OS pins None: today's view) and pins it."""
    try:
        view = read(row)
    except PlanUnavailable:
        view = None
    with pinned(view):
        yield view


def applied(row, view: dict) -> bool:
    """Whether the plan view belongs to this choice. A view of an older decision version counts only when its plan is
    still live (not stopped or finished) and its route (origin, destination, level) is the row's: a plan of another
    route, or one the earlier choice ended, must not show under the new choice. A consent change is a newer version
    of the same route and keeps its plan."""
    if (view.get("decision_version") or 0) >= row.decision_version:
        return True
    if view.get("state") in ("stopped", "finished"):
        return False
    route = view.get("route") or {}
    return ((route.get("origin_country"), route.get("destination_country"), route.get("level"))
            == (row.origin_country, row.destination_country, row.level))


def chosen(row, cards: list[dict]) -> dict:
    """The decision as the page shows it: `serialize`, or the plan's steps when the OS runs this route and has a plan.
    With the flag on and no plan yet, today's view plus `plan: {state: "empty"}`. An unavailable OS shows today's view."""
    from app.pai_c.roadmap.decisions import serialize

    try:
        view = read(row)
    except PlanUnavailable:
        return serialize(row, cards)
    if view is None:
        return serialize(row, cards)
    if view["state"] == "empty" or not applied(row, view):
        return {**serialize(row, cards), "plan": {"state": "empty"}}
    return chosen_from_plan(row, cards, view)


def steps_of(view: dict) -> list[dict]:
    colours = roadmap_policy()["steps"]["colours"]
    out = []
    for step in view["steps"]:
        status = STATUS.get(step["status"])
        if status is None:
            continue
        tickable = (step["owner"] == "student" and step["status"] == "waiting_student"
                    and step["inbox_kind"] in TICK_KINDS and not step.get("review"))
        out.append({"key": step["instance_key"], "kind": "os", "label_key": "", "values": {}, "status": status,
                    "evidence": None, "rule": None, "manual_done": False, "timing": None,
                    "colour": colours[status], "tickable": tickable, "title": step["title"],
                    **{name: step[name] for name in STEP_FIELDS}, "task_id": step["task_id"],
                    "review": bool(step.get("review"))})
    return out


def chosen_from_plan(row, cards: list[dict], view: dict) -> dict:
    """Today's chosen-route dict (every key of `serialize`) with the plan's steps, plus `plan`."""
    from app.pai_c.roadmap.decisions import serialize

    steps = steps_of(view)
    plan = {"state": view["state"], "state_reason": view["state_reason"], "revision": view["revision"],
            "decision_version": view["decision_version"], "proposals_waiting": view["proposals_waiting"],
            "changes": view["changes"], **_reason_copy(view)}
    return {**serialize(row, cards), "steps": [{k: v for k, v in s.items() if k not in ("task_id", "review")}
                                                for s in steps],
            "time": None, "steps_done": [s["key"] for s in steps if s["status"] == "done"], "plan": plan}


def _reason_copy(view: dict) -> dict:
    """A plan paused by an escalation (R-11) carries the student's sentence and the button label, when the texts may
    be shown. Additive keys only (R-44); a consent pause and every other state add nothing."""
    from app.pai_c.connect import escalation_texts

    reason = view["state_reason"]
    if view["state"] != "paused" or reason not in escalation_texts.REASONS or not part_on("CONNECT_HANDOFF"):
        return {}
    sentence = escalation_texts.text(reason)
    return {} if sentence is None else {"reason_text": sentence, "reason_action": escalation_texts.action()}


def plan_superseded(row) -> bool:
    """True when CONNECT_CHECKINS_FROM_PLANVIEW is on and the row's plan is stopped or finished: the check-in no longer
    applies. False for every other case (including a plan of an earlier choice), and no OS call while the flag is off."""
    if not part_on("CONNECT_CHECKINS_FROM_PLANVIEW") or not row.os_supported:
        return False
    view = pai_os_bridge.plan_view(str(row.workspace_id))
    return view is not None and view["state"] in ("stopped", "finished") and applied(row, view)
