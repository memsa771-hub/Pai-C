"""Slice 9a Task 7: ResendSender with an allow-list. httpx.MockTransport only; no real network, no real email."""

import hashlib
import json
import logging
import pickle

import httpx
import pytest
from sqlalchemy import select

from app.os import models
from app.os.outbox import Outbox
from app.os.outbox.outbox import OutboxMessage
from app.os.outbox.senders import (
    NotAllowed,
    ProviderUnavailable,
    Refused,
    ResendSender,
    make_sender,
)
from app.os.settings import load_settings

KEY = "re_test_dummy"


def settings(allow="ali@example.com", **extra):
    env = {"DATABASE_URL": "postgresql://x/y", "OS_EMAIL_SENDER": "resend", "OS_RESEND_API_KEY": KEY,
           "OS_EMAIL_FROM": "pai@example.com", "OS_EMAIL_ALLOWLIST": allow}
    env.update(extra)
    return load_settings(env)


def client(handler):
    calls = []

    def wrapped(request):
        calls.append(request)
        return handler(request)

    return httpx.Client(transport=httpx.MockTransport(wrapped)), calls


def msg(recipient="ali@example.com", key="k1"):
    return OutboxMessage(1, key, "email", recipient, "inbox_reminder", {"task": "Passport copy"})


def ok(request):
    return httpx.Response(200, json={"id": "abc"})


def test_sends_with_idempotency_key():
    http, calls = client(ok)
    ResendSender(settings(), http).send(msg(key="reminder:7:3"))
    (req,) = calls
    assert req.method == "POST" and str(req.url) == "https://api.resend.com/emails"
    assert req.headers["Authorization"] == f"Bearer {KEY}"
    assert req.headers["Idempotency-Key"] == "reminder:7:3"
    body = json.loads(req.content)
    assert body["from"] == "pai@example.com" and body["to"] == ["ali@example.com"]
    assert body["subject"] and "Passport copy" in body["text"]


def test_not_on_allowlist_is_blocked_not_sent(engine, clean):
    http, calls = client(ok)
    box = Outbox(engine, "pai")
    box.add("k1", "email", "stranger@example.com", "inbox_reminder", {})
    assert box.deliver(ResendSender(settings(), http)) == 0
    assert calls == []
    with engine.connect() as conn:
        row = conn.execute(select(models.outbox)).one()
    assert row.status == "blocked"


def test_empty_allowlist_sends_nothing():
    http, calls = client(ok)
    for allow in ("", " , "):
        with pytest.raises(NotAllowed):
            ResendSender(settings(allow=allow), http).send(msg())
    assert settings(allow="").email_allowlist == frozenset()
    assert load_settings({"DATABASE_URL": "x"}).email_allowlist == frozenset()
    assert calls == []


def test_allowlist_normalises_case_and_space():
    http, calls = client(ok)
    s = settings(allow="  Ali@Example.com , bo@example.com")
    assert s.email_allowlist == frozenset({"ali@example.com", "bo@example.com"})
    ResendSender(s, http).send(msg(recipient=" Ali@Example.com"))
    assert len(calls) == 1


def test_4xx_marks_failed(engine, clean, caplog):
    http, _ = client(lambda r: httpx.Response(422, json={"message": "bad"}))
    box = Outbox(engine, "pai")
    box.add("k1", "email", "ali@example.com", "inbox_reminder", {})
    box.add("k2", "email", "ali@example.com", "inbox_reminder", {})
    ok_http = ResendSender(settings(), http)
    with pytest.raises(Refused) as exc:
        ok_http.send(msg())
    assert exc.value.status == 422 and KEY not in str(exc.value)
    with caplog.at_level(logging.INFO, logger="app.os.outbox"):
        assert box.deliver(ok_http) == 0
    with engine.connect() as conn:
        rows = conn.execute(select(models.outbox).order_by(models.outbox.c.id)).all()
    assert [r.status for r in rows] == ["failed", "failed"]  # terminal; the loop went on to the next row
    assert "422" in caplog.text


def test_5xx_raises_for_step_retry(engine, clean):
    state = {"n": 0}

    def handler(request):
        state["n"] += 1
        return httpx.Response(200) if state["n"] == 1 else httpx.Response(503)

    http, _ = client(handler)
    box = Outbox(engine, "pai")
    for k in ("k1", "k2", "k3"):
        box.add(k, "email", "ali@example.com", "inbox_reminder", {})
    with pytest.raises(ProviderUnavailable):
        box.deliver(ResendSender(settings(), http))
    with engine.connect() as conn:
        statuses = [r.status for r in conn.execute(select(models.outbox).order_by(models.outbox.c.id))]
    assert statuses == ["sent", "pending", "pending"]


def test_network_error_raises():
    def boom(request):
        raise httpx.ConnectError("down")

    http, _ = client(boom)
    with pytest.raises(ProviderUnavailable):
        ResendSender(settings(), http).send(msg())


def test_resend_needs_key_and_from():
    base = {"DATABASE_URL": "x", "OS_EMAIL_SENDER": "resend"}
    with pytest.raises(ValueError):
        load_settings(base)
    with pytest.raises(ValueError):
        load_settings({**base, "OS_RESEND_API_KEY": KEY})
    with pytest.raises(ValueError):
        load_settings({**base, "OS_EMAIL_FROM": "a@example.com"})
    assert load_settings({**base, "OS_RESEND_API_KEY": KEY, "OS_EMAIL_FROM": "a@example.com"}).resend_api_key == KEY


def test_make_sender_builds_resend():
    assert isinstance(make_sender(settings(), None), ResendSender)


def test_log_never_contains_address(engine, clean, caplog):
    http, _ = client(ok)
    refused, _ = client(lambda r: httpx.Response(400))
    box = Outbox(engine, "pai")
    box.add("k1", "email", " Ali@Example.com", "inbox_reminder", {})
    box.add("k2", "email", "Stranger@Example.com", "inbox_reminder", {})
    box.add("k3", "email", "ali@example.com", "inbox_reminder", {})
    with caplog.at_level(logging.DEBUG):
        box.deliver(ResendSender(settings(), http))
        box.add("k4", "email", "ali@example.com", "inbox_reminder", {})
        box.deliver(ResendSender(settings(), refused))
    text = caplog.text.lower()
    assert "example.com" not in text and "ali@" not in text and "stranger" not in text and KEY not in text
    assert hashlib.sha256(b"ali@example.com").hexdigest() in text
    assert hashlib.sha256(b"stranger@example.com").hexdigest() in text


def test_migration_down_turns_new_statuses_into_skipped(os_db, engine, clean):
    from sqlalchemy import insert, text

    from tests.os.conftest import run_alembic

    with engine.begin() as conn:
        for i, st in enumerate(("blocked", "failed", "sent")):
            conn.execute(insert(models.outbox).values(tenant_id="pai", idempotency_key=f"m{i}", channel="email",
                                                      recipient="r", template="t", status=st))
    engine.dispose()
    run_alembic(["downgrade", "os_0015"], os_db)
    try:
        with engine.connect() as conn:
            got = conn.execute(text("SELECT status FROM os.os_outbox ORDER BY id")).scalars().all()
        assert got == ["skipped", "skipped", "sent"]
    finally:
        engine.dispose()
        run_alembic(["upgrade", "os@head"], os_db)


def _boom(request):
    raise httpx.ConnectError("down", request=request)


@pytest.mark.parametrize("handler", [lambda r: httpx.Response(503), _boom, lambda r: httpx.Response(429),
                                     lambda r: httpx.Response(408)])
def test_retryable_errors_do_not_carry_the_key(handler, engine, clean):
    http, _ = client(handler)
    with pytest.raises(ProviderUnavailable) as exc:
        ResendSender(settings(), http).send(msg())
    e = exc.value
    assert e.__cause__ is None and e.__context__ is None
    assert KEY not in repr(e) and KEY not in str(e) and KEY.encode() not in pickle.dumps(e)
    # through the outbox: it propagates and the row stays pending
    box = Outbox(engine, "pai")
    box.add("k1", "email", "ali@example.com", "inbox_reminder", {})
    with pytest.raises(ProviderUnavailable):
        box.deliver(ResendSender(settings(), http))
    with engine.connect() as conn:
        assert conn.execute(select(models.outbox.c.status)).scalar_one() == "pending"


def test_other_4xx_is_still_refused():
    for code in (400, 401, 403, 404, 422):
        http, _ = client(lambda r, c=code: httpx.Response(c))
        with pytest.raises(Refused):
            ResendSender(settings(), http).send(msg())


def test_blank_key_is_missing_and_not_in_repr():
    with pytest.raises(ValueError):
        load_settings({"DATABASE_URL": "x", "OS_EMAIL_SENDER": "resend", "OS_RESEND_API_KEY": "   ",
                       "OS_EMAIL_FROM": "a@example.com"})
    assert KEY not in repr(settings())
