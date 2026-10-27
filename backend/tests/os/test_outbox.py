from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.os import models
from app.os.outbox import LogSender, Outbox, make_sender
from app.os.settings import load_settings
from app.os.workers.reminders import reminder_slot

NOW = datetime(2027, 3, 10, 9, 30, tzinfo=timezone.utc)


class Recorder:
    def __init__(self):
        self.sent = []

    def send(self, msg):
        self.sent.append(msg)


def test_same_key_sends_once(engine, clean):
    box = Outbox(engine, "pai")
    assert box.add("k1", "email", "stu-1", "inbox_reminder", {"x": 1}) is True
    assert box.add("k1", "email", "stu-1", "inbox_reminder", {"x": 1}) is False
    rec = Recorder()
    assert box.deliver(rec) == 1
    assert box.deliver(rec) == 0
    assert [m.idempotency_key for m in rec.sent] == ["k1"]
    with engine.connect() as conn:
        row = conn.execute(select(models.outbox)).one()
    assert (row.status, row.attempts) == ("sent", 1) and row.sent_at is not None


def test_failed_send_stays_pending(engine, clean):
    box = Outbox(engine, "pai")
    box.add("k1", "email", "stu-1", "inbox_reminder", {})

    class Broken:
        def send(self, msg):
            raise RuntimeError("provider down")

    with pytest.raises(RuntimeError):
        box.deliver(Broken())
    with engine.connect() as conn:
        assert conn.execute(select(models.outbox.c.status)).scalar_one() == "pending"


def test_log_sender_writes_event(engine, clean):
    box = Outbox(engine, "pai")
    box.add("k1", "email", "stu-1", "inbox_reminder", {"title": "Book IELTS"})
    box.deliver(LogSender(engine, "pai"))
    with engine.connect() as conn:
        ev = conn.execute(select(models.events).where(models.events.c.type == "email_logged")).one()
    assert ev.payload["recipient"] == "stu-1" and ev.payload["idempotency_key"] == "k1"


def test_make_sender():
    s = load_settings({"DATABASE_URL": "x"})
    assert isinstance(make_sender(s, engine=None), LogSender)
    with pytest.raises(ValueError, match="email sender"):
        make_sender(load_settings({"DATABASE_URL": "x", "OS_EMAIL_SENDER": "smtp"}), engine=None)


@pytest.mark.parametrize("due_in,slack,expected", [
    (timedelta(days=-1), 3, "esc:2027-03-10"),
    (timedelta(hours=30), 1, "h12:2027-03-10:0"),
    (timedelta(days=5), 4, "d:2027-03-10"),
    (timedelta(days=12), 10, f"d3:{NOW.toordinal() // 3}"),
    (timedelta(days=40), 30, "w:2027-10"),
    (timedelta(days=40), None, None),
])
def test_reminder_slots(due_in, slack, expected):
    assert reminder_slot(NOW, NOW + due_in, slack) == expected


def test_no_due_date_no_reminder():
    assert reminder_slot(NOW, None, 5) is None
