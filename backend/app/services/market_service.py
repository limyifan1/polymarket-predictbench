"""Higher-level conveniences for interacting with market persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

from sqlalchemy.orm import Session

from app.repositories import EventGroupRecord, MarketRepository
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

    def to_repository_kwargs(self) -> dict[str, Any]:
        """Serialize the query so repository functions receive consistent kwargs."""

        return {
            "status": self.status,
            "close_before": self.close_before,
            "close_after": self.close_after,
            "min_volume": self.min_volume,
            "category": self.category,
            "sort": self.sort,
            "order": self.order,
            "limit": self.limit,
            "offset": self.offset,
        }


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
        raw_markets, total = self._market_repo.list_markets(**query.to_repository_kwargs())
        markets = self._normalize_markets(raw_markets)
        return MarketQueryResult(total=total, markets=markets)

    def list_events(self, query: MarketQuery) -> EventQueryResult:
        groups, total = self._market_repo.list_events(**query.to_repository_kwargs())
        events = [self._build_event_payload(group) for group in groups]
        return EventQueryResult(total=total, events=events)

    def get_market(self, market_id: str) -> Market | None:
        market = self._market_repo.get_market(market_id)
        if not market:
            return None
        return Market.model_validate(market)

    def _normalize_markets(self, raw_markets: Sequence[Any]) -> list[Market]:
        """Convert ORM models into API schemas while preserving order."""

        return [Market.model_validate(market) for market in raw_markets]

    def _build_event_payload(self, group: EventGroupRecord) -> EventWithMarkets:
        """Adapt repository event groups into the API schema."""

        markets = self._normalize_markets(group.markets)
        if group.event is not None:
            event_model = Event.model_validate(group.event)
            return EventWithMarkets(
                **event_model.model_dump(),
                markets=markets,
                market_count=len(markets),
            )

        primary = markets[0] if markets else None
        return EventWithMarkets(
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
