"""Balanced research sweep strategy."""

from __future__ import annotations

from typing import Any

from ..base import EventMarketGroup
from ...context import PipelineContext
from .base import StructuredLLMResearchStrategy, _format_event_context


class AtlasResearchSweep(StructuredLLMResearchStrategy):
    """Multi-angle evidence sweep that contrasts bullish and bearish narratives."""

    name = "atlas_research_sweep"
    version = "0.1"
    description = "Structured sweep of supporting and challenging evidence"
    system_message = (
        "You are compiling a balanced research brief. Surface the strongest points for and against "
        "the event resolving in favour of the primary market outcome."
    )

    def build_user_prompt(
        self,
        group: EventMarketGroup,
        *,
        context: PipelineContext,
        runtime,
    ) -> str:
        del context, runtime
        return (
            "Identify the most compelling bullish and bearish evidence for this market. "
            "Limit each side to three concise points with citations."
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
        schema = {
            "type": "object",
            "properties": {
                "bullish": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Arguments suggesting the main outcome resolves positive",
                },
                "bearish": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Arguments suggesting the main outcome fails",
                },
                "key_risks": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Cross-cutting risks or unknowns",
                },
                "generated_at": {"type": "string"},
            },
            "required": ["bullish", "bearish", "key_risks", "generated_at"],
            "additionalProperties": False,
        }
        return "EvidenceSweep", schema


__all__ = ["AtlasResearchSweep"]
