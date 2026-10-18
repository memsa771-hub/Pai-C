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
