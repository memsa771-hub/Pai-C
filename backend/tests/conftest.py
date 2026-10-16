"""Offline defaults; tests may explicitly install their own fake hybrid index."""
import pytest
from app.memory import index


@pytest.fixture(autouse=True)
def offline_api_key(monkeypatch):
    from app.config import config
    monkeypatch.setattr(config, "PAI_API_KEY", "offline-test-key")


@pytest.fixture(autouse=True)
def hermetic_providers_and_database(monkeypatch):
    """Fail at the boundary, even when application code catches Exception.

    Tests explicitly replace transports with fakes and bind sessions to their
    own SQLite engines. Guard Session construction too: imported SessionLocal
    aliases and the background factory must not escape the database check.
    """
    from app import database
    from app.inference import client
    from sqlalchemy.orm import Session

    def forbidden_provider(*args, **kwargs):
        pytest.fail("Offline test attempted an unpatched model provider; install a fake transport", pytrace=False)

    monkeypatch.setattr(client, "create_client", forbidden_provider)
    monkeypatch.setattr(client, "create_sync_client", forbidden_provider)
    monkeypatch.setattr(client, "AsyncOpenAI", forbidden_provider)
    monkeypatch.setattr(client, "OpenAI", forbidden_provider)

    original_init = Session.__init__

    def guarded_init(self, *args, **kwargs):
        bind = kwargs.get("bind", args[0] if args else None)
        engine = getattr(bind, "engine", bind)
        if engine is database.engine or (
            engine is not None and getattr(getattr(engine, "dialect", None), "name", None) != "sqlite"
        ):
            pytest.fail("Offline test attempted a non-test database session; bind the factory to the test database", pytrace=False)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(Session, "__init__", guarded_init)


@pytest.fixture(autouse=True)
def offline_memory_index():
    previous = index._index
    index.set_memory_index(index.NullMemoryIndex())
    try:
        yield
    finally:
        index._index = previous


@pytest.fixture(autouse=True)
def offline_classifier_model(monkeypatch):
    from unittest.mock import AsyncMock
    from app.pai_c.policy import classifier as gate
    monkeypatch.setattr(gate, "complete", AsyncMock(return_value='{"safety":{"level":"none","category":null},"intent":"sharing","emotion":"neutral","request":null,"mentioned_areas":[],"declined_area":null}'))
