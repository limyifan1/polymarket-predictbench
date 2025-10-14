"""Typed domain representations used across ingestion, persistence, and APIs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class NormalizedContract:
    """Clean contract snapshot ready for persistence."""

    contract_id: str
    name: str
    outcome_type: str | None
    current_price: float | None
    confidence: float | None
    implied_probability: float | None
    raw_data: dict[str, Any] | None


@dataclass(slots=True)
class NormalizedEvent:
    """Clean event snapshot potentially shared by multiple markets."""

    event_id: str
    slug: str | None
    title: str | None
    description: str | None
    start_time: datetime | None
    end_time: datetime | None
    icon_url: str | None
    series_slug: str | None
    series_title: str | None
    raw_data: dict[str, Any] | None
    is_resolved: bool | None = None
    resolved_at: datetime | None = None
    resolution_source: str | None = None


@dataclass(slots=True)
class NormalizedMarket:
    """Normalized market with nested contracts and optional upstream event."""

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
    contracts: list[NormalizedContract] = field(default_factory=list)
    raw_data: dict[str, Any] | None = None
    is_resolved: bool | None = None
    resolved_at: datetime | None = None
    resolution_source: str | None = None
    winning_outcome: str | None = None
    payout_token: str | None = None
    resolution_tx_hash: str | None = None
    resolution_notes: str | None = None

