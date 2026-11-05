"""The Counsellor adapter for the OS plan (P1-T5, R-01, R-04, R-44). With CONNECT_ROADMAP_FROM_PLANVIEW on, the chosen
route of a route PAI OS runs is filled from the OS plan view, in today's `RoadmapPage.chosen` shape; a tick on an OS step
completes the OS task. Only a row with `os_supported` true whose plan view is not `empty` uses it: everything else, and
every flag-off call, is today's `serialize`, so the page stays as it was. All OS reads go through `pai_os_bridge`."""

from app import pai_os_bridge
from app.pai_c.connect.flags import part_on
from app.pai_c.roadmap.engine import roadmap_policy

STATUS = {"done": "done", "running": "half", "ready": "half", "waiting_student": "half", "waiting_review": "half",
          "pending": "not", "blocked": "not", "failed": "not"}  # skipped and cancelled steps are not shown
TICK_KINDS = ("act", "provide")
STEP_FIELDS = ("due_at", "due_tz", "owner", "provisional", "estimated")


def view_for(row) -> dict | None:
    """The OS plan view of an active row the OS runs, or None (flag off, withdrawn row, route the OS does not run, OS
    unavailable): today's path then runs. The flag is read before anything is asked of the OS."""
    if not part_on("CONNECT_ROADMAP_FROM_PLANVIEW") or row.withdrawn_at is not None or not row.os_supported:
        return None
    return pai_os_bridge.plan_view(str(row.workspace_id))


def applied(row, view: dict) -> bool:
    """False when the OS has not applied this choice yet: its plan is of an older decision version and of another route,
    which must not be shown under the new one (a consent change is a newer version of the same route: shown)."""
    if (view.get("decision_version") or 0) >= row.decision_version:
        return True
    route = view.get("route") or {}
    return (route.get("destination_country"), route.get("level")) == (row.destination_country, row.level)


def chosen(row, cards: list[dict]) -> dict:
    """The decision as the page shows it: `serialize`, or the plan's steps when the OS runs this route and has a plan.
    With the flag on and no plan yet, today's view plus `plan: {state: "empty"}`."""
    from app.pai_c.roadmap.decisions import serialize

    view = view_for(row)
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
    return {**serialize(row, cards), "steps": [{k: v for k, v in s.items() if k not in ("task_id", "review")}
                                                for s in steps],
            "time": None, "steps_done": [s["key"] for s in steps if s["status"] == "done"],
            "plan": {"state": view["state"], "state_reason": view["state_reason"], "revision": view["revision"],
                     "decision_version": view["decision_version"], "proposals_waiting": view["proposals_waiting"],
                     "changes": view["changes"]}}


def plan_superseded(row) -> bool:
    """True when CONNECT_CHECKINS_FROM_PLANVIEW is on and the row's plan is stopped or finished: the check-in no longer
    applies. False for every other case, and no OS call while the flag is off."""
    if not part_on("CONNECT_CHECKINS_FROM_PLANVIEW") or not row.os_supported:
        return False
    view = pai_os_bridge.plan_view(str(row.workspace_id))
    return view is not None and view["state"] in ("stopped", "finished") and applied(row, view)
