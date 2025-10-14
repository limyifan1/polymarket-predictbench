"""Market-focused data access helpers."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import datetime
from typing import Any, Sequence

from sqlalchemy import asc, desc, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.domain import NormalizedEvent, NormalizedMarket
from app.models import Contract, Event, Market

from .types import EventGroupRecord


class MarketRepository:
    """Encapsulate all market and event persistence concerns."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Mutations

    def upsert_market(self, market: NormalizedMarket) -> Market:
        existing = self._session.get(Market, market.market_id)
        is_new = False
        if existing is None:
            existing = Market(market_id=market.market_id)
            is_new = True

        if market.event and market.event.event_id:
            event_record = self.upsert_event(market.event)
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
        if market.is_resolved is not None:
            existing.is_resolved = bool(market.is_resolved)
        if market.resolved_at is not None:
            existing.resolved_at = market.resolved_at
        if market.resolution_source is not None:
            existing.resolution_source = market.resolution_source
        if market.winning_outcome is not None:
            existing.winning_outcome = market.winning_outcome
        if market.payout_token is not None:
            existing.payout_token = market.payout_token
        if market.resolution_tx_hash is not None:
            existing.resolution_tx_hash = market.resolution_tx_hash
        if market.resolution_notes is not None:
            existing.resolution_notes = market.resolution_notes

        existing_contracts = {contract.contract_id: contract for contract in existing.contracts}

        for contract in market.contracts:
            existing_contract = existing_contracts.pop(contract.contract_id, None)
            if existing_contract is None:
                existing_contract = Contract(contract_id=contract.contract_id, market=existing)
                self._session.add(existing_contract)

            existing_contract.name = contract.name
            existing_contract.outcome_type = contract.outcome_type
            existing_contract.current_price = contract.current_price
            existing_contract.confidence = contract.confidence
            existing_contract.implied_probability = contract.implied_probability
            existing_contract.raw_data = contract.raw_data

        for orphan_contract in existing_contracts.values():
            self._session.delete(orphan_contract)

        if is_new:
            self._session.add(existing)

        return existing

    def upsert_markets(self, markets: Iterable[NormalizedMarket]) -> None:
        for market in markets:
            self.upsert_market(market)

    def upsert_event(self, event: NormalizedEvent) -> Event:
        existing = self._session.get(Event, event.event_id)
        if existing is None:
            existing = Event(event_id=event.event_id)
            self._session.add(existing)

        existing.slug = event.slug
        existing.title = event.title
        existing.description = event.description
        existing.start_time = event.start_time
        existing.end_time = event.end_time
        existing.icon_url = event.icon_url
        existing.series_slug = event.series_slug
        existing.series_title = event.series_title
        existing.raw_data = event.raw_data
        if event.is_resolved is not None:
            existing.is_resolved = bool(event.is_resolved)
        if event.resolved_at is not None:
            existing.resolved_at = event.resolved_at
        if event.resolution_source is not None:
            existing.resolution_source = event.resolution_source
        return existing

    # ------------------------------------------------------------------
    # Queries

    def list_markets(
        self,
        *,
        status: str | None = None,
        close_before: datetime | None = None,
        close_after: datetime | None = None,
        min_volume: float | None = None,
        category: str | None = None,
        is_resolved: bool | None = None,
        resolution_source: str | None = None,
        sort: str = "close_time",
        order: str = "asc",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Market], int]:
        filters: list[Any] = []
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
        if is_resolved is not None:
            filters.append(Market.is_resolved.is_(is_resolved))
        if resolution_source:
            filters.append(Market.resolution_source == resolution_source)

        query = (
            select(Market)
            .options(
                selectinload(Market.contracts),
                selectinload(Market.event),
                selectinload(Market.uma_resolution_events),
            )
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

        markets = self._session.execute(query).scalars().all()
        total = self._session.execute(total_query).scalar_one()
        return markets, total

    def list_events(
        self,
        *,
        status: str | None = None,
        close_before: datetime | None = None,
        close_after: datetime | None = None,
        min_volume: float | None = None,
        category: str | None = None,
        is_resolved: bool | None = None,
        resolution_source: str | None = None,
        sort: str = "close_time",
        order: str = "asc",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[EventGroupRecord], int]:
        filters: list[Any] = []
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
        if is_resolved is not None:
            filters.append(Market.is_resolved.is_(is_resolved))
        if resolution_source:
            filters.append(
                or_(
                    Market.resolution_source == resolution_source,
                    Event.resolution_source == resolution_source,
                )
            )

        query = (
            select(Market)
            .join(Event, Market.event, isouter=True)
            .options(
                selectinload(Market.contracts),
                selectinload(Market.event),
                selectinload(Market.uma_resolution_events),
            )
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

        markets = self._session.execute(query).scalars().all()

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

    def get_market(self, market_id: str) -> Market | None:
        query = (
            select(Market)
            .options(
                selectinload(Market.contracts),
                selectinload(Market.event),
                selectinload(Market.uma_resolution_events),
            )
            .where(Market.market_id == market_id)
        )
        return self._session.execute(query).scalar_one_or_none()

    def get_unresolved_markets(
        self,
        *,
        limit: int | None = None,
        event_ids: Sequence[str] | None = None,
        recent_cutoff: datetime | None = None,
    ) -> list[Market]:
        filters: list[Any] = [or_(Market.is_resolved.is_(False), Market.is_resolved.is_(None))]
        if event_ids:
            filters.append(Market.event_id.in_(list(event_ids)))
        if recent_cutoff is not None:
            filters.append(Market.last_synced_at >= recent_cutoff)

        query = (
            select(Market)
            .options(
                selectinload(Market.event),
                selectinload(Market.uma_resolution_events),
            )
            .where(*filters)
            .order_by(
                Market.close_time.asc().nulls_last(),
                Market.market_id.asc(),
            )
        )
        if limit:
            query = query.limit(limit)
        return self._session.execute(query).scalars().all()

    def refresh_event_resolution(self, event_id: str) -> Event | None:
        event = self._session.get(Event, event_id)
        if not event:
            return None

        markets = list(event.markets)
        if not markets:
            event.is_resolved = False
            event.resolved_at = None
            event.resolution_source = None
            return event

        unresolved = [market for market in markets if not market.is_resolved]
        if unresolved:
            event.is_resolved = False
            event.resolved_at = None
            event.resolution_source = None
            return event

        event.is_resolved = True
        event.resolved_at = max(
            (market.resolved_at for market in markets if market.resolved_at),
            default=None,
        )
        sources = Counter(
            market.resolution_source for market in markets if market.resolution_source
        )
        event.resolution_source = sources.most_common(1)[0][0] if sources else None
        return event


__all__ = ["MarketRepository", "EventGroupRecord"]
