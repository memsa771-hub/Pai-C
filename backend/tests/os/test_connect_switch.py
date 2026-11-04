import pytest

from app.os.adapters.counsellor import manifest
from scripts import connect_switch

pytestmark = pytest.mark.req("R-59")


def test_switch_on_off(engine, clean, capsys):
    assert connect_switch.main(["on"], engine, tenant_id="pai") == 0
    assert "counsellor module: on" in capsys.readouterr().out
    assert manifest.is_enabled(engine, "pai") is True
    assert connect_switch.main(["off"], engine, tenant_id="pai") == 0
    assert manifest.is_enabled(engine, "pai") is False
    capsys.readouterr()
    assert connect_switch.main(["status"], engine, tenant_id="pai") == 0
    assert "counsellor module: off" in capsys.readouterr().out


def test_switch_rejects_unknown_command(engine, clean):
    assert connect_switch.main(["sideways"], engine) == 2


def test_switch_uses_given_tenant(engine, clean):
    assert connect_switch.main(["on"], engine, tenant_id="other") == 0
    assert manifest.is_enabled(engine, "other") is True
    assert manifest.is_enabled(engine, "pai") is False
