"""The review workload and the estimate that feeds the owner's checker decision (P2 spec §4.9; master §12, §11 Q2).

Estimate = registry size x high-stakes facts per institution x checks per fact, against the measured rows per hour.
Nothing is assumed about speed: with no review measured yet the hours are None."""

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
    rows_per_hour: float | None  # measured; None until someone has verified a row
    hours_left: float | None
    days_left: float | None  # at the work hours per day


def measured_rows_per_hour(engine: Engine, tenant_id: str, now: datetime) -> float | None:
    """Rows verified by review in the last `measure_days` days over (days with any review) x work hours per day."""
    s = expected.settings()
    since = now - timedelta(days=s["measure_days"])
    with engine.connect() as conn:
        rows, days = conn.execute(select(func.count(), func.count(func.distinct(func.date(RV.c.at)))).where(
            RV.c.tenant_id == tenant_id, RV.c.cause == "review", RV.c.action == "status",
            RV.c.after["status"].astext == "verified", RV.c.at >= since)).one()
    return rows / (days * s["work_hours_per_day"]) if rows and days else None


def estimate(engine: Engine, tenant_id: str, now: datetime, *, institutions: int, high_stakes_facts: int,
             not_verified: int) -> Workload:
    s = expected.settings()
    per = high_stakes_facts / institutions if institutions else 0.0
    rate = measured_rows_per_hour(engine, tenant_id, now)
    checks_left = not_verified * s["checks_per_fact"]
    # one row needs `checks_per_fact` checks, and the measured rate counts rows verified (both checks done)
    hours = not_verified / rate if rate else None
    return Workload(
        institutions=institutions, high_stakes_facts=high_stakes_facts, high_stakes_per_institution=round(per, 2),
        not_verified=not_verified, checks_needed=round(institutions * per) * s["checks_per_fact"],
        checks_left=checks_left, rows_per_hour=round(rate, 3) if rate else None,
        hours_left=round(hours, 1) if hours is not None else None,
        days_left=round(hours / s["work_hours_per_day"], 1) if hours is not None else None)
