"""Structured manifest generation for experiment suites."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Collection, Iterable, Mapping

from app.models import ExperimentStage

from .base import ForecastStrategy, ResearchStrategy
from .suites import BaseExperimentSuite

__all__ = ["build_manifest"]


def _timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _strategy_entry(
    *,
    suite: BaseExperimentSuite,
    stage: ExperimentStage,
    strategy: ResearchStrategy | ForecastStrategy,
    stage_active: bool,
    selection: Collection[str] | None,
) -> Mapping[str, Any]:
    selected = stage_active and _is_selected(suite.suite_id, strategy.name, selection)
    entry: dict[str, Any] = {
        "name": strategy.name,
        "version": getattr(strategy, "version", "1.0"),
        "description": getattr(strategy, "description", None),
        "experiment_name": suite.experiment_name(stage, strategy.name),
        "selected": selected,
    }
    if stage == ExperimentStage.FORECAST:
        entry["requires"] = list(getattr(strategy, "requires", ()))
    return entry


def _is_selected(suite_id: str, variant: str, selection: Collection[str] | None) -> bool:
    if not selection:
        return True
    return variant in selection or f"{suite_id}:{variant}" in selection


def build_manifest(
    suites: Sequence[BaseExperimentSuite],
    *,
    active_stages: Iterable[ExperimentStage] | None = None,
    enabled_research: Collection[str] | None = None,
    enabled_forecast: Collection[str] | None = None,
) -> Mapping[str, Any]:
    """Return a JSON-serialisable manifest describing configured suites."""

    stage_set = set(active_stages or (ExperimentStage.RESEARCH, ExperimentStage.FORECAST))
    payload = {
        "generated_at": _timestamp(),
        "suite_count": len(suites),
        "suites": [],
    }
    for suite in suites:
        research_active = ExperimentStage.RESEARCH in stage_set
        forecast_active = ExperimentStage.FORECAST in stage_set
        suite_entry = {
            "suite_id": suite.suite_id,
            "version": suite.version,
            "description": suite.description,
            "stages": {
                "research": {
                    "active": research_active,
                    "variants": [
                        _strategy_entry(
                            suite=suite,
                            stage=ExperimentStage.RESEARCH,
                            strategy=strategy,
                            stage_active=research_active,
                            selection=enabled_research,
                        )
                        for strategy in suite.research_strategies()
                    ],
                },
                "forecast": {
                    "active": forecast_active,
                    "variants": [
                        _strategy_entry(
                            suite=suite,
                            stage=ExperimentStage.FORECAST,
                            strategy=strategy,
                            stage_active=forecast_active,
                            selection=enabled_forecast,
                        )
                        for strategy in suite.forecast_strategies()
                    ],
                },
            },
        }
        payload["suites"].append(suite_entry)
    return payload
