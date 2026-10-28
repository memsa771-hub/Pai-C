"""Replan rules (Slice 7 spec S7-D3, §2): pure. An event and the plan's state give operations, a retry, or a
hand-over to the Supervisor. Rules always run first. Nothing here names a route: templates and counts come from
the plan, the playbook and the route's replan config (invariant 12)."""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.os.kernel.states import is_started
from app.os.replan.config import ReplanConfig
from app.os.replan.events import Event
from app.os.replan.ops import (
    AddTask, CancelProgramme, Escalate, Op, Reprioritise, RequestFromStudent, SwapProgramme, TaskRow, UpgradePlaybook,
)

REASONS = {
    "rejected": "The programme did not admit you: its remaining steps are removed.",
    "rejected_kept": "The programme did not admit you: its steps that have not started are removed; steps already "
                     "started or kept on purpose stay.",
    "swap": "You have fewer programmes than planned: this one is a close match.",
    "critical": "This step is on the critical path for a deadline.",
    "request": "This is needed to keep your plan on time.",
    "late": "A deadline is at risk: a person will look at your plan.",
    "failed": "A step failed twice: a person will look at it.",
    "upgrade": "There is a newer version of your route's guide.",
    "review": "The file you approved changed: please approve it again.",
}
MESSAGE = "Please do this soon so your plan stays on time."
CLOSED = ("done", "cancelled", "skipped")
_NEVER = datetime(1970, 1, 1, tzinfo=timezone.utc)  # a step with no date sorts first


@dataclass(frozen=True)
class PlanState:
    plan_id: int
    route_key: str
    programmes: list[str]  # the live programme refs, by rank
    tasks: dict[str, TaskRow]
    suggestions: dict[str, list[str]] = field(default_factory=dict)  # programme -> close matches (Slice 4 swaps)
    playbook_version: int = 1


@dataclass(frozen=True)
class Handover:
    reason: str  # why the rules leave it to the Supervisor


@dataclass(frozen=True)
class Retry:
    instance_key: str  # retry this failed step once, through the kernel


def _open(t: TaskRow | None) -> bool:
    return t is not None and t.state not in CLOSED


def _rejected(event: Event, state: PlanState, cfg: ReplanConfig) -> list[Op] | Handover:
    ref = event.payload.get("programme_ref")
    if ref not in state.programmes:
        return []
    left = [p for p in state.programmes if p != ref]
    if len(left) >= cfg.min_programmes:  # the kernel keeps started and protected steps: say so (Slice 7 minor #6)
        kept = any(_open(t) and t.programme_ref == ref and (t.protected or _stays(t)) for t in state.tasks.values())
        return [CancelProgramme(programme_ref=ref, reason=REASONS["rejected_kept" if kept else "rejected"])]
    match = next((s for s in state.suggestions.get(ref, []) if s not in state.programmes), None)
    if match is None:
        return Handover(f"a rejection left {len(left)} programme(s) and there is no close match")
    return [SwapProgramme(out_ref=ref, in_ref=match, reason=REASONS["swap"])]


def _stays(t: TaskRow) -> bool:
    """Whether the kernel keeps this started step when its programme is removed. A fact check only waiting for a
    review goes with its programme (kernel `revisions._left_with_programme`)."""
    return is_started(t.state, t.kind) and not (t.kind == "work" and t.state == "waiting_review")


def _unstarted_student(t: TaskRow | None) -> bool:
    return _open(t) and t.kind == "student" and not is_started(t.state, t.kind)


def _at_risk(event: Event, state: PlanState) -> list[Op] | Handover:
    key = event.payload.get("instance_key")
    t = state.tasks.get(key)
    if not _open(t):
        return []
    blocking = next((d for d, hard in sorted(t.depends_on) if hard and _unstarted_student(state.tasks.get(d))),
                    key if _unstarted_student(t) else None)  # what holds it up comes first, then the step itself
    if blocking is None:
        if t.programme_ref is not None:
            return Handover(f"a deadline of programme '{t.programme_ref}' is at risk and no student step blocks it")
        return [Escalate(reason=REASONS["late"])]
    ops: list[Op] = []
    movable = [(x.latest_finish or _NEVER, x.slack_days or 0, k) for k, x in state.tasks.items()
               if k not in (blocking, key) and _unstarted_student(x) and not x.critical
               and blocking not in {d for d, _ in x.depends_on}]
    later = max(movable)[2] if movable else None  # the most deferrable student step
    if later is not None:
        ops.append(Reprioritise(instance_key=blocking, before=later, reason=REASONS["critical"]))
    ops.append(RequestFromStudent(instance_key=blocking, message=MESSAGE, reason=REASONS["request"]))
    return ops


def rules_for(event: Event, state: PlanState, cfg: ReplanConfig) -> list[Op] | Handover | Retry:
    """The rules' answer to one event (spec §2). [] means nothing needs to change."""
    p = event.payload
    if event.type == "admission_rejected":
        return _rejected(event, state, cfg)
    if event.type == "deadline_at_risk":
        return _at_risk(event, state)
    if event.type == "document_missing":
        key = p.get("instance_key")
        if not _open(state.tasks.get(key)):
            return []
        return [RequestFromStudent(instance_key=key, message=MESSAGE, reason=REASONS["request"])]
    if event.type == "task_failed":
        if int(p.get("attempt") or 1) < 2:
            return Retry(p.get("instance_key"))
        return [Escalate(reason=REASONS["failed"])]
    if event.type == "playbook_newer":
        return [UpgradePlaybook(version=int(p["version"]), reason=REASONS["upgrade"])]
    if event.type == "approved_changed":
        return [AddTask(template_key=p["template_key"], programme_ref=p.get("programme_ref"),
                        reason=REASONS["review"])]
    return Handover(f"no rule for '{event.type}'")
