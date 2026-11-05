"""P1-T5 Task 4: PAI OS plan events become app notifications, never chat (R-45, R-04). The OS ports are stubbed (the
legacy suite has no OS database); the Counsellor side is real. Fictional data."""

import types
from datetime import datetime, timezone

import pytest
import yaml
from sqlalchemy import func, select

from app import pai_os_bridge as bridge
from app.models import NotificationRecord
from app.os import ports
from app.os.contracts.os_event import OsEventV1
from app.os.ports import os_events as os_events_port
from scripts.counselor_eval_support import StudentSession

pytestmark = [pytest.mark.req("R-45"), pytest.mark.req("R-04")]
KINDS = OsEventV1.model_fields["kind"].annotation.__args__


@pytest.fixture
def student():
    with StudentSession() as s:
        yield s


def event(student, kind: str = "plan_paused", n: int = 1, ref: str | None = None) -> OsEventV1:
    return OsEventV1(key=f"os_event:7:{kind}:{n}", student_ref=ref or student.workspace_id, plan_id=7,
                     decision_version=2, kind=kind, instance_key=None, at=datetime(2027, 1, 10, tzinfo=timezone.utc))


@pytest.fixture
def os_events(monkeypatch):
    """The event port, recorded: what is pending and what the glue marked."""
    got = {"pending": [], "marked": []}
    monkeypatch.setattr(os_events_port, "pending_events", lambda limit=100: list(got["pending"]))
    monkeypatch.setattr(os_events_port, "mark_event_delivery", lambda key, status: got["marked"].append((key, status)))
    ports.configure(types.SimpleNamespace())
    yield got
    ports.configure(None)


def notices(student) -> list[NotificationRecord]:
    with student.factory() as db:
        return list(db.scalars(select(NotificationRecord).order_by(NotificationRecord.created_at)))


def row_counts(student) -> dict[str, int]:
    """Row counts of every table the test database has except notifications (chat and events live in the others)."""
    from sqlalchemy import inspect

    from app.models import Base

    have = set(inspect(student.engine).get_table_names())
    with student.factory() as db:
        return {t.name: db.scalar(select(func.count()).select_from(t)) for t in Base.metadata.sorted_tables
                if t.name in have and t.name != "notifications"}


def test_each_event_is_one_notification_with_fixed_copy(student, os_events):
    texts = yaml.safe_load(bridge.OS_EVENT_TEXTS.read_text(encoding="utf-8"))
    os_events["pending"] = [event(student, k, i) for i, k in enumerate(KINDS)]
    with student.factory() as db:
        assert bridge.deliver_os_events(db) == {"sent": len(KINDS), "refused": 0, "waiting": 0}
    got = notices(student)
    assert len(got) == len(KINDS)
    assert {(n.title, n.message) for n in got} == {(t["title"], t["message"]) for t in texts.values()}
    assert {n.dedupe_key for n in got} == {f"os_event:7:{k}:{i}" for i, k in enumerate(KINDS)}
    assert all(n.link_url == f"/{student.workspace_id}?view=roadmap" and n.workspace_id == student.workspace_id
               for n in got)
    assert [m[1] for m in os_events["marked"]] == ["sent"] * len(KINDS)


def test_repeat_sweep_makes_no_second_notification(student, os_events):
    os_events["pending"] = [event(student)]
    with student.factory() as db:
        bridge.deliver_os_events(db)
        bridge.deliver_os_events(db)  # the OS still lists it (the mark was lost): the same key, so none is added
    assert len(notices(student)) == 1


def test_no_chat_or_other_rows_are_created(student, os_events):
    before = row_counts(student)
    assert before  # the check really looks at tables
    os_events["pending"] = [event(student, k, i) for i, k in enumerate(KINDS)]
    with student.factory() as db:
        bridge.deliver_os_events(db)
    assert row_counts(student) == before  # no message, event, turn or job row: only notifications grew
    assert len(notices(student)) == len(KINDS)


def test_unknown_student_is_refused_not_retried(student, os_events):
    os_events["pending"] = [event(student, ref="00000000-0000-4000-8000-000000000000")]
    with student.factory() as db:
        assert bridge.deliver_os_events(db) == {"sent": 0, "refused": 1, "waiting": 0}
    assert os_events["marked"] == [("os_event:7:plan_paused:1", "refused")]
    assert notices(student) == []


def test_sweep_delivers_events_only_with_the_part_on(student, os_events, monkeypatch):
    os_events["pending"] = [event(student)]
    monkeypatch.setattr(bridge, "part_on", lambda name: name == "CONNECT_ROADMAP_FROM_PLANVIEW")
    monkeypatch.setattr(bridge, "_deliver", lambda db: {"sent": 0, "refused": 0, "waiting": 0})
    with student.factory() as db:
        assert bridge.sweep_once(db)["events"]["sent"] == 1
    assert len(notices(student)) == 1
    monkeypatch.setattr(bridge, "part_on", lambda name: False)
    os_events["pending"] = [event(student, n=2)]
    with student.factory() as db:
        assert "events" not in bridge.sweep_once(db)
    assert len(notices(student)) == 1


def test_copy_covers_every_kind_in_plain_english():
    texts = yaml.safe_load(bridge.OS_EVENT_TEXTS.read_text(encoding="utf-8"))
    assert set(texts) == set(KINDS)
    countries = yaml.safe_load((bridge.OS_EVENT_TEXTS.parent / "countries.yaml").read_text(encoding="utf-8"))
    for kind, t in texts.items():
        assert set(t) == {"title", "message", "priority"} and t["priority"] in {"low", "normal", "high"}
        text = f"{t['title']} {t['message']}".lower()
        assert all(name.lower() not in text for name in countries if len(name) > 3), kind
        assert "—" not in text and "chat" not in text
