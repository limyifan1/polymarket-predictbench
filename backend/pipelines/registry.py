from __future__ import annotations

from importlib import import_module
from typing import Iterable

from loguru import logger

from .experiments.base import Experiment


def load_experiments(import_paths: Iterable[str]) -> list[Experiment]:
    experiments: list[Experiment] = []
    for path in import_paths:
        try:
            module_path, _, attr_name = path.partition(":")
            if not module_path or not attr_name:
                raise ValueError("Experiment path must be in 'module:ClassName' format")
            module = import_module(module_path)
            candidate = getattr(module, attr_name)
            experiment: Experiment = candidate()  # type: ignore[assignment]
            experiments.append(experiment)
            logger.debug("Loaded experiment {} (version {})", experiment.name, experiment.version)
        except Exception as exc:  # noqa: BLE001 - surface import errors
            logger.error("Failed to load experiment {}: {}", path, exc)
            raise
    return experiments
