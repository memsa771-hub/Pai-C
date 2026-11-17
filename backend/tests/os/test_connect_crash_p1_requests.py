# ruff: noqa: F811, SIM117
"""P1-T10 Task D2 (R-12), the T8 request-answer channel. The matrix is in `test_connect_crash_p1.py`; this file has its
own module because the T8 world fixtures share their names with the fixtures of the other channels.

Kill points: (a) the answer is written to the Vault and committed, then the OS close raises (the process dies before the
plan is recomputed): the hourly recompile closes the step, one request is answered, and the Vault was written once;
(b) the student answers again after that crash: no second Vault write. Fictional student and marks."""

from unittest.mock import patch

import pytest
from sqlalchemy import func, select

from app import pai_os_bridge as bridge
from app.models import MemoryCandidate, OsOutbox
from app.os import models
from app.os.requests.refresh import refresh
from tests.os.connect_check import assert_consistent
from tests.os.test_which_is_right import (  # noqa: F401 - fixtures
    WHICH,
    books,
    conflict,
    education,
    world,
)

pytestmark = [pytest.mark.req("R-12"), pytest.mark.chaos]


def candidates(world) -> int:
    with world.who.factory() as db:
        return db.scalar(select(func.count()).select_from(MemoryCandidate))


def vault_events(world) -> int:
    with world.who.factory() as db:
        return db.scalar(select(func.count()).select_from(OsOutbox).where(OsOutbox.kind == "vault_event"))


def answered_rows(world) -> int:
    with world.engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(models.student_requests).where(
            models.student_requests.c.status == "answered")).scalar_one()


def crash_after_the_vault_write(world, conflict):
    """The answer reaches the Vault (committed), then the process dies before the OS recomputes the plan."""
    with patch("app.os.api.router.refresh", side_effect=RuntimeError("the process stopped")):
        with pytest.raises(RuntimeError):
            world.answer(conflict.asked["id"], "proposed")


def closed_once(world, conflict, before_candidates):
    assert world.row(conflict.asked["id"]).status == "answered" and answered_rows(world) == 1
    done = [k for k, s in world.steps(conflict.plan_id).items() if k.startswith(WHICH) and s == "done"]
    assert len(done) == 1 and candidates(world) == before_candidates + 1
    assert refresh(world.svc, world.ws, "test") == 0 and answered_rows(world) == 1  # a repeat changes nothing
    assert_consistent(world.who.factory, handoff=True)


def test_a_crash_after_the_vault_write_is_closed_by_the_vault_event(world, conflict):
    before_candidates, before_events = candidates(world), vault_events(world)
    crash_after_the_vault_write(world, conflict)
    with world.who.factory() as db:
        assert education(db, world.ws)[0]["result"]["marks_obtained"] == 760  # the Vault holds the answer
        assert world.card(db).status == "resolved"
    assert candidates(world) == before_candidates + 1 and world.row(conflict.asked["id"]).status == "open"
    assert vault_events(world) > before_events  # the Vault write queued its events in the same transaction
    with world.who.factory() as db:
        assert bridge.sweep_once(db)["submitted"] >= 1  # the events reach the OS, which recomputes the plan
        assert bridge.sweep_once(db)["submitted"] == 0
    closed_once(world, conflict, before_candidates)


def test_a_crash_after_the_vault_write_is_closed_by_the_recompile(world, conflict):
    before_candidates = candidates(world)
    crash_after_the_vault_write(world, conflict)
    assert world.row(conflict.asked["id"]).status == "open"  # the OS has heard nothing
    assert refresh(world.svc, world.ws, "test") >= 1  # the hourly recompile notices the resolved card
    closed_once(world, conflict, before_candidates)


def test_a_repeat_answer_after_the_crash_writes_the_vault_once(world, conflict):
    before, events = candidates(world), vault_events(world)
    crash_after_the_vault_write(world, conflict)
    assert candidates(world) == before + 1 and vault_events(world) > events
    events = vault_events(world)
    again = world.answer(conflict.asked["id"], "proposed")  # the student tries again: the Vault says "gone"
    assert again.status_code == 200 and again.json() == {"status": "answered"}
    assert candidates(world) == before + 1 and vault_events(world) == events and answered_rows(world) == 1
    third = world.answer(conflict.asked["id"], "proposed")
    assert third.status_code == 409 and third.json()["detail"] == "already_answered"
    assert candidates(world) == before + 1 and answered_rows(world) == 1
    with world.who.factory() as db:
        (row,) = education(db, world.ws)
        assert row["result"]["marks_obtained"] == 760
    assert_consistent(world.who.factory, handoff=True)
