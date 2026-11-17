"""The consistency cases and runs (P1-T10 A1). The only writes of the consistency check, and only to its own two
tables: a case holds the rule number, codes and IDs, never a value or a student sentence. Resolving a case changes
nothing else (no plan, task, pause or event). Every query is filtered by tenant."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import Engine, and_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.postgresql import insert

from app.os import clock, models

C, R = models.consistency_cases, models.consistency_runs
STALE_CLAIM = timedelta(hours=1)  # a nightly run takes seconds; an unfinished claim this old is a dead replica's


@dataclass(frozen=True)
class Case:
    id: int
    student_ref: str
    rule: int
    plan_id: int | None
    codes: list[str]
    status: str
    resolution: str | None
    first_seen_at: datetime
    last_seen_at: datetime
    resolved_at: datetime | None


def _case(r) -> Case:
    return Case(r.id, r.student_ref, r.rule, r.plan_id, list(r.codes), r.status, r.resolution, r.first_seen_at,
                r.last_seen_at, r.resolved_at)


class ConsistencyStore:
    def __init__(self, engine: Engine, tenant_id: str) -> None:
        self.engine, self.tenant_id = engine, tenant_id

    def open_or_touch(self, student_ref: str, rule: int, plan_id: int | None, codes: list[str]) -> tuple[int, bool]:
        """One open case per student, rule and plan (a case with no plan counts as one): a repeat only moves
        `last_seen_at` and takes the latest codes. Returns `(case id, created)`. Two runs at once still give one row
        (the partial unique index; the loser touches the winner's row)."""
        now = clock.now()
        same = and_(C.c.tenant_id == self.tenant_id, C.c.student_ref == student_ref, C.c.rule == rule,
                    C.c.status == "open", C.c.plan_id.is_not_distinct_from(plan_id))
        for _ in range(3):
            with self.engine.begin() as conn:
                touched = conn.execute(update(C).where(same).values(last_seen_at=now, codes=list(codes))
                                       .returning(C.c.id)).scalar()
                if touched is not None:
                    return touched, False
            try:
                with self.engine.begin() as conn:
                    return conn.execute(insert(C).values(
                        tenant_id=self.tenant_id, student_ref=student_ref, rule=rule, plan_id=plan_id,
                        codes=list(codes), first_seen_at=now, last_seen_at=now).returning(C.c.id)).scalar_one(), True
            except IntegrityError:
                continue  # another run opened it first: touch that one
        raise RuntimeError("could not open or touch the consistency case")

    def get(self, case_id: int) -> Case | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(C).where(C.c.tenant_id == self.tenant_id, C.c.id == case_id)).first()
        return _case(row) if row else None

    def list(self, status: str | None = None) -> list[Case]:
        q = select(C).where(C.c.tenant_id == self.tenant_id)
        if status is not None:
            q = q.where(C.c.status == status)
        with self.engine.connect() as conn:
            return [_case(r) for r in conn.execute(q.order_by(C.c.id)).all()]

    def resolve(self, case_id: int, note: str) -> bool:
        """Closes the case with the person's note. It touches nothing else. False when the case is not open."""
        with self.engine.begin() as conn:
            done = conn.execute(update(C).where(
                C.c.tenant_id == self.tenant_id, C.c.id == case_id, C.c.status == "open")
                .values(status="resolved", resolution=note, resolved_at=clock.now()).returning(C.c.id)).first()
        return done is not None

    def claim_run(self, run_date: date, mode: str, stale_after: timedelta = STALE_CLAIM) -> int | None:
        """The run row of this date, or None when another run holds it (one run per date across replicas). A claim that
        never finished (its replica died) and is older than `stale_after` is taken over, so the date is not lost."""
        now = clock.now()
        with self.engine.begin() as conn:
            got = conn.execute(insert(R).values(
                tenant_id=self.tenant_id, run_date=run_date, mode=mode, started_at=now,
            ).on_conflict_do_nothing(constraint="uq_os_consistency_runs_date").returning(R.c.id)).first()
            if got is not None:
                return got.id
            taken = conn.execute(update(R).where(
                R.c.tenant_id == self.tenant_id, R.c.run_date == run_date, R.c.finished_at.is_(None),
                R.c.started_at < now - stale_after).values(started_at=now, mode=mode).returning(R.c.id)).first()
        return taken.id if taken else None

    def finish_run(self, run_id: int, counts: dict) -> None:
        with self.engine.begin() as conn:
            conn.execute(update(R).where(R.c.tenant_id == self.tenant_id, R.c.id == run_id)
                         .values(finished_at=clock.now(), counts=counts))

    def last_run(self) -> dict | None:
        with self.engine.connect() as conn:
            r = conn.execute(select(R).where(R.c.tenant_id == self.tenant_id).order_by(R.c.run_date.desc()).limit(1)).first()
        return None if r is None else {"run_date": r.run_date, "mode": r.mode, "started_at": r.started_at,
                                       "finished_at": r.finished_at, "counts": r.counts}
