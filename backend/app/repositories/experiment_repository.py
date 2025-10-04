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
    ForecastResearchLink,
    ProcessedEvent,
    ProcessedMarket,
    ProcessingRun,
    ResearchArtifactRecord,
    ResearchRunRecord,
)


@dataclass(slots=True)
class EventResearchBundle:
    """Envelope tying research artifacts to their execution context."""

    event_id: str | None
    processed_event_id: str
    artifact: ResearchArtifactRecord
    research_run: ResearchRunRecord
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
    dependencies: list["ForecastResearchDependency"]


@dataclass(slots=True)
class ForecastResearchDependency:
    link: ForecastResearchLink
    artifact: ResearchArtifactRecord
    research_run: ResearchRunRecord
    experiment: ExperimentDefinition


class ExperimentRepository:
    """Expose read operations for experiment artifacts and results."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Event-level research artifacts

    def load_event_research(
        self, event_ids: Sequence[str]
    ) -> list[EventResearchBundle]:
        if not event_ids:
            return []

        query: Select[
            tuple[
                ResearchArtifactRecord,
                ResearchRunRecord,
                ExperimentDefinition,
                ProcessedEvent,
                ProcessingRun | None,
            ]
        ] = (
            select(
                ResearchArtifactRecord,
                ResearchRunRecord,
                ExperimentDefinition,
                ProcessedEvent,
                ProcessingRun,
            )
            .join(
                ResearchRunRecord,
                ResearchArtifactRecord.research_run_id
                == ResearchRunRecord.research_run_id,
                isouter=True,
            )
            .join(
                ExperimentDefinition,
                ResearchRunRecord.experiment_id == ExperimentDefinition.experiment_id,
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
                ProcessedEvent.event_id.in_(set(event_ids)),
            )
            .order_by(ResearchArtifactRecord.created_at.desc())
        )

        rows = self._session.execute(query).all()

        bundles: list[EventResearchBundle] = []
        for artifact, research_run, experiment, processed_event, processing_run in rows:
            bundles.append(
                EventResearchBundle(
                    event_id=processed_event.event_id,
                    processed_event_id=processed_event.processed_event_id,
                    artifact=artifact,
                    research_run=research_run,
                    experiment=experiment,
                    processing_run=processing_run,
                )
            )
        return bundles

    # ------------------------------------------------------------------
    # Market-level forecast results

    def load_market_forecasts(
        self, market_ids: Sequence[str]
    ) -> list[MarketForecastBundle]:
        if not market_ids:
            return []

        query: Select[
            tuple[
                ExperimentResultRecord,
                ExperimentRunRecord,
                ExperimentDefinition,
                ProcessedMarket,
                ProcessingRun | None,
            ]
        ] = (
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

        if not rows:
            return []

        result_ids = [row[0].experiment_result_id for row in rows]
        dependency_query: Select[
            tuple[
                ForecastResearchLink,
                ResearchArtifactRecord,
                ResearchRunRecord,
                ExperimentDefinition,
            ]
        ] = (
            select(
                ForecastResearchLink,
                ResearchArtifactRecord,
                ResearchRunRecord,
                ExperimentDefinition,
            )
            .join(
                ResearchArtifactRecord,
                ForecastResearchLink.artifact_id == ResearchArtifactRecord.artifact_id,
            )
            .join(
                ResearchRunRecord,
                ResearchArtifactRecord.research_run_id
                == ResearchRunRecord.research_run_id,
            )
            .join(
                ExperimentDefinition,
                ResearchRunRecord.experiment_id == ExperimentDefinition.experiment_id,
            )
            .where(ForecastResearchLink.experiment_result_id.in_(result_ids))
        )

        dependency_rows = self._session.execute(dependency_query).all()
        dependency_map: dict[int, list[ForecastResearchDependency]] = {}
        for link, artifact, research_run, experiment in dependency_rows:
            dependency_map.setdefault(link.experiment_result_id, []).append(
                ForecastResearchDependency(
                    link=link,
                    artifact=artifact,
                    research_run=research_run,
                    experiment=experiment,
                )
            )

        bundles: list[MarketForecastBundle] = []
        for (
            result,
            experiment_run,
            experiment,
            processed_market,
            processing_run,
        ) in rows:
            bundles.append(
                MarketForecastBundle(
                    market_id=processed_market.market_id,
                    processed_market_id=processed_market.processed_market_id,
                    result=result,
                    experiment_run=experiment_run,
                    experiment=experiment,
                    processing_run=processing_run,
                    dependencies=dependency_map.get(result.experiment_result_id, []),
                )
            )
        return bundles


__all__ = [
    "ExperimentRepository",
    "EventResearchBundle",
    "MarketForecastBundle",
    "ForecastResearchDependency",
]
