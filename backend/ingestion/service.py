from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import SessionLocal
from app.repositories import MarketRepository

from .client import PolymarketClient
from .normalize import normalize_market


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _isoformat_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@contextmanager
def session_scope() -> Session:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def ingest_open_markets(*, force_close_after_now: bool = False) -> int:
    base_filters: dict[str, Any] = dict(settings.ingestion_filters)
    if force_close_after_now:
        now = datetime.now(timezone.utc)
        existing_end_min = _parse_datetime(base_filters.get("end_date_min"))
        target = existing_end_min if existing_end_min and existing_end_min > now else now
        base_filters["end_date_min"] = _isoformat_utc(target)

    count = 0
    client_kwargs = {"filters": base_filters} if base_filters else {}
    with PolymarketClient(**client_kwargs) as client:
        with session_scope() as session:
            market_repo = MarketRepository(session)
            for raw_market in client.iter_markets():
                normalized = normalize_market(raw_market)
                market_repo.upsert_market(normalized)
                count += 1
    logger.info("Ingested {} markets", count)
    return count
