from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ContractBase(BaseModel):
    contract_id: str
    market_id: str
    name: str
    outcome_type: str | None = None
    current_price: float | None = None
    confidence: float | None = None
    implied_probability: float | None = None

    @field_validator("current_price", "confidence", "implied_probability", mode="before")
    @classmethod
    def _coerce_decimal(cls, value: Any) -> float | None:
        if value is None:
            return None
        return float(value)


class Contract(ContractBase):
    raw_data: dict[str, Any] | None = None

    model_config = {"from_attributes": True}


class MarketBase(BaseModel):
    market_id: str
    slug: str | None = None
    question: str
    category: str | None = None
    sub_category: str | None = None
    open_time: datetime | None = None
    close_time: datetime | None = None
    volume_usd: float | None = None
    liquidity_usd: float | None = None
    fee_bps: int | None = None
    status: str
    archived: bool
    last_synced_at: datetime
    description: str | None = None
    icon_url: str | None = None

    @field_validator("volume_usd", "liquidity_usd", mode="before")
    @classmethod
    def _coerce_numeric(cls, value: Any) -> float | None:
        if value is None:
            return None
        return float(value)


class Event(BaseModel):
    event_id: str
    slug: str | None = None
    title: str | None = None
    description: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    icon_url: str | None = None
    series_slug: str | None = None
    series_title: str | None = None

    model_config = {"from_attributes": True}


class Market(MarketBase):
    contracts: list[Contract] = Field(default_factory=list)
    event: Event | None = None

    model_config = {"from_attributes": True}


class MarketList(BaseModel):
    total: int
    items: list[Market]


class EventWithMarkets(Event):
    markets: list[Market] = Field(default_factory=list)
    market_count: int


class EventList(BaseModel):
    total: int
    items: list[EventWithMarkets]
