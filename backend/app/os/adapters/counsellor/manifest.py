"""The Counsellor module's manifest (spec §2.6, S8-D2). It owns no task types; its `os_modules` row is the switch.
`os_0013` inserts the row disabled, and a missing row also means off: real students never reach it by accident."""

from sqlalchemy import Engine, select

from app.os import models

NAME = "counsellor"
TASK_TYPES: tuple[str, ...] = ()
EVENTS = ("counsellor_intake",)
FALLBACK = "standalone"


def is_enabled(engine: Engine, tenant_id: str) -> bool:
    M = models.modules
    with engine.connect() as conn:
        enabled = conn.execute(select(M.c.enabled).where(M.c.module == NAME, M.c.tenant_id == tenant_id)).scalar()
    return enabled is True
