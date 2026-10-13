import pytest

from app.os.settings import load_settings


def test_defaults_and_fallback():
    s = load_settings({"DATABASE_URL": "postgresql://u:p@h/db"})
    assert s.database_url == "postgresql://u:p@h/db"
    assert (s.model_cheap, s.model_strong, s.dbos_system_schema, s.os_enabled) == ("gpt-5.4-mini", "gpt-5.4", "dbos", False)


def test_os_database_url_wins():
    s = load_settings({"DATABASE_URL": "a", "OS_DATABASE_URL": "b", "OS_ENABLED": "true"})
    assert s.database_url == "b" and s.os_enabled is True


def test_missing_database_url_raises():
    with pytest.raises(ValueError, match="OS_DATABASE_URL or DATABASE_URL"):
        load_settings({})
