"""The intake rows (P2-D23). `current` is reached only with a recorded gate pass (R-66); the gate itself is T9's."""

import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine, and_, select, update
from sqlalchemy.exc import IntegrityError

from app.os import clock, models
from app.os.intakes.terms import check_term

T = models.intakes
_CODE = re.compile(r"[a-z][a-z0-9_]*")
# planned -> open -> current -> closed; an open intake may close without ever being current
_NEXT = {"planned": ("open", "closed"), "open": ("current", "closed"), "current": ("closed",), "closed": ()}


class IntakeError(ValueError):
    pass


@dataclass(frozen=True)
class Intake:
    id: int
    region: str
    family: str
    term: str
    year: int
    state: str
    gate_passed_at: datetime | None
    opened_from_id: int | None


def _intake(r) -> Intake:
    return Intake(r.id, r.region, r.family, r.term, r.year, r.state, r.gate_passed_at, r.opened_from_id)


class IntakeStore:
    def __init__(self, engine: Engine, tenant_id: str) -> None:
        self.engine = engine
        self.tenant_id = tenant_id

    def create(self, region: str, family: str, term: str, year: int, *, state: str = "planned",
               opened_from_id: int | None = None, extra_terms: tuple[str, ...] = ()) -> Intake:
        """A new intake row. Two intakes in one year are two rows with different terms (R-62)."""
        for label, code in (("region", region), ("family", family)):
            if not _CODE.fullmatch(code):
                raise IntakeError(f"{label} '{code}' must be a lowercase code")
        check_term(term, extra_terms)
        if state not in ("planned", "open"):
            raise IntakeError("an intake starts planned or open; `current` needs the gate")
        try:
            with self.engine.begin() as conn:
                row = conn.execute(T.insert().values(
                    tenant_id=self.tenant_id, region=region, family=family, term=term, year=year, state=state,
                    opened_from_id=opened_from_id).returning(T)).one()
        except IntegrityError:
            raise IntakeError(f"intake {region}/{family}/{term}/{year} already exists") from None
        return _intake(row)

    def get(self, region: str, family: str, term: str, year: int) -> Intake | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(T).where(
                T.c.tenant_id == self.tenant_id, T.c.region == region, T.c.family == family, T.c.term == term,
                T.c.year == year)).first()
        return _intake(row) if row else None

    def by_id(self, intake_id: int) -> Intake | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(T).where(T.c.tenant_id == self.tenant_id, T.c.id == intake_id)).first()
        return _intake(row) if row else None

    def list_intakes(self, *, region: str | None = None, family: str | None = None, state: str | None = None) -> list[Intake]:
        q = select(T).where(T.c.tenant_id == self.tenant_id)
        for col, val in ((T.c.region, region), (T.c.family, family), (T.c.state, state)):
            if val is not None:
                q = q.where(col == val)
        with self.engine.connect() as conn:
            return [_intake(r) for r in conn.execute(q.order_by(T.c.year, T.c.term, T.c.id)).all()]

    def previous(self, region: str, family: str, term: str, year: int) -> Intake | None:
        """The newest earlier intake of the same region, family and term."""
        with self.engine.connect() as conn:
            row = conn.execute(select(T).where(
                T.c.tenant_id == self.tenant_id, T.c.region == region, T.c.family == family, T.c.term == term,
                T.c.year < year).order_by(T.c.year.desc()).limit(1)).first()
        return _intake(row) if row else None

    def set_state(self, intake_id: int, state: str, *, gate_passed_at: datetime | None = None) -> Intake:
        """Moves an intake one step. `current` needs `gate_passed_at` (R-66): only the coverage gate (T9) passes it."""
        current = self.by_id(intake_id)
        if current is None:
            raise IntakeError(f"no intake {intake_id}")
        if state not in _NEXT[current.state]:
            raise IntakeError(f"an intake cannot go from {current.state} to {state}")
        values: dict = {"state": state, "updated_at": clock.now()}
        if state == "current":
            if gate_passed_at is None:
                raise IntakeError("an intake becomes current only through the coverage gate (R-66)")
            values["gate_passed_at"] = gate_passed_at
        elif gate_passed_at is not None:
            raise IntakeError("only `current` records a gate pass")
        with self.engine.begin() as conn:
            row = conn.execute(update(T).where(T.c.tenant_id == self.tenant_id, T.c.id == intake_id,
                                               T.c.state == current.state).values(**values).returning(T)).first()
        if row is None:
            raise IntakeError(f"intake {intake_id} changed while it was being moved")
        return _intake(row)

    def plannable(self, term: str, year: int) -> bool:
        """R-63: a student may plan for any open or current intake. An intake nobody registered is not restricted
        (today's behaviour); one that is registered only as planned or closed is not plannable."""
        states = self._states(term, year)
        return not states or bool(states & {"open", "current"})

    def fallback_applies(self, term: str, year: int) -> bool:
        """P2-D24: plans of this intake read the previous year's labelled facts while the intake is open and no
        region of it is current yet. No registered intake: no fallback (today's behaviour)."""
        states = self._states(term, year)
        return "open" in states and "current" not in states

    def _states(self, term: str, year: int) -> set[str]:
        with self.engine.connect() as conn:
            return set(conn.execute(select(T.c.state).where(and_(
                T.c.tenant_id == self.tenant_id, T.c.term == term, T.c.year == year))).scalars().all())
