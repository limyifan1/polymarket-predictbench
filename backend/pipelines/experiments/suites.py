from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable, Generic, Sequence, TypeVar

from app.models import ExperimentStage

from .base import ForecastStrategy, ResearchStrategy, StrategyDescriptor


_StrategyT = TypeVar("_StrategyT")


@dataclass(slots=True)
class StrategyFactory(Generic[_StrategyT]):
    """Lightweight callable wrapper that normalises strategy builders."""

    builder: Callable[[], _StrategyT]
    overrides: Mapping[str, Any] | None = None
    alias: str | None = None
    version: str | None = None
    description: str | None = None

    def __call__(self) -> _StrategyT:
        strategy = self.builder()
        if not _is_strategy_instance(strategy):
            msg = (
                "Strategy factory produced an object without a 'run' method: "
                f"{strategy!r}"
            )
            raise TypeError(msg)
        if self.alias:
            setattr(strategy, "name", self.alias)
        if self.version:
            setattr(strategy, "version", self.version)
        if self.description:
            setattr(strategy, "description", self.description)
        return strategy


def _is_strategy_instance(candidate: Any) -> bool:
    """Return True when the candidate looks like a strategy instance."""

    return hasattr(candidate, "run") and not isinstance(candidate, type)


def strategy(
    target: Any,
    /,
    *args: Any,
    alias: str | None = None,
    version: str | None = None,
    description: str | None = None,
    overrides: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> StrategyFactory[Any]:
    """Return a factory that instantiates strategy instances on demand.

    Accepts a strategy instance, class, or callable. Optional ``*args`` / ``**kwargs``
    are forwarded when a callable/class is provided. This keeps suite definitions
    declarative and compact:

    ``strategy(MyStrategy, temperature=0.7)``
    ``strategy(lambda: CustomStrategy(config))``

    Providing an already-instantiated strategy forbids args/kwargs to avoid
    accidental reuse of partially configured objects.
    """

    if isinstance(target, type):
        def _builder() -> Any:
            return target(*args, **kwargs)

        return StrategyFactory(
            builder=_builder,
            overrides=dict(overrides) if overrides else None,
            alias=alias,
            version=version,
            description=description,
        )

    if callable(target) and not _is_strategy_instance(target):
        def _builder_callable() -> Any:
            return target(*args, **kwargs)

        return StrategyFactory(
            builder=_builder_callable,
            overrides=dict(overrides) if overrides else None,
            alias=alias,
            version=version,
            description=description,
        )

    if args or kwargs:
        raise TypeError(
            "Cannot supply args/kwargs when providing a pre-built strategy instance"
        )

    def _builder_instance() -> Any:
        return target

    return StrategyFactory(
        builder=_builder_instance,
        overrides=dict(overrides) if overrides else None,
        alias=alias,
        version=version,
        description=description,
    )


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

    def experiment_overrides(self) -> Mapping[str, Mapping[str, Any]]:
        """Return per-experiment default overrides supplied by the suite."""

        return {}


class DeclarativeExperimentSuite(BaseExperimentSuite):
    """A suite that reads its inventory from declarative factories."""

    research_factories: Sequence[StrategyFactory[ResearchStrategy]] = ()
    forecast_factories: Sequence[StrategyFactory[ForecastStrategy]] = ()

    def __init__(
        self,
        *,
        suite_id: str | None = None,
        version: str | None = None,
        description: str | None = None,
        research: Sequence[StrategyFactory[ResearchStrategy]] | None = None,
        forecasts: Sequence[StrategyFactory[ForecastStrategy]] | None = None,
    ) -> None:
        if suite_id is not None:
            self.suite_id = suite_id
        if version is not None:
            self.version = version
        if description is not None:
            self.description = description

        self._research_factories: tuple[StrategyFactory[ResearchStrategy], ...] = (
            tuple(research) if research is not None else tuple(self.research_factories)
        )
        self._forecast_factories: tuple[StrategyFactory[ForecastStrategy], ...] = (
            tuple(forecasts)
            if forecasts is not None
            else tuple(self.forecast_factories)
        )
        super().__init__()
        self._experiment_overrides: dict[str, dict[str, Any]] = self._collect_experiment_overrides()

    def _build_research_strategies(self) -> Sequence[ResearchStrategy]:
        return tuple(factory() for factory in self._research_factories)

    def _build_forecast_strategies(self) -> Sequence[ForecastStrategy]:
        return tuple(factory() for factory in self._forecast_factories)

    def _collect_experiment_overrides(self) -> dict[str, dict[str, Any]]:
        overrides: dict[str, dict[str, Any]] = {}
        for factory, strategy in zip(self._research_factories, self._inventory.research):
            if factory.overrides:
                overrides[self.experiment_name(ExperimentStage.RESEARCH, strategy.name)] = dict(factory.overrides)
        for factory, strategy in zip(self._forecast_factories, self._inventory.forecasts):
            if factory.overrides:
                overrides[self.experiment_name(ExperimentStage.FORECAST, strategy.name)] = dict(factory.overrides)
        return overrides

    def experiment_overrides(self) -> Mapping[str, Mapping[str, Any]]:
        return self._experiment_overrides


def suite(
    suite_id: str,
    *,
    version: str = "1.0",
    description: str | None = None,
    research: Sequence[StrategyFactory[ResearchStrategy]] | None = None,
    forecasts: Sequence[StrategyFactory[ForecastStrategy]] | None = None,
) -> BaseExperimentSuite:
    """Convenience helper to assemble suites without subclassing."""

    return DeclarativeExperimentSuite(
        suite_id=suite_id,
        version=version,
        description=description,
        research=tuple(research or ()),
        forecasts=tuple(forecasts or ()),
    )


__all__ = [
    "BaseExperimentSuite",
    "DeclarativeExperimentSuite",
    "StrategyFactory",
    "SuiteInventory",
    "strategy",
    "suite",
]
