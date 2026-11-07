"""P2-T8: the rollover script (`scripts.os_rollover`). Fictional codes."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.os.knowledge.port import Fact
from app.os.knowledge.store import SqlKnowledge
from scripts import os_rollover
from tests.os.test_compiler import IE

pytestmark = pytest.mark.req("R-61")
AT = datetime(2026, 11, 1, tzinfo=UTC)


@pytest.fixture
def svc(engine, clean):
    plans = SimpleNamespace(playbooks={(IE.key, IE.version): IE})
    return SimpleNamespace(engine=engine, settings=SimpleNamespace(tenant_id="pai"), plans=plans)


def test_rollover_list_export_and_backfill(svc, capsys, tmp_path):
    k = SqlKnowledge(svc.engine, "pai")
    k.upsert("route", IE.key, "funds", Fact(11000, "q", "https://a.test/x", AT, 2026, "confirmed"))  # pre-P2: no term
    assert os_rollover.main(["--backfill-terms"], services=svc) == 0
    assert "1 fact(s) got an intake term" in capsys.readouterr().out
    term = IE.intake_terms[0]
    assert os_rollover.main(["--region", "r_one", "--family", "masters", "--term", term, "--year", "2026"],
                            services=svc) == 0
    out = tmp_path / "s.csv"
    args = ["--region", "r_one", "--family", "masters", "--term", term, "--year", "2027", "--export", str(out)]
    assert os_rollover.main(args, services=svc) == 0
    assert "intake r_one masters" in capsys.readouterr().out and out.read_text(encoding="utf-8").count("\n") == 2
    assert os_rollover.main(["--list"], services=svc) == 0
    assert capsys.readouterr().out.count("open") == 2


def test_refusals(svc, capsys):
    assert os_rollover.main(["--region", "r_one"], services=svc) == 2
    assert "needs --family" in capsys.readouterr().err
    assert os_rollover.main(["--region", "r_one", "--family", "f", "--term", "monsoon", "--year", "2027"],
                            services=svc) == 2
    assert "monsoon" in capsys.readouterr().err
