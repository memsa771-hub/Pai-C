"""A real-ASGI client over an isolated SQLite student, for HTTP tests.

The engine differs from the shared one on purpose: TestClient serves the app
on another thread, so the SQLite connection has to be shareable across threads.
Import `api` (and the headers) into a test module to use it.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.memory.field_definitions import VaultFieldDefinitionService, catalog_field_definitions
from app.memory.student_records import ENTITY_MODELS
from app.models import (
    BackgroundJob, EventRecord, FileRecord, MemoryCandidate, PaiEpisode, PaiMemory,
    ProfileFieldResponse, ProfileIssue, ProfileRequirement, StudentRecordRevision, User, VaultFact,
    VaultFieldDefinition, Workspace, VAULT_INTAKE_MODELS,
    Roadmap, RoadmapStudentState, VaultDrop, VaultItem,
)


@compiles(JSONB, "sqlite")
def _compile_jsonb(type_, compiler, **kw):
    return "JSON"


TOKEN = "machine-secret"
# The signed-in owner: the frontend sends the machine token and the bearer together.
HEADERS = {"X-Workspace-Token": TOKEN, "Authorization": "Bearer owner"}
MACHINE_ONLY = {"X-Workspace-Token": TOKEN}
# Bearer -> verified user id; only "owner" owns the fixture's workspace.
BEARERS = {}


def _claims(bearer):
    user_id = BEARERS.get(bearer)
    return {"session_user_id": user_id} if user_id else None

# One of each sensitivity class, mirroring migration 063.
EXTRA_FIELDS = (
    ("identity.current_status", "normal"),
    ("location.current_city", "normal"),
    ("location.current_country", "normal"),
    ("identity.passport_number", "restricted"),
)


@pytest.fixture
def api():
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _setup(connection, record):
        connection.create_function("NOW", 0, lambda: datetime.now(timezone.utc).isoformat())
        connection.execute("PRAGMA foreign_keys=ON")

    tables = [User, Workspace, EventRecord, FileRecord, VaultFact, VaultFieldDefinition,
              MemoryCandidate, PaiMemory, PaiEpisode, ProfileIssue, ProfileRequirement,
              ProfileFieldResponse,
              StudentRecordRevision,
              BackgroundJob, *ENTITY_MODELS.values(), *VAULT_INTAKE_MODELS]
    tables.extend([Roadmap, RoadmapStudentState, VaultDrop, VaultItem])
    Base.metadata.create_all(engine, tables=[model.__table__ for model in tables])

    session = Session(engine, autoflush=False)
    user = User(email="student@example.test", display_name="Ali Ahmed")
    session.add(user)
    session.flush()
    workspace = Workspace(name="Student", owner_user_id=user.id, password_hash=TOKEN)
    session.add(workspace)
    session.flush()
    fields = VaultFieldDefinitionService(session)
    for spec in catalog_field_definitions():
        fields.upsert_definition(spec)
    for key, sensitivity in EXTRA_FIELDS:
        fields.upsert_definition({"key": key, "category": key.split(".")[0],
                                  "sensitivity": sensitivity, "data_type": "string",
                                  "validation_schema": {"type": "string"}})
    session.commit()
    BEARERS.clear()
    BEARERS.update({"owner": str(user.id), "stranger": "someone-else"})

    app.dependency_overrides[get_db] = lambda: session
    try:
        with patch("app.security.access.verify_identity_claims", side_effect=_claims):
            yield TestClient(app), session, str(workspace.id)
    finally:
        app.dependency_overrides.pop(get_db, None)
        session.close()
        engine.dispose()
