"""PostgreSQL integration for the durable summary and idempotent queue."""

import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import normalize_database_url
from app.journey import JourneyService
from app.models import Workspace


def test_summary_confirmation_queues_once():
    url = os.environ.get("COUNSELOR_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set COUNSELOR_TEST_DATABASE_URL for PostgreSQL integration")
    engine = create_engine(normalize_database_url(url))
    try:
        with Session(engine) as db:
            workspace = Workspace(name="Counselor v2 transition test")
            db.add(workspace)
            db.flush()
            service = JourneyService(db)
            journey = service.ensure_counselor(str(workspace.id))
            for stage in ("FOUNDATION", "DIRECTION"):
                journey = service.set_counselor_stage(str(workspace.id), journey.id, stage)
            summary = {"stated_goal": {"value": "MS", "status": "pending"},
                       "budget": {"value": {"amount": 10}, "status": "pending"}}
            draft = service.set_counselor_summary(str(workspace.id), journey.id,
                                                   summary, "You want an MS. Correct?", "student-1")
            assert draft.counselor_summary_draft["status"] == "awaiting_confirmation"
            assert draft.research_request is None
            queued = service.queue_counselor_research(str(workspace.id), journey.id, "student-2")
            repeated = service.queue_counselor_research(str(workspace.id), journey.id, "student-2")
            assert queued.current_stage == "RESEARCHING"
            assert repeated.research_request == queued.research_request
            assert queued.research_request["status"] == "queued"
            assert queued.research_request["payload"] == summary
            assert queued.research_request["confirmation_event_id"] == "student-2"
            db.rollback()
    finally:
        engine.dispose()
