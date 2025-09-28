"""Helpers for composing the OpenAI research + forecast suite."""

from __future__ import annotations

from ..suites import BaseExperimentSuite, strategy, suite
from .forecast_gpt5 import GPT5ForecastStrategy
from .research_atlas import AtlasResearchSweep
from .research_timeline import HorizonSignalTimeline
from .research_web_search import OpenAIWebSearchResearch


def build_openai_suite() -> BaseExperimentSuite:
    """Return the configured OpenAI experiment suite."""

    return suite(
        "openai",
        version="0.2",
        description="Experimental OpenAI-backed research + forecast flow",
        research=(
            strategy(OpenAIWebSearchResearch),
            strategy(AtlasResearchSweep),
            strategy(HorizonSignalTimeline),
        ),
        forecasts=(
            strategy(
                GPT5ForecastStrategy,
                alias="gpt41_forecast",
                version="0.2-gpt4.1",
                description="JSON-mode forecast prompt using GPT-4.1 preview",
                overrides={"model": "gpt-4.1"},
            ),
            strategy(
                GPT5ForecastStrategy,
                alias="gpt5mini_forecast",
                version="0.2-gpt5mini",
                description="JSON-mode forecast prompt using GPT-5 mini",
                overrides={"model": "gpt-5-mini"},
            ),
        ),
    )


__all__ = ["build_openai_suite"]
