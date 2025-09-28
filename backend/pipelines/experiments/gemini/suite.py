"""Experiment suite wiring for Gemini-based workflows."""

from __future__ import annotations

from ..suites import BaseExperimentSuite, strategy, suite
from .forecast import GeminiForecastStrategy
from .research_web_search import GeminiWebSearchResearch


def build_gemini_suite() -> BaseExperimentSuite:
    """Return the configured Gemini experiment suite."""

    return suite(
        "gemini",
        version="0.1",
        description="Gemini-backed research and forecast flow grounded with Google Search",
        research=(strategy(GeminiWebSearchResearch),),
        forecasts=(
            strategy(
                GeminiForecastStrategy,
                requires=("gemini_web_search",),
            ),
        ),
    )


__all__ = ["build_gemini_suite"]
