"""The stored rehearsal offset, one row per tenant, and the switch that makes the shared clock read it."""

import logging
from datetime import timedelta

from sqlalchemy import Engine, func, select
from sqlalchemy.dialects.postgresql import insert

from app.os import clock, models
from app.os.settings import OsSettings

log = logging.getLogger("app.os.rehearsal")

R = models.rehearsal_clock
WARNING = ("REHEARSAL MODE is on (OS_REHEARSAL): the OS clock is moved by the stored offset, the worker runs no "
           "scheduled jobs (only admin tick), and the admin advance/tick calls are open. Never run a pilot like this.")


class ClockStore:
    def __init__(self, engine: Engine, tenant_id: str):
        self.engine = engine
        self.tenant_id = tenant_id

    def offset(self) -> timedelta:
        """How far this tenant's clock is moved; no row means not moved. Read on every clock.now()."""
        with self.engine.connect() as conn:
            seconds = conn.execute(select(R.c.offset_seconds).where(R.c.tenant_id == self.tenant_id)).scalar()
        return timedelta(seconds=seconds or 0)

    def advance(self, days: int) -> timedelta:
        """Moves the clock forward by `days` in one atomic statement, so two calls at once both count. Returns the new
        offset."""
        seconds = int(days) * 86400
        stmt = insert(R).values(tenant_id=self.tenant_id, offset_seconds=seconds)
        stmt = stmt.on_conflict_do_update(
            index_elements=[R.c.tenant_id],
            set_={"offset_seconds": R.c.offset_seconds + seconds, "updated_at": func.now()},
        ).returning(R.c.offset_seconds)
        with self.engine.begin() as conn:
            return timedelta(seconds=conn.execute(stmt).scalar_one())


def install_clock(settings: OsSettings, engine: Engine) -> None:
    """Rehearsal on: the shared clock reads the stored offset (and a loud warning is logged). Off: real time, whatever
    row is left in the table."""
    if settings.rehearsal:
        log.warning(WARNING)
        clock.configure(ClockStore(engine, settings.tenant_id).offset)
    else:
        clock.configure(None)
