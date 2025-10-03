from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
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
    connect_args: dict[str, object] = {}
    engine_kwargs: dict[str, object] = {
        "echo": settings.debug,
        "future": True,
        "pool_pre_ping": True,
    }

    parsed = make_url(url)
    backend = parsed.get_backend_name()

    if backend == "sqlite":
        connect_args["check_same_thread"] = False
        _ensure_sqlite_path(url)
    else:
        # Recycle long-lived connections so Supabase/PgBouncer idle timeouts
        # do not kill them mid-run, and rely on pre-ping to revive stale ones.
        engine_kwargs["pool_recycle"] = 300

        if backend.startswith("postgresql"):
            connect_args.setdefault("keepalives", 1)
            connect_args.setdefault("keepalives_idle", 120)
            connect_args.setdefault("keepalives_interval", 30)
            connect_args.setdefault("keepalives_count", 5)
            # PgBouncer in transaction-pooling mode does not support reusing server-side
            # prepared statements; disable them so psycopg does not reissue duplicates
            # during large batch inserts (see GitHub Actions daily pipeline failures).
            connect_args.setdefault("prepare_threshold", 0)

    if connect_args:
        engine_kwargs["connect_args"] = connect_args

    return create_engine(url, **engine_kwargs)


def _create_session_factory(engine) -> sessionmaker[Session]:
    # Enable autoflush so repeated upserts in a single transaction can see newly
    # added objects via Session.get; without this, offset pagination returning the
    # same market twice would surface as a UNIQUE constraint violation.
    return sessionmaker(bind=engine, autoflush=True, autocommit=False, future=True)


def _build_db_components(url: str):
    engine = _create_engine(url)
    session_factory = _create_session_factory(engine)
    return engine, session_factory


engine, SessionLocal = _build_db_components(settings.resolved_database_url)
Base = declarative_base()


def _ensure_column(engine, table: str, column: str, definition: str) -> None:
    inspector = inspect(engine)
    columns = {col["name"] for col in inspector.get_columns(table)}
    if column in columns:
        return
    with engine.begin() as connection:
        connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))


def _apply_schema_updates() -> None:
    _ensure_column(engine, "markets", "event_id", "VARCHAR")
    _ensure_column(engine, "processed_markets", "processed_event_id", "VARCHAR")
    _ensure_column(engine, "experiment_results", "processed_event_id", "VARCHAR")
    _ensure_column(engine, "experiment_runs", "stage", "VARCHAR")
    _ensure_column(engine, "experiment_results", "stage", "VARCHAR")
    _ensure_column(engine, "experiment_results", "variant_name", "VARCHAR")
    _ensure_column(engine, "experiment_results", "variant_version", "VARCHAR")
    _ensure_column(engine, "experiment_results", "source_artifact_id", "VARCHAR")


def get_db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _apply_schema_updates()
