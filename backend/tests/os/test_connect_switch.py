import pytest

from app.os.adapters.counsellor import manifest
from scripts import connect_switch

pytestmark = pytest.mark.req("R-59")


def test_switch_on_off(engine, clean, capsys):
    assert connect_switch.main(["on"], engine) == 0
    assert manifest.is_enabled(engine, "pai") is True
    assert connect_switch.main(["off"], engine) == 0
    assert manifest.is_enabled(engine, "pai") is False
    capsys.readouterr()
    assert connect_switch.main(["status"], engine) == 0
    assert "counsellor module: off" in capsys.readouterr().out


def test_switch_rejects_unknown_command(engine, clean):
    assert connect_switch.main(["sideways"], engine) == 2
