"""The Counsellor intake and the glue's sweep mark (Slice 8 spec §3). Every query is filtered by tenant. These tables
are not plan state: plans change only through the kernel (invariant 1)."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine, func, select, update
from sqlalchemy.dialects.postgresql import insert

from app.os import models

I, W = models.counsellor_intake, models.counsellor_sweep


@dataclass(frozen=True)
class Intake:
    id: int
    decision_id: str
    student_ref: str
    journey_id: str
    export: dict
    export_sha256: str
    chosen_at: datetime
    status: str  # pending | planned | revised | replaced | refused
    reason: str | None
    plan_id: int | None
    counsellor_status: str | None
    created_at: datetime
    processed_at: datetime | None


def _intake(r) -> Intake:
    return Intake(r.id, r.decision_id, r.student_ref, r.journey_id, r.export, r.export_sha256, r.chosen_at, r.status,
                  r.reason, r.plan_id, r.counsellor_status, r.created_at, r.processed_at)


class IntakeStore:
    def __init__(self, engine: Engine, tenant_id: str) -> None:
        self.engine, self.tenant_id = engine, tenant_id

    def add(self, export: dict, sha: str) -> bool:
        """Stores a submitted export as pending. False when this decision is already stored (S8-D9): the first copy
        stays, and two replicas submitting at once still give one row."""
        chosen_at = export["chosen_at"]
        with self.engine.begin() as conn:
            got = conn.execute(insert(I).values(
                tenant_id=self.tenant_id, decision_id=export["decision_id"], student_ref=export["student_ref"],
                journey_id=export["journey_id"], export=export, export_sha256=sha,
                chosen_at=datetime.fromisoformat(chosen_at) if isinstance(chosen_at, str) else chosen_at,
            ).on_conflict_do_nothing(constraint="uq_os_counsellor_intake_decision").returning(I.c.id)).first()
        return got is not None

    def get(self, decision_id: str) -> Intake | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(I).where(I.c.tenant_id == self.tenant_id, I.c.decision_id == decision_id)).first()
        return _intake(row) if row else None

    def pending(self, limit: int = 100) -> list[Intake]:
        """Pending rows per student in `chosen_at` order, so a student's newest decision is processed last."""
        with self.engine.connect() as conn:
            rows = conn.execute(select(I).where(I.c.tenant_id == self.tenant_id, I.c.status == "pending")
                                .order_by(I.c.student_ref, I.c.chosen_at, I.c.id).limit(limit)).all()
        return [_intake(r) for r in rows]

    def finish(self, intake_id: int, status: str, reason: str | None = None, plan_id: int | None = None) -> None:
        with self.engine.begin() as conn:
            conn.execute(update(I).where(I.c.tenant_id == self.tenant_id, I.c.id == intake_id).values(
                status=status, reason=reason, plan_id=plan_id, processed_at=func.now()))

    def set_counsellor_status(self, decision_id: str, status: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(update(I).where(I.c.tenant_id == self.tenant_id, I.c.decision_id == decision_id)
                         .values(counsellor_status=status))


class SweepStore:
    def __init__(self, engine: Engine, tenant_id: str) -> None:
        self.engine, self.tenant_id = engine, tenant_id

    def mark(self) -> dict | None:
        with self.engine.connect() as conn:
            return conn.execute(select(W.c.mark).where(W.c.tenant_id == self.tenant_id)).scalar()

    def set_mark(self, mark: dict) -> None:
        with self.engine.begin() as conn:
            conn.execute(insert(W).values(tenant_id=self.tenant_id, mark=mark).on_conflict_do_update(
                index_elements=[W.c.tenant_id], set_={"mark": mark, "updated_at": func.now()}))
