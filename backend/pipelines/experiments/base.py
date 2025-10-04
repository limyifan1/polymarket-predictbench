from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Protocol, Sequence

from app.domain import NormalizedEvent, NormalizedMarket
from app.models import ExperimentStage

from ..context import PipelineContext


class ExperimentExecutionError(Exception):
    """Raised when an experiment fails and should halt market persistence."""


class ExperimentSkip(Exception):
    """Raised when an experiment decides to skip processing for a market."""


@dataclass(slots=True)
class EventMarketGroup:
    event: NormalizedEvent | None
    markets: list[NormalizedMarket]


@dataclass(slots=True)
class ResearchOutput:
    payload: dict[str, Any] | None
    artifact_uri: str | None = None
    artifact_hash: str | None = None
    diagnostics: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if isinstance(self.payload, dict) and "generated_at" not in self.payload:
            self.payload["generated_at"] = (
                datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
            )


@dataclass(slots=True)
class ForecastOutput:
    market_id: str
    outcome_prices: dict[str, float | None]
    reasoning: str
    score: float | None = None
    artifact_uri: str | None = None
    diagnostics: dict[str, Any] | None = None


class ResearchStrategy(Protocol):
    """Interface implemented by research stage variants."""

    name: str
    version: str
    description: str | None

    def run(self, group: EventMarketGroup, context: PipelineContext) -> ResearchOutput:
        """Produce research artifact(s) for a market group."""
        raise NotImplementedError


class ForecastStrategy(Protocol):
    """Interface implemented by forecast stage variants."""

    name: str
    version: str
    description: str | None
    requires: Sequence[str]

    def run(
        self,
        group: EventMarketGroup,
        research_artifacts: Mapping[str, ResearchOutput],
        context: PipelineContext,
    ) -> Sequence[ForecastOutput]:
        """Produce forecast outputs using research artifacts."""
        raise NotImplementedError


@dataclass(slots=True)
class StrategyDescriptor:
    """Runtime descriptor for a strategy within a suite."""

    suite_id: str
    stage: ExperimentStage
    strategy_name: str
    strategy_version: str
    experiment_name: str


__all__ = [
    "EventMarketGroup",
    "ExperimentExecutionError",
    "ExperimentSkip",
    "ForecastOutput",
    "ForecastStrategy",
    "ResearchOutput",
    "ResearchStrategy",
    "StrategyDescriptor",
]
