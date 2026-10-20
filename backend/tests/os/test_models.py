from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import DateTime

from app.os.db import OS_SCHEMA, OsBase
from app.os import models  # noqa: F401  (registers the tables on OsBase.metadata)


def _only_os_schema(name, type_, parent_names):
    if type_ == "schema":
        return name == OS_SCHEMA
    return True


def test_every_datetime_column_is_timezone_aware():
    cols = [c for t in OsBase.metadata.tables.values() for c in t.columns if isinstance(c.type, DateTime)]
    assert cols and all(c.type.timezone for c in cols)


def test_every_table_has_tenant_id():
    assert OsBase.metadata.tables
    assert all("tenant_id" in t.c for t in OsBase.metadata.tables.values())


def test_os_tables_present():
    names = {t.name for t in OsBase.metadata.tables.values()}
    assert names == {
        "os_plans", "os_tasks", "os_task_edges", "os_plan_revisions", "os_playbook_pins",
        "os_enqueue_requests", "os_task_attempts", "os_events", "os_modules", "os_outbox",
        "os_knowledge_facts",
        # Slice 2 (os_0003)
        "os_programmes", "os_pages", "os_research_runs", "os_agent_runs",
        # Slice 3 (os_0004)
        "os_documents", "os_document_files", "os_document_fields", "os_document_findings", "os_profile_values",
    }


def test_migration_matches_models(engine):
    with engine.connect() as conn:
        mc = MigrationContext.configure(
            conn, opts={"include_schemas": True, "include_name": _only_os_schema}
        )
        assert compare_metadata(mc, OsBase.metadata) == []


def test_task_state_check_rejects_unknown_state(engine, clean):
    from sqlalchemy import insert
    from sqlalchemy.exc import IntegrityError
    import pytest

    with engine.begin() as conn:
        plan_id = conn.execute(insert(models.plans).values(
            tenant_id="pai", source="self_serve", external_ref="e", student_ref="s",
            contract={}, contract_sha256="x",
        ).returning(models.plans.c.id)).scalar_one()
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(insert(models.tasks).values(
                tenant_id="pai", plan_id=plan_id, instance_key="k", template_key="k",
                task_type="t", kind="work", title="t", state="sleeping", due_tz="UTC",
                playbook_version=1,
            ))


def test_downgrade_then_upgrade_slice2(os_db):
    """os_0003 can be taken back and re-applied; the models still match afterwards."""
    from sqlalchemy import create_engine, inspect

    from tests.os.conftest import run_alembic

    run_alembic(["downgrade", "os_0002"], os_db)  # a fixed target: later slices add revisions on top
    eng = create_engine(os_db)
    try:
        assert "os_programmes" not in inspect(eng).get_table_names(schema=OS_SCHEMA)
        assert "source" not in {c["name"] for c in inspect(eng).get_columns("os_knowledge_facts", schema=OS_SCHEMA)}
    finally:
        eng.dispose()
    run_alembic(["upgrade", "os@head"], os_db)
    eng = create_engine(os_db)
    try:
        with eng.connect() as conn:
            mc = MigrationContext.configure(conn, opts={"include_schemas": True, "include_name": _only_os_schema})
            assert compare_metadata(mc, OsBase.metadata) == []
    finally:
        eng.dispose()
