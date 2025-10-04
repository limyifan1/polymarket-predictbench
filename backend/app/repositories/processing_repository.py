"""Processing run persistence helpers."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    ExperimentDefinition,
    ExperimentResultRecord,
    ExperimentRunRecord,
    ForecastResearchLink,
    ProcessedContract,
    ProcessedEvent,
    ProcessedMarket,
    ProcessingFailure,
    ProcessingRun,
    ResearchArtifactRecord,
    ResearchRunRecord,
)

from .pipeline_models import (
    ExperimentResultInput,
    ExperimentRunInput,
    ForecastResearchLinkInput,
    ProcessedContractInput,
    ProcessedEventInput,
    ProcessedMarketInput,
    ResearchArtifactInput,
    ResearchRunInput,
)


class ProcessingRepository:
    """Encapsulate pipeline persistence logic."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Processing runs

    def create_processing_run(
        self,
        *,
        run_id: str,
        run_date: date,
        window_days: int,
        target_date: date,
        git_sha: str | None,
        environment: str | None,
    ) -> ProcessingRun:
        record = ProcessingRun(
            run_id=run_id,
            run_date=run_date,
            window_days=window_days,
            target_date=target_date,
            git_sha=git_sha,
            environment=environment,
        )
        self._session.add(record)
        self._session.flush()
        return record

    def get_processing_run(self, run_id: str) -> ProcessingRun | None:
        return self._session.get(ProcessingRun, run_id)

    def finalize_processing_run(
        self,
        run: ProcessingRun,
        *,
        status: str,
        total_markets: int,
        processed_markets: int,
        failed_markets: int,
        finished_at: datetime,
    ) -> None:
        run.status = status
        run.total_markets = total_markets
        run.processed_markets = processed_markets
        run.failed_markets = failed_markets
        run.finished_at = finished_at

    # ------------------------------------------------------------------
    # Processed entities

    def record_processed_event(self, payload: ProcessedEventInput) -> ProcessedEvent:
        processed_event = ProcessedEvent(
            processed_event_id=payload.processed_event_id,
            run_id=payload.run_id,
            event_key=payload.event_key,
            event_id=payload.event_id,
            event_slug=payload.event_slug,
            event_title=payload.event_title,
            raw_snapshot=payload.raw_snapshot,
        )
        self._session.add(processed_event)
        self._session.flush()
        return processed_event

    def fetch_completed_event_keys(self, event_keys: set[str]) -> set[str]:
        if not event_keys:
            return set()

        query = select(ProcessedEvent.event_key).where(
            ProcessedEvent.event_key.in_(event_keys),
            ProcessedEvent.event_key.is_not(None),
        )
        rows = self._session.execute(query).scalars().all()
        return {row for row in rows if row is not None}

    def record_processed_market(self, payload: ProcessedMarketInput) -> ProcessedMarket:
        processed_market = ProcessedMarket(
            processed_market_id=payload.processed_market_id,
            run_id=payload.run_id,
            market_id=payload.market_id,
            market_slug=payload.market_slug,
            question=payload.question,
            close_time=payload.close_time,
            raw_snapshot=payload.raw_snapshot,
            processed_event_id=payload.processed_event_id,
        )
        self._session.add(processed_market)

        for contract in payload.contracts:
            processed_contract = ProcessedContract(
                processed_market=processed_market,
                contract_id=contract.contract_id,
                name=contract.name,
                price=contract.price,
                attributes=contract.attributes,
            )
            self._session.add(processed_contract)

        self._session.flush()
        return processed_market

    def record_processing_failure(
        self,
        *,
        run_id: str,
        market_id: str | None,
        reason: str,
        retriable: bool,
        details: dict[str, Any] | None = None,
    ) -> None:
        failure = ProcessingFailure(
            run_id=run_id,
            market_id=market_id,
            reason=reason,
            retriable=retriable,
            details=details,
        )
        self._session.add(failure)

    # ------------------------------------------------------------------
    # Experiment runs and artifacts

    def ensure_experiment_definition(
        self,
        *,
        name: str,
        version: str,
        description: str | None = None,
    ) -> ExperimentDefinition:
        query = select(ExperimentDefinition).where(
            ExperimentDefinition.name == name,
            ExperimentDefinition.version == version,
        )
        existing = self._session.execute(query).scalar_one_or_none()
        if existing:
            return existing

        definition = ExperimentDefinition(
            name=name,
            version=version,
            description=description,
        )
        self._session.add(definition)
        self._session.flush()
        return definition

    def record_experiment_run(
        self,
        payload: ExperimentRunInput,
        description: str | None = None,
    ) -> ExperimentRunRecord:
        definition = self.ensure_experiment_definition(
            name=payload.experiment_name,
            version=payload.experiment_version,
            description=description,
        )
        existing = self._session.get(ExperimentRunRecord, payload.experiment_run_id)
        if existing:
            existing.stage = payload.stage
            existing.status = payload.status
            existing.started_at = payload.started_at
            existing.finished_at = payload.finished_at
            existing.error_message = payload.error_message
            existing.experiment = definition
            return existing

        experiment_run = ExperimentRunRecord(
            experiment_run_id=payload.experiment_run_id,
            run_id=payload.run_id,
            experiment=definition,
            stage=payload.stage,
            status=payload.status,
            started_at=payload.started_at,
            finished_at=payload.finished_at,
            error_message=payload.error_message,
        )
        self._session.add(experiment_run)
        self._session.flush()
        return experiment_run

    def record_research_run(
        self,
        payload: ResearchRunInput,
    ) -> ResearchRunRecord:
        definition = self.ensure_experiment_definition(
            name=payload.experiment_name,
            version=payload.strategy_version,
            description=payload.description,
        )
        existing = self._session.get(ResearchRunRecord, payload.research_run_id)
        if existing:
            existing.status = payload.status
            existing.started_at = payload.started_at
            existing.finished_at = payload.finished_at
            existing.error_message = payload.error_message
            existing.description = payload.description
            existing.suite_id = payload.suite_id
            existing.strategy_name = payload.strategy_name
            existing.strategy_version = payload.strategy_version
            existing.experiment = definition
            return existing

        research_run = ResearchRunRecord(
            research_run_id=payload.research_run_id,
            run_id=payload.run_id,
            suite_id=payload.suite_id,
            experiment=definition,
            strategy_name=payload.strategy_name,
            strategy_version=payload.strategy_version,
            status=payload.status,
            started_at=payload.started_at,
            finished_at=payload.finished_at,
            error_message=payload.error_message,
            description=payload.description,
        )
        self._session.add(research_run)
        self._session.flush()
        return research_run

    def record_research_artifact(self, payload: ResearchArtifactInput) -> ResearchArtifactRecord:
        existing = self._session.get(ResearchArtifactRecord, payload.artifact_id)
        if existing:
            existing.research_run_id = payload.research_run_id
            existing.processed_market_id = payload.processed_market_id
            existing.processed_event_id = payload.processed_event_id
            existing.variant_name = payload.variant_name
            existing.variant_version = payload.variant_version
            existing.artifact_hash = payload.artifact_hash
            existing.payload = payload.payload
            existing.artifact_uri = payload.artifact_uri
            return existing

        artifact = ResearchArtifactRecord(
            artifact_id=payload.artifact_id,
            research_run_id=payload.research_run_id,
            processed_market_id=payload.processed_market_id,
            processed_event_id=payload.processed_event_id,
            variant_name=payload.variant_name,
            variant_version=payload.variant_version,
            artifact_hash=payload.artifact_hash,
            payload=payload.payload,
            artifact_uri=payload.artifact_uri,
        )
        self._session.add(artifact)
        self._session.flush()
        return artifact

    def record_experiment_result(self, payload: ExperimentResultInput) -> ExperimentResultRecord:
        result = ExperimentResultRecord(
            experiment_run_id=payload.experiment_run_id,
            processed_market_id=payload.processed_market_id,
            processed_event_id=payload.processed_event_id,
            stage=payload.stage,
            variant_name=payload.variant_name,
            variant_version=payload.variant_version,
            payload=payload.payload,
            score=payload.score,
            artifact_uri=payload.artifact_uri,
        )
        self._session.add(result)
        self._session.flush()
        return result

    def record_forecast_research_links(
        self, payloads: Sequence[ForecastResearchLinkInput]
    ) -> None:
        for payload in payloads:
            link = ForecastResearchLink(
                experiment_result_id=payload.experiment_result_id,
                artifact_id=payload.artifact_id,
                dependency_key=payload.dependency_key,
            )
            self._session.add(link)
        if payloads:
            self._session.flush()

    def load_event_research_artifacts(
        self, event_id: str
    ) -> list[tuple[ResearchArtifactRecord, ResearchRunRecord]]:
        query = (
            select(ResearchArtifactRecord, ResearchRunRecord)
            .join(ResearchRunRecord, ResearchArtifactRecord.research_run_id == ResearchRunRecord.research_run_id)
            .join(
                ProcessedEvent,
                ResearchArtifactRecord.processed_event_id == ProcessedEvent.processed_event_id,
            )
            .where(ProcessedEvent.event_id == event_id)
            .order_by(ResearchArtifactRecord.created_at.desc())
        )
        rows = self._session.execute(query).all()
        return [(artifact, research_run) for artifact, research_run in rows]


__all__ = ["ProcessingRepository"]
