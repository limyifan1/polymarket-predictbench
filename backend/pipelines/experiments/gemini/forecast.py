"""Forecast strategy backed by Gemini."""

from __future__ import annotations

from ..openai.forecast_gpt5 import GPT5ForecastStrategy


class GeminiForecastStrategy(GPT5ForecastStrategy):
    """Reuse the JSON forecast prompt with Gemini models."""

    name = "gemini_forecast"
    version = "0.1"
    description = "JSON-mode forecast prompt using Gemini 2.5 Pro"
    default_model = "gemini-2.5-pro"
    default_provider = "gemini"


__all__ = ["GeminiForecastStrategy"]
