from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app import schemas
from app.main import _market_service, _overview_service, app
from app.services.market_service import EventQueryResult, MarketQueryResult
from app.services.overview_service import OverviewService


@pytest.fixture
def client():
    """Test client that cleans up dependency overrides after each test."""
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_healthcheck(client):
    """Verify the healthcheck endpoint returns a successful response."""
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_list_markets(client):
    """Verify the /markets endpoint returns a list of markets."""
    mock_service = MagicMock()
    mock_service.list_markets.return_value = MarketQueryResult(total=0, markets=[])
    app.dependency_overrides[_market_service] = lambda: mock_service

    response = client.get("/markets")
    assert response.status_code == 200
    assert response.json() == {"total": 0, "items": []}
    mock_service.list_markets.assert_called_once()


def test_get_market_success(client):
    """Verify the /markets/{market_id} endpoint returns a market."""
    mock_service = MagicMock()
    market_payload = {
        "market_id": "1",
        "slug": "test-market",
        "question": "Will this test pass?",
        "status": "open",
        "archived": False,
        "last_synced_at": datetime.now(),
        "contracts": [],
        "event": None,
        "experiment_results": [],
    }
    mock_service.get_market.return_value = schemas.Market.model_validate(market_payload)
    app.dependency_overrides[_market_service] = lambda: mock_service

    response = client.get("/markets/1")
    assert response.status_code == 200
    # The response is a full Market schema, so we just check a few fields
    json_response = response.json()
    assert json_response["market_id"] == "1"
    assert json_response["slug"] == "test-market"
    mock_service.get_market.assert_called_once_with("1")


def test_get_market_not_found(client):
    """Verify the /markets/{market_id} endpoint returns 404 for a missing market."""
    mock_service = MagicMock()
    mock_service.get_market.return_value = None
    app.dependency_overrides[_market_service] = lambda: mock_service

    response = client.get("/markets/non-existent-id")
    assert response.status_code == 404
    mock_service.get_market.assert_called_once_with("non-existent-id")


def test_list_events(client):
    """Verify the /events endpoint returns a list of events."""
    mock_service = MagicMock()
    mock_service.list_events.return_value = EventQueryResult(total=0, events=[])
    app.dependency_overrides[_market_service] = lambda: mock_service

    response = client.get("/events")
    assert response.status_code == 200
    assert response.json() == {"total": 0, "items": []}
    mock_service.list_events.assert_called_once()


def test_dataset_overview(client):
    """Verify the /overview endpoint returns dataset overview statistics."""
    mock_service = MagicMock(spec=OverviewService)
    overview_payload = {
        "generated_at": datetime.now(),
        "total_events": 10,
        "events_with_research": 5,
        "events_with_forecasts": 3,
        "total_markets": 100,
        "markets_with_forecasts": 50,
        "market_status": [{"status": "open", "count": 100}],
        "total_research_artifacts": 20,
        "total_forecast_results": 30,
        "research_variants": [],
        "forecast_variants": [],
        "latest_pipeline_run": None,
        "recent_pipeline_runs": [],
    }
    # The service returns a schema object, so we mock that behavior
    mock_service.dataset_overview.return_value = schemas.DatasetOverview.model_validate(
        overview_payload
    )
    app.dependency_overrides[_overview_service] = lambda: mock_service

    response = client.get("/overview")
    assert response.status_code == 200
    # FastAPI will serialize the datetime to a string, so we adjust our expected payload
    overview_payload["generated_at"] = overview_payload["generated_at"].isoformat()
    assert response.json() == overview_payload
    mock_service.dataset_overview.assert_called_once()