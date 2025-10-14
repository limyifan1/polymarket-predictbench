from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from .core.config import settings


def _psycopg_supports_cache_flag(version_str: str) -> bool:
    """Return True if psycopg accepts the prepared_statement_cache_size option."""

    parts: list[int] = []
    for token in version_str.split("."):
        digits = ""
        for char in token:
            if char.isdigit():
                digits += char
            else:
                break
        if not digits:
            break
        parts.append(int(digits))
        if len(parts) >= 3:
            break
    if not parts:
        return False
    return tuple(parts) < (3, 2)


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
    driver = parsed.get_driver_name()

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
            # PgBouncer's transaction pooler rejects PREPARE, so disable psycopg's
            # automatic server-side statements to keep Supabase connections healthy.
            if driver == "psycopg":
                connect_args.setdefault("prepare_threshold", None)

                try:  # psycopg<3.2 accepted prepared_statement_cache_size
                    import psycopg  # type: ignore[import]
                except ImportError:  # pragma: no cover - psycopg always available in prod
                    pass
                else:
                    if _psycopg_supports_cache_flag(psycopg.__version__):
                        connect_args.setdefault("prepared_statement_cache_size", 0)

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


def _backfill_processed_event_keys() -> None:
    from .models import ProcessedEvent

    with SessionLocal() as session:
        query = select(ProcessedEvent).where(ProcessedEvent.event_key.is_(None))
        events = session.execute(query).scalars().all()
        if not events:
            return

        updated = 0
        for event in events:
            if event.event_key:
                continue
            if event.event_id:
                event.event_key = event.event_id
            else:
                market_ids = sorted(
                    market.market_id for market in event.markets if market.market_id
                )
                if market_ids:
                    event.event_key = "market:" + ",".join(market_ids)
            if event.event_key:
                updated += 1

        if updated:
            session.commit()
        else:
            session.rollback()


def _apply_schema_updates() -> None:
    dialect_name = engine.dialect.name
    boolean_default = "BOOLEAN DEFAULT FALSE" if dialect_name == "postgresql" else "BOOLEAN DEFAULT 0"
    false_literal = "FALSE" if dialect_name == "postgresql" else "0"
    timestamp_type = (
        "TIMESTAMP WITH TIME ZONE" if dialect_name == "postgresql" else "TIMESTAMP"
    )
    _ensure_column(engine, "markets", "event_id", "VARCHAR")
    _ensure_column(engine, "processed_markets", "processed_event_id", "VARCHAR")
    _ensure_column(engine, "processed_events", "event_key", "VARCHAR")
    _ensure_column(engine, "experiment_results", "processed_event_id", "VARCHAR")
    _ensure_column(engine, "experiment_runs", "stage", "VARCHAR")
    _ensure_column(engine, "experiment_results", "stage", "VARCHAR")
    _ensure_column(engine, "experiment_results", "variant_name", "VARCHAR")
    _ensure_column(engine, "experiment_results", "variant_version", "VARCHAR")
    _ensure_column(engine, "research_artifacts", "experiment_run_id", "VARCHAR")
    _ensure_column(engine, "research_artifacts", "research_run_id", "VARCHAR")
    _ensure_column(engine, "markets", "is_resolved", boolean_default)
    _ensure_column(engine, "markets", "resolved_at", timestamp_type)
    _ensure_column(engine, "markets", "resolution_source", "VARCHAR(50)")
    _ensure_column(engine, "markets", "winning_outcome", "VARCHAR(255)")
    _ensure_column(engine, "markets", "payout_token", "VARCHAR(20)")
    _ensure_column(engine, "markets", "resolution_tx_hash", "VARCHAR(66)")
    _ensure_column(engine, "markets", "resolution_notes", "TEXT")
    _ensure_column(engine, "events", "is_resolved", boolean_default)
    _ensure_column(engine, "events", "resolved_at", timestamp_type)
    _ensure_column(engine, "events", "resolution_source", "VARCHAR(50)")
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE research_artifacts"
                " SET experiment_run_id = research_run_id"
                " WHERE experiment_run_id IS NULL AND research_run_id IS NOT NULL"
            )
        )
        connection.execute(
            text(
                f"UPDATE markets SET is_resolved = COALESCE(is_resolved, {false_literal})"
            )
        )
        connection.execute(
            text(
                f"UPDATE events SET is_resolved = COALESCE(is_resolved, {false_literal})"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_markets_is_resolved ON markets (is_resolved)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_markets_event_is_resolved ON markets (event_id, is_resolved)"
            )
        )
    _backfill_processed_event_keys()


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
