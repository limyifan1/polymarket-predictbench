"""Code-first registry for experiment suites.

The pipeline imports :func:`load_suites` to instantiate every configured
experiment suite. Configuration happens in code by editing
``REGISTERED_SUITE_BUILDERS`` – each entry is a callable that returns a fresh
``BaseExperimentSuite`` instance. Builders keep suites easy to tweak without
digging through environment variables or YAML indirection.

For small suites, the :func:`pipelines.experiments.suites.suite` helper keeps
definitions compact::

    from pipelines.experiments.suites import strategy, suite
    from pipelines.experiments.example import ExampleResearch, ExampleForecast

    def example_suite() -> BaseExperimentSuite:
        return suite(
            "example",
            research=(strategy(ExampleResearch),),
            forecasts=(strategy(ExampleForecast),),
        )

To add or remove suites, modify :data:`REGISTERED_SUITE_BUILDERS`. The pipeline
will pick up the new configuration automatically.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import Final

from loguru import logger

from .baseline import BaselineSnapshotSuite
from .openai import build_openai_suite
from .suites import BaseExperimentSuite

SuiteBuilder = Callable[[], BaseExperimentSuite]


def _baseline_suite() -> BaseExperimentSuite:
    return BaselineSnapshotSuite()


REGISTERED_SUITE_BUILDERS: Final[tuple[SuiteBuilder, ...]] = (
    _baseline_suite,
    build_openai_suite,
)
"""Ordered suite builders executed for every pipeline run."""


def instantiate_suites(builders: Sequence[SuiteBuilder]) -> list[BaseExperimentSuite]:
    """Instantiate suites from the provided builders."""

    suites = [builder() for builder in builders]
    if not suites:
        raise RuntimeError(
            "No experiment suites configured. Update REGISTERED_SUITE_BUILDERS "
            "in pipelines.experiments.registry."
        )
    return suites


def _normalise_requested(requested: Iterable[str] | None) -> set[str]:
    if not requested:
        return set()
    normalised = {item.strip() for item in requested if item and item.strip()}
    return {item for item in normalised if item}


def load_suites(requested: Iterable[str] | None = None) -> list[BaseExperimentSuite]:
    """Return configured suites, optionally filtered by ``requested`` IDs."""

    suites = instantiate_suites(REGISTERED_SUITE_BUILDERS)
    allowed = _normalise_requested(requested)
    if not allowed:
        return suites

    filtered: list[BaseExperimentSuite] = [
        suite for suite in suites if suite.suite_id in allowed
    ]
    missing = allowed - {suite.suite_id for suite in filtered}
    if missing:
        logger.warning(
            "Requested suite IDs not found in registry: {}",
            ", ".join(sorted(missing)),
        )
    if not filtered:
        raise RuntimeError(
            "No suites left after filtering. Check the requested IDs or update the registry."
        )
    return filtered


__all__ = [
    "SuiteBuilder",
    "REGISTERED_SUITE_BUILDERS",
    "instantiate_suites",
    "load_suites",
]
