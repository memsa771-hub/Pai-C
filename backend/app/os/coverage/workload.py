"""The review workload and the estimate that feeds the owner's checker decision (P2 spec §4.9; master §12, §11 Q2).

Estimate = registry size x high-stakes facts per institution x checks per fact, against the measured rate. What is
measured is rows verified by review per reviewer-day (a reviewer who verified anything on a day = one reviewer-day). The
hours per working day (`work_hours_per_day`) are an ASSUMPTION used only to show rows per hour: nobody timed the
checkers. With no review measured yet there is no rate and no hours."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import Engine, func, select

from app.os import models
from app.os.coverage import expected

RV = models.fact_revisions


@dataclass(frozen=True)
class Workload:
    institutions: int
    high_stakes_facts: int  # expected or held, over the institutions in scope
    high_stakes_per_institution: float
    not_verified: int  # rows left to verify
    checks_needed: int  # for all the rows: institutions x per-institution x checks per fact
    checks_left: int  # rows left x checks per fact
    reviewers_active: int  # distinct reviewers who verified a row in the window
    rows_per_reviewer_day: float | None  # measured: rows verified / distinct (reviewer, day) pairs
    rows_per_hour: float | None  # per reviewer, ASSUMING `work_hours_per_day` hours in a working day
    work_hours_per_day: float  # the assumption behind rows_per_hour
    reviewer_hours_left: float | None  # rows left / rows_per_hour, for one reviewer
    team_days_left: float | None  # at the reviewers active in the window


def measure(engine: Engine, tenant_id: str, now: datetime) -> tuple[int, int, int]:
    """(rows verified by review in the last `measure_days` days, distinct (reviewer, day) pairs, distinct reviewers).
    A row with no recorded reviewer counts as one anonymous reviewer."""
    s = expected.settings()
    since = now - timedelta(days=s["measure_days"])
    who = func.coalesce(RV.c.actor, "")
    with engine.connect() as conn:
        rows = conn.execute(select(who, func.date(RV.c.at)).where(
            RV.c.tenant_id == tenant_id, RV.c.cause == "review", RV.c.action == "status",
            RV.c.after["status"].astext == "verified", RV.c.at >= since)).all()
    return len(rows), len({(w, d) for w, d in rows}), len({w for w, _ in rows})


def measured_rows_per_reviewer_day(engine: Engine, tenant_id: str, now: datetime) -> float | None:
    rows, pairs, _ = measure(engine, tenant_id, now)
    return rows / pairs if rows and pairs else None


def estimate(engine: Engine, tenant_id: str, now: datetime, *, institutions: int, high_stakes_facts: int,
             not_verified: int) -> Workload:
    s = expected.settings()
    per = high_stakes_facts / institutions if institutions else 0.0
    rows, pairs, reviewers = measure(engine, tenant_id, now)
    per_day = rows / pairs if rows and pairs else None
    per_hour = per_day / s["work_hours_per_day"] if per_day else None
    hours = not_verified / per_hour if per_hour else None
    return Workload(
        institutions=institutions, high_stakes_facts=high_stakes_facts, high_stakes_per_institution=round(per, 2),
        not_verified=not_verified, checks_needed=round(institutions * per) * s["checks_per_fact"],
        checks_left=not_verified * s["checks_per_fact"], reviewers_active=reviewers,
        rows_per_reviewer_day=round(per_day, 2) if per_day else None,
        rows_per_hour=round(per_hour, 3) if per_hour else None, work_hours_per_day=s["work_hours_per_day"],
        reviewer_hours_left=round(hours, 1) if hours is not None else None,
        team_days_left=round(not_verified / (per_day * reviewers), 1) if per_day and reviewers else None)
