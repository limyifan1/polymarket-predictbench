from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query

from . import schemas
from .core.config import settings
from .db import get_db, init_db
from .services.market_service import MarketQuery, MarketService

app = FastAPI(title="PredictBench API", version="0.1.0", debug=settings.debug)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/healthz", tags=["system"])
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


def _build_market_query(
    *,
    status: str | None,
    close_before: datetime | None,
    close_after: datetime | None,
    min_volume: float | None,
    category: str | None,
    sort: str,
    order: str,
    limit: int,
    offset: int,
) -> MarketQuery:
    return MarketQuery(
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


def _market_service(db=Depends(get_db)) -> MarketService:
    return MarketService(db)


@app.get("/events", response_model=schemas.EventList, tags=["events"])
def list_events(
    *,
    status: Annotated[str | None, Query(description="Market status filter", example="open")] = "open",
    close_before: Annotated[datetime | None, Query(description="Return events with markets closing before this timestamp")] = None,
    close_after: Annotated[datetime | None, Query(description="Return events with markets closing after this timestamp")] = None,
    min_volume: Annotated[float | None, Query(description="Minimum market volume in USD")] = None,
    category: Annotated[str | None, Query(description="Category filter")] = None,
    sort: Annotated[str, Query(description="Field to sort by", pattern="^(close_time|volume_usd|liquidity_usd|last_synced_at)$")] = "close_time",
    order: Annotated[str, Query(description="Sort order (asc|desc)", pattern="^(asc|desc)$", min_length=3, max_length=4)] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    service: MarketService = Depends(_market_service),
):
    query = _build_market_query(
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
    result = service.list_events(query)
    return schemas.EventList(total=result.total, items=list(result.events))


@app.get("/markets", response_model=schemas.MarketList, tags=["markets"])
def list_markets(
    *,
    status: Annotated[str | None, Query(description="Market status filter", example="open")] = "open",
    close_before: Annotated[datetime | None, Query(description="Return markets closing before this timestamp")] = None,
    close_after: Annotated[datetime | None, Query(description="Return markets closing after this timestamp")] = None,
    min_volume: Annotated[float | None, Query(description="Minimum volume in USD")] = None,
    category: Annotated[str | None, Query(description="Category filter")] = None,
    sort: Annotated[str, Query(description="Field to sort by", pattern="^(close_time|volume_usd|liquidity_usd|last_synced_at)$")] = "close_time",
    order: Annotated[str, Query(description="Sort order (asc|desc)", pattern="^(asc|desc)$", min_length=3, max_length=4)] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    service: MarketService = Depends(_market_service),
):
    query = _build_market_query(
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
    result = service.list_markets(query)
    return schemas.MarketList(total=result.total, items=list(result.markets))


@app.get("/markets/{market_id}", response_model=schemas.Market, tags=["markets"])
def get_market(market_id: str, service: MarketService = Depends(_market_service)):
    market = service.get_market(market_id)
    if not market:
        raise HTTPException(status_code=404, detail="Market not found")
    return market
