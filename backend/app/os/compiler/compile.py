"""The plan compiler (spec §4.3): RouteContract + playbook + facts + today -> PlanDraft.

Pure: no database, no clock, no randomness. The same input always gives the same draft.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.os.compiler.conditions import evaluate
from app.os.compiler.schedule import Node, end_of_day, schedule
from app.os.contracts.route_contract import RouteContract
from app.os.knowledge import Fact
from app.os.playbooks import Playbook, TaskTemplate

CONFIRM_TYPE = "knowledge.confirm_fact"


class CompileError(ValueError):
    pass


@dataclass(frozen=True)
class DraftTask:
    instance_key: str
    template_key: str
    task_type: str
    kind: str
    inbox_kind: str | None
    programme_ref: str | None
    title: str
    depends_on: tuple[tuple[str, bool], ...]
    duration_days: int
    earliest_start: datetime
    latest_start: datetime | None
    latest_finish: datetime | None
    due_tz: str
    provisional: bool
    estimated: bool
    blocked_reason: str | None
    slack_days: int | None
    critical: bool
    protected: bool
    citations: tuple[dict, ...]
    fact_refs: tuple[tuple[str, str, str], ...]


@dataclass(frozen=True)
class PlanDraft:
    playbook_key: str
    playbook_version: int
    tasks: tuple[DraftTask, ...]
    at_risk: bool


@dataclass
class _Inst:
    key: str
    tmpl: TaskTemplate
    ref: str | None
    task_type: str
    kind: str
    inbox_kind: str | None
    deps: list[tuple[str, bool]] = field(default_factory=list)
    provisional: bool = False
    estimated: bool = False
    blocked_reason: str | None = None
    deadline: datetime | None = None
    tz: str = ""
    citations: list[dict] = field(default_factory=list)
    fact_refs: list[tuple[str, str, str]] = field(default_factory=list)


def needed_fields(playbook: Playbook) -> tuple[set[str], set[str]]:
    """(route fields, programme fields) that conditions, anchors and citation_from_fact refer to."""
    route, programme = set(), set()
    for t in playbook.tasks:
        target = programme if t.fan_out == "programme" else route
        for name in (t.condition.fact if t.condition else None, t.citation_from_fact):
            if name:
                target.add(name)
        if t.anchor:  # an anchor on a chosen programme reads that programme's fact (Slice 9 Task 11, F1)
            (programme if t.anchor.programme else target).add(t.anchor.fact)
    return route, programme


def date_of(value, label: str) -> tuple[date, str | None]:
    """A date fact: "YYYY-MM-DD", or {"date": "YYYY-MM-DD", "tz": "Area/City"}. CompileError otherwise."""
    raw, tz = (value.get("date"), value.get("tz")) if isinstance(value, dict) else (value, None)
    try:
        parsed = date.fromisoformat(str(raw))
        if tz is not None:
            ZoneInfo(str(tz))
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        raise CompileError(f"fact {label} is not a date (YYYY-MM-DD, optional tz): {value!r}") from None
    return parsed, tz


def _find_cycle(keys: list[str], edges: dict[str, list[str]]) -> list[str]:
    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(k: str) -> list[str] | None:
        state[k] = 1
        stack.append(k)
        for nxt in edges.get(k, []):
            if state.get(nxt) == 1:
                return stack[stack.index(nxt):] + [nxt]
            if nxt not in state and (found := visit(nxt)):
                return found
        stack.pop()
        state[k] = 2
        return None

    for k in keys:
        if k not in state and (found := visit(k)):
            return found
    return []


def _topological(keys: list[str], deps: Mapping[str, list[tuple[str, bool]]]) -> list[str]:
    succs: dict[str, list[str]] = {k: [] for k in keys}
    indeg = {k: 0 for k in keys}
    for k in keys:
        for d, _ in deps[k]:
            succs[d].append(k)
            indeg[k] += 1
    ready = sorted(k for k in keys if indeg[k] == 0)
    order: list[str] = []
    while ready:
        k = ready.pop(0)
        order.append(k)
        for s in sorted(succs[k]):
            indeg[s] -= 1
            if indeg[s] == 0:
                ready.append(s)
        ready.sort()
    if len(order) != len(keys):
        cycle = _find_cycle(keys, succs)
        raise CompileError("cycle: " + " -> ".join(cycle))
    return order


def _waits_for(insts: dict[str, _Inst], key: str) -> set[str]:
    """Every step `key` waits for, directly or through others."""
    seen: set[str] = set()
    todo = [key]
    while todo:
        for d, _ in insts[todo.pop()].deps:
            if d in insts and d not in seen:
                seen.add(d)
                todo.append(d)
    return seen


def _apply_overrides(insts: dict[str, _Inst], confirms: dict[str, tuple[str, str]], overrides: Sequence) -> None:
    def drop(keys: set[str]) -> None:
        for k in keys:
            insts.pop(k, None)
        for inst in insts.values():
            inst.deps = [d for d in inst.deps if d[0] not in keys]

    for o in overrides:
        if o.op in ("skip", "cancel"):
            drop({o.target} & set(insts))
        elif o.op == "cancel_programme":
            drop({k for k, i in insts.items() if i.ref == o.target})
            for k in [k for k, (ref, _) in confirms.items() if ref == o.target]:
                del confirms[k]
        elif o.op == "add":
            ref = o.payload.get("programme_ref")
            base_key = o.target if ref is None else f"{o.target}@{ref}"
            base = insts.get(base_key)
            if base is None:
                continue
            n = 2
            while f"{base_key}#{n}" in insts:
                n += 1
            key = f"{base_key}#{n}"
            insts[key] = replace(base, key=key, deps=list(base.deps), citations=list(base.citations),
                                 fact_refs=list(base.fact_refs))
            for inst in insts.values():  # what waited for the base step now also waits for the new one
                if inst.key != key and (base_key, True) in inst.deps:
                    inst.deps.append((key, True))
                    inst.deps.sort()
        elif o.op == "reprioritise":
            before = insts.get(o.payload.get("before", ""))
            if before is not None and o.target in insts and before.key not in _waits_for(insts, o.target) \
                    and (o.target, False) not in before.deps and (o.target, True) not in before.deps:
                before.deps.append((o.target, False))  # never a cycle: `target` does not already wait for `before`
                before.deps.sort()


def compile_plan(
    contract: RouteContract,
    playbook: Playbook,
    route_facts: Mapping[str, Fact],
    programme_facts: Mapping[tuple[str, str], Fact],
    today: date,
    disabled_types: frozenset[str] = frozenset(),
    overrides: Sequence = (),
    chosen: Mapping[str, str | None] = {},
) -> PlanDraft:
    """`overrides`: a replan's plan overrides (Slice 7 S7-D5), each with `op`, `target` and `payload`, applied after
    the playbook is expanded, so every recompile keeps them. An override whose target is gone is ignored.
    `chosen`: the programme the student chose for a purpose, by the name an `anchor.programme` uses ("visa": the
    programme the visa file is for), or None while there is none (Slice 9 Task 11, F1)."""
    refs = [p.programme_ref for p in sorted(contract.programmes, key=lambda p: p.rank)]
    removed = {o.target for o in overrides if o.op == "cancel_programme"}
    route_key = playbook.key
    insts: dict[str, _Inst] = {}
    by_template: dict[str, list[_Inst]] = {}
    confirms: dict[str, tuple[str, str]] = {}  # instance key -> (ref, field)

    def lookup(ref: str | None, name: str) -> tuple[Fact | None, tuple[str, str, str]]:
        if ref is None:
            return route_facts.get(name), ("route", route_key, name)
        return programme_facts.get((ref, name)), ("programme", ref, name)

    def need_confirm(fref: tuple[str, str, str]) -> None:
        _, ref, name = fref
        confirms[f"confirm_fact@{ref}:{name}"] = (ref, name)

    for t in playbook.tasks:
        task_type, kind, inbox_kind = t.task_type, t.kind, t.inbox_kind
        if task_type in disabled_types:
            if t.fallback == "skip":
                continue
            task_type, kind, inbox_kind = "student.act", "student", "act"
        for ref in (refs if t.fan_out == "programme" else [None]):
            inst = _Inst(key=t.template_key if ref is None else f"{t.template_key}@{ref}", tmpl=t, ref=ref,
                         task_type=task_type, kind=kind, inbox_kind=inbox_kind, tz=playbook.default_timezone,
                         citations=[c.model_dump(mode="json") for c in t.citations])
            if t.condition:
                fact, fref = lookup(ref, t.condition.fact)
                result = evaluate(t.condition, fact)
                if result is False and fact is not None and fact.confirmed:
                    continue
                if result is False:  # decided by an unconfirmed fact: drop, but keep the decision checkable
                    need_confirm(fref)
                    continue
                inst.fact_refs.append(fref)
                if fact is None or not fact.confirmed:
                    inst.provisional = True
                    need_confirm(fref)
            lead_days = 0
            if t.lead_time:
                if t.lead_time.days is not None:
                    lead_days = t.lead_time.days
                else:
                    const = playbook.constants[t.lead_time.constant]
                    lead_days = int(const.value)
                    inst.estimated |= const.estimate
            if t.anchor:
                if t.anchor.programme and ref is None:  # the chosen programme's fact, else the earliest (F1)
                    live = [r for r in refs if r not in removed]
                    pick = chosen.get(t.anchor.programme)
                    sources = [pick] if pick in live else live
                else:
                    sources = [ref]
                usable = []
                for src in sources:
                    fact, fref = lookup(src, t.anchor.fact)
                    inst.fact_refs.append(fref)
                    if fact is None or fact.value is None:
                        need_confirm(fref)
                        continue
                    if not fact.confirmed:
                        need_confirm(fref)
                    usable.append((date_of(fact.value, f"{fref[1]}:{fref[2]}"), fact))
                if not usable:
                    inst.blocked_reason = f"fact_missing:{t.anchor.fact}"
                else:
                    (d, tz), fact = min(usable, key=lambda u: u[0][0])
                    inst.tz = tz or playbook.default_timezone
                    if fact.url:  # the date comes from this page: cite it first (invariant 3, review I5)
                        cite = {"source": f"fact:{t.anchor.fact}", "url": fact.url}
                        if t.anchor.note:  # and say plainly how the date follows from it (F1)
                            cite["note"] = t.anchor.note.format(date=f"{d.day} {d:%B} {d.year}", days=lead_days,
                                                                weeks=lead_days // 7)
                        inst.citations.insert(0, cite)
                    inst.deadline = end_of_day(d, inst.tz) - timedelta(days=lead_days)
                    if not fact.confirmed or len(sources) > 1:  # several: it may move once one is chosen
                        inst.provisional = True
            if t.citation_from_fact:
                fact, fref = lookup(ref, t.citation_from_fact)
                inst.fact_refs.append(fref)
                if fact is not None and fact.url:
                    inst.citations.append({"source": f"fact:{t.citation_from_fact}", "url": fact.url})
                else:
                    need_confirm(fref)
            insts[inst.key] = inst
            by_template.setdefault(t.template_key, []).append(inst)

    for inst in insts.values():
        for dep in inst.tmpl.depends_on:
            targets = by_template.get(dep.key, [])
            if inst.ref is not None and playbook.task(dep.key).fan_out == "programme":
                targets = [x for x in targets if x.ref == inst.ref]
            inst.deps.extend((x.key, dep.hard) for x in targets)
        inst.deps.sort()

    _apply_overrides(insts, confirms, overrides)

    for key, (ref, name) in confirms.items():
        insts[key] = _Inst(key=key, tmpl=None, ref=None if ref == route_key else ref, task_type=CONFIRM_TYPE,
                           kind="work", inbox_kind=None, tz=playbook.default_timezone)
        insts[key].fact_refs.append(("route" if ref == route_key else "programme", ref, name))

    keys = sorted(insts)
    order = _topological(keys, {k: insts[k].deps for k in keys})

    def duration(inst: _Inst) -> int:
        if inst.tmpl is None:
            return 0
        if inst.tmpl.duration_constant:
            const = playbook.constants[inst.tmpl.duration_constant]
            inst.estimated |= const.estimate
            return int(const.value)
        return inst.tmpl.duration_days

    nodes = {
        k: Node(key=k, duration_days=duration(insts[k]), tz=insts[k].tz, deadline=insts[k].deadline,
                hard_preds=[d for d, hard in insts[k].deps if hard],
                hard_succs=[s for s in keys if (k, True) in insts[s].deps])
        for k in keys
    }
    schedule(nodes, order, today)
    slacks = [n.slack_days for n in nodes.values() if n.slack_days is not None]
    min_slack = min(slacks) if slacks else None

    tasks = []
    for k in keys:
        inst, n = insts[k], nodes[k]
        t = inst.tmpl
        title = t.title if t else f"Confirm {inst.fact_refs[0][2]} for {inst.fact_refs[0][1]}"
        tasks.append(DraftTask(
            instance_key=k, template_key=t.template_key if t else "confirm_fact", task_type=inst.task_type,
            kind=inst.kind, inbox_kind=inst.inbox_kind, programme_ref=inst.ref, title=title,
            depends_on=tuple(inst.deps), duration_days=n.duration_days, earliest_start=n.earliest_start,
            latest_start=n.latest_start, latest_finish=n.latest_finish, due_tz=inst.tz,
            provisional=inst.provisional, estimated=inst.estimated, blocked_reason=inst.blocked_reason,
            slack_days=n.slack_days, critical=n.slack_days is not None and n.slack_days == min_slack,
            protected=bool(t and t.protected), citations=tuple(inst.citations),
            fact_refs=tuple(dict.fromkeys(inst.fact_refs)),
        ))
    return PlanDraft(playbook_key=playbook.key, playbook_version=playbook.version, tasks=tuple(tasks),
                     at_risk=any(s < 0 for s in slacks))
