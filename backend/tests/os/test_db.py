from app.os.db import OsBase
from conftest import run_alembic, schema_exists
from scripts import check_alembic_heads


def test_one_head_per_branch():
    assert check_alembic_heads.main() == 0


def test_os_branch_upgrade_creates_schema(fresh_db, pg_url):
    run_alembic(["upgrade", "os@head"], pg_url)
    assert schema_exists(pg_url, "os")


def test_os_base_uses_os_schema():
    assert OsBase.metadata.schema == "os"
