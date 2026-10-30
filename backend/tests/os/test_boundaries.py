import subprocess
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]


@pytest.fixture
def tmp_violation():
    path = BACKEND / "app" / "os" / "_violation.py"
    path.write_text("from app.services import operator\n", encoding="utf-8")
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


def test_tach_passes():
    assert subprocess.run(["tach", "check"], cwd=BACKEND).returncode == 0


def test_tach_blocks_os_importing_app_code(tmp_violation):
    # fixture writes backend/app/os/_violation.py containing "from app.services import operator"
    # and deletes it in teardown
    r = subprocess.run(["tach", "check"], cwd=BACKEND, capture_output=True, text=True)
    assert r.returncode == 1 and "cannot depend on '<root>'" in r.stderr
