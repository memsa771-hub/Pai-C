"""Slice 9b: usable pilot email (handoff 9a §7, entry condition 3). The recipient lookup port, real templates, and
Resend configuration errors that stop and alert. httpx.MockTransport only; fictional addresses only."""

import json
import logging
import pickle
from datetime import date
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.os import models, ports
from app.os.outbox import Outbox
from app.os.outbox.outbox import OutboxMessage
from app.os.outbox.senders import (
    RecipientLookupUnavailable,
    Refused,
    ResendSender,
    make_sender,
)
from app.os.outbox.templates import (
    INBOX_SLOTS,
    TemplateError,
    Unrenderable,
    format_due,
    load_templates,
)
from app.os.ports import recipients
from app.os.settings import load_settings

KEY = "re_test_dummy_9b"
ADDRESS = "student@example.test"
STUDENT = "0b6f1c1e-0000-4000-8000-000000000001"  # a workspace-like ref (fictional)
TOKEN = "test-admin-token"
ADMIN = {"X-OS-Admin-Token": TOKEN}
FAKE_PLAYBOOKS = Path(__file__).parent / "playbooks"
BOOK = {STUDENT: ADDRESS, "stu-other": "other@example.test", "stu-bad": "not an address"}


def fake_lookup(student_ref: str) -> str | None:  # OS_RECIPIENT_LOOKUP=tests.os.test_email_pilot:fake_lookup
    return BOOK.get(student_ref)


not_callable = 42


def settings(allow=ADDRESS, **extra):
    env = {"DATABASE_URL": "postgresql://x/y", "OS_EMAIL_SENDER": "resend", "OS_RESEND_API_KEY": KEY,
           "OS_EMAIL_FROM": "pai@example.test", "OS_EMAIL_ALLOWLIST": allow}
    env.update(extra)
    return load_settings(env)


def client(handler):
    calls = []

    def wrapped(request):
        calls.append(request)
        return handler(request)

    return httpx.Client(transport=httpx.MockTransport(wrapped)), calls


def ok(request):
    return httpx.Response(200, json={"id": "abc"})


def reminder(slot="d:2027-07-10", title="Upload your passport copy"):
    return {"task_id": 7, "title": title, "due_at": "2027-07-16T21:59:00+00:00", "due_tz": "Europe/Berlin",
            "slot": slot}


def sender(http, lookup=fake_lookup, **extra):
    return ResendSender(settings(**extra), http, lookup)


def all_text(engine) -> str:
    with engine.connect() as conn:
        rows = [*conn.execute(select(models.outbox)).all(), *conn.execute(select(models.events)).all()]
    return json.dumps([list(map(str, r)) for r in rows])


def events_of(engine, type_):
    with engine.connect() as conn:
        return conn.execute(select(models.events).where(models.events.c.type == type_)
                            .order_by(models.events.c.id)).all()


# ---- 1. the port ----------------------------------------------------------------------------------------------------

def test_load_lookup_from_spec():
    assert recipients.load("tests.os.test_email_pilot:fake_lookup")(STUDENT) == ADDRESS
    for bad in ("", "no_colon", "tests.os.test_email_pilot:missing", "tests.os.test_email_pilot:not_callable",
                "no.such.module_9b:fn"):
        with pytest.raises(recipients.RecipientLookupError):
            recipients.load(bad)


def test_worker_lookup_from_settings():
    assert recipients.from_settings(load_settings({"DATABASE_URL": "x"})) is None  # log sender: nothing looked up
    got = recipients.from_settings(settings(OS_RECIPIENT_LOOKUP="tests.os.test_email_pilot:fake_lookup"))
    assert got(STUDENT) == ADDRESS  # pytest may import this file under another module name
    with pytest.raises(recipients.RecipientLookupError, match="OS_RECIPIENT_LOOKUP"):
        recipients.from_settings(settings())  # resend without a lookup: refuse to start


def test_worker_refuses_to_start_with_resend_and_no_lookup(monkeypatch, capsys):
    from app.os.runner import worker

    for k, v in {"OS_DATABASE_URL": "postgresql://x/y", "OS_WORKER_ID": "w-9b", "OS_EMAIL_SENDER": "resend",
                 "OS_RESEND_API_KEY": KEY, "OS_EMAIL_FROM": "pai@example.test"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("OS_RECIPIENT_LOOKUP", raising=False)
    monkeypatch.setattr(worker, "build", lambda s: pytest.fail("build must not run"))
    assert worker.main() == 2
    err = capsys.readouterr().err
    assert "OS_RECIPIENT_LOOKUP" in err and KEY not in err


def test_make_sender_resend_needs_a_lookup():
    with pytest.raises(ValueError, match="OS_RECIPIENT_LOOKUP"):
        make_sender(settings(), None)
    assert isinstance(make_sender(settings(), None, lookup=fake_lookup), ResendSender)


def test_ports_configure_sets_the_lookup():
    try:
        ports.configure(None, recipient_lookup=fake_lookup)
        assert recipients.current() is fake_lookup
    finally:
        ports.configure(None)
    assert recipients.current() is None


# ---- 2. resolve at send time -----------------------------------------------------------------------------------------

def test_address_is_resolved_at_send_time_and_never_stored(engine, clean, caplog):
    http, calls = client(ok)
    box = Outbox(engine, "pai")
    box.add("k1", "email", STUDENT, "inbox_reminder", reminder())
    with caplog.at_level(logging.DEBUG):
        assert box.deliver(sender(http)) == 1
    (req,) = calls
    assert json.loads(req.content)["to"] == [ADDRESS]
    with engine.connect() as conn:
        row = conn.execute(select(models.outbox)).one()
    assert row.status == "sent" and row.recipient == STUDENT
    assert ADDRESS not in all_text(engine) and "example.test" not in caplog.text


def test_no_address_is_blocked_with_a_reason(engine, clean):
    http, calls = client(ok)
    box = Outbox(engine, "pai")
    box.add("k1", "email", "stu-unknown", "inbox_reminder", reminder())
    assert box.deliver(sender(http)) == 0
    assert calls == []
    with engine.connect() as conn:
        assert conn.execute(select(models.outbox.c.status)).scalar_one() == "blocked"
    (ev,) = events_of(engine, "email_blocked")
    assert ev.payload["reason"] == "no_address" and ev.payload["idempotency_key"] == "k1" and ev.plan_id is None


@pytest.mark.parametrize("found", ["", "   ", None])
def test_blank_address_is_no_address(engine, clean, found):
    http, calls = client(ok)
    box = Outbox(engine, "pai")
    box.add("k1", "email", STUDENT, "inbox_reminder", reminder())
    box.deliver(ResendSender(settings(), http, lambda ref: found))
    assert calls == [] and events_of(engine, "email_blocked")[0].payload["reason"] == "no_address"


def test_allowlist_is_checked_against_the_resolved_address(engine, clean):
    http, calls = client(ok)
    box = Outbox(engine, "pai")
    box.add("k1", "email", "stu-other", "inbox_reminder", reminder())
    box.add("k2", "email", ADDRESS, "inbox_reminder", reminder())  # a raw address as ref: looked up, not trusted
    box.deliver(sender(http))
    assert calls == []
    reasons = [e.payload["reason"] for e in events_of(engine, "email_blocked")]
    assert reasons == ["not_on_allowlist", "no_address"]
    assert "other@example.test" not in all_text(engine)


def test_invalid_address_is_blocked_not_sent(engine, clean):
    http, calls = client(ok)
    box = Outbox(engine, "pai")
    box.add("k1", "email", "stu-bad", "inbox_reminder", reminder())
    box.deliver(sender(http, allow=f"{ADDRESS},not an address"))
    assert calls == [] and events_of(engine, "email_blocked")[0].payload["reason"] == "invalid_address"


def test_lookup_error_is_temporary_and_leaves_the_row_pending(engine, clean):
    http, calls = client(ok)

    def broken(ref):
        raise ConnectionError(f"database down while looking up {ADDRESS}")

    box = Outbox(engine, "pai")
    box.add("k1", "email", STUDENT, "inbox_reminder", reminder())
    with pytest.raises(RecipientLookupUnavailable) as exc:
        box.deliver(ResendSender(settings(), http, broken))
    e = exc.value
    assert e.__cause__ is None and e.__context__ is None
    assert ADDRESS not in str(e) and ADDRESS.encode() not in pickle.dumps(e) and "ConnectionError" in str(e)
    assert calls == []
    with engine.connect() as conn:
        assert conn.execute(select(models.outbox.c.status)).scalar_one() == "pending"


# ---- 3. templates ----------------------------------------------------------------------------------------------------

def test_due_date_in_the_tasks_own_time_zone():
    assert format_due("2027-07-16T21:59:00+00:00", "Europe/Berlin") == "Friday 16 July 2027, 23:59 (Europe/Berlin)"
    assert format_due("2027-01-04T10:05:00+00:00", None) == "Monday 4 January 2027, 10:05 (UTC)"
    with pytest.raises(Unrenderable):
        format_due("2027-07-16T21:59:00+00:00", "Mars/Olympus")


@pytest.mark.parametrize("slot", [f"{s}:x" for s in INBOX_SLOTS])
@pytest.mark.parametrize("app_url", [None, "https://pai.example.test/"])
def test_every_inbox_reminder_renders(slot, app_url):
    t = load_templates()
    msg = OutboxMessage(1, "k", "email", STUDENT, "inbox_reminder", reminder(slot=slot))
    subject, body = t.render(msg, app_url)
    assert "Upload your passport copy" in subject and "\n" not in subject
    assert "Friday 16 July 2027, 23:59 (Europe/Berlin)" in body and "Upload your passport copy" in body
    assert body.startswith("Hello") and "because" in body.lower() and "{" not in body + subject
    link = f"https://pai.example.test/{STUDENT}/os-inbox"
    assert (link in body) is (app_url is not None) and "//" + STUDENT not in body


def test_slots_are_worded_by_urgency():
    t = load_templates()
    subjects = {s: t.render(OutboxMessage(1, "k", "email", STUDENT, "inbox_reminder", reminder(slot=f"{s}:x")),
                            None)[0] for s in INBOX_SLOTS}
    assert len(set(subjects.values())) == len(INBOX_SLOTS)
    assert "overdue" in subjects["esc"].lower()


@pytest.mark.parametrize("app_url", [None, "https://pai.example.test"])
def test_replan_request_renders_without_ai_text(app_url):
    msg = OutboxMessage(1, "k", "email", STUDENT, "replan_request",
                        {"instance_key": "visa_apply", "message": "AI WORDS HERE", "reason": "SUPERVISOR REASON"})
    subject, body = load_templates().render(msg, app_url)
    assert subject and body.startswith("Hello") and "because" in body.lower()
    assert "AI WORDS" not in body + subject and "SUPERVISOR" not in body + subject and "visa_apply" not in body
    assert (f"https://pai.example.test/{STUDENT}/os-inbox" in body) is (app_url is not None)


def test_unknown_template_or_missing_payload_field_is_unrenderable():
    t = load_templates()
    with pytest.raises(Unrenderable):
        t.render(OutboxMessage(1, "k", "email", STUDENT, "no_such_template", {}), None)
    with pytest.raises(Unrenderable):
        t.render(OutboxMessage(1, "k", "email", STUDENT, "inbox_reminder", {"slot": "d:x"}), None)
    with pytest.raises(Unrenderable):
        t.render(OutboxMessage(1, "k", "email", STUDENT, "inbox_reminder", reminder(slot="zz:1")), None)


def _yaml(tmp_path, text):
    p = tmp_path / "t.yaml"
    p.write_text(text)
    return p


def test_load_time_check(tmp_path):
    good = Path(load_templates.__globals__["TEMPLATES_PATH"]).read_text()
    with pytest.raises(TemplateError, match="replan_request"):
        load_templates(_yaml(tmp_path, good.replace("replan_request:", "replan_requestx:")))
    with pytest.raises(TemplateError, match="nope"):
        load_templates(_yaml(tmp_path, good.replace('"Coming up: {title}"', '"Coming up: {nope}"')))
    with pytest.raises(TemplateError):
        load_templates(_yaml(tmp_path, good.replace('"Coming up: {title}"', '"Coming up: {title"')))
    with pytest.raises(TemplateError):
        load_templates(_yaml(tmp_path, "greeting: hi\n"))


def test_unrenderable_row_is_failed_with_an_event(engine, clean):
    http, calls = client(ok)
    box = Outbox(engine, "pai")
    box.add("k1", "email", STUDENT, "inbox_reminder", {"slot": "d:x"})
    box.deliver(sender(http))
    assert calls == []
    with engine.connect() as conn:
        assert conn.execute(select(models.outbox.c.status)).scalar_one() == "failed"
    assert events_of(engine, "email_failed")[0].payload["reason"] == "unrenderable"


def test_resend_body_is_the_template_and_has_the_link():
    http, calls = client(ok)
    msg = OutboxMessage(1, "k", "email", STUDENT, "inbox_reminder", reminder(slot="h12:x"))
    sender(http, OS_APP_URL="https://pai.example.test").send(msg)
    body = json.loads(calls[0].content)
    assert "Upload your passport copy" in body["subject"] and "slot" not in body["text"]
    assert f"https://pai.example.test/{STUDENT}/os-inbox" in body["text"]


# ---- 4. configuration errors stop and alert --------------------------------------------------------------------------

@pytest.mark.parametrize("code", [401, 403, 422])
def test_config_error_stops_the_pass_and_alerts(engine, clean, caplog, code):
    http, calls = client(lambda r: httpx.Response(code, json={"message": f"bad key {KEY}"}))
    box = Outbox(engine, "pai")
    for k in ("k1", "k2", "k3"):
        box.add(k, "email", STUDENT, "inbox_reminder", reminder())
    with caplog.at_level(logging.INFO, logger="app.os.outbox"):
        assert box.deliver(sender(http)) == 0
    assert len(calls) == 1  # stopped at the first
    with engine.connect() as conn:
        assert [r.status for r in conn.execute(select(models.outbox))] == ["pending"] * 3
    (ev,) = events_of(engine, "email_config_error")
    assert ev.plan_id is None and ev.task_id is None and ev.payload["status"] == code
    assert KEY not in json.dumps(ev.payload) and ADDRESS not in json.dumps(ev.payload)
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert errors and str(code) in errors[0].getMessage() and KEY not in caplog.text
    box.deliver(sender(http))  # the next pass tries again and alerts again: one event per pass
    assert len(events_of(engine, "email_config_error")) == 2


@pytest.mark.parametrize("code", [400, 404, 409])
def test_other_4xx_still_fail_the_row(engine, clean, code):
    http, _ = client(lambda r: httpx.Response(code))
    box = Outbox(engine, "pai")
    box.add("k1", "email", STUDENT, "inbox_reminder", reminder())
    box.add("k2", "email", STUDENT, "inbox_reminder", reminder())
    with pytest.raises(Refused):
        sender(http).send(OutboxMessage(1, "k", "email", STUDENT, "inbox_reminder", reminder()))
    box.deliver(sender(http))
    with engine.connect() as conn:
        assert [r.status for r in conn.execute(select(models.outbox))] == ["failed", "failed"]
    assert [e.payload["status"] for e in events_of(engine, "email_failed")] == [code, code]


# ---- admin email-status ----------------------------------------------------------------------------------------------

def _api(engine, os_db, **env):
    from app.os.api import build_router, make_services
    from app.os.playbooks import load_playbook_dir

    s = load_settings({"OS_DATABASE_URL": os_db, "OS_ADMIN_TOKEN": TOKEN, "OS_ENABLED": "true", **env})
    services = make_services(s, engine=engine, playbooks=load_playbook_dir(FAKE_PLAYBOOKS),
                             today=lambda: date(2027, 3, 1), dbos_client=lambda: None)
    app = FastAPI()
    app.include_router(build_router(lambda: services), prefix="/v1/os")
    return TestClient(app)


def test_email_status_needs_admin(engine, clean, os_db):
    api = _api(engine, os_db)
    assert api.get("/v1/os/admin/email-status").status_code == 401
    assert api.get("/v1/os/admin/email-status", headers={"X-OS-Admin-Token": "wrong"}).status_code == 401


def test_email_status_shows_state_without_secrets(engine, clean, os_db):
    env = {"OS_EMAIL_SENDER": "resend", "OS_RESEND_API_KEY": KEY, "OS_EMAIL_FROM": "pai@example.test",
           "OS_EMAIL_ALLOWLIST": ADDRESS, "OS_RECIPIENT_LOOKUP": "tests.os.test_email_pilot:fake_lookup"}
    api = _api(engine, os_db, **env)
    empty = api.get("/v1/os/admin/email-status", headers=ADMIN).json()
    assert empty["last_config_error"] is None and empty["counts"]["pending"] == 0
    box = Outbox(engine, "pai")
    box.add("k1", "email", "stu-unknown", "inbox_reminder", reminder())  # blocked, then the 401 stops the pass
    box.add("k2", "email", STUDENT, "inbox_reminder", reminder())
    box.add("k3", "counsellor", STUDENT, "escalation", {})  # not email: not counted
    box.deliver(sender(client(lambda r: httpx.Response(401))[0]))
    try:
        ports.configure(None, recipient_lookup=fake_lookup)
        r = api.get("/v1/os/admin/email-status", headers=ADMIN)
    finally:
        ports.configure(None)
    assert r.status_code == 200
    body = r.json()
    assert body["sender"] == "resend" and body["lookup_setting"] is True and body["lookup_in_api"] is True
    assert body["allowlist_size"] == 1 and body["app_url_set"] is False
    assert body["counts"] == {"pending": 1, "sent": 0, "skipped": 0, "blocked": 1, "failed": 0}
    assert body["last_config_error"]["status"] == 401 and body["last_config_error"]["at"]
    assert KEY not in r.text and "example.test" not in r.text and "fake_lookup" not in r.text


# ---- mount errors ----------------------------------------------------------------------------------------------------

def test_mount_logs_invalid_settings_at_error(caplog):
    from app.os.api.mount import mount_os

    with caplog.at_level(logging.DEBUG):
        assert mount_os(FastAPI(), env={"OS_ENABLED": "true", "DATABASE_URL": "postgresql://x/y",
                                        "OS_EMAIL_SENDER": "resend", "OS_RESEND_API_KEY": KEY}) is False
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert errors and "OS_EMAIL_FROM" in errors[0].getMessage() and KEY not in caplog.text


def test_mount_with_os_off_stays_quiet(caplog):
    from app.os.api.mount import mount_os

    with caplog.at_level(logging.DEBUG):
        assert mount_os(FastAPI(), env={}) is False
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_mount_hands_the_lookup_to_the_port():
    from app.os.api.mount import mount_os

    try:
        assert mount_os(FastAPI(), env={"DATABASE_URL": "postgresql://x/y", "OS_ENABLED": "true",
                                        "OS_ADMIN_TOKEN": "t"}, recipient_lookup=fake_lookup) is True
        assert recipients.current() is fake_lookup
    finally:
        ports.configure(None)

