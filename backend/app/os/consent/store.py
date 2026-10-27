"""Who agreed to which terms version (`os_consents`, one row per tenant, student and version)."""

from sqlalchemy import Engine, select
from sqlalchemy.dialects.postgresql import insert

from app.os import clock, models

C = models.consents


class ConsentStore:
    def __init__(self, engine: Engine, tenant_id: str):
        self.engine = engine
        self.tenant_id = tenant_id

    def agree(self, student_ref: str, version: int) -> None:
        """Idempotent: agreeing again keeps the first row and its time."""
        stmt = insert(C).values(tenant_id=self.tenant_id, student_ref=student_ref, terms_version=version,
                                agreed_at=clock.now()).on_conflict_do_nothing(
            index_elements=[C.c.tenant_id, C.c.student_ref, C.c.terms_version])
        with self.engine.begin() as conn:
            conn.execute(stmt)

    def has(self, student_ref: str, version: int) -> bool:
        with self.engine.connect() as conn:
            return conn.execute(select(C.c.id).where(
                C.c.tenant_id == self.tenant_id, C.c.student_ref == student_ref,
                C.c.terms_version == version)).first() is not None
