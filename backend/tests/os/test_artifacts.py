"""Slice 5 Task 3: artifact tables (os_0008) and the store (spec S5-D7, S5-D8). Fictional text only."""

import hashlib

import pytest
from sqlalchemy import create_engine, inspect

from app.os.artifacts.store import ArtifactStore
from app.os.db import OS_SCHEMA

TEXT = "I want to study data science because of a traffic project I built."


def sha(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def test_migration_up_down(os_db):
    from tests.os.conftest import run_alembic

    run_alembic(["downgrade", "os_0007"], os_db)
    eng = create_engine(os_db)
    try:
        tables = set(inspect(eng).get_table_names(schema=OS_SCHEMA))
        assert not tables & {"os_artifacts", "os_artifact_versions", "os_approvals", "os_statement_answers",
                             "os_statement_rules"}
        assert "artifact_id" not in {c["name"] for c in inspect(eng).get_columns("os_agent_runs", schema=OS_SCHEMA)}
    finally:
        eng.dispose()
    run_alembic(["upgrade", "os@head"], os_db)


def test_versions_immutable_and_numbered(engine, clean):
    s = ArtifactStore(engine, "pai")
    a = s.get_or_create("stu-1", "sop", None)
    v1 = s.add_version(a.id, TEXT, "writer", critic={"ok": True}, flags=[], limit_words=1000)
    v2 = s.add_version(a.id, TEXT + " More.", "student")
    assert (v1.number, v2.number) == (1, 2)
    assert [v.text for v in s.versions(a.id)] == [TEXT, TEXT + " More."]
    assert s.get(a.id).current_version == 2 and s.get(a.id).status == "draft"
    assert v1.words == 13 and v1.critic == {"ok": True} and v1.limit_words == 1000


def test_sha256_of_text(engine, clean):
    s = ArtifactStore(engine, "pai")
    a = s.get_or_create("stu-1", "cv", None)
    assert s.add_version(a.id, "Café — naïve", "writer").sha256 == sha("Café — naïve")


def test_approve_binds_hash(engine, clean):
    s = ArtifactStore(engine, "pai")
    a = s.get_or_create("stu-1", "sop", None)
    s.add_version(a.id, TEXT, "writer")
    approval = s.approve(a.id, 1)
    assert (approval.version, approval.sha256) == (1, sha(TEXT)) and s.get(a.id).status == "approved"
    assert s.approval(a.id) == approval
    with pytest.raises(KeyError):
        s.approve(a.id, 9)


def test_edit_after_approval_unbinds(engine, clean):
    s = ArtifactStore(engine, "pai")
    a = s.get_or_create("stu-1", "sop", None)
    s.add_version(a.id, TEXT, "writer")
    s.approve(a.id, 1)
    s.add_version(a.id, TEXT + " Edited.", "student")
    assert s.approval(a.id) is None and s.get(a.id).status == "draft"
    assert s.versions(a.id)[0].sha256 == sha(TEXT)  # the approved text itself is unchanged
    assert s.approve(a.id, 1).sha256 == sha(TEXT)  # an older version can still be approved


def test_base_and_programme_artifacts_apart(engine, clean):
    s = ArtifactStore(engine, "pai")
    base = s.get_or_create("stu-1", "sop", None)
    prog = s.get_or_create("stu-1", "sop", "p1")
    assert base.id != prog.id and s.get_or_create("stu-1", "sop", None).id == base.id
    assert (base.programme_ref, prog.programme_ref) == (None, "p1")
    assert {(a.kind, a.programme_ref) for a in s.list_for("stu-1")} == {("sop", None), ("sop", "p1")}


def test_tenant_isolation(engine, clean):
    a = ArtifactStore(engine, "pai").get_or_create("stu-1", "sop", None)
    other = ArtifactStore(engine, "other")
    assert other.list_for("stu-1") == [] and other.get(a.id) is None
    with pytest.raises(KeyError):
        other.add_version(a.id, TEXT, "writer")


def test_delete_for_student(engine, clean):
    s = ArtifactStore(engine, "pai")
    a = s.get_or_create("stu-1", "sop", None)
    s.add_version(a.id, TEXT, "writer")
    s.approve(a.id, 1)
    s.get_or_create("stu-2", "cv", None)
    s.delete_for("stu-1")
    assert s.list_for("stu-1") == [] and len(s.list_for("stu-2")) == 1
