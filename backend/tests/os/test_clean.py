"""The `clean` fixture survives a deadlock with work a previous test left running (the CI flake on #142: a DBOS
thread from test_approve_200_completes_task still held a table when the next test's TRUNCATE ran)."""

import threading
import time

from sqlalchemy import text

from tests.os.conftest import os_table_names, truncate_os_tables


def _truncate_waits_on(engine, table: str) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        with engine.connect() as conn:
            if conn.execute(text("SELECT count(*) FROM pg_locks WHERE NOT granted AND mode = 'AccessExclusiveLock' "
                                 "AND relation = to_regclass(:t)"), {"t": f"os.{table}"}).scalar_one():
                return
        time.sleep(0.05)
    raise TimeoutError("the TRUNCATE never waited")


def test_truncate_survives_losing_a_deadlock(engine):
    with engine.connect() as conn:
        names = os_table_names(conn)
    first, last = names[0], names[-1]
    holding, errors = threading.Event(), []

    def straggler() -> None:  # like a leftover worker thread: holds the last table, then reads the first one
        try:
            with engine.begin() as conn:
                conn.execute(text(f"LOCK TABLE os.{last} IN ACCESS SHARE MODE"))
                holding.set()
                _truncate_waits_on(engine, last)  # the TRUNCATE has locked `first` and now waits for `last`
                conn.execute(text(f"LOCK TABLE os.{first} IN ACCESS SHARE MODE"))
        except Exception as e:  # noqa: BLE001 - reported by the assert below
            errors.append(e)

    thread = threading.Thread(target=straggler)
    thread.start()
    assert holding.wait(10)
    try:
        truncate_os_tables(engine)
    finally:
        thread.join(30)
    assert errors == []
