"""The kernel's checks on replan operations (Slice 7 spec S7-D6). Pure, except `task_rows`, which reads the plan.

Each operation is checked in order against the plan with the operations kept so far, so a refused one never
changes what the next is checked against. Refused when:
- the step (template) does not exist in the plan's pinned playbook, or the target step is not in the plan;
- it touches a protected or started step;
- a surviving, unstarted step has a hard dependency on a step it removes;
- with it, a step that had slack would miss its deadline (negative slack);
- a swapped-in programme has no confirmed facts.
"""

from collections.abc import Callable, Mapping

from sqlalchemy import Engine, select

from app.os import models
from app.os.compiler import CompileError
from app.os.kernel.revisions import CANCELLED_MARK, DONE_MARK
from app.os.kernel.states import is_started
from app.os.replan.ops import (
    AddTask, CancelProgramme, CancelTask, Op, Reprioritise, RequestFromStudent, SkipTask, SwapProgramme, TaskRow,
    to_overrides,
)

T, E = models.tasks, models.task_edges


def task_rows(engine: Engine, tenant_id: str, plan_id: int) -> dict[str, TaskRow]:
    """The plan's live tasks (not the renamed history rows of cancelled or re-checked tasks), with their edges."""
    with engine.connect() as conn:
        tasks = conn.execute(select(T).where(T.c.tenant_id == tenant_id, T.c.plan_id == plan_id)).all()
        edges = conn.execute(select(E.c.from_task, E.c.to_task, E.c.hard).where(E.c.plan_id == plan_id)).all()
    key_of = {t.id: t.instance_key for t in tasks}
    deps: dict[int, list[tuple[str, bool]]] = {}
    for e in edges:
        deps.setdefault(e.to_task, []).append((key_of[e.from_task], e.hard))
    return {t.instance_key: TaskRow(t.instance_key, t.template_key, t.programme_ref, t.state, t.kind, t.critical,
                                    t.protected, t.latest_finish, t.slack_days, t.duration_days,
                                    tuple(sorted(deps.get(t.id, []))))
            for t in tasks if CANCELLED_MARK not in t.instance_key and DONE_MARK not in t.instance_key}


def _removed(ops: list[Op], tasks: Mapping[str, TaskRow]) -> set[str]:
    out: set[str] = set()
    for op in ops:
        if isinstance(op, (SkipTask, CancelTask)):
            out.add(op.instance_key)
        elif isinstance(op, CancelProgramme):
            out |= {k for k, t in tasks.items() if t.programme_ref == op.programme_ref}
    return out


def _static(op: Op, tasks: Mapping[str, TaskRow], playbook, confirmed: Callable[[str], bool]) -> str | None:
    """Why the operation is refused on its own, or None."""
    if isinstance(op, AddTask):
        if not any(t.template_key == op.template_key for t in playbook.tasks):
            return f"'{op.template_key}' is not a step of this route's guide"
        base = op.template_key if op.programme_ref is None else f"{op.template_key}@{op.programme_ref}"
        if base not in tasks:  # the compiler adds a step again only next to the one the plan has
            return f"'{base}' is not in the plan"
        return None
    targets = []
    if isinstance(op, (SkipTask, CancelTask, RequestFromStudent)):
        targets = [op.instance_key]
    elif isinstance(op, Reprioritise):
        targets = [op.instance_key, op.before]
    for key in targets:
        t = tasks.get(key)
        if t is None:
            return f"there is no step '{key}' in the plan"
        if isinstance(op, (SkipTask, CancelTask)) and t.protected:
            return f"'{key}' is protected"
        if isinstance(op, (SkipTask, CancelTask, Reprioritise)) and is_started(t.state, t.kind):
            return f"'{key}' has started"
    live = {t.programme_ref for t in tasks.values() if t.programme_ref}
    if isinstance(op, CancelProgramme) and op.programme_ref not in live:
        return f"'{op.programme_ref}' is not in the plan"
    if isinstance(op, SwapProgramme):
        if op.out_ref not in live:
            return f"'{op.out_ref}' is not in the plan"
        if op.in_ref in live:
            return f"'{op.in_ref}' is already in the plan"
        if not confirmed(op.in_ref):
            return f"'{op.in_ref}' has no confirmed facts yet"
    return None


def _loses_input(ops: list[Op], tasks: Mapping[str, TaskRow]) -> str | None:
    removed = _removed(ops, tasks)
    for key, t in tasks.items():
        if key in removed or is_started(t.state, t.kind):
            continue
        hard = [d for d, h in t.depends_on if h and d in tasks]
        for d in (d for d in hard if d in removed):  # still fed by another step of the same kind (another programme)?
            same = tasks[d].template_key
            if not any(x not in removed and tasks[x].template_key == same for x in hard):
                return f"'{key}' needs it ('{d}')"
    return None


def _late(current, candidate) -> str | None:
    before = {t.instance_key: t.slack_days for t in current.tasks}
    for t in candidate.tasks:
        was = before.get(t.instance_key)
        if t.slack_days is not None and t.slack_days < 0 and (was is None or was >= 0):
            return f"'{t.instance_key}' would be past its deadline"
    return None


def check_operations(ops: list[Op], tasks: Mapping[str, TaskRow], playbook,
                     compile_with: Callable[[list[Op]], object], current,
                     confirmed: Callable[[str], bool]) -> tuple[list[Op], list[dict]]:
    """(kept, refused). `compile_with(ops)` compiles the plan with those operations' overrides; `current` is the
    plan compiled with none; `confirmed(ref)` says whether a programme has the facts the compiler needs."""
    kept: list[Op] = []
    refused: list[dict] = []
    for op in ops:
        why = _static(op, tasks, playbook, confirmed) or _loses_input([*kept, op], tasks)
        if why is None and to_overrides(op):
            try:
                why = _late(current, compile_with([*kept, op]))
            except CompileError as e:  # e.g. a reorder that closes a cycle (final review C1)
                why = f"it would make the plan invalid ({e})"[:200]
        if why is None:
            kept.append(op)
        else:
            refused.append({"op": op.model_dump(mode="json"), "why": why})
    return kept, refused
