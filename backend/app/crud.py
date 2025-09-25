from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy import asc, desc, func, select
from sqlalchemy.orm import Session, selectinload

from .models import (
    Contract,
    Event,
    ExperimentDefinition,
    ExperimentResultRecord,
    ExperimentRunRecord,
    Market,
    ProcessedEvent,
    ProcessedContract,
    ProcessedMarket,
    ProcessingFailure,
    ProcessingRun,
)


@dataclass(slots=True)
class NormalizedContract:
    contract_id: str
    name: str
    outcome_type: str | None
    current_price: float | None
    confidence: float | None
    implied_probability: float | None
    raw_data: dict | None


@dataclass(slots=True)
class NormalizedEvent:
    event_id: str
    slug: str | None
    title: str | None
    description: str | None
    start_time: datetime | None
    end_time: datetime | None
    icon_url: str | None
    series_slug: str | None
    series_title: str | None
    raw_data: dict | None


@dataclass(slots=True)
class NormalizedMarket:
    market_id: str
    slug: str | None
    question: str
    category: str | None
    sub_category: str | None
    open_time: datetime | None
    close_time: datetime | None
    volume_usd: float | None
    liquidity_usd: float | None
    fee_bps: int | None
    status: str
    description: str | None
    icon_url: str | None
    event: NormalizedEvent | None
    contracts: list[NormalizedContract]
    raw_data: dict | None


def upsert_market(session: Session, market: NormalizedMarket) -> None:
    existing = session.get(Market, market.market_id)
    is_new = False
    if existing is None:
        existing = Market(market_id=market.market_id)
        is_new = True

    if market.event and market.event.event_id:
        event_record = upsert_event(session, market.event)
        existing.event = event_record
    else:
        existing.event = None

    existing.slug = market.slug
    existing.question = market.question
    existing.category = market.category
    existing.sub_category = market.sub_category
    existing.open_time = market.open_time
    existing.close_time = market.close_time
    existing.volume_usd = market.volume_usd
    existing.liquidity_usd = market.liquidity_usd
    existing.fee_bps = market.fee_bps
    existing.status = market.status
    existing.description = market.description
    existing.icon_url = market.icon_url
    existing.raw_data = market.raw_data

    existing_contracts = {contract.contract_id: contract for contract in existing.contracts}

    for contract in market.contracts:
        existing_contract = existing_contracts.pop(contract.contract_id, None)
        if existing_contract is None:
            existing_contract = Contract(contract_id=contract.contract_id, market=existing)
            session.add(existing_contract)

        existing_contract.name = contract.name
        existing_contract.outcome_type = contract.outcome_type
        existing_contract.current_price = contract.current_price
        existing_contract.confidence = contract.confidence
        existing_contract.implied_probability = contract.implied_probability
        existing_contract.raw_data = contract.raw_data

    for orphan_contract in existing_contracts.values():
        session.delete(orphan_contract)

    if is_new:
        session.add(existing)


def upsert_event(session: Session, event: NormalizedEvent) -> Event:
    existing = session.get(Event, event.event_id)
    if existing is None:
        existing = Event(event_id=event.event_id)
        session.add(existing)

    existing.slug = event.slug
    existing.title = event.title
    existing.description = event.description
    existing.start_time = event.start_time
    existing.end_time = event.end_time
    existing.icon_url = event.icon_url
    existing.series_slug = event.series_slug
    existing.series_title = event.series_title
    existing.raw_data = event.raw_data
    return existing


@dataclass(slots=True)
class ProcessedContractInput:
    contract_id: str
    name: str
    price: float | None
    attributes: dict | None


@dataclass(slots=True)
class ProcessedMarketInput:
    processed_market_id: str
    run_id: str
    market_id: str
    market_slug: str | None
    question: str
    close_time: datetime | None
    raw_snapshot: dict | None
    processed_event_id: str | None
    contracts: list[ProcessedContractInput]


@dataclass(slots=True)
class ProcessedEventInput:
    processed_event_id: str
    run_id: str
    event_id: str | None
    event_slug: str | None
    event_title: str | None
    raw_snapshot: dict | None


@dataclass(slots=True)
class ExperimentRunInput:
    experiment_run_id: str
    run_id: str
    experiment_name: str
    experiment_version: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    error_message: str | None


@dataclass(slots=True)
class ExperimentResultInput:
    experiment_run_id: str
    processed_market_id: str | None
    processed_event_id: str | None
    payload: dict | None
    score: float | None
    artifact_uri: str | None


@dataclass(slots=True)
class EventGroupRecord:
    event: Event | None
    markets: list[Market] = field(default_factory=list)


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
    record = ProcessingRun(
        run_id=run_id,
        run_date=run_date,
        window_days=window_days,
        target_date=target_date,
        git_sha=git_sha,
        environment=environment,
    )
    session.add(record)
    session.flush()
    return record


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
    run.status = status
    run.total_markets = total_markets
    run.processed_markets = processed_markets
    run.failed_markets = failed_markets
    run.finished_at = finished_at


def record_processed_event(session: Session, payload: ProcessedEventInput) -> ProcessedEvent:
    processed_event = ProcessedEvent(
        processed_event_id=payload.processed_event_id,
        run_id=payload.run_id,
        event_id=payload.event_id,
        event_slug=payload.event_slug,
        event_title=payload.event_title,
        raw_snapshot=payload.raw_snapshot,
    )
    session.add(processed_event)
    session.flush()
    return processed_event


def record_processed_market(session: Session, payload: ProcessedMarketInput) -> ProcessedMarket:
    processed_market = ProcessedMarket(
        processed_market_id=payload.processed_market_id,
        run_id=payload.run_id,
        market_id=payload.market_id,
        market_slug=payload.market_slug,
        question=payload.question,
        close_time=payload.close_time,
        raw_snapshot=payload.raw_snapshot,
        processed_event_id=payload.processed_event_id,
    )
    session.add(processed_market)

    for contract in payload.contracts:
        processed_contract = ProcessedContract(
            processed_market=processed_market,
            contract_id=contract.contract_id,
            name=contract.name,
            price=contract.price,
            attributes=contract.attributes,
        )
        session.add(processed_contract)

    session.flush()
    return processed_market


def record_processing_failure(
    session: Session,
    *,
    run_id: str,
    market_id: str | None,
    reason: str,
    retriable: bool,
    details: dict[str, Any] | None = None,
) -> None:
    failure = ProcessingFailure(
        run_id=run_id,
        market_id=market_id,
        reason=reason,
        retriable=retriable,
        details=details,
    )
    session.add(failure)


def ensure_experiment_definition(
    session: Session,
    *,
    name: str,
    version: str,
    description: str | None = None,
) -> ExperimentDefinition:
    query = select(ExperimentDefinition).where(
        ExperimentDefinition.name == name, ExperimentDefinition.version == version
    )
    existing = session.execute(query).scalar_one_or_none()
    if existing:
        return existing

    definition = ExperimentDefinition(
        name=name,
        version=version,
        description=description,
    )
    session.add(definition)
    session.flush()
    return definition


def record_experiment_run(
    session: Session,
    payload: ExperimentRunInput,
    description: str | None = None,
) -> ExperimentRunRecord:
    definition = ensure_experiment_definition(
        session,
        name=payload.experiment_name,
        version=payload.experiment_version,
        description=description,
    )
    existing = session.get(ExperimentRunRecord, payload.experiment_run_id)
    if existing:
        existing.status = payload.status
        existing.started_at = payload.started_at
        existing.finished_at = payload.finished_at
        existing.error_message = payload.error_message
        return existing

    experiment_run = ExperimentRunRecord(
        experiment_run_id=payload.experiment_run_id,
        run_id=payload.run_id,
        experiment=definition,
        status=payload.status,
        started_at=payload.started_at,
        finished_at=payload.finished_at,
        error_message=payload.error_message,
    )
    session.add(experiment_run)
    session.flush()
    return experiment_run


def record_experiment_result(session: Session, payload: ExperimentResultInput) -> ExperimentResultRecord:
    result = ExperimentResultRecord(
        experiment_run_id=payload.experiment_run_id,
        processed_market_id=payload.processed_market_id,
        processed_event_id=payload.processed_event_id,
        payload=payload.payload,
        score=payload.score,
        artifact_uri=payload.artifact_uri,
    )
    session.add(result)
    session.flush()
    return result


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
    filters = []
    if status:
        filters.append(Market.status == status)
    if close_before:
        filters.append(Market.close_time <= close_before)
    if close_after:
        filters.append(Market.close_time >= close_after)
    if min_volume is not None:
        filters.append(Market.volume_usd >= min_volume)
    if category:
        filters.append(Market.category == category)

    query = (
        select(Market)
        .options(selectinload(Market.contracts), selectinload(Market.event))
        .where(*filters)
    )

    sort_column = {
        "close_time": Market.close_time,
        "volume_usd": Market.volume_usd,
        "liquidity_usd": Market.liquidity_usd,
        "last_synced_at": Market.last_synced_at,
    }.get(sort, Market.close_time)

    sort_direction = asc if order.lower() != "desc" else desc
    query = query.order_by(sort_direction(sort_column)).limit(limit).offset(offset)

    total_query = select(func.count(Market.market_id)).where(*filters)

    markets = session.execute(query).scalars().all()
    total = session.execute(total_query).scalar_one()
    return markets, total


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
    filters = []
    if status:
        filters.append(Market.status == status)
    if close_before:
        filters.append(Market.close_time <= close_before)
    if close_after:
        filters.append(Market.close_time >= close_after)
    if min_volume is not None:
        filters.append(Market.volume_usd >= min_volume)
    if category:
        filters.append(Market.category == category)

    query = (
        select(Market)
        .options(selectinload(Market.contracts), selectinload(Market.event))
        .where(*filters)
    )

    sort_column = {
        "close_time": Market.close_time,
        "volume_usd": Market.volume_usd,
        "liquidity_usd": Market.liquidity_usd,
        "last_synced_at": Market.last_synced_at,
    }.get(sort, Market.close_time)

    sort_direction = asc if order.lower() != "desc" else desc
    query = query.order_by(sort_direction(sort_column))

    markets = session.execute(query).scalars().all()

    grouped: dict[str, EventGroupRecord] = {}
    order_keys: list[str] = []

    for market in markets:
        event = market.event
        if event and event.event_id:
            key = event.event_id
        else:
            key = f"market:{market.market_id}"

        bucket = grouped.get(key)
        if bucket is None:
            bucket = EventGroupRecord(event=event)
            grouped[key] = bucket
            order_keys.append(key)
        bucket.markets.append(market)

    total_events = len(order_keys)
    if offset >= total_events:
        return [], total_events

    sliced_keys = order_keys[offset : offset + limit]
    return [grouped[key] for key in sliced_keys], total_events


def upsert_markets(session: Session, markets: Iterable[NormalizedMarket]) -> None:
    for market in markets:
        upsert_market(session, market)


def get_market(session: Session, market_id: str) -> Market | None:
    query = (
        select(Market)
        .options(selectinload(Market.contracts), selectinload(Market.event))
        .where(Market.market_id == market_id)
    )
    result = session.execute(query).scalar_one_or_none()
    return result
