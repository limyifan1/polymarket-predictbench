"""Higher-level conveniences for interacting with market persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

from sqlalchemy.orm import Session

from app.repositories import (
    EventGroupRecord,
    ExperimentRepository,
    EventResearchBundle,
    ForecastResearchDependency,
    MarketForecastBundle,
    MarketRepository,
)
from app.schemas import (
    Event,
    EventWithMarkets,
    ExperimentDescriptor,
    ExperimentRunSummary,
    ForecastResearchReference,
    ForecastResult,
    Market,
    PipelineRunSummary,
    ResearchArtifact,
)
from app.models import ExperimentStage


@dataclass(slots=True)
class MarketQuery:
    status: str | None = None
    close_before: datetime | None = None
    close_after: datetime | None = None
    min_volume: float | None = None
    category: str | None = None
    sort: str = "close_time"
    order: str = "asc"
    limit: int = 50
    offset: int = 0

    def to_repository_kwargs(self) -> dict[str, Any]:
        """Serialize the query so repository functions receive consistent kwargs."""

        return {
            "status": self.status,
            "close_before": self.close_before,
            "close_after": self.close_after,
            "min_volume": self.min_volume,
            "category": self.category,
            "sort": self.sort,
            "order": self.order,
            "limit": self.limit,
            "offset": self.offset,
        }


@dataclass(slots=True)
class MarketQueryResult:
    total: int
    markets: Sequence[Market]


@dataclass(slots=True)
class EventQueryResult:
    total: int
    events: Sequence[EventWithMarkets]


class MarketService:
    """Read-only facade over market listings used by the API and experiments."""

    def __init__(self, session: Session):
        self._session = session
        self._market_repo = MarketRepository(session)
        self._experiment_repo = ExperimentRepository(session)

    def list_markets(self, query: MarketQuery) -> MarketQueryResult:
        raw_markets, total = self._market_repo.list_markets(**query.to_repository_kwargs())
        market_ids = [market.market_id for market in raw_markets]
        forecasts_map = self._collect_market_forecasts(market_ids)
        markets = self._normalize_markets(raw_markets, forecast_map=forecasts_map)
        return MarketQueryResult(total=total, markets=markets)

    def list_events(self, query: MarketQuery) -> EventQueryResult:
        groups, total = self._market_repo.list_events(**query.to_repository_kwargs())
        event_ids = [group.event.event_id for group in groups if group.event and group.event.event_id]
        market_ids = [market.market_id for group in groups for market in group.markets]
        research_map = self._collect_event_research(event_ids)
        forecasts_map = self._collect_market_forecasts(market_ids)
        events = [self._build_event_payload(group, research_map, forecasts_map) for group in groups]
        return EventQueryResult(total=total, events=events)

    def get_market(self, market_id: str) -> Market | None:
        market = self._market_repo.get_market(market_id)
        if not market:
            return None
        forecasts_map = self._collect_market_forecasts([market_id])
        payload = Market.model_validate(market)
        results = forecasts_map.get(market_id, [])
        if results:
            return payload.model_copy(update={"experiment_results": results})
        return payload

    def _normalize_markets(
        self,
        raw_markets: Sequence[Any],
        *,
        forecast_map: dict[str, list[ForecastResult]] | None = None,
    ) -> list[Market]:
        """Convert ORM models into API schemas while preserving order."""

        forecast_map = forecast_map or {}
        normalized: list[Market] = []
        for record in raw_markets:
            payload = Market.model_validate(record)
            results = forecast_map.get(payload.market_id, [])
            if results:
                payload = payload.model_copy(update={"experiment_results": results})
            normalized.append(payload)
        return normalized

    def _build_event_payload(
        self,
        group: EventGroupRecord,
        research_map: dict[str, list[ResearchArtifact]],
        forecast_map: dict[str, list[ForecastResult]],
    ) -> EventWithMarkets:
        """Adapt repository event groups into the API schema."""

        markets = self._normalize_markets(group.markets, forecast_map=forecast_map)
        if group.event is not None:
            event_model = Event.model_validate(group.event)
            return EventWithMarkets(
                **event_model.model_dump(),
                markets=markets,
                market_count=len(markets),
                research=research_map.get(event_model.event_id, []),
            )

        primary = markets[0] if markets else None
        return EventWithMarkets(
            event_id=f"market:{primary.market_id}" if primary else "unknown",
            slug=primary.slug if primary else None,
            title=primary.question if primary else None,
            description=primary.description if primary else None,
            start_time=primary.open_time if primary else None,
            end_time=primary.close_time if primary else None,
            icon_url=primary.icon_url if primary else None,
            series_slug=None,
            series_title=None,
            markets=markets,
            market_count=len(markets),
            research=[],
        )

    def _collect_event_research(
        self, event_ids: Sequence[str]
    ) -> dict[str, list[ResearchArtifact]]:
        bundles = self._experiment_repo.load_event_research(event_ids)
        research_map: dict[str, list[ResearchArtifact]] = {}
        seen: dict[str, set[tuple[str, str, str]]] = {}

        for bundle in sorted(
            bundles, key=lambda item: item.artifact.created_at, reverse=True
        ):
            if not bundle.event_id:
                continue
            variant_key = (
                bundle.experiment.name,
                bundle.artifact.variant_name,
                bundle.artifact.variant_version,
            )
            bucket = seen.setdefault(bundle.event_id, set())
            if variant_key in bucket:
                continue
            bucket.add(variant_key)
            adapted = self._adapt_research_bundle(bundle)
            research_map.setdefault(bundle.event_id, []).append(adapted)

        return research_map

    def _collect_market_forecasts(
        self, market_ids: Sequence[str]
    ) -> dict[str, list[ForecastResult]]:
        if not market_ids:
            return {}

        bundles = self._experiment_repo.load_market_forecasts(market_ids)
        forecasts_map: dict[str, list[ForecastResult]] = {}
        seen: dict[str, set[tuple[str, str, str]]] = {}

        for bundle in sorted(
            bundles, key=lambda item: item.result.recorded_at, reverse=True
        ):
            variant_key = (
                bundle.experiment.name,
                bundle.result.variant_name or "",
                bundle.result.variant_version or "",
            )
            bucket = seen.setdefault(bundle.market_id, set())
            if variant_key in bucket:
                continue
            bucket.add(variant_key)
            adapted = self._adapt_forecast_bundle(bundle)
            forecasts_map.setdefault(bundle.market_id, []).append(adapted)

        return forecasts_map

    def _adapt_research_bundle(self, bundle: EventResearchBundle) -> ResearchArtifact:
        return ResearchArtifact(
            descriptor=self._build_descriptor(
                bundle.experiment,
                bundle.artifact.variant_name,
                bundle.artifact.variant_version,
                ExperimentStage.RESEARCH.value,
            ),
            run=self._build_run_summary(
                bundle.research_run, identifier_attr="research_run_id"
            ),
            pipeline_run=self._build_pipeline_summary(bundle.processing_run),
            artifact_id=bundle.artifact.artifact_id,
            artifact_uri=bundle.artifact.artifact_uri,
            artifact_hash=bundle.artifact.artifact_hash,
            created_at=bundle.artifact.created_at,
            updated_at=bundle.artifact.updated_at,
            payload=bundle.artifact.payload,
        )

    def _adapt_forecast_bundle(self, bundle: MarketForecastBundle) -> ForecastResult:
        dependencies = [
            self._adapt_forecast_dependency(dependency)
            for dependency in bundle.dependencies
        ]
        return ForecastResult(
            descriptor=self._build_descriptor(
                bundle.experiment,
                bundle.result.variant_name or "",
                bundle.result.variant_version or "",
                bundle.experiment_run.stage,
            ),
            run=self._build_run_summary(
                bundle.experiment_run, identifier_attr="experiment_run_id"
            ),
            pipeline_run=self._build_pipeline_summary(bundle.processing_run),
            recorded_at=bundle.result.recorded_at,
            score=bundle.result.score,
            artifact_uri=bundle.result.artifact_uri,
            payload=bundle.result.payload,
            research_dependencies=dependencies,
        )

    def _adapt_forecast_dependency(
        self, dependency: ForecastResearchDependency
    ) -> ForecastResearchReference:
        return ForecastResearchReference(
            dependency_key=dependency.link.dependency_key,
            artifact_id=dependency.link.artifact_id,
            descriptor=self._build_descriptor(
                dependency.experiment,
                dependency.artifact.variant_name,
                dependency.artifact.variant_version,
                ExperimentStage.RESEARCH.value,
            ),
            run=self._build_run_summary(
                dependency.research_run, identifier_attr="research_run_id"
            ),
        )

    @staticmethod
    def _build_descriptor(
        experiment: Any,
        variant_name: str | None,
        variant_version: str | None,
        stage: str,
    ) -> ExperimentDescriptor:
        return ExperimentDescriptor(
            experiment_name=experiment.name,
            experiment_version=experiment.version,
            variant_name=variant_name or "default",
            variant_version=variant_version or "unspecified",
            stage=stage,
        )

    @staticmethod
    def _build_run_summary(
        run_record: Any, *, identifier_attr: str
    ) -> ExperimentRunSummary:
        run_identifier = getattr(run_record, identifier_attr, None)
        if run_identifier is None:
            run_identifier = getattr(run_record, "run_id")
        return ExperimentRunSummary(
            run_id=run_identifier,
            status=run_record.status,
            started_at=run_record.started_at,
            finished_at=run_record.finished_at,
        )

    @staticmethod
    def _build_pipeline_summary(
        processing_run: Any | None,
    ) -> PipelineRunSummary | None:
        if processing_run is None:
            return None
        return PipelineRunSummary(
            run_id=processing_run.run_id,
            run_date=processing_run.run_date,
            target_date=processing_run.target_date,
            window_days=processing_run.window_days,
            status=processing_run.status,
            environment=processing_run.environment,
        )
