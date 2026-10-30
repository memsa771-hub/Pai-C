"""Cost report (Slice 9 spec §3.4, D7): AI cost per student from rows already recorded in os_agent_runs. Read only;
nothing new is tracked. A row reaches its student through the one thing it is linked to (a document, an artifact or a
plan, joined inside the tenant). Research readings belong to no student and are one shared total. A row with no link,
or whose link was nulled (a deleted document), is counted as unlinked and never guessed."""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Literal

from sqlalchemy import Engine, and_, case, func, literal, select

from app.os import models

ALERT_USD = Decimal("8")  # D7: $10 per student per year; flagged at $8
OVER_USD = Decimal("10")
ZERO = Decimal("0")

Flag = Literal["ok", "alert", "over"]


@dataclass(frozen=True)
class StudentCost:
    student_ref: str
    documents_usd: Decimal
    statements_usd: Decimal
    replan_usd: Decimal
    total_usd: Decimal
    flag: Flag


@dataclass(frozen=True)
class CostReport:
    start: date
    end: date
    students: list[StudentCost] = field(default_factory=list)
    research_usd: Decimal = ZERO
    unlinked_rows: int = 0
    unlinked_usd: Decimal = ZERO


def flag_for(total: Decimal) -> Flag:
    return "over" if total >= OVER_USD else "alert" if total >= ALERT_USD else "ok"


def cost_report(engine: Engine, tenant_id: str, start: date, end: date) -> CostReport:
    """Rows with start 00:00 UTC <= at < (end + 1 day) 00:00 UTC, so both calendar days are included."""
    if end < start:
        raise ValueError("end is before start")
    lo = datetime.combine(start, time.min, tzinfo=timezone.utc)
    hi = datetime.combine(end + timedelta(days=1), time.min, tzinfo=timezone.utc)
    r, d, a, p = models.agent_runs, models.documents, models.artifacts, models.plans
    # Every join repeats the tenant, so a link into another tenant's row never counts.
    j = (r.outerjoin(d, and_(r.c.document_id == d.c.id, d.c.tenant_id == r.c.tenant_id))
          .outerjoin(a, and_(r.c.artifact_id == a.c.id, a.c.tenant_id == r.c.tenant_id))
          .outerjoin(p, and_(r.c.plan_id == p.c.id, p.c.tenant_id == r.c.tenant_id)))
    bucket = case((r.c.research_run_id.is_not(None), "research"),
                  (d.c.id.is_not(None), "documents"),
                  (a.c.id.is_not(None), "statements"),
                  (p.c.id.is_not(None), "replan"),
                  else_="unlinked")
    student = case((r.c.research_run_id.is_not(None), literal(None)),
                   (d.c.id.is_not(None), d.c.student_ref),
                   (a.c.id.is_not(None), a.c.student_ref),
                   (p.c.id.is_not(None), p.c.student_ref), else_=literal(None))
    stmt = (select(bucket.label("bucket"), student.label("student"), func.sum(r.c.cost_usd), func.count())
            .select_from(j)
            .where(r.c.tenant_id == tenant_id, r.c.at >= lo, r.c.at < hi)
            .group_by("bucket", "student"))
    with engine.connect() as conn:
        rows = conn.execute(stmt).all()
    research, unlinked_usd, unlinked_rows = ZERO, ZERO, 0
    per: dict[str, dict[str, Decimal]] = {}
    for kind, ref, usd, n in rows:
        usd = Decimal(usd)
        if kind == "research":
            research += usd
        elif kind == "unlinked":
            unlinked_usd += usd
            unlinked_rows += n
        else:
            per.setdefault(ref, {})[kind] = usd
    students = []
    for ref, b in per.items():
        docs, stmts, replan = b.get("documents", ZERO), b.get("statements", ZERO), b.get("replan", ZERO)
        total = docs + stmts + replan
        students.append(StudentCost(ref, docs, stmts, replan, total, flag_for(total)))
    students.sort(key=lambda s: (-s.total_usd, s.student_ref))
    return CostReport(start, end, students, research, unlinked_rows, unlinked_usd)
