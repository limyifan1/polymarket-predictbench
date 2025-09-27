"""Research strategy capturing superforecaster planning artifacts."""

from __future__ import annotations

from typing import Any

from ..base import EventMarketGroup
from ...context import PipelineContext
from ..openai.base import StructuredLLMResearchStrategy, _format_event_context


class SuperforecasterBriefingResearch(StructuredLLMResearchStrategy):
    """Produce a base-rate anchored brief inspired by superforecaster workflows."""

    name = "superforecaster_briefing"
    version = "0.1"
    description = (
        "Structured brief that records base rates, scenario decomposition, and update triggers"
    )
    system_message = (
        "You are an elite superforecaster preparing a briefing for a prediction market run. "
        "Combine outside-view base rates with specific scenario analysis and an update plan."
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
            "Review the market group information and craft a structured planning brief. "
            "Follow superforecaster best practices: identify an appropriate reference class, "
            "quantify an outside-view base rate, break the question into key scenarios, and "
            "list concrete indicators you will monitor to update the forecast."
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
                "reference_class": {
                    "type": "string",
                    "description": "Short description of the closest historical comparison",
                },
                "base_rate": {
                    "type": "object",
                    "properties": {
                        "probability": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 1,
                        },
                        "source": {"type": "string"},
                        "notes": {"type": "string"},
                    },
                    "required": ["probability", "source"],
                    "additionalProperties": False,
                },
                "scenario_decomposition": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "description": {"type": "string"},
                            "probability": {
                                "type": "number",
                                "minimum": 0,
                                "maximum": 1,
                            },
                            "impact": {"type": "string"},
                        },
                        "required": ["name", "description", "probability"],
                        "additionalProperties": False,
                    },
                },
                "key_uncertainties": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "update_triggers": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "indicator": {"type": "string"},
                            "threshold": {"type": "string"},
                            "direction": {"type": "string"},
                        },
                        "required": ["indicator"],
                        "additionalProperties": False,
                    },
                },
                "confidence": {
                    "type": "string",
                    "description": "Low/Medium/High self-assessed confidence in the current read",
                },
                "generated_at": {"type": "string"},
            },
            "required": [
                "reference_class",
                "base_rate",
                "scenario_decomposition",
                "update_triggers",
                "confidence",
                "generated_at",
            ],
            "additionalProperties": False,
        }
        return "SuperforecasterBriefing", schema

    def postprocess_payload(
        self,
        payload: dict[str, Any],
        *,
        group: EventMarketGroup,
        context: PipelineContext,
        runtime,
        response: Any,
    ) -> dict[str, Any]:
        payload = super().postprocess_payload(
            payload,
            group=group,
            context=context,
            runtime=runtime,
            response=response,
        )

        base_rate = payload.get("base_rate", {})
        probability = base_rate.get("probability")
        if isinstance(probability, (int, float)):
            base_rate["probability"] = max(0.0, min(1.0, float(probability)))
        else:
            base_rate.pop("probability", None)

        for scenario in payload.get("scenario_decomposition", []):
            prob = scenario.get("probability")
            if isinstance(prob, (int, float)):
                scenario["probability"] = max(0.0, min(1.0, float(prob)))
            else:
                scenario.pop("probability", None)

        return payload

    def extra_diagnostics(
        self,
        *,
        group: EventMarketGroup,
        context: PipelineContext,
        runtime,
        response: Any,
    ) -> dict[str, Any] | None:
        artifact = getattr(response, "output_text", None)
        diagnostics: dict[str, Any] = {}
        if artifact:
            diagnostics["raw_output_excerpt"] = artifact[:4000]
        return diagnostics or None


__all__ = ["SuperforecasterBriefingResearch"]
