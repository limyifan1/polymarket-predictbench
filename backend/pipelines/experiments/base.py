from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.crud import NormalizedMarket

from ..context import PipelineContext


class ExperimentExecutionError(Exception):
    """Raised when an experiment fails and should halt market persistence."""


class ExperimentSkip(Exception):
    """Raised when an experiment decides to skip processing for a market."""


@dataclass(slots=True)
class ExperimentResult:
    name: str
    version: str
    payload: dict[str, Any] | None
    score: float | None = None
    artifact_uri: str | None = None


class Experiment(Protocol):
    """Interface that all experiments must implement."""

    name: str
    version: str
    description: str | None

    def run(self, market: NormalizedMarket, context: PipelineContext) -> ExperimentResult:
        """Execute experiment logic for a single market."""
        raise NotImplementedError
