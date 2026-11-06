"""Shared helpers for the P1-T7 upload tests (R-01): a signed-in student on the real Counsellor app (SQLite), with the
file store in a temp folder. Fictional data only; no model, no PAI OS unless the test brings one."""

import base64
import json
import re
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.database import get_db
from app.files import storage
from app.main import app
from app.models import User
from scripts.counselor_eval_support import StudentSession
from tests.auth_fakes import firebase_tokens, link_owner
from tests.documents.fixtures import TRANSCRIPT_PAGES, make_pdf

PDF = make_pdf(TRANSCRIPT_PAGES)
PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 64


@contextmanager
def upload_world(tmp_path):
    """Yields `(client, student, auth)`: the app on the student's database, the owner's bearer, a temp file store."""
    with StudentSession() as student:
        with student.factory() as db:
            token, identity = link_owner(db, db.get(User, student.user_id))

        def database():
            with student.factory() as db:
                yield db

        old = dict(app.dependency_overrides)
        app.dependency_overrides[get_db] = database
        previous = storage._store
        storage._store = storage.LocalFileStore(str(tmp_path / "files"))
        try:
            with patch("app.database.SessionLocal", student.factory), \
                    patch("app.routers.events.SessionLocal", student.factory), \
                    firebase_tokens({token: identity}):
                yield TestClient(app), student, {"Authorization": "Bearer " + token}
        finally:
            storage._store = previous
            app.dependency_overrides.clear()
            app.dependency_overrides.update(old)


def post_file(client, student, auth, name="transcript.pdf", data=PDF, content_type="application/pdf", **fields):
    return client.post("/v1/files", headers=auth, data={"network": student.workspace_id, **fields},
                       files={"file": (name, data, content_type)})


def post_folder(client, student, auth, name="transcript.pdf", data=PDF, content_type="application/pdf", **fields):
    return client.post("/v1/files/upload", headers=auth, data={"network": student.workspace_id, **fields},
                       files={"files": (name, data, content_type)})


def post_base64(client, student, auth, name="notes.txt", data=b"hello", content_type="text/plain"):
    return client.post("/v1/files/base64", headers=auth, json={
        "network": student.workspace_id, "filename": name, "content_type": content_type,
        "content_base64": base64.b64encode(data).decode()})


def jobs(student, job_type=None):
    from sqlalchemy import select

    from app.models import BackgroundJob

    with student.factory() as db:
        rows = db.scalars(select(BackgroundJob).order_by(BackgroundJob.created_at)).all()
        return [(j.job_type, dict(j.payload or {})) for j in rows if job_type is None or j.job_type == job_type]


def run_parse_job(student, file_id):
    """Runs the queued `document.parse` job for the file, the way the worker does."""
    import asyncio

    from sqlalchemy import select

    from app.documents.handlers import parse_document_job
    from app.models import BackgroundJob

    with student.factory() as db:
        job = db.scalars(select(BackgroundJob).where(BackgroundJob.job_type == "document.parse")).all()
        job = next(j for j in job if (j.payload or {}).get("file_id") == file_id)
        shim = SimpleNamespace(id=job.id, workspace_id=job.workspace_id, payload=dict(job.payload), job_type=job.job_type)
        result = asyncio.run(parse_document_job(shim, db))
        db.commit()
        return result


_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?")


_STAMP = re.compile(r"\d{8}_\d{6}")  # the agent upload route puts the upload time in the name


def masked(response) -> dict:
    """`{status, body}` with ids and times replaced, so two runs compare."""
    text = _STAMP.sub("<stamp>", _TIME.sub("<time>", _ID.sub("<id>", response.text)))
    return {"status": response.status_code, "body": json.loads(text)}
