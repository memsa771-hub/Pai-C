"""Shared Counselor test helpers: a student in direction discovery, a fake
chat post and an API client bound to the student's isolated database.

They lived in test_counselor_mirror.py with the old confirm-gated Mirror; the
helpers outlived it (FOUR_FEATURES_SPEC 2.3)."""

from uuid import uuid4

from fastapi.testclient import TestClient

from app.database import get_db
from app.journey import JourneyService
from app.main import app
from app.models import EventRecord
from app.pai_c.deep.notebook import NotebookService
from app.pai_c.deep.turn_input import CounselorTurnInput
from tests.truth_map_fixtures import item


def prepare(student, db, *, ready=True):
    """One student message, a notebook and a Counselor journey in DIRECTION."""
    event_id = str(uuid4())
    stamp = student.next_timestamp()
    db.add(EventRecord(id=event_id, network_id=student.workspace_id,
        type="workspace.message.posted", source=f"human:{student.user_id}",
        target="channel/pai-counselor", payload={"content": "Please show how you understand me."},
        timestamp=stamp))
    db.commit()
    snapshot, _ = NotebookService(db).apply(student.workspace_id, {
        "said": [item("I study and work on practical projects.", key="daily_life")], "mirror_ready": ready,
    }, event_id, expected_version=0)
    service = JourneyService(db)
    journey = service.ensure_counselor(student.workspace_id)
    for stage in ("FOUNDATION", "DIRECTION"):
        journey = service.set_counselor_stage(student.workspace_id, journey.id, stage)
    db.commit()
    turn = CounselorTurnInput("channel/pai-counselor", student.workspace_id,
        "Please show how you understand me.", (), None, event_id, stamp, f"human:{student.user_id}")
    return turn, journey, snapshot


def fake_post(student):
    async def post(db, workspace_id, target, agent, content, depth, **kwargs):
        event_id = str(uuid4())
        db.add(EventRecord(id=event_id, network_id=workspace_id,
            type="workspace.message.posted", source="openagents:pai", target=target,
            timestamp=student.next_timestamp(), metadata_=kwargs.get("metadata") or {},
            payload={**kwargs.get("extra_payload", {}), "content": content,
                     "message_type": kwargs.get("message_type", "chat")}))
        db.commit()
        return event_id
    return post


def client_for(student):
    def scoped():
        with student.factory() as db:
            yield db
    app.dependency_overrides[get_db] = scoped
    return TestClient(app)
