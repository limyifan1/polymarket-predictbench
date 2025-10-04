from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from app import crud
from app.domain import NormalizedEvent, NormalizedMarket
from app.repositories.pipeline_models import ProcessedEventInput, ProcessedMarketInput


@patch("app.crud.MarketRepository")
def test_upsert_market(mock_market_repo):
    """Verify that upsert_market calls the repository method correctly."""
    mock_session = MagicMock()
    market = NormalizedMarket(
        market_id="1",
        question="Test Question",
        slug="test-question",
        status="open",
        close_time=datetime.now(),
        raw_data={},
        contracts=[],
        category="test",
        sub_category="test",
        open_time=datetime.now(),
        volume_usd=1.0,
        liquidity_usd=1.0,
        fee_bps=1,
        description="test",
        icon_url="test",
        event=None,
    )

    crud.upsert_market(mock_session, market)

    mock_market_repo.assert_called_once_with(mock_session)
    mock_market_repo.return_value.upsert_market.assert_called_once_with(market)


@patch("app.crud.MarketRepository")
def test_upsert_event(mock_market_repo):
    """Verify that upsert_event calls the repository method correctly."""
    mock_session = MagicMock()
    event = NormalizedEvent(
        event_id="1",
        slug="test-event",
        title="Test Event",
        description="test",
        start_time=datetime.now(),
        end_time=datetime.now(),
        icon_url="test",
        series_slug="test",
        series_title="test",
        raw_data={},
    )

    crud.upsert_event(mock_session, event)

    mock_market_repo.assert_called_once_with(mock_session)
    mock_market_repo.return_value.upsert_event.assert_called_once_with(event)


@patch("app.crud.ProcessingRepository")
def test_create_processing_run(mock_processing_repo):
    """Verify that create_processing_run calls the repository method correctly."""
    mock_session = MagicMock()
    run_args = {
        "run_id": "test-run",
        "run_date": date.today(),
        "window_days": 1,
        "target_date": date.today(),
        "git_sha": "test-sha",
        "environment": "test",
    }

    crud.create_processing_run(mock_session, **run_args)

    mock_processing_repo.assert_called_once_with(mock_session)
    mock_processing_repo.return_value.create_processing_run.assert_called_once_with(
        **run_args
    )


@patch("app.crud.ProcessingRepository")
def test_finalize_processing_run(mock_processing_repo):
    """Verify that finalize_processing_run calls the repository method correctly."""
    mock_session = MagicMock()
    mock_run = MagicMock()
    finalize_args = {
        "status": "completed",
        "total_markets": 10,
        "processed_markets": 8,
        "failed_markets": 2,
        "finished_at": datetime.now(),
    }

    crud.finalize_processing_run(mock_session, mock_run, **finalize_args)

    mock_processing_repo.assert_called_once_with(mock_session)
    (
        mock_processing_repo.return_value.finalize_processing_run.assert_called_once_with(
            mock_run, **finalize_args
        )
    )


@patch("app.crud.ProcessingRepository")
def test_record_processed_event(mock_processing_repo):
    """Verify that record_processed_event calls the repository method correctly."""
    mock_session = MagicMock()
    payload = ProcessedEventInput(
        processed_event_id="test-id",
        run_id="test-run",
        event_key="test-key",
        event_id="event-id",
        event_slug="event-slug",
        event_title="event-title",
        raw_snapshot={},
    )

    crud.record_processed_event(mock_session, payload)

    mock_processing_repo.assert_called_once_with(mock_session)
    mock_processing_repo.return_value.record_processed_event.assert_called_once_with(
        payload
    )


@patch("app.crud.ProcessingRepository")
def test_record_processed_market(mock_processing_repo):
    """Verify that record_processed_market calls the repository method correctly."""
    mock_session = MagicMock()
    payload = ProcessedMarketInput(
        processed_market_id="test-id",
        run_id="test-run",
        market_id="market-id",
        market_slug="market-slug",
        question="question",
        close_time=datetime.now(),
        raw_snapshot={},
        processed_event_id="event-id",
        contracts=[],
    )

    crud.record_processed_market(mock_session, payload)

    mock_processing_repo.assert_called_once_with(mock_session)
    mock_processing_repo.return_value.record_processed_market.assert_called_once_with(
        payload
    )


@patch("app.crud.ProcessingRepository")
def test_record_processing_failure(mock_processing_repo):
    """Verify that record_processing_failure calls the repository method correctly."""
    mock_session = MagicMock()
    failure_args = {
        "run_id": "test-run",
        "market_id": "market-id",
        "reason": "test-reason",
        "retriable": True,
        "details": {"foo": "bar"},
    }

    crud.record_processing_failure(mock_session, **failure_args)

    mock_processing_repo.assert_called_once_with(mock_session)
    mock_processing_repo.return_value.record_processing_failure.assert_called_once_with(
        **failure_args
    )