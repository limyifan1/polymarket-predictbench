from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from app.models import ExperimentStage

from .base import ForecastStrategy, ResearchStrategy, StrategyDescriptor


@dataclass(slots=True)
class SuiteInventory:
    """Materialized strategies for a suite."""

    research: tuple[ResearchStrategy, ...]
    forecasts: tuple[ForecastStrategy, ...]


class BaseExperimentSuite:
    """Helper base class for experiment suites composed of stages."""

    suite_id: str = "suite"
    version: str = "1.0"
    description: str | None = None

    def __init__(self) -> None:
        self._inventory = SuiteInventory(
            research=tuple(self._build_research_strategies()),
            forecasts=tuple(self._build_forecast_strategies()),
        )
        self._validate()

    def _build_research_strategies(self) -> Sequence[ResearchStrategy]:
        return ()

    def _build_forecast_strategies(self) -> Sequence[ForecastStrategy]:
        return ()

    def _validate(self) -> None:
        research_names = {strategy.name for strategy in self._inventory.research}
        if len(research_names) != len(self._inventory.research):
            raise ValueError(
                f"Suite {self.suite_id} defines duplicate research strategy names."
            )

        for forecast in self._inventory.forecasts:
            missing = [name for name in forecast.requires if name not in research_names]
            if missing:
                raise ValueError(
                    "Suite {} forecast {} is missing research dependencies: {}".format(
                        self.suite_id,
                        forecast.name,
                        ", ".join(missing),
                    )
                )

    @property
    def inventory(self) -> SuiteInventory:
        return self._inventory

    def research_strategies(self) -> tuple[ResearchStrategy, ...]:
        return self._inventory.research

    def forecast_strategies(self) -> tuple[ForecastStrategy, ...]:
        return self._inventory.forecasts

    def experiment_name(self, stage: ExperimentStage, strategy_name: str) -> str:
        return f"{self.suite_id}:{stage.value}:{strategy_name}"

    def strategy_descriptors(self) -> list[StrategyDescriptor]:
        descriptors: list[StrategyDescriptor] = []
        for strategy in self._inventory.research:
            descriptors.append(
                StrategyDescriptor(
                    suite_id=self.suite_id,
                    stage=ExperimentStage.RESEARCH,
                    strategy_name=strategy.name,
                    strategy_version=strategy.version,
                    experiment_name=self.experiment_name(ExperimentStage.RESEARCH, strategy.name),
                )
            )
        for strategy in self._inventory.forecasts:
            descriptors.append(
                StrategyDescriptor(
                    suite_id=self.suite_id,
                    stage=ExperimentStage.FORECAST,
                    strategy_name=strategy.name,
                    strategy_version=strategy.version,
                    experiment_name=self.experiment_name(ExperimentStage.FORECAST, strategy.name),
                )
            )
        return descriptors


__all__ = ["BaseExperimentSuite", "SuiteInventory"]
