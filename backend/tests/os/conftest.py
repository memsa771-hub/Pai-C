import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

BACKEND = Path(__file__).resolve().parents[2]


def run_alembic(args: list[str], url: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": url},
        check=True,
    )


def schema_exists(url: str, name: str) -> bool:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            return (
                conn.execute(
                    text("SELECT 1 FROM information_schema.schemata WHERE schema_name = :name"),
                    {"name": name},
                ).first()
                is not None
            )
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def pg_url() -> str:
    url = os.environ.get("OS_TEST_DATABASE_URL")
    if not url:
        pytest.skip("OS_TEST_DATABASE_URL is not set")
    return url


@pytest.fixture(scope="session")
def os_db(pg_url: str, fresh_db: None) -> str:
    """A database with the os Alembic branch at head."""
    run_alembic(["upgrade", "os@head"], pg_url)
    return pg_url


@pytest.fixture(scope="session")
def engine(os_db: str):
    eng = create_engine(os_db, pool_pre_ping=True)
    yield eng
    eng.dispose()


@pytest.fixture
def clean(engine) -> None:
    """Empty every os_* table before the test."""
    with engine.begin() as conn:
        names = conn.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'os' AND tablename LIKE 'os\\_%'"
        )).scalars().all()
        if names:
            conn.execute(text("TRUNCATE " + ", ".join(f"os.{n}" for n in names) + " RESTART IDENTITY CASCADE"))


TEST_DBOS_SCHEMA = "dbos_os_test"


def reset_dbos_schema(url: str, schema: str = TEST_DBOS_SCHEMA) -> None:
    """Workflow IDs are task_id:attempt and `clean` restarts IDs, so each DBOS test starts from an empty schema."""
    eng = create_engine(url)
    try:
        with eng.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
    finally:
        eng.dispose()


@pytest.fixture
def dbos_worker(os_db: str, engine, clean):
    """DBOS launched in this process (one worker, executor 'test-w0') plus a kernel-side DBOSClient."""
    from dbos import DBOS, DBOSClient

    from app.os.kernel import Kernel
    from app.os.runner import APP_NAME, default_registry, dbos_config, launch, register_workflow
    from app.os.settings import load_settings
    from tests.os.runner_helpers import FAIL_MODULE, SLEEP_MODULE

    reset_dbos_schema(os_db)
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_DBOS_SYSTEM_SCHEMA": TEST_DBOS_SCHEMA})
    kernel = Kernel(engine, settings.tenant_id)
    registry = default_registry()
    registry.register(SLEEP_MODULE)
    registry.register(FAIL_MODULE)
    os.environ.setdefault("OS_TEST_SLEEP_S", "0.2")
    DBOS(config=dbos_config(settings, "test-w0"))
    register_workflow(engine, settings, registry, kernel)
    launch()
    client = DBOSClient(system_database_url=os_db, dbos_system_schema=TEST_DBOS_SCHEMA, application_name=APP_NAME)
    try:
        yield client, kernel
    finally:
        client.destroy()
        DBOS.destroy(destroy_registry=True)


@pytest.fixture(scope="session")
def fresh_db(pg_url: str) -> None:
    """Reset the OS schemas so the os migration really runs again. `os` is left for the migration to create."""
    engine = create_engine(pg_url)
    try:
        with engine.begin() as conn:
            conn.execute(text("DROP SCHEMA IF EXISTS os CASCADE"))
            if conn.execute(text("SELECT to_regclass('public.alembic_version')")).scalar() is not None:
                conn.execute(text(r"DELETE FROM public.alembic_version WHERE version_num LIKE 'os\_%'"))
            for schema in ("dbos_os_test",):
                conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
                conn.execute(text(f"CREATE SCHEMA {schema}"))
    finally:
        engine.dispose()
