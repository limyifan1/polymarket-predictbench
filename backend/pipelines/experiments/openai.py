"""OpenAI-powered research and forecasting strategies."""

from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Any, Mapping, Sequence

from loguru import logger

from app.domain import NormalizedMarket
from app.core.config import Settings
from app.services.openai_client import get_openai_client

from .base import (
    EventMarketGroup,
    ExperimentExecutionError,
    ExperimentSkip,
    ForecastOutput,
    ForecastStrategy,
    ResearchOutput,
    ResearchStrategy,
)
from .suites import BaseExperimentSuite
from ..context import PipelineContext


def _ensure_api_ready(settings: Settings) -> None:
    if not settings.openai_api_key:
        raise ExperimentSkip("OPENAI_API_KEY is not configured; skipping OpenAI suite")


def _hash_payload(payload: dict[str, Any] | None) -> str | None:
    if not payload:
        return None
    serialized = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


@lru_cache(maxsize=8)
def _supports_text_config_for_class(responses_cls) -> bool:
    signature = inspect.signature(responses_cls.create)
    return "text" in signature.parameters


def _json_mode_kwargs(
    client, *, schema_name: str, schema: dict[str, Any]
) -> dict[str, Any]:
    structured: dict[str, Any] = {
        "type": "json_schema",
        "name": schema_name,
        "schema": schema,
    }
    if _supports_text_config_for_class(type(client.responses)):
        return {"text": {"format": structured}}
    return {"response_format": structured}


def _extract_json(response) -> dict[str, Any]:
    """Best-effort extraction of JSON payload from a Responses API result."""

    text_candidate: str | None = None
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text.strip():
        text_candidate = output_text
    if text_candidate is None:
        dump: dict[str, Any] = (
            response.model_dump() if hasattr(response, "model_dump") else dict(response)  # type: ignore[arg-type]
        )
        for item in dump.get("output", []):
            for content in item.get("content", []):
                if isinstance(content, dict):
                    text = content.get("text") or content.get("output_text")
                    if isinstance(text, str) and text.strip():
                        text_candidate = text
                        break
            if text_candidate:
                break
    if not text_candidate:
        raise ExperimentExecutionError("OpenAI response did not include a JSON payload")
    try:
        return json.loads(text_candidate)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise ExperimentExecutionError("Failed to decode OpenAI JSON payload") from exc


def _usage_dict(response) -> dict[str, Any] | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    try:
        return dict(usage)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        return {"raw": str(usage)}


def _format_event_context(group: EventMarketGroup) -> str:
    event = group.event
    parts: list[str] = []
    if event and event.title:
        parts.append(f"Event: {event.title}")
    if event and event.description:
        parts.append(f"Event description: {event.description}")
    parts.append("Markets:")
    for market in group.markets:
        line = f"- {market.question}"
        if market.close_time:
            line += f" (closes {market.close_time.isoformat()} UTC)"
        if market.volume_usd is not None:
            line += f" | volume ${market.volume_usd:,.0f}"
        contracts = ", ".join(contract.name for contract in market.contracts)
        if contracts:
            line += f" | outcomes: {contracts}"
        parts.append(line)
    return "\n".join(parts)


def _research_schema() -> tuple[str, dict[str, Any]]:
    schema = {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "High-level synthesis"},
            "key_insights": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Bullet points capturing market movers",
            },
            "confidence": {
                "type": "string",
                "description": "Low/Medium/High confidence in the research",
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
                "description": "Supporting references with URLs",
            },
            "generated_at": {
                "type": "string",
                "description": "ISO-8601 generation timestamp",
            },
        },
        "required": [
            "summary",
            "key_insights",
            "confidence",
            "sources",
            "generated_at",
        ],
        "additionalProperties": False,
    }
    return "ResearchArtifact", schema


def _forecast_schema(market: NormalizedMarket) -> tuple[str, dict[str, Any]]:
    outcome_properties = {}
    required = []
    for contract in market.contracts:
        outcome_properties[contract.name] = {
            "type": "object",
            "properties": {
                "probability": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                },
                "rationale": {"type": "string"},
            },
            "required": ["probability", "rationale"],
            "additionalProperties": False,
        }
        required.append(contract.name)
    schema = {
        "type": "object",
        "properties": {
            "outcomes": {
                "type": "object",
                "properties": outcome_properties,
                "required": required,
                "additionalProperties": False,
            },
            "market_view": {
                "type": "string",
                "description": "One paragraph explaining the allocation",
            },
            "confidence": {
                "type": "string",
                "description": "Low/Medium/High confidence flag",
            },
        },
        "required": ["outcomes", "market_view", "confidence"],
        "additionalProperties": False,
    }
    schema_name = f"MarketForecast_{market.market_id}"
    return schema_name, schema


@dataclass(slots=True)
class OpenAIWebSearchResearch(ResearchStrategy):
    """Fetch fresh context with OpenAI's web search tool."""

    name: str = "openai_web_research"
    version: str = "0.1"
    description: str | None = (
        "Use OpenAI web search to synthesize a concise brief for each event and market."
    )

    _system_prompt: str = (
        "You are a research analyst creating a briefing for a prediction market team. "
        "Use the web_search tool to gather current facts from reputable sources. "
        "Respond with JSON that includes a summary, bullet insights, confidence, and sources."
    )

    def run(self, group: EventMarketGroup, context: PipelineContext) -> ResearchOutput:  # type: ignore[override]
        _ensure_api_ready(context.settings)
        client = get_openai_client(context.settings)

        prompt = (
            "Prepare a research brief for the following Polymarket markets. "
            "Focus on drivers that will resolve the question. "
            "Include clear references that we can review later.\n\n"
            f"Context:\n{_format_event_context(group)}"
        )

        schema_name, schema = _research_schema()
        request_kwargs = _json_mode_kwargs(
            client, schema_name=schema_name, schema=schema
        )
        try:
            response = client.responses.create(
                model=context.settings.openai_research_model,
                input=[
                    {"role": "system", "content": self._system_prompt},
                    {"role": "user", "content": prompt},
                ],
                tools=[{"type": "web_search"}],
                **request_kwargs,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("OpenAI research request failed")
            raise ExperimentExecutionError(str(exc)) from exc

        payload = _extract_json(response)
        payload.setdefault("generated_at", datetime.utcnow().isoformat() + "Z")
        diagnostics = {
            "model": context.settings.openai_research_model,
            "usage": _usage_dict(response),
        }
        artifact_hash = _hash_payload(payload)
        return ResearchOutput(
            payload=payload,
            artifact_hash=artifact_hash,
            diagnostics=diagnostics,
        )


@dataclass(slots=True)
class GPT5ForecastStrategy(ForecastStrategy):
    """Convert research artifacts into outcome probabilities with GPT-5."""

    requires: tuple[str, ...] = ("openai_web_research",)
    name: str = "gpt5_market_forecast"
    version: str = "0.1"
    description: str | None = (
        "Translate research briefs into probability distributions for each market outcome."
    )

    _system_prompt: str = (
        "You are a calibrated probabilistic forecaster. "
        "Produce well-justified probabilities (0-1) for the listed market outcomes. "
        "Respect the JSON schema and ensure the probabilities approximately sum to 1."
    )

    def run(
        self,
        group: EventMarketGroup,
        research_artifacts: Mapping[str, ResearchOutput],
        context: PipelineContext,
    ) -> Sequence[ForecastOutput]:  # type: ignore[override]
        research = research_artifacts.get("openai_web_research")
        if research is None or research.payload is None:
            raise ExperimentSkip("OpenAI research payload missing; skip forecast")
        _ensure_api_ready(context.settings)
        client = get_openai_client(context.settings)

        research_summary = json.dumps(research.payload, ensure_ascii=False, indent=2)

        outputs: list[ForecastOutput] = []
        for market in group.markets:
            if not market.contracts:
                logger.info(
                    "Market %s has no contracts; skipping forecast", market.market_id
                )
                continue
            schema_name, schema = _forecast_schema(market)
            prompt = (
                "Using the research JSON below, assign probabilities to each outcome "
                "for the target market. Provide a short market_view paragraph that "
                "explains the allocation.\n\n"
                f"Research JSON:\n{research_summary}\n\n"
                "Market question: "
                f"{market.question}\n"
            )
            request_kwargs = _json_mode_kwargs(
                client, schema_name=schema_name, schema=schema
            )
            try:
                response = client.responses.create(
                    model=context.settings.openai_forecast_model,
                    input=[
                        {"role": "system", "content": self._system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                    **request_kwargs,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "OpenAI forecast request failed for market %s", market.market_id
                )
                raise ExperimentExecutionError(str(exc)) from exc

            forecast_payload = _extract_json(response)
            outcomes = forecast_payload.get("outcomes", {})
            outcome_prices: dict[str, float | None] = {}
            rationales: list[str] = []
            for outcome_name, values in outcomes.items():
                probability = values.get("probability")
                rationale = values.get("rationale")
                if probability is None:
                    continue
                clamped = max(0.0, min(1.0, float(probability)))
                outcome_prices[outcome_name] = clamped
                if rationale:
                    rationales.append(f"{outcome_name}: {rationale}")
            total = sum(outcome_prices.values())
            if 0 < total and abs(total - 1.0) > 0.05:
                outcome_prices = {k: (v / total) for k, v in outcome_prices.items()}
            reasoning = forecast_payload.get("market_view")
            if not reasoning:
                reasoning = (
                    "\n".join(rationales)
                    if rationales
                    else "Forecast generated via GPT-5"
                )
            diagnostics = {
                "model": context.settings.openai_forecast_model,
                "usage": _usage_dict(response),
                "confidence": forecast_payload.get("confidence"),
            }
            outputs.append(
                ForecastOutput(
                    market_id=market.market_id,
                    outcome_prices=outcome_prices,
                    reasoning=reasoning,
                    diagnostics=diagnostics,
                )
            )
        return outputs


class OpenAIResearchForecastSuite(BaseExperimentSuite):
    """Bundle OpenAI-powered research and forecasting into one suite."""

    suite_id = "openai"
    version = "0.1"
    description = "Experimental OpenAI-backed research + forecast flow"

    def _build_research_strategies(self):  # noqa: D401
        return (OpenAIWebSearchResearch(),)

    def _build_forecast_strategies(self):  # noqa: D401
        return (GPT5ForecastStrategy(),)


__all__ = [
    "OpenAIResearchForecastSuite",
    "OpenAIWebSearchResearch",
    "GPT5ForecastStrategy",
]
