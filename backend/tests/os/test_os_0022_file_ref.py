"""P1-T7 Task 1: migration os_0022 (`os_documents.file_ref` and its partial unique index). Fictional data."""

import subprocess
import sys

import pytest
from sqlalchemy import create_engine, inspect, insert, text
from sqlalchemy.exc import IntegrityError

from app.os import models
from app.os.db import OS_SCHEMA
from tests.os.conftest import BACKEND, run_alembic

pytestmark = pytest.mark.req("R-01")


def _doc(engine, sha: str, **values) -> None:
    base = dict(tenant_id="pai", student_ref="stu-1", doc_type="transcript", type_version=1, filename="t.png",
                content_type="image/png", size=3, sha256=sha)
    with engine.begin() as conn:
        conn.execute(insert(models.documents).values(**{**base, **values}))


def test_file_ref_upgrade_downgrade(os_db, engine, clean):
    cols = {c["name"] for c in inspect(engine).get_columns("os_documents", schema=OS_SCHEMA)}
    assert "file_ref" in cols
    _doc(engine, "a" * 64, file_ref="file-1")
    with pytest.raises(IntegrityError):  # one live document per tenant and file
        _doc(engine, "b" * 64, file_ref="file-1", student_ref="stu-2")
    _doc(engine, "c" * 64, file_ref=None)  # rows without a link are not constrained
    _doc(engine, "d" * 64, file_ref=None)
    with engine.begin() as conn:
        conn.execute(text("UPDATE os.os_documents SET status = 'deleted' WHERE file_ref = 'file-1'"))
    _doc(engine, "e" * 64, file_ref="file-1")  # a deleted one plus a live one insert

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM os.os_documents"))
    engine.dispose()
    run_alembic(["downgrade", "os_0021"], os_db)  # works on an empty table
    try:
        eng = create_engine(os_db)
        try:
            cols = {c["name"] for c in inspect(eng).get_columns("os_documents", schema=OS_SCHEMA)}
            assert "file_ref" not in cols
            names = {i["name"] for i in inspect(eng).get_indexes("os_documents", schema=OS_SCHEMA)}
            assert "uq_os_documents_file_ref" not in names
        finally:
            eng.dispose()
    finally:
        run_alembic(["upgrade", "os@head"], os_db)


def test_downgrade_refuses_while_a_linked_document_has_no_bytes(os_db, engine, clean):
    _doc(engine, "a" * 64, file_ref="file-1")
    engine.dispose()
    with pytest.raises(subprocess.CalledProcessError):
        run_alembic(["downgrade", "os_0021"], os_db)
    eng = create_engine(os_db)
    try:
        assert "file_ref" in {c["name"] for c in inspect(eng).get_columns("os_documents", schema=OS_SCHEMA)}
        with eng.begin() as conn:
            conn.execute(text("DELETE FROM os.os_documents"))
    finally:
        eng.dispose()


def test_one_os_head():
    done = subprocess.run([sys.executable, "scripts/check_alembic_heads.py"], cwd=BACKEND, capture_output=True,
                          text=True)
    assert done.returncode == 0, done.stdout
