"""Utilities for loading experiment suites from declarative config files.

The YAML schema mirrors the in-code helpers exposed by
``pipelines.experiments.suites``. A file must expose a top-level ``suites``
array where each entry describes a suite and optionally overrides the
``suite_id``, ``version``, and ``description`` attributes. ``research`` and
``forecasts`` arrays list strategy factories; every research strategy runs for
each event processed by the suite and forecasts execute once their declared
``requires`` dependencies are satisfied. See :mod:`docs/experiments-
forecasting-design.md` for a narrative walkthrough and examples.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml
from loguru import logger

from .suites import BaseExperimentSuite, DeclarativeExperimentSuite, StrategyFactory, strategy

__all__ = ["load_yaml_suites", "SuiteDefinition", "StrategyDefinition"]


@dataclass(slots=True)
class StrategyDefinition:
    """In-memory representation of a strategy entry from YAML."""

    target: Any
    args: Sequence[Any]
    kwargs: Mapping[str, Any]

    def factory(self) -> StrategyFactory[Any]:
        return strategy(self.target, *self.args, **dict(self.kwargs))


@dataclass(slots=True)
class SuiteDefinition:
    """Structured data extracted from a YAML suite block."""

    suite_class: type[BaseExperimentSuite]
    suite_id: str | None
    version: str | None
    description: str | None
    research: Sequence[StrategyFactory[Any]]
    forecasts: Sequence[StrategyFactory[Any]]

    def build(self) -> BaseExperimentSuite:
        init_kwargs: dict[str, Any] = {}
        if self.suite_id is not None:
            init_kwargs["suite_id"] = self.suite_id
        if self.version is not None:
            init_kwargs["version"] = self.version
        if self.description is not None:
            init_kwargs["description"] = self.description

        if issubclass(self.suite_class, DeclarativeExperimentSuite):
            init_kwargs.setdefault("research", self.research)
            init_kwargs.setdefault("forecasts", self.forecasts)
        elif self.research or self.forecasts:
            logger.warning(
                "Suite class {} ignores declarative research/forecast factories; override _build_* manually.",
                self.suite_class.__name__,
            )
        return self.suite_class(**init_kwargs)


def _import_symbol(path: str) -> Any:
    module_path, _, attr_name = path.partition(":")
    if not module_path or not attr_name:
        raise ValueError(f"Import path must be in 'module:Attribute' format (got {path!r})")
    module = import_module(module_path)
    try:
        return getattr(module, attr_name)
    except AttributeError as exc:  # noqa: B904
        raise AttributeError(f"{attr_name!r} not found in module {module_path!r}") from exc


def _coerce_sequence(value: Any, *, label: str) -> Sequence[Any]:
    if value is None:
        return ()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return list(value)
    raise TypeError(f"Expected a sequence for {label}, received {type(value)!r}")


def _coerce_mapping(value: Any, *, label: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    raise TypeError(f"Expected a mapping for {label}, received {type(value)!r}")


def _parse_strategy_entry(entry: Any, *, context_label: str) -> StrategyDefinition:
    if isinstance(entry, str):
        target = _import_symbol(entry)
        return StrategyDefinition(target=target, args=(), kwargs={})
    if not isinstance(entry, Mapping):
        raise TypeError(f"Strategy entry in {context_label} must be a string or mapping, got {type(entry)!r}")

    target = entry.get("target") or entry.get("strategy")
    if target is None:
        raise ValueError(f"Strategy entry in {context_label} is missing a 'target' field")
    if isinstance(target, str):
        target_obj = _import_symbol(target)
    else:
        target_obj = target

    args = _coerce_sequence(entry.get("args"), label=f"{context_label}.args")
    kwargs = _coerce_mapping(entry.get("kwargs"), label=f"{context_label}.kwargs")
    return StrategyDefinition(target=target_obj, args=args, kwargs=kwargs)


def _parse_strategy_factories(
    entries: Iterable[Any],
    *,
    context_label: str,
) -> tuple[StrategyFactory[Any], ...]:
    factories: list[StrategyFactory[Any]] = []
    for index, entry in enumerate(entries):
        definition = _parse_strategy_entry(entry, context_label=f"{context_label}[{index}]")
        factories.append(definition.factory())
    return tuple(factories)


def _parse_suite_block(raw_suite: Mapping[str, Any]) -> SuiteDefinition:
    suite_class_path = raw_suite.get("class") or "pipelines.experiments.suites:DeclarativeExperimentSuite"
    suite_class_obj = _import_symbol(suite_class_path)
    if not isinstance(suite_class_obj, type) or not issubclass(suite_class_obj, BaseExperimentSuite):
        raise TypeError(f"Suite class {suite_class_path!r} must resolve to a BaseExperimentSuite subclass")

    research_entries = _coerce_sequence(raw_suite.get("research", []), label="research")
    forecast_entries = _coerce_sequence(
        raw_suite.get("forecasts", raw_suite.get("forecast", [])),
        label="forecasts",
    )
    research_factories = _parse_strategy_factories(research_entries, context_label="research")
    forecast_factories = _parse_strategy_factories(forecast_entries, context_label="forecasts")

    return SuiteDefinition(
        suite_class=suite_class_obj,
        suite_id=raw_suite.get("suite_id"),
        version=raw_suite.get("version"),
        description=raw_suite.get("description"),
        research=research_factories,
        forecasts=forecast_factories,
    )


def load_yaml_suites(path: str | Path) -> list[BaseExperimentSuite]:
    """Load experiment suites from a YAML config file.

    The loader expects the following structure::

        suites:
          - suite_id: openai
            version: "0.2"
            description: Optional free-form text
            research:
              - target: package.module:StrategyClass
              - target: package.module:create_strategy
                args: ["positional", "args"]
                kwargs:
                  option: value
            forecasts:
              - target: package.module:ForecastStrategy

    ``research`` and ``forecasts`` entries may be strings (``module:Attribute``)
    or dictionaries with optional ``args``/``kwargs``. Every listed research
    strategy runs for each event handled by the suite. Forecast strategies are
    invoked for the same events once all required research artifacts named in
    ``ForecastStrategy.requires`` have succeeded. Multiple forecasts can share
    the same research artifacts; dependencies are resolved by the strategy name
    recorded on each research result.
    """

    file_path = Path(path).expanduser()
    if not file_path.is_file():
        raise FileNotFoundError(f"Suite config file not found: {file_path}")

    raw = yaml.safe_load(file_path.read_text())
    if raw is None:
        logger.debug("Suite config {} is empty; no suites loaded", file_path)
        return []

    suites_section = raw.get("suites") if isinstance(raw, Mapping) else None
    if suites_section is None:
        raise ValueError(f"Suite config {file_path} must define a top-level 'suites' list")
    if not isinstance(suites_section, Sequence):
        raise TypeError("'suites' must be a list of suite definitions")

    suites: list[BaseExperimentSuite] = []
    for index, suite_entry in enumerate(suites_section):
        if not isinstance(suite_entry, Mapping):
            raise TypeError(f"Suite entry at index {index} must be a mapping, got {type(suite_entry)!r}")
        definition = _parse_suite_block(suite_entry)
        suite = definition.build()
        suites.append(suite)
        logger.debug(
            "Loaded suite {} (version {}) from {}",
            suite.suite_id,
            suite.version,
            file_path,
        )
    return suites
