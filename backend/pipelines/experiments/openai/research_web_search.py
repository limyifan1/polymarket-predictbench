"""Structured research strategy that leans on OpenAI web search."""

from __future__ import annotations

from typing import Any

from ..base import EventMarketGroup
from ...context import PipelineContext
from .base import StructuredLLMResearchStrategy, _format_event_context


class OpenAIWebSearchResearch(StructuredLLMResearchStrategy):
    """Collect fresh context via OpenAI's web-search tool."""

    name = "openai_web_search"
    version = "0.2"
    shared_identity = "catalog:openai_web_search:v0.2"
    description = "High-signal synthesis grounded in recent web results"
    system_message = (
        "You are an analyst producing structured intelligence summaries for prediction markets. "
        "Use the provided context plus web search results to build a concise brief."
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
            "Summarise the current state of the following market group. Highlight catalysts, "
            "key uncertainties, and cite high-quality sources."
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
                "summary": {"type": "string", "description": "Three-sentence synthesis"},
                "key_insights": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Bullet list of the most important takeaways",
                },
                "confidence": {
                    "type": "string",
                    "description": "Low/Medium/High confidence assessment",
                },
                "sources": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "url": {"type": "string"},
                            "snippet": {"type": "string"},
                        },
                        "required": ["title", "url", "snippet"],
                        "additionalProperties": False,
                    },
                },
                "generated_at": {"type": "string"},
            },
            "required": ["summary", "key_insights", "confidence", "sources", "generated_at"],
            "additionalProperties": False,
        }
        return "ResearchArtifact", schema


__all__ = ["OpenAIWebSearchResearch"]
