from __future__ import annotations

from importlib import import_module
from typing import Iterable

from loguru import logger

from .suites import BaseExperimentSuite


def _materialize_suite(candidate) -> BaseExperimentSuite:
    if isinstance(candidate, BaseExperimentSuite):
        return candidate
    if isinstance(candidate, type) and issubclass(candidate, BaseExperimentSuite):
        return candidate()
    if callable(candidate):
        suite = candidate()
        if isinstance(suite, BaseExperimentSuite):
            return suite
    raise TypeError(
        "Experiment suite factory must be an instance, subclass, or callable returning BaseExperimentSuite"
    )


def load_suites(import_paths: Iterable[str]) -> list[BaseExperimentSuite]:
    suites: list[BaseExperimentSuite] = []
    for path in import_paths:
        module_path, _, attr_name = path.partition(":")
        if not module_path or not attr_name:
            raise ValueError("Suite path must be in 'module:Attribute' format")
        module = import_module(module_path)
        candidate = getattr(module, attr_name)
        suite = _materialize_suite(candidate)
        suites.append(suite)
        logger.debug("Loaded suite {} (version {})", suite.suite_id, suite.version)
    return suites


__all__ = ["load_suites"]
