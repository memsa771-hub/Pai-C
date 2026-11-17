"""P1-T10 A3 (R-05): the owner CLI `scripts/connect_consistency.py`: usage, exit codes, and counts only."""

import pytest

from app.os import ports
from scripts import connect_consistency as cli

pytestmark = pytest.mark.req("R-05")


def test_usage_exit_code(capsys):
    for argv in ([], ["bogus"], ["run", "status"]):
        assert cli.main(argv, db=object()) == 2
    assert "usage" in capsys.readouterr().err


def test_not_mounted_exit_code(capsys):
    ports.configure(None)
    assert cli.main(["run"], db=object()) == 3
    assert cli.main(["status"], db=object()) == 3
    assert "not mounted" in capsys.readouterr().out
