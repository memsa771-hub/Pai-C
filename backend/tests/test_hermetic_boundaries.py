"""Regression checks for the test-only provider and database tripwires."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def test_unpatched_provider_factories_are_blocked():
    from app.inference import client
    for factory in (client.create_client, client.create_sync_client, client.create_embedding_client):
        with pytest.raises(pytest.fail.Exception, match="unpatched model provider"):
            factory("fake")


def test_application_and_background_factories_are_blocked():
    from app import database
    for factory in (database.SessionLocal, database.new_session):
        with pytest.raises(pytest.fail.Exception, match="non-test database"):
            factory()


def test_explicit_test_database_factory_is_allowed():
    from app import database
    engine = create_engine("sqlite://")
    factory = sessionmaker(bind=engine)
    previous = database.set_session_factory(factory)
    try:
        with database.new_session() as session:
            assert session.get_bind() is engine
    finally:
        database.set_session_factory(previous)
        engine.dispose()
