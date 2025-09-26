from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.domain import NormalizedEvent, NormalizedMarket
from app.repositories import MarketRepository, ProcessingRepository
from app.repositories.pipeline_models import (
    ExperimentResultInput,
    ExperimentRunInput,
    ProcessedContractInput,
    ProcessedEventInput,
    ProcessedMarketInput,
    ResearchArtifactInput,
)
from app.repositories.types import EventGroupRecord

from .models import (
    Event,
    ExperimentDefinition,
    ExperimentResultRecord,
    ExperimentRunRecord,
    Market,
    ProcessedEvent,
    ProcessedMarket,
    ProcessingRun,
    ResearchArtifactRecord,
)


def upsert_market(session: Session, market: NormalizedMarket) -> Market:
    return MarketRepository(session).upsert_market(market)


def upsert_event(session: Session, event: NormalizedEvent) -> Event:
    return MarketRepository(session).upsert_event(event)
def create_processing_run(
    session: Session,
    *,
    run_id: str,
    run_date: date,
    window_days: int,
    target_date: date,
    git_sha: str | None,
    environment: str | None,
) -> ProcessingRun:
    repo = ProcessingRepository(session)
    return repo.create_processing_run(
        run_id=run_id,
        run_date=run_date,
        window_days=window_days,
        target_date=target_date,
        git_sha=git_sha,
        environment=environment,
    )


def finalize_processing_run(
    session: Session,
    run: ProcessingRun,
    *,
    status: str,
    total_markets: int,
    processed_markets: int,
    failed_markets: int,
    finished_at: datetime,
) -> None:
    ProcessingRepository(session).finalize_processing_run(
        run,
        status=status,
        total_markets=total_markets,
        processed_markets=processed_markets,
        failed_markets=failed_markets,
        finished_at=finished_at,
    )


def record_processed_event(session: Session, payload: ProcessedEventInput) -> ProcessedEvent:
    return ProcessingRepository(session).record_processed_event(payload)


def record_processed_market(session: Session, payload: ProcessedMarketInput) -> ProcessedMarket:
    return ProcessingRepository(session).record_processed_market(payload)


def record_processing_failure(
    session: Session,
    *,
    run_id: str,
    market_id: str | None,
    reason: str,
    retriable: bool,
    details: dict[str, Any] | None = None,
) -> None:
    ProcessingRepository(session).record_processing_failure(
        run_id=run_id,
        market_id=market_id,
        reason=reason,
        retriable=retriable,
        details=details,
    )


def ensure_experiment_definition(
    session: Session,
    *,
    name: str,
    version: str,
    description: str | None = None,
) -> ExperimentDefinition:
    return ProcessingRepository(session).ensure_experiment_definition(
        name=name,
        version=version,
        description=description,
    )


def record_experiment_run(
    session: Session,
    payload: ExperimentRunInput,
    description: str | None = None,
) -> ExperimentRunRecord:
    return ProcessingRepository(session).record_experiment_run(
        payload,
        description=description,
    )


def record_research_artifact(
    session: Session, payload: ResearchArtifactInput
) -> ResearchArtifactRecord:
    return ProcessingRepository(session).record_research_artifact(payload)


def record_experiment_result(session: Session, payload: ExperimentResultInput) -> ExperimentResultRecord:
    return ProcessingRepository(session).record_experiment_result(payload)


def list_markets(
    session: Session,
    *,
    status: str | None = None,
    close_before: datetime | None = None,
    close_after: datetime | None = None,
    min_volume: float | None = None,
    category: str | None = None,
    sort: str = "close_time",
    order: str = "asc",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Market], int]:
    return MarketRepository(session).list_markets(
        status=status,
        close_before=close_before,
        close_after=close_after,
        min_volume=min_volume,
        category=category,
        sort=sort,
        order=order,
        limit=limit,
        offset=offset,
    )


def list_events(
    session: Session,
    *,
    status: str | None = None,
    close_before: datetime | None = None,
    close_after: datetime | None = None,
    min_volume: float | None = None,
    category: str | None = None,
    sort: str = "close_time",
    order: str = "asc",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[EventGroupRecord], int]:
    return MarketRepository(session).list_events(
        status=status,
        close_before=close_before,
        close_after=close_after,
        min_volume=min_volume,
        category=category,
        sort=sort,
        order=order,
        limit=limit,
        offset=offset,
    )


def upsert_markets(session: Session, markets: Iterable[NormalizedMarket]) -> None:
    MarketRepository(session).upsert_markets(markets)


def get_market(session: Session, market_id: str) -> Market | None:
    return MarketRepository(session).get_market(market_id)
