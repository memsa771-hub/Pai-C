"""The stored rehearsal offset, one row per tenant, and the switch that makes the shared clock read it."""

import logging
from datetime import date, timedelta

from sqlalchemy import Date, Engine, cast, exists, func, literal, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import OperationalError

from app.os import clock, models
from app.os.settings import OsSettings

log = logging.getLogger("app.os.rehearsal")

R = models.rehearsal_clock
WARNING = ("REHEARSAL MODE is on (OS_REHEARSAL): the OS clock is moved by the stored offset, the worker runs no "
           "scheduled jobs (only admin tick), and the admin advance/tick calls are open. Never run a pilot like this.")


class RehearsalDataLeft(RuntimeError):
    """Rehearsal is off but the tenant has a rehearsal clock row: the database holds rehearsal data (dated by the moved
    clock, often in the future), which must never become a pilot database. The OS must not start."""


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

    def start(self, day: date) -> timedelta | None:
        """Sets the clock once, on a clean rehearsal clock, so that today is `day`: whole days from the real UTC date,
        which may be negative (a day already past). Clean means no clock row yet and no plan of this tenant (plans that
        ran at real time would have timestamps after a past start). Returns the new offset, or None when refused (time
        never goes back once set). One atomic statement: two starts at once set it once. Seeded facts do not count:
        they are loaded before the start.

        The real date is the database's (`now()` in UTC), so this module reads no time itself (clock rule)."""
        real_today = cast(func.timezone("UTC", func.now()), Date)
        seconds = (cast(literal(day.isoformat()), Date) - real_today) * 86400
        no_plans = ~exists().where(models.plans.c.tenant_id == self.tenant_id)  # nothing has run at real time yet
        rows = select(literal(self.tenant_id), seconds).where(no_plans)
        stmt = insert(R).from_select([R.c.tenant_id, R.c.offset_seconds], rows)
        stmt = stmt.on_conflict_do_nothing(index_elements=[R.c.tenant_id]).returning(R.c.offset_seconds)
        with self.engine.begin() as conn:
            got = conn.execute(stmt).scalar()
        return None if got is None else timedelta(seconds=got)


def install_clock(settings: OsSettings, engine: Engine) -> None:
    """Rehearsal on: the shared clock reads the stored offset (and a loud warning is logged). Off: real time, and
    startup is refused (RehearsalDataLeft) while the tenant still has a clock row, so rehearsal data never becomes a
    pilot database (an unreachable database is logged, not refused: the worker cannot start without it). It
    overwrites the module-global clock, so a test that sets its own offset does so after building services or the
    worker."""
    if settings.rehearsal:
        log.warning(WARNING)
        clock.configure(ClockStore(engine, settings.tenant_id).offset)
        return
    try:
        with engine.connect() as conn:
            left = conn.execute(select(exists().where(R.c.tenant_id == settings.tenant_id))).scalar()
    except OperationalError:  # no database yet (mounting the API does not need one): nothing to check against
        log.warning("could not check os_rehearsal_clock for leftover rehearsal data: the database is not reachable")
        left = False
    if left:
        raise RehearsalDataLeft(
            f"OS_REHEARSAL is off but os_rehearsal_clock has a row for tenant '{settings.tenant_id}': this database "
            "holds rehearsal data and must not run as a pilot. Use a clean database, or turn rehearsal mode on.")
    clock.configure(None)
