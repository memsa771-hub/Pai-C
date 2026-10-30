"""Slice 9a final review, fix pass: one test (or a few) per finding. Fictional data only."""
# ruff: noqa: F811  (`api` is a fixture imported from test_api_replan, so test arguments of that name redefine it)

import logging
from pathlib import Path

import pytest
import yaml
from sqlalchemy import insert, select

from app.os import clock, models
from app.os.api.queries import notice_changes, task_plan_and_template
from app.os.playbooks import PlaybookError, load_playbook
from app.os.settings import load_settings
from tests.os.test_api_replan import ME, P1, api  # noqa: F401  (api is a fixture)
from tests.os.test_rehearsal_mode import (  # noqa: F401  (real_clock is a fixture)
    _app,
    _settings,
    real_clock,
)

T = models.tasks
GERMANY = Path(__file__).parents[2] / "app" / "os" / "playbooks" / "germany_master.v1.yaml"


# ---- 1: the visa note's weeks ----------------------------------------------------------------------------------------

def _germany_with_visa_lead(tmp_path: Path, days: int) -> Path:
    data = yaml.safe_load(GERMANY.read_text())
    data["constants"]["visa_before_semester_days"]["value"] = days
    p = tmp_path / GERMANY.name
    p.write_text(yaml.safe_dump(data, sort_keys=False))
    return p


def test_note_with_weeks_needs_whole_weeks(tmp_path):
    """A note that says "{weeks} weeks" would show a wrong figure for 40 days (5, not 5.7): the playbook is refused."""
    with pytest.raises(PlaybookError, match="whole weeks"):
        load_playbook(_germany_with_visa_lead(tmp_path, 40))
    assert load_playbook(_germany_with_visa_lead(tmp_path, 49))  # 7 weeks loads


# ---- 2: leftover rehearsal data with rehearsal off -------------------------------------------------------------------

def test_startup_refuses_rehearsal_clock_row_when_off(engine, clean, os_db):
    """A clock row left for the tenant means the database holds rehearsal data (dated in the future): with rehearsal
    off it must not become a pilot database, so startup stops with a clear error (the API path too)."""
    from app.os.rehearsal.store import RehearsalDataLeft, install_clock

    with engine.begin() as conn:
        conn.execute(insert(models.rehearsal_clock).values(tenant_id="pai", offset_seconds=30 * 86400))
    with pytest.raises(RehearsalDataLeft, match="os_rehearsal_clock"):
        install_clock(_settings(os_db, False), engine)
    with pytest.raises(RehearsalDataLeft):
        _app(engine, _settings(os_db, False))
    install_clock(_settings(os_db, True), engine)  # rehearsal on: it is that mode's own data


def test_another_tenants_clock_row_does_not_stop_startup(engine, clean, os_db):
    from app.os.rehearsal.store import install_clock

    with engine.begin() as conn:
        conn.execute(insert(models.rehearsal_clock).values(tenant_id="other", offset_seconds=3 * 86400))
    install_clock(_settings(os_db, False), engine)
    assert clock.now()


# ---- 3: two inbox loads at once ------------------------------------------------------------------------------------

def test_empty_notice_closed_by_another_load_is_quiet(api, monkeypatch, caplog):
    """While one inbox load closes an empty plan-update notice, another request moves it on (here: a revision
    cancels it). The kernel's IllegalTransition is expected and is not logged as an error; the notice is no longer
    the student's to see, so it is not listed."""
    with api.engine.begin() as conn:
        conn.execute(insert(models.plan_revisions).values(tenant_id="pai", plan_id=api.plan_id, number=93,
                                                          cause="fact:y", diff={"added": [], "removed": [],
                                                                                "changed": []}))
        conn.execute(insert(T).values(
            tenant_id="pai", plan_id=api.plan_id, instance_key="plan_updated@r93", template_key="plan_updated",
            task_type="student.act", kind="student", inbox_kind="act", title="Your plan was updated",
            state="waiting_student", due_tz="UTC", playbook_version=1, result={"revision": 93, "cause": "fact:y"}))
    real = api.svc.kernel.complete_student_task

    def racing(task_id, student, payload):
        with api.engine.begin() as conn:  # the other request got there first (the kernel's write, simulated)
            conn.execute(T.update().where(T.c.id == task_id).values(state="cancelled"))
        return real(task_id, student, payload)

    monkeypatch.setattr(api.svc.kernel, "complete_student_task", racing)
    with caplog.at_level(logging.WARNING):
        r = api.get("/v1/os/inbox", headers=ME)
    assert r.status_code == 200
    assert all(i["instance_key"] != "plan_updated@r93" for i in r.json()["items"])
    assert not [rec for rec in caplog.records if rec.levelno >= logging.WARNING and rec.name.startswith("app.os")]


# ---- 4: admitted follows the latest answer ---------------------------------------------------------------------------

def test_admitted_follows_the_latest_answer(api):
    """A programme that said "admitted" and later "rejected" is not admitted any more, as in `answers`."""
    from app.os.packs.visa import admitted, answers

    with api.engine.begin() as conn:
        first = conn.execute(select(T).where(T.c.plan_id == api.plan_id,
                                             T.c.instance_key == f"admission_result@{P1}")).one()
        conn.execute(T.update().where(T.c.id == first.id).values(state="done", result={"choice": "admitted"}))
        conn.execute(insert(T).values(
            tenant_id="pai", plan_id=api.plan_id, instance_key=f"admission_result@{P1}#2",
            template_key="admission_result", task_type=first.task_type, kind="student", inbox_kind=first.inbox_kind,
            title=first.title, programme_ref=P1, state="done", due_tz="UTC", playbook_version=1,
            result={"choice": "rejected"}))
    assert answers(api.engine, "pai", api.plan_id) == {P1: "rejected"}
    assert admitted(api.engine, "pai", api.plan_id) == []


# ---- 5: tenant filters -----------------------------------------------------------------------------------------------

def test_notice_changes_and_task_lookup_keep_to_the_tenant(api):
    with api.engine.begin() as conn:
        key, tid = conn.execute(select(T.c.instance_key, T.c.id).where(
            T.c.plan_id == api.plan_id, T.c.kind == "student").order_by(T.c.id).limit(1)).one()
        conn.execute(insert(models.plan_revisions).values(tenant_id="pai", plan_id=api.plan_id, number=94,
                                                          cause="fact:y", diff={"added": [key]}))
    with api.engine.connect() as conn:
        assert [c["instance_key"] for c in notice_changes(conn, "pai", api.plan_id, {"revision": 94})] == [key]
        assert notice_changes(conn, "other", api.plan_id, {"revision": 94}) == []
    assert task_plan_and_template(api.engine, "pai", tid)[0] == api.plan_id
    assert task_plan_and_template(api.engine, "other", tid) is None


# ---- 6: OS_EMAIL_SENDER spelling -------------------------------------------------------------------------------------

@pytest.mark.parametrize("raw,want", [("Resend", "resend"), (" resend ", "resend"), ("LOG", "log"), ("  ", "log")])
def test_email_sender_normalised(raw, want):
    env = {"DATABASE_URL": "x", "OS_EMAIL_SENDER": raw, "OS_RESEND_API_KEY": "fictional",
           "OS_EMAIL_FROM": "os@example.org"}
    assert load_settings(env).email_sender == want


def test_normalised_resend_still_needs_its_settings():
    with pytest.raises(ValueError, match="OS_RESEND_API_KEY"):
        load_settings({"DATABASE_URL": "x", "OS_EMAIL_SENDER": " Resend "})
