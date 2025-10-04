"""DTOs for pipeline persistence operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class ProcessedContractInput:
    contract_id: str
    name: str
    price: float | None
    attributes: dict[str, Any] | None


@dataclass(slots=True)
class ProcessedMarketInput:
    processed_market_id: str
    run_id: str
    market_id: str
    market_slug: str | None
    question: str
    close_time: datetime | None
    raw_snapshot: dict | None
    processed_event_id: str | None
    contracts: list[ProcessedContractInput]


@dataclass(slots=True)
class ProcessedEventInput:
    processed_event_id: str
    run_id: str
    event_key: str | None
    event_id: str | None
    event_slug: str | None
    event_title: str | None
    raw_snapshot: dict | None


@dataclass(slots=True)
class ExperimentRunInput:
    experiment_run_id: str
    run_id: str
    experiment_name: str
    experiment_version: str
    stage: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    error_message: str | None


@dataclass(slots=True)
class ExperimentResultInput:
    experiment_run_id: str
    processed_market_id: str | None
    processed_event_id: str | None
    stage: str
    variant_name: str | None
    variant_version: str | None
    source_artifact_id: str | None
    payload: dict | None
    score: float | None
    artifact_uri: str | None


@dataclass(slots=True)
class ResearchArtifactInput:
    artifact_id: str
    experiment_run_id: str
    processed_market_id: str | None
    processed_event_id: str | None
    variant_name: str
    variant_version: str
    artifact_hash: str | None
    payload: dict | None
    artifact_uri: str | None


__all__ = [
    "ProcessedContractInput",
    "ProcessedEventInput",
    "ProcessedMarketInput",
    "ExperimentRunInput",
    "ExperimentResultInput",
    "ResearchArtifactInput",
]
