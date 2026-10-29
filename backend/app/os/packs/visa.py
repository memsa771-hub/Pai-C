"""The visa file's choice (Slice 6b spec S6b-D8): the one programme the visa file is for, and the amount other proof
(a scholarship, a sponsor) covers. One row per student. `preselect` proposes the programme the student told us
admitted them, when only one did."""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import Engine, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.os import models
from app.os.kernel.states import TaskState

V, T = models.visa_choices, models.tasks
VISA_ITEMS = ":visa"  # the os_pack_items key of the visa file's ticks and added items (no programme ref has a colon)
ADMISSION_TASK = "admission_result"
ADMITTED = "admitted"  # the admission_result payload: {"choice": "admitted" | "rejected"}
REJECTED = "rejected"


@dataclass(frozen=True)
class VisaChoice:
    programme_ref: str | None
    reduction: float


class VisaChoiceStore:
    def __init__(self, engine: Engine, tenant_id: str):
        self.engine, self.tenant_id = engine, tenant_id

    def get(self, student_ref: str) -> VisaChoice | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(V.c.programme_ref, V.c.reduction).where(
                V.c.tenant_id == self.tenant_id, V.c.student_ref == student_ref)).first()
        return None if row is None else VisaChoice(row.programme_ref, float(row.reduction))

    def _upsert(self, student_ref: str, **values) -> None:
        stmt = pg_insert(V).values(tenant_id=self.tenant_id, student_ref=student_ref, **values)
        with self.engine.begin() as conn:
            conn.execute(stmt.on_conflict_do_update(constraint="uq_os_visa_choices",
                                                    set_={**values, "updated_at": func.now()}))

    def set_programme(self, student_ref: str, programme_ref: str) -> None:
        self._upsert(student_ref, programme_ref=programme_ref)

    def set_reduction(self, student_ref: str, amount: float) -> None:
        amount = Decimal(str(amount))
        if not amount.is_finite() or amount < 0:
            raise ValueError("the amount must be 0 or more")
        self._upsert(student_ref, reduction=amount)


def answers(engine: Engine, tenant_id: str, plan_id: int) -> dict[str, str]:
    """Programme -> the student's admission answer ("admitted" or "rejected"), from the done `admission_result`
    tasks; the latest answer of a programme wins."""
    with engine.connect() as conn:
        rows = conn.execute(select(T.c.programme_ref, T.c.result).where(
            T.c.tenant_id == tenant_id, T.c.plan_id == plan_id, T.c.template_key == ADMISSION_TASK,
            T.c.state == TaskState.DONE).order_by(T.c.id)).all()
    return {r.programme_ref: r.result["choice"] for r in rows
            if r.programme_ref and isinstance(r.result, dict) and r.result.get("choice") in (ADMITTED, REJECTED)}


def admitted(engine: Engine, tenant_id: str, plan_id: int) -> list[str]:
    """Every programme of a done `admission_result` task whose result is {"choice": "admitted"} (what the inbox sends
    for that task), in task order, each once."""
    with engine.connect() as conn:
        rows = conn.execute(select(T.c.programme_ref, T.c.result).where(
            T.c.tenant_id == tenant_id, T.c.plan_id == plan_id, T.c.template_key == ADMISSION_TASK,
            T.c.state == TaskState.DONE).order_by(T.c.id)).all()
    return list(dict.fromkeys(r.programme_ref for r in rows
                              if r.programme_ref and isinstance(r.result, dict) and r.result.get("choice") == ADMITTED))


def preselect(engine: Engine, tenant_id: str, plan_id: int, among: tuple[str, ...] | None = None) -> str | None:
    """The one admitted programme (of `among`, when given), else None: with two admissions the student chooses
    which one the visa file is for; nothing is chosen for them (Slice 9 Task 11, `walk:S1:visa_admitted_label_one_only`)."""
    found = [r for r in admitted(engine, tenant_id, plan_id) if among is None or r in among]
    return found[0] if len(found) == 1 else None
