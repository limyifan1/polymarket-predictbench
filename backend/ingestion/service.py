from __future__ import annotations

from contextlib import contextmanager

from loguru import logger
from sqlalchemy.orm import Session

from app import crud
from app.db import SessionLocal

from .client import PolymarketClient
from .normalize import normalize_market


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


def ingest_open_markets() -> int:
    count = 0
    with PolymarketClient() as client:
        with session_scope() as session:
            for raw_market in client.iter_markets():
                normalized = normalize_market(raw_market)
                crud.upsert_market(session, normalized)
                count += 1
    logger.info("Ingested {} markets", count)
    return count
