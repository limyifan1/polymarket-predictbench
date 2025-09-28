"""Structured research strategy powered by Gemini + Google Search."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..openai.base import StructuredLLMResearchStrategy, _format_event_context
from ..base import EventMarketGroup
from ...context import PipelineContext


class GeminiWebSearchResearch(StructuredLLMResearchStrategy):
    """Collect fresh context via Gemini's Google Search grounding."""

    name = "gemini_web_search"
    version = "0.1"
    shared_identity = "catalog:gemini_web_search:v0.1"
    description = "Google Search grounded synthesis using Gemini"
    system_message = (
        "You are an analyst producing structured intelligence summaries for prediction markets. "
        "Use the provided context plus grounded Google Search results to craft a concise brief."
    )
    default_model = "gemini-2.5-flash"
    default_provider = "gemini"

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
        return "GeminiResearchArtifact", schema

    def extra_diagnostics(
        self,
        *,
        group: EventMarketGroup,
        context: PipelineContext,
        runtime,
        response: Any,
    ) -> Mapping[str, Any] | None:
        del group, context, runtime
        metadata = self._extract_grounding_metadata(response)
        if metadata is None:
            return None
        return {"grounding_metadata": metadata}

    def _extract_grounding_metadata(self, response: Any) -> Mapping[str, Any] | None:
        candidates = getattr(response, "candidates", None)
        if not candidates:
            return None
        for candidate in candidates:
            raw_metadata = None
            if isinstance(candidate, Mapping):
                raw_metadata = candidate.get("grounding_metadata") or candidate.get(
                    "groundingMetadata"
                )
            if raw_metadata is None:
                raw_metadata = getattr(candidate, "grounding_metadata", None)
            if raw_metadata is None:
                raw_metadata = getattr(candidate, "groundingMetadata", None)
            if raw_metadata is None and hasattr(candidate, "to_dict"):
                try:
                    raw_metadata = candidate.to_dict().get("grounding_metadata")
                except Exception:  # noqa: BLE001 - best effort only
                    raw_metadata = None
            if raw_metadata is None and hasattr(candidate, "model_dump"):
                try:
                    raw_metadata = candidate.model_dump().get("grounding_metadata")
                except Exception:  # noqa: BLE001 - best effort only
                    raw_metadata = None
            if raw_metadata is None:
                continue
            serialised = self._serialise_metadata(raw_metadata)
            if serialised:
                return serialised
        return None

    def _serialise_metadata(self, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, Mapping):
            return {key: self._serialise_metadata(val) for key, val in value.items()}
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            return [self._serialise_metadata(item) for item in value]
        if hasattr(value, "to_dict"):
            try:
                return self._serialise_metadata(value.to_dict())
            except Exception:  # noqa: BLE001
                return None
        if hasattr(value, "model_dump"):
            try:
                return self._serialise_metadata(value.model_dump())
            except Exception:  # noqa: BLE001
                return None
        if hasattr(value, "__dict__") and not isinstance(value, type):
            return {
                key: self._serialise_metadata(val)
                for key, val in vars(value).items()
                if not key.startswith("_")
            }
        return value


__all__ = ["GeminiWebSearchResearch"]
