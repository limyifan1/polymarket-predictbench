"""Summary analytics for visualizing collected datasets."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Event,
    ExperimentDefinition,
    ExperimentResultRecord,
    ExperimentRunRecord,
    ExperimentStage,
    Market,
    ProcessedEvent,
    ProcessedMarket,
    ProcessingRun,
    ResearchArtifactRecord,
    ResearchRunRecord,
)
from app.schemas import (
    DatasetOverview,
    ExperimentVariantSummary,
    MarketStatusCount,
    PipelineRunSummary,
)


class OverviewService:
    """Calculate aggregate dataset metrics for dashboard views."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def dataset_overview(self) -> DatasetOverview:
        total_events = self._scalar(select(func.count(Event.event_id)))
        total_markets = self._scalar(select(func.count(Market.market_id)))

        status_rows = self._session.execute(
            select(Market.status, func.count(Market.market_id)).group_by(Market.status)
        ).all()
        market_status = self._normalize_market_status(status_rows)

        total_research_artifacts = self._scalar(
            select(func.count(ResearchArtifactRecord.artifact_id))
        )

        total_forecast_results = self._scalar(
            select(func.count(ExperimentResultRecord.experiment_result_id)).where(
                ExperimentResultRecord.stage == ExperimentStage.FORECAST.value
            )
        )

        research_event_ids = self._collect_research_event_ids()
        forecast_event_ids = self._collect_forecast_event_ids()
        forecast_market_ids = self._collect_forecast_market_ids()

        research_variants = list(self._summarize_research_variants())
        forecast_variants = list(self._summarize_forecast_variants())

        recent_pipeline_runs = self._load_recent_pipeline_runs(limit=10)
        latest_pipeline_run = recent_pipeline_runs[0] if recent_pipeline_runs else None

        return DatasetOverview(
            generated_at=datetime.now(timezone.utc),
            total_events=int(total_events),
            events_with_research=len(research_event_ids),
            events_with_forecasts=len(forecast_event_ids),
            total_markets=int(total_markets),
            markets_with_forecasts=len(forecast_market_ids),
            market_status=market_status,
            total_research_artifacts=int(total_research_artifacts),
            total_forecast_results=int(total_forecast_results),
            research_variants=research_variants,
            forecast_variants=forecast_variants,
            latest_pipeline_run=latest_pipeline_run,
            recent_pipeline_runs=recent_pipeline_runs,
        )

    # ------------------------------------------------------------------
    # Aggregation helpers

    def _collect_research_event_ids(self) -> set[str]:
        event_ids: set[str] = set()

        direct_rows = self._session.execute(
            select(func.distinct(ProcessedEvent.event_id))
            .join(
                ResearchArtifactRecord,
                ResearchArtifactRecord.processed_event_id == ProcessedEvent.processed_event_id,
            )
            .join(
                ResearchRunRecord,
                ResearchArtifactRecord.research_run_id == ResearchRunRecord.research_run_id,
            )
            .where(ProcessedEvent.event_id.is_not(None))
        ).scalars()
        event_ids.update(filter(None, direct_rows))

        via_market_rows = self._session.execute(
            select(func.distinct(ProcessedEvent.event_id))
            .select_from(ProcessedMarket)
            .join(
                ResearchArtifactRecord,
                ResearchArtifactRecord.processed_market_id == ProcessedMarket.processed_market_id,
            )
            .join(
                ResearchRunRecord,
                ResearchArtifactRecord.research_run_id == ResearchRunRecord.research_run_id,
            )
            .join(
                ProcessedEvent,
                ProcessedMarket.processed_event_id == ProcessedEvent.processed_event_id,
            )
            .where(ProcessedEvent.event_id.is_not(None))
        ).scalars()
        event_ids.update(filter(None, via_market_rows))

        return event_ids

    def _collect_forecast_event_ids(self) -> set[str]:
        event_ids: set[str] = set()

        direct_rows = self._session.execute(
            select(func.distinct(ProcessedEvent.event_id))
            .join(
                ExperimentResultRecord,
                ExperimentResultRecord.processed_event_id == ProcessedEvent.processed_event_id,
            )
            .where(
                ExperimentResultRecord.stage == ExperimentStage.FORECAST.value,
                ProcessedEvent.event_id.is_not(None),
            )
        ).scalars()
        event_ids.update(filter(None, direct_rows))

        via_market_rows = self._session.execute(
            select(func.distinct(ProcessedEvent.event_id))
            .select_from(ProcessedMarket)
            .join(
                ExperimentResultRecord,
                ExperimentResultRecord.processed_market_id == ProcessedMarket.processed_market_id,
            )
            .join(
                ProcessedEvent,
                ProcessedMarket.processed_event_id == ProcessedEvent.processed_event_id,
            )
            .where(
                ExperimentResultRecord.stage == ExperimentStage.FORECAST.value,
                ProcessedEvent.event_id.is_not(None),
            )
        ).scalars()
        event_ids.update(filter(None, via_market_rows))

        return event_ids

    def _collect_forecast_market_ids(self) -> set[str]:
        rows = self._session.execute(
            select(func.distinct(ProcessedMarket.market_id))
            .join(
                ExperimentResultRecord,
                ExperimentResultRecord.processed_market_id == ProcessedMarket.processed_market_id,
            )
            .where(
                ExperimentResultRecord.stage == ExperimentStage.FORECAST.value,
                ProcessedMarket.market_id.is_not(None),
            )
        ).scalars()
        return set(filter(None, rows))

    def _summarize_research_variants(self) -> Iterable[ExperimentVariantSummary]:
        rows = self._session.execute(
            select(
                ExperimentDefinition.name,
                ExperimentDefinition.version,
                ResearchArtifactRecord.variant_name,
                ResearchArtifactRecord.variant_version,
                func.count(ResearchArtifactRecord.artifact_id),
                func.max(ResearchArtifactRecord.created_at),
            )
            .join(
                ResearchRunRecord,
                ResearchArtifactRecord.research_run_id == ResearchRunRecord.research_run_id,
            )
            .join(
                ExperimentDefinition,
                ResearchRunRecord.experiment_id == ExperimentDefinition.experiment_id,
            )
            .group_by(
                ExperimentDefinition.name,
                ExperimentDefinition.version,
                ResearchArtifactRecord.variant_name,
                ResearchArtifactRecord.variant_version,
            )
            .order_by(
                ExperimentDefinition.name,
                ResearchArtifactRecord.variant_name,
                ResearchArtifactRecord.variant_version,
            )
        ).all()

        for name, version, variant, variant_version, count, latest in rows:
            yield ExperimentVariantSummary(
                stage=ExperimentStage.RESEARCH.value,
                experiment_name=name,
                experiment_version=version,
                variant_name=variant or "default",
                variant_version=variant_version or "unspecified",
                output_count=int(count),
                last_activity=latest,
            )

    def _summarize_forecast_variants(self) -> Iterable[ExperimentVariantSummary]:
        rows = self._session.execute(
            select(
                ExperimentDefinition.name,
                ExperimentDefinition.version,
                ExperimentResultRecord.variant_name,
                ExperimentResultRecord.variant_version,
                func.count(ExperimentResultRecord.experiment_result_id),
                func.max(ExperimentResultRecord.recorded_at),
            )
            .join(
                ExperimentRunRecord,
                ExperimentResultRecord.experiment_run_id == ExperimentRunRecord.experiment_run_id,
            )
            .join(
                ExperimentDefinition,
                ExperimentRunRecord.experiment_id == ExperimentDefinition.experiment_id,
            )
            .where(ExperimentResultRecord.stage == ExperimentStage.FORECAST.value)
            .group_by(
                ExperimentDefinition.name,
                ExperimentDefinition.version,
                ExperimentResultRecord.variant_name,
                ExperimentResultRecord.variant_version,
            )
            .order_by(
                ExperimentDefinition.name,
                ExperimentResultRecord.variant_name,
                ExperimentResultRecord.variant_version,
            )
        ).all()

        for name, version, variant, variant_version, count, latest in rows:
            yield ExperimentVariantSummary(
                stage=ExperimentStage.FORECAST.value,
                experiment_name=name,
                experiment_version=version,
                variant_name=variant or "default",
                variant_version=variant_version or "unspecified",
                output_count=int(count),
                last_activity=latest,
            )

    def _load_recent_pipeline_runs(self, *, limit: int = 10) -> list[PipelineRunSummary]:
        rows = (
            self._session.execute(
                select(ProcessingRun).order_by(ProcessingRun.started_at.desc()).limit(limit)
            ).scalars()
        )

        summaries: list[PipelineRunSummary] = []
        for record in rows:
            summaries.append(
                PipelineRunSummary(
                    run_id=record.run_id,
                    run_date=record.run_date,
                    target_date=record.target_date,
                    window_days=record.window_days,
                    status=record.status,
                    environment=record.environment,
                )
            )
        return summaries

    def _normalize_market_status(self, rows: list[tuple[str | None, int]]) -> list[MarketStatusCount]:
        counts: dict[str, int] = {}
        for status, count in rows:
            if status is None:
                continue
            counts[status] = int(count)

        for default_status in ("open", "closed", "resolved"):
            counts.setdefault(default_status, 0)

        ordered_statuses = sorted(
            counts,
            key=lambda value: {"open": 0, "closed": 1, "resolved": 2}.get(value, 99),
        )

        return [MarketStatusCount(status=status, count=counts[status]) for status in ordered_statuses]

    def _scalar(self, statement) -> int:
        return int(self._session.execute(statement).scalar_one() or 0)


__all__ = ["OverviewService"]
