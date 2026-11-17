import pytest

from app.config import config
from app.pai_c.connect import flags

pytestmark = pytest.mark.req("R-59")


def test_flags_default_off():
    for name in flags.PARTS:
        assert getattr(config, name) is False, name


def test_part_on_needs_module(monkeypatch):
    from app import pai_os_bridge

    monkeypatch.setattr(config, "CONNECT_HANDOFF", True)
    monkeypatch.setattr(pai_os_bridge, "counsellor_module_on", lambda: False)
    assert flags.part_on("CONNECT_HANDOFF") is False
    monkeypatch.setattr(pai_os_bridge, "counsellor_module_on", lambda: True)
    assert flags.part_on("CONNECT_HANDOFF") is True


def test_part_on_false_without_os(monkeypatch):
    monkeypatch.setattr(config, "CONNECT_HANDOFF", True)
    assert flags.part_on("CONNECT_HANDOFF") is False


def test_unknown_part_raises():
    with pytest.raises(KeyError):
        flags.part_on("CONNECT_NOPE")
