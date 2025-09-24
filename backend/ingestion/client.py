from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Iterable

import httpx
from loguru import logger

from app.core.config import settings


ALLOWED_FILTER_KEYS = {
    "limit",
    "offset",
    "order",
    "ascending",
    "id",
    "slug",
    "clob_token_ids",
    "condition_ids",
    "market_maker_address",
    "liquidity_num_min",
    "liquidity_num_max",
    "volume_num_min",
    "volume_num_max",
    "start_date_min",
    "start_date_max",
    "end_date_min",
    "end_date_max",
    "tag_id",
    "related_tags",
    "cyom",
    "uma_resolution_status",
    "game_id",
    "sports_market_types",
    "rewards_min_size",
    "question_ids",
    "include_tag",
    "closed",
}


class PolymarketClient:
    """Thin wrapper around Polymarket public endpoints."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        markets_path: str | None = None,
        page_size: int | None = None,
        filters: dict[str, Any] | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.base_url = base_url or str(settings.polymarket_base_url)
        self.markets_path = markets_path or settings.polymarket_markets_path
        self.page_size = page_size or settings.ingestion_page_size
        base_filters = settings.ingestion_filters if filters is None else filters
        normalized_filters = dict(base_filters)
        self.filters = {
            key: value for key, value in normalized_filters.items() if key in ALLOWED_FILTER_KEYS
        }
        dropped_filters = sorted(set(normalized_filters) - ALLOWED_FILTER_KEYS)
        if dropped_filters:
            logger.warning(
                "Dropped unsupported Polymarket query filters from configuration: {}",
                ", ".join(dropped_filters),
            )
        self.timeout = timeout
        self.client = httpx.Client(base_url=self.base_url, timeout=timeout)

    def _build_params(self, *, cursor: str | None, offset: int) -> dict[str, Any]:
        params: dict[str, Any] = {
            "limit": self.page_size,
            "offset": offset,
        }
        if cursor:
            params["cursor"] = cursor
        if self.filters:
            for key, value in self.filters.items():
                serialized = self._serialize_filter_value(value)
                if serialized is not None:
                    params[key] = serialized
        return params

    @staticmethod
    def _serialize_filter_value(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            parts: list[str] = []
            for item in value:
                serialized = PolymarketClient._serialize_filter_value(item)
                if serialized is not None:
                    parts.append(serialized)
            return ",".join(parts) if parts else None
        return str(value)

    def fetch_page(self, *, cursor: str | None, offset: int) -> dict[str, Any]:
        params = self._build_params(cursor=cursor, offset=offset)
        logger.info("Polymarket GET {} params={}", self.markets_path, params)
        response = self.client.get(self.markets_path, params=params)
        response.raise_for_status()
        return response.json()

    def iter_markets(self) -> Iterable[dict[str, Any]]:
        cursor: str | None = None
        offset = 0
        while True:
            payload = self.fetch_page(cursor=cursor, offset=offset)

            next_cursor: str | None = None
            if isinstance(payload, list):
                raw_markets = payload
            elif isinstance(payload, dict):
                candidates: tuple[Any, ...] = (
                    payload.get("markets"),
                    payload.get("data"),
                    payload.get("result"),
                )
                raw_markets = next(
                    (value for value in candidates if isinstance(value, list)), []
                )
                if not raw_markets:
                    single_market = payload.get("market")
                    raw_markets = (
                        [single_market] if isinstance(single_market, dict) else []
                    )
                next_cursor = payload.get("cursor") or payload.get("nextCursor")
            else:
                raw_markets = []

            if not raw_markets:
                break

            for market in raw_markets:
                yield market

            if next_cursor:
                cursor = next_cursor
                offset = 0
            else:
                cursor = None
                offset += self.page_size

            if not cursor and len(raw_markets) < self.page_size:
                break

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "PolymarketClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
