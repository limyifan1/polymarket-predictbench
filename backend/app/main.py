from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query

from . import crud, schemas
from .core.config import settings
from .db import get_db, init_db

app = FastAPI(title="PredictBench API", version="0.1.0", debug=settings.debug)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/healthz", tags=["system"])
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


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
    db=Depends(get_db),
):
    groups, total = crud.list_events(
        db,
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

    items: list[schemas.EventWithMarkets] = []
    for group in groups:
        markets = [schemas.Market.model_validate(market) for market in group.markets]
        if group.event is not None:
            event_payload = schemas.Event.model_validate(group.event)
        else:
            primary = markets[0] if markets else None
            event_payload = schemas.Event(
                event_id=f"market:{primary.market_id}" if primary else "unknown",
                slug=primary.slug if primary else None,
                title=primary.question if primary else None,
                description=primary.description if primary else None,
                start_time=primary.open_time if primary else None,
                end_time=primary.close_time if primary else None,
                icon_url=primary.icon_url if primary else None,
                series_slug=None,
                series_title=None,
            )

        items.append(
            schemas.EventWithMarkets(
                **event_payload.model_dump(),
                markets=markets,
                market_count=len(markets),
            )
        )

    return schemas.EventList(total=total, items=items)


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
    db=Depends(get_db),
):
    markets, total = crud.list_markets(
        db,
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
    items = [schemas.Market.model_validate(market) for market in markets]
    return schemas.MarketList(total=total, items=items)


@app.get("/markets/{market_id}", response_model=schemas.Market, tags=["markets"])
def get_market(market_id: str, db=Depends(get_db)):
    market = crud.get_market(db, market_id)
    if not market:
        raise HTTPException(status_code=404, detail="Market not found")
    return schemas.Market.model_validate(market)
