"""SQLAlchemy engine + session factory. Import get_session everywhere."""
from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from config.settings import settings
from data.models.schema import Base

_connect_args: dict = {}
if "sqlite" in settings.database_url:
    _connect_args["check_same_thread"] = False

engine = create_engine(
    settings.database_url,
    echo=(settings.log_level.upper() == "DEBUG"),
    **(_connect_args and {"connect_args": _connect_args}),
)

if "sqlite" in settings.database_url:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn: object, _: object) -> None:
        cursor = dbapi_conn.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def create_tables() -> None:
    """Create all tables. Run once on first setup: invest db-init"""
    Base.metadata.create_all(bind=engine)


def drop_tables() -> None:
    """Drop all tables. Destructive — dev only."""
    Base.metadata.drop_all(bind=engine)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
