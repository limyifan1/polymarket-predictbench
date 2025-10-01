"""Read-side helpers for experiment runs, research, and forecast results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models import (
    ExperimentDefinition,
    ExperimentResultRecord,
    ExperimentRunRecord,
    ExperimentStage,
    ProcessedEvent,
    ProcessedMarket,
    ProcessingRun,
    ResearchArtifactRecord,
)


@dataclass(slots=True)
class EventResearchBundle:
    """Envelope tying research artifacts to their execution context."""

    event_id: str | None
    processed_event_id: str
    artifact: ResearchArtifactRecord
    experiment_run: ExperimentRunRecord
    experiment: ExperimentDefinition
    processing_run: ProcessingRun | None


@dataclass(slots=True)
class MarketForecastBundle:
    """Envelope tying forecast results to their execution context."""

    market_id: str
    processed_market_id: str
    result: ExperimentResultRecord
    experiment_run: ExperimentRunRecord
    experiment: ExperimentDefinition
    processing_run: ProcessingRun | None


class ExperimentRepository:
    """Expose read operations for experiment artifacts and results."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Event-level research artifacts

    def load_event_research(self, event_ids: Sequence[str]) -> list[EventResearchBundle]:
        if not event_ids:
            return []

        query: Select[tuple[
            ResearchArtifactRecord,
            ExperimentRunRecord,
            ExperimentDefinition,
            ProcessedEvent,
            ProcessingRun |
            None,
        ]] = (
            select(
                ResearchArtifactRecord,
                ExperimentRunRecord,
                ExperimentDefinition,
                ProcessedEvent,
                ProcessingRun,
            )
            .join(
                ExperimentRunRecord,
                ResearchArtifactRecord.experiment_run_id
                == ExperimentRunRecord.experiment_run_id,
            )
            .join(
                ExperimentDefinition,
                ExperimentRunRecord.experiment_id == ExperimentDefinition.experiment_id,
            )
            .join(
                ProcessedEvent,
                ResearchArtifactRecord.processed_event_id
                == ProcessedEvent.processed_event_id,
            )
            .join(
                ProcessingRun,
                ProcessedEvent.run_id == ProcessingRun.run_id,
                isouter=True,
            )
            .where(
                ResearchArtifactRecord.processed_event_id.is_not(None),
                ExperimentRunRecord.stage == ExperimentStage.RESEARCH.value,
                ProcessedEvent.event_id.in_(set(event_ids)),
            )
            .order_by(ResearchArtifactRecord.created_at.desc())
        )

        rows = self._session.execute(query).all()

        bundles: list[EventResearchBundle] = []
        for artifact, experiment_run, experiment, processed_event, processing_run in rows:
            bundles.append(
                EventResearchBundle(
                    event_id=processed_event.event_id,
                    processed_event_id=processed_event.processed_event_id,
                    artifact=artifact,
                    experiment_run=experiment_run,
                    experiment=experiment,
                    processing_run=processing_run,
                )
            )
        return bundles

    # ------------------------------------------------------------------
    # Market-level forecast results

    def load_market_forecasts(self, market_ids: Sequence[str]) -> list[MarketForecastBundle]:
        if not market_ids:
            return []

        query: Select[tuple[
            ExperimentResultRecord,
            ExperimentRunRecord,
            ExperimentDefinition,
            ProcessedMarket,
            ProcessingRun |
            None,
        ]] = (
            select(
                ExperimentResultRecord,
                ExperimentRunRecord,
                ExperimentDefinition,
                ProcessedMarket,
                ProcessingRun,
            )
            .join(
                ExperimentRunRecord,
                ExperimentResultRecord.experiment_run_id
                == ExperimentRunRecord.experiment_run_id,
            )
            .join(
                ExperimentDefinition,
                ExperimentRunRecord.experiment_id == ExperimentDefinition.experiment_id,
            )
            .join(
                ProcessedMarket,
                ExperimentResultRecord.processed_market_id
                == ProcessedMarket.processed_market_id,
            )
            .join(
                ProcessingRun,
                ProcessedMarket.run_id == ProcessingRun.run_id,
                isouter=True,
            )
            .where(
                ExperimentResultRecord.processed_market_id.is_not(None),
                ExperimentResultRecord.stage == ExperimentStage.FORECAST.value,
                ProcessedMarket.market_id.in_(set(market_ids)),
            )
            .order_by(ExperimentResultRecord.recorded_at.desc())
        )

        rows = self._session.execute(query).all()

        bundles: list[MarketForecastBundle] = []
        for result, experiment_run, experiment, processed_market, processing_run in rows:
            bundles.append(
                MarketForecastBundle(
                    market_id=processed_market.market_id,
                    processed_market_id=processed_market.processed_market_id,
                    result=result,
                    experiment_run=experiment_run,
                    experiment=experiment,
                    processing_run=processing_run,
                )
            )
        return bundles


__all__ = ["ExperimentRepository", "EventResearchBundle", "MarketForecastBundle"]
