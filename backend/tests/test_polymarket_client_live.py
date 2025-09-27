from __future__ import annotations

import httpx
import pytest

from ingestion.client import PolymarketClient


@pytest.mark.network
def test_polymarket_client_live_fetches_markets():
    client = PolymarketClient(page_size=5)
    markets: list[dict[str, object]] = []
    try:
        for market in client.iter_markets():
            markets.append(market)
            if len(markets) >= 5:
                break
    except httpx.HTTPError as exc:
        pytest.skip(f"Polymarket API unavailable: {exc}")
    finally:
        client.close()

    assert markets, "Polymarket API returned no markets"
    for market in markets:
        assert isinstance(market, dict)
        assert market.get("id"), "market payload missing identifier"
        assert market.get("question") or market.get("title"), "market payload missing question text"
