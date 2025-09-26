"""Higher-level conveniences for interacting with market persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from sqlalchemy.orm import Session

from app.repositories import MarketRepository
from app.schemas import Event, EventWithMarkets, Market


@dataclass(slots=True)
class MarketQuery:
    status: str | None = None
    close_before: datetime | None = None
    close_after: datetime | None = None
    min_volume: float | None = None
    category: str | None = None
    sort: str = "close_time"
    order: str = "asc"
    limit: int = 50
    offset: int = 0


@dataclass(slots=True)
class MarketQueryResult:
    total: int
    markets: Sequence[Market]


@dataclass(slots=True)
class EventQueryResult:
    total: int
    events: Sequence[EventWithMarkets]


class MarketService:
    """Read-only facade over market listings used by the API and experiments."""

    def __init__(self, session: Session):
        self._session = session
        self._market_repo = MarketRepository(session)

    def list_markets(self, query: MarketQuery) -> MarketQueryResult:
        raw_markets, total = self._market_repo.list_markets(
            status=query.status,
            close_before=query.close_before,
            close_after=query.close_after,
            min_volume=query.min_volume,
            category=query.category,
            sort=query.sort,
            order=query.order,
            limit=query.limit,
            offset=query.offset,
        )
        markets = [Market.model_validate(market) for market in raw_markets]
        return MarketQueryResult(total=total, markets=markets)

    def list_events(self, query: MarketQuery) -> EventQueryResult:
        groups, total = self._market_repo.list_events(
            status=query.status,
            close_before=query.close_before,
            close_after=query.close_after,
            min_volume=query.min_volume,
            category=query.category,
            sort=query.sort,
            order=query.order,
            limit=query.limit,
            offset=query.offset,
        )
        events: list[EventWithMarkets] = []
        for group in groups:
            markets = [Market.model_validate(market) for market in group.markets]
            if group.event is not None:
                event_model = Event.model_validate(group.event)
                event_payload = EventWithMarkets(
                    **event_model.model_dump(),
                    markets=markets,
                    market_count=len(markets),
                )
            else:
                primary = markets[0] if markets else None
                event_payload = EventWithMarkets(
                    event_id=f"market:{primary.market_id}" if primary else "unknown",
                    slug=primary.slug if primary else None,
                    title=primary.question if primary else None,
                    description=primary.description if primary else None,
                    start_time=primary.open_time if primary else None,
                    end_time=primary.close_time if primary else None,
                    icon_url=primary.icon_url if primary else None,
                    series_slug=None,
                    series_title=None,
                    markets=markets,
                    market_count=len(markets),
                )
            events.append(event_payload)
        return EventQueryResult(total=total, events=events)

    def get_market(self, market_id: str) -> Market | None:
        market = self._market_repo.get_market(market_id)
        if not market:
            return None
        return Market.model_validate(market)
