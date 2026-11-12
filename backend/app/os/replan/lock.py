"""The per-plan replan lock (a session advisory lock). One replan, answer or builder request per plan at a time."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, text

LOCK_CLASS = 7007  # pg_advisory_lock(LOCK_CLASS, plan id)


@contextmanager
def plan_lock(engine: Engine, plan_id: int) -> Iterator[None]:
    """Holds the plan's lock for the block (final review I2, I5)."""
    with engine.connect() as conn:
        conn.execute(text("SELECT pg_advisory_lock(:c, :p)"), {"c": LOCK_CLASS, "p": plan_id})
        conn.commit()
        try:
            yield
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(:c, :p)"), {"c": LOCK_CLASS, "p": plan_id})
            conn.commit()
