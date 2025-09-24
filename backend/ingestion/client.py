from __future__ import annotations

from typing import Any, Iterable

import httpx

from app.core.config import settings


class PolymarketClient:
    """Thin wrapper around Polymarket public endpoints."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        markets_path: str | None = None,
        page_size: int | None = None,
        market_status: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.base_url = base_url or str(settings.polymarket_base_url)
        self.markets_path = markets_path or settings.polymarket_markets_path
        self.page_size = page_size or settings.ingestion_page_size
        self.market_status = market_status or settings.ingestion_status
        self.timeout = timeout
        self.client = httpx.Client(base_url=self.base_url, timeout=timeout)

    def _build_params(self, *, cursor: str | None, offset: int) -> dict[str, Any]:
        params: dict[str, Any] = {
            "limit": self.page_size,
            "offset": offset,
            "status": self.market_status,
        }
        if cursor:
            params["cursor"] = cursor
        return params

    def fetch_page(self, *, cursor: str | None, offset: int) -> dict[str, Any]:
        response = self.client.get(
            self.markets_path, params=self._build_params(cursor=cursor, offset=offset)
        )
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
