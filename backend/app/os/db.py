"""Database area of the PAI OS: the `os` schema, its declarative base and the engine."""

from sqlalchemy import Engine, MetaData, create_engine
from sqlalchemy.orm import DeclarativeBase

from app.os.settings import OsSettings

OS_SCHEMA = "os"


class OsBase(DeclarativeBase):
    metadata = MetaData(schema=OS_SCHEMA)


def make_engine(settings: OsSettings) -> Engine:
    return create_engine(settings.database_url, pool_pre_ping=True)
