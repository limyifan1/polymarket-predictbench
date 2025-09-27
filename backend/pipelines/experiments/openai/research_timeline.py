"""Timeline-focused research strategy."""

from __future__ import annotations

from typing import Any

from ..base import EventMarketGroup
from ...context import PipelineContext
from .base import StructuredLLMResearchStrategy, _format_event_context


class HorizonSignalTimeline(StructuredLLMResearchStrategy):
    """Categorise catalysts into past and upcoming timelines."""

    name = "horizon_signal_timeline"
    version = "0.1"
    description = "Categorised timeline of catalysts with impact annotations"
    default_tools: tuple[dict[str, Any], ...] | None = None

    def build_user_prompt(
        self,
        group: EventMarketGroup,
        *,
        context: PipelineContext,
        runtime,
    ) -> str:
        del context, runtime
        return (
            "List notable catalysts that have already happened and those expected soon. "
            "Explain how each item might move the market."
            "\n\nContext:\n"
            f"{_format_event_context(group)}"
        )

    def build_schema(
        self,
        group: EventMarketGroup,
        *,
        context: PipelineContext,
        runtime,
    ) -> tuple[str, dict[str, Any]]:
        del group, context, runtime
        entry_schema = {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "date": {"type": "string"},
                "impact": {"type": "string"},
                "notes": {"type": "string"},
            },
            "required": ["title", "impact"],
            "additionalProperties": False,
        }
        schema = {
            "type": "object",
            "properties": {
                "past": {"type": "array", "items": entry_schema},
                "upcoming": {"type": "array", "items": entry_schema},
                "generated_at": {"type": "string"},
            },
            "required": ["past", "upcoming", "generated_at"],
            "additionalProperties": False,
        }
        return "CatalystTimeline", schema


__all__ = ["HorizonSignalTimeline"]
