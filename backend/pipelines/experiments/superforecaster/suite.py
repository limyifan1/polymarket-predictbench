"""Experiment suite wiring for the superforecaster-inspired flow."""

from __future__ import annotations

from ..suites import BaseExperimentSuite, strategy, suite
from .forecast_calibrated import SuperforecasterDelphiForecast
from .research_briefing import SuperforecasterBriefingResearch
from ..openai.research_web_search import OpenAIWebSearchResearch


def build_superforecaster_suite() -> BaseExperimentSuite:
    """Return the configured superforecaster suite."""

    return suite(
        "superforecaster",
        version="0.1",
        description=(
            "Superforecaster-style research brief with calibrated probability aggregation"
        ),
        research=(
            strategy(OpenAIWebSearchResearch),
            strategy(SuperforecasterBriefingResearch),
        ),
        forecasts=(strategy(SuperforecasterDelphiForecast),),
    )


__all__ = ["build_superforecaster_suite"]
