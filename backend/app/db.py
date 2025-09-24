from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from .core.config import settings


def _ensure_sqlite_path(url: str) -> None:
    if not url.startswith("sqlite"):
        return

    parsed = make_url(url)
    database = parsed.database
    if not database or database == ":memory:":
        return

    path = Path(database)
    path.parent.mkdir(parents=True, exist_ok=True)


def _create_engine(url: str):
    connect_args = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        _ensure_sqlite_path(url)
    return create_engine(url, echo=settings.debug, connect_args=connect_args, future=True)


def _create_session_factory(engine) -> sessionmaker[Session]:
    # Enable autoflush so repeated upserts in a single transaction can see newly
    # added objects via Session.get; without this, offset pagination returning the
    # same market twice would surface as a UNIQUE constraint violation.
    return sessionmaker(bind=engine, autoflush=True, autocommit=False, future=True)


def _build_db_components(url: str):
    engine = _create_engine(url)
    session_factory = _create_session_factory(engine)
    return engine, session_factory


engine, SessionLocal = _build_db_components(settings.database_url)
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
