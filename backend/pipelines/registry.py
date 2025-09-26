from __future__ import annotations

from typing import Iterable

from loguru import logger

from .experiments.registry import load_suites as _load_suites
from .experiments.suites import BaseExperimentSuite


def load_suites(import_paths: Iterable[str]) -> list[BaseExperimentSuite]:
    return _load_suites(import_paths)


def load_experiments(import_paths: Iterable[str]):
    """Legacy shim kept for compatibility."""
    logger.error(
        "load_experiments is deprecated. Update configuration to use experiment suites."
    )
    raise RuntimeError(
        "Legacy experiment loader is no longer supported. Use load_suites instead."
    )


__all__ = ["load_suites", "load_experiments"]
