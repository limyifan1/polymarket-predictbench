from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import asc, desc, func, select
from sqlalchemy.orm import Session, selectinload

from .models import Contract, Market


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
    contracts: list[NormalizedContract]
    raw_data: dict | None


def upsert_market(session: Session, market: NormalizedMarket) -> None:
    existing = session.get(Market, market.market_id)
    if existing is None:
        existing = Market(market_id=market.market_id)
        session.add(existing)

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

    query = select(Market).options(selectinload(Market.contracts)).where(*filters)

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


def upsert_markets(session: Session, markets: Iterable[NormalizedMarket]) -> None:
    for market in markets:
        upsert_market(session, market)


def get_market(session: Session, market_id: str) -> Market | None:
    query = (
        select(Market)
        .options(selectinload(Market.contracts))
        .where(Market.market_id == market_id)
    )
    result = session.execute(query).scalar_one_or_none()
    return result
