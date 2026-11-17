"""What a playbook step needs from the student becomes steps and blocks (P1-T8, D-w5; R-17, R-18, R-20, R-21).

Pure, like the compiler that calls it: the same playbook, state, facts and day always give the same result. It works on
the steps the compiler has built (after conditions and overrides) and adds, for each fact or document a live step needs:

- `provide@<kind>:<ref>:<level>` when it is missing or too weak, dated backwards from the steps that need it. One per
  ref at the lowest unmet level a live step needs, so typing the marks closes "tell us" and then opens "upload";
- `which_is_right@<fact|document>:<ref>:<level>` when the Vault, a document or a limit puts it in question (no
  provide step then; a document is asked the same way as a fact);
- `result_expected@fact:<ref>` before the provide step while the route's calendar says the result is not out yet.

Every step with an unmet or doubtful need gets a hard edge to that request and a `blocked_reason`
(`awaiting_fact:<ref>` or `which_is_right:<ref>`; with several, the first ref in order). A step that already has a
blocked reason (an anchor with no date) keeps it. Returns the request keys this state considers answered."""

from collections.abc import Callable, Mapping
from datetime import date

from app.os.compiler.compile import CompileError, _Inst, date_of
from app.os.compiler.schedule import end_of_day
from app.os.knowledge import Fact
from app.os.playbooks import Ask, Need, Playbook
from app.os.requests import keys
from app.os.requests.state import StudentState

RANK = {level: i for i, level in enumerate(keys.LEVELS)}
AWAITING, DOUBT, EXPECTED = keys.AWAITING, keys.DOUBT, keys.EXPECTED


def _met(student: StudentState, need: Need) -> bool:
    if need.kind == "document":
        return student.document_met(need.ref)
    level = student.level(need.ref)
    return level is not None and RANK[level] >= RANK[need.evidence]


def _request(key: str, template: str, task_type: str, inbox_kind: str, title: str, ask: Ask, tz: str) -> _Inst:
    return _Inst(key=key, tmpl=None, ref=None, task_type=task_type, kind="student", inbox_kind=inbox_kind, tz=tz,
                 title=title, template=template, days=ask.duration_days if template == keys.PROVIDE else 1,
                 citations=[c.model_dump(mode="json") for c in ask.citations])


def _result_expected(ref: str, ask: Ask, playbook: Playbook, route_facts: Mapping[str, Fact], today: date, tz: str,
                     need_confirm: Callable | None, calendar_facts: Mapping[tuple[str, str], Fact] | None = None,
                     year: int | None = None) -> _Inst | None:
    """The step that waits for a result still to come (R-20), when the calendar fact holds a date after today.
    An ask that names an official calendar (P2-T11) reads that calendar's date by its registry id; otherwise the route
    fact, exactly as before."""
    expected = ask.expected
    if expected is not None and expected.calendar:
        fact = (calendar_facts or {}).get((expected.calendar, expected.fact))
        fref = ("registry", expected.calendar, expected.fact)
    else:
        fact = route_facts.get(expected.fact) if expected else None
        fref = ("route", playbook.key, expected.fact) if expected else None
    if expected is None or fact is None or fact.value is None:
        return None
    try:
        day, fact_tz = date_of(fact.value, expected.fact)
    except CompileError:
        return None  # a calendar that is not a date asks nothing of the student: the provide step stands alone
    if day <= today:
        return None
    # a calendar date of another year (the labelled previous-year read, R-26) is never firm: the step stays provisional
    firm = fact.confirmed and (not expected.calendar or year is None or fact.intake_year == year)
    inst = _Inst(key=keys.make(keys.RESULT_EXPECTED, "fact", ref), tmpl=None, ref=None, task_type="system.milestone",
                 kind="work", inbox_kind=None, tz=fact_tz or tz, title=expected.title, template=keys.RESULT_EXPECTED,
                 days=0, blocked_reason=f"{EXPECTED}:{ref}", deadline=end_of_day(day, fact_tz or tz),
                 provisional=not firm)
    inst.fact_refs.append(fref)
    if fact.url:  # the date comes from this page: cite it (a calendar's date is labelled with the calendar's id)
        label = f"fact:{expected.calendar}:{expected.fact}" if expected.calendar else f"fact:{expected.fact}"
        inst.citations.append({"source": label, "url": fact.url})
    if not firm and need_confirm is not None:
        need_confirm(fref)
    return inst


def expand(insts: dict[str, _Inst], playbook: Playbook, student: StudentState, route_facts: Mapping[str, Fact],
           today: date, tz: str, *, need_confirm: Callable | None = None,
           calendar_facts: Mapping[tuple[str, str], Fact] | None = None, year: int | None = None) -> tuple[str, ...]:
    """Adds the request steps and edges to `insts` in place; returns the answered request keys, sorted."""
    wanted: dict[tuple[str, str], list[tuple[_Inst, Need]]] = {}
    for key in sorted(insts):
        inst = insts[key]
        for need in inst.tmpl.needs if inst.tmpl is not None else ():
            wanted.setdefault((need.kind, need.ref), []).append((inst, need))
    answered: set[str] = set()
    blocks: dict[str, set[tuple[str, str]]] = {}

    def link(waiting: list[_Inst], request: str, code: str, ref: str) -> None:
        for inst in waiting:
            if request and (request, True) not in inst.deps:
                inst.deps.append((request, True))
                inst.deps.sort()
            blocks.setdefault(inst.key, set()).add((ref, code))

    for (kind, ref), steps in sorted(wanted.items()):
        ask = playbook.asks[ref]
        highest = max((n.evidence for _, n in steps), key=RANK.__getitem__)
        if student.question(kind, ref) is not None:  # two sources disagree, or the value cannot be: ask which (R-21)
            request = keys.make(keys.WHICH_IS_RIGHT, kind, ref, highest)  # a fact or a document: both get the step
            title = ask.which_is_right or getattr(ask, highest)  # a document's ask need not word the question
            insts[request] = _request(request, keys.WHICH_IS_RIGHT, "student.choose", "choose", title or "", ask,
                                      playbook.default_timezone)
            link([i for i, _ in steps], request, DOUBT, ref)
            continue
        answered.add(keys.make(keys.WHICH_IS_RIGHT, kind, ref, highest))
        unmet = [(i, n) for i, n in steps if not _met(student, n)]
        answered.update(keys.make(keys.PROVIDE, kind, ref, n.evidence) for _, n in steps if _met(student, n))
        if not unmet:
            continue
        level = min((n.evidence for _, n in unmet), key=RANK.__getitem__)
        request = keys.make(keys.PROVIDE, kind, ref, level)
        provide = _request(request, keys.PROVIDE, "student.provide", "provide", getattr(ask, level), ask, tz)
        insts[request] = provide
        if kind == "fact" and student.level(ref) is None:
            waits = _result_expected(ref, ask, playbook, route_facts, today, tz, need_confirm, calendar_facts, year)
            if ask.expected is not None and ask.expected.calendar:
                # the provide step follows the calendar fact, so a date that arrives or moves revises the plan (P2-T11)
                provide.fact_refs.append(("registry", ask.expected.calendar, ask.expected.fact))
            if waits is not None:
                insts[waits.key] = waits
                provide.deps.append((waits.key, True))  # the provide step waits for it but never pulls it earlier
                provide.no_pull.add(waits.key)
        link([i for i, _ in unmet], request, AWAITING, ref)

    for key, found in blocks.items():
        inst = insts[key]
        if inst.blocked_reason is None:
            ref, code = min(found)
            inst.blocked_reason = f"{code}:{ref}"
    return tuple(sorted(answered))
