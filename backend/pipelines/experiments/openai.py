"""OpenAI-powered research and forecasting strategies."""

from __future__ import annotations

import json
from dataclasses import dataclass

from loguru import logger

from app.domain import NormalizedMarket

from ..context import PipelineContext
from .base import (
    EventMarketGroup,
    ExperimentExecutionError,
    ExperimentSkip,
    ForecastOutput,
    ForecastStrategy,
    ResearchOutput,
    ResearchStrategy,
)
from .llm_support import (
    LLMRequestSpec,
    extract_json,
    hash_payload,
    iso_timestamp,
    json_mode_kwargs,
    resolve_llm_request,
    usage_dict,
)
from .suites import BaseExperimentSuite

def _strategy_stage_name(strategy: Any, default: str = "research") -> str:
        return default


class StructuredLLMResearchStrategy(ResearchStrategy):
    """Base class that handles LLM request lifecycle for research strategies."""
    system_message: str = ""
    default_model: str | None = None
    fallback_settings_attr: str | None = "openai_research_model"
    default_tools: tuple[Mapping[str, Any], ...] | None = ({"type": "web_search"},)
    default_request_options: Mapping[str, Any] | None = None
    require_api_key: bool = True
    error_label: str = "LLM research request failed"

    def _fallback_model(self, context: PipelineContext) -> str | None:
        if self.default_model:
            return self.default_model
        if self.fallback_settings_attr:
            return getattr(context.settings, self.fallback_settings_attr, None)
        return None
    def build_messages(
        self,
        group: EventMarketGroup,
        *,
        context: PipelineContext,
        runtime: LLMRequestSpec,
    ) -> Sequence[Mapping[str, str]]:
        return [
            {"role": "system", "content": self.system_prompt(group=group, context=context, runtime=runtime)},
            {"role": "user", "content": self.build_user_prompt(group, context=context, runtime=runtime)},
        ]

    def system_prompt(
        self,
        *,
        group: EventMarketGroup,
        context: PipelineContext,
        runtime: LLMRequestSpec,
    ) -> str:
        return self.system_message

    def build_user_prompt(
        self,
        group: EventMarketGroup,
        *,
        context: PipelineContext,
        runtime: LLMRequestSpec,
    ) -> str:
        raise NotImplementedError

    def build_schema(
        self,
        group: EventMarketGroup,
        *,
        context: PipelineContext,
        runtime: LLMRequestSpec,
    ) -> tuple[str, dict[str, Any]]:
        raise NotImplementedError

    def extra_request_options(
        self,
        group: EventMarketGroup,
        *,
        context: PipelineContext,
        runtime: LLMRequestSpec,
    ) -> Mapping[str, Any] | None:
        return None

    def postprocess_payload(
        self,
        payload: dict[str, Any],
        *,
        group: EventMarketGroup,
        context: PipelineContext,
        runtime: LLMRequestSpec,
        response: Any,
    ) -> dict[str, Any]:
        payload.setdefault("generated_at", iso_timestamp())
        return payload

    def extra_diagnostics(
        self,
        *,
        group: EventMarketGroup,
        context: PipelineContext,
        runtime: LLMRequestSpec,
        response: Any,
    ) -> Mapping[str, Any] | None:
        return None

    def run(self, group: EventMarketGroup, context: PipelineContext) -> ResearchOutput:  # type: ignore[override]
        stage_name = _strategy_stage_name(self, "research")
        runtime = resolve_llm_request(
            self,
            context,
            stage=stage_name,
            default_model=self.default_model,
            fallback_model=self._fallback_model(context),
            default_tools=self.default_tools,
            default_request_options=self.default_request_options,
            require_api_key=self.require_api_key,
        )
        schema_name, schema = self.build_schema(group, context=context, runtime=runtime)
        request_kwargs = runtime.merge_options(
            json_mode_kwargs(runtime.client, schema_name=schema_name, schema=schema)
        )
        extra_options = self.extra_request_options(group, context=context, runtime=runtime)
        if extra_options:
            request_kwargs.update(extra_options)
        try:
            request_payload: dict[str, Any] = {
                "model": runtime.model,
                "input": self.build_messages(group, context=context, runtime=runtime),
                **request_kwargs,
            }
            tools_payload = runtime.tools_payload()
            if tools_payload is not None:
                request_payload["tools"] = tools_payload
            response = runtime.client.responses.create(**request_payload)
        except Exception as exc:  # noqa: BLE001
            logger.exception(self.error_label)
            raise ExperimentExecutionError(str(exc)) from exc

        payload = extract_json(response)
        payload = self.postprocess_payload(
            payload,
            group=group,
            context=context,
            runtime=runtime,
            response=response,
        )
        diagnostics = runtime.diagnostics(
            usage=usage_dict(response),
            extra=self.extra_diagnostics(
                group=group,
                context=context,
                runtime=runtime,
                response=response,
            ),
        )
        artifact_hash = hash_payload(payload)
        return ResearchOutput(
            payload=payload,
            artifact_hash=artifact_hash,
            diagnostics=diagnostics,
        )
class OpenAIWebSearchResearch(StructuredLLMResearchStrategy):
    system_message: str = (
    def build_user_prompt(
        self,
        group: EventMarketGroup,
        *,
        context: PipelineContext,
        runtime: LLMRequestSpec,
    ) -> str:
        return (
    def build_schema(
        self,
        group: EventMarketGroup,
        *,
        context: PipelineContext,
        runtime: LLMRequestSpec,
    ) -> tuple[str, dict[str, Any]]:
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
        return "ResearchArtifact", schema
class AtlasResearchSweep(StructuredLLMResearchStrategy):
    system_message: str = (
    def _schema_definition() -> tuple[str, dict[str, Any]]:
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
    def build_user_prompt(
        self,
        group: EventMarketGroup,
        *,
        context: PipelineContext,
        runtime: LLMRequestSpec,
    ) -> str:
        return (
    def build_schema(
        self,
        group: EventMarketGroup,
        *,
        context: PipelineContext,
        runtime: LLMRequestSpec,
    ) -> tuple[str, dict[str, Any]]:
        return self._schema_definition()
class ScoutChainReflex(StructuredLLMResearchStrategy):
    system_message: str = (
    def _iteration_count(runtime: LLMRequestSpec) -> int:
        raw = runtime.overrides.get("iterations", 3)
        try:
            iterations = int(raw)
        except (TypeError, ValueError):
            iterations = 3
        return max(1, min(iterations, 5))

    def build_user_prompt(
        self,
        group: EventMarketGroup,
        *,
        context: PipelineContext,
        runtime: LLMRequestSpec,
    ) -> str:
        iterations = self._iteration_count(runtime)
        return (
            f"Run up to {iterations} scouting passes focusing on fresh, high-signal data. "
            "After each pass, critique whether the findings change our stance and note the next move. "
            "Close with an explicit final assessment and open questions.\n\n"
            f"Context:\n{_format_event_context(group)}"
        )

    def build_schema(
        self,
        group: EventMarketGroup,
        *,
        context: PipelineContext,
        runtime: LLMRequestSpec,
    ) -> tuple[str, dict[str, Any]]:
    def extra_diagnostics(
        self,
        *,
        group: EventMarketGroup,
        context: PipelineContext,
        runtime: LLMRequestSpec,
        response: Any,
    ) -> Mapping[str, Any] | None:
        return {"iterations": self._iteration_count(runtime)}
class LexisDigestStructured(StructuredLLMResearchStrategy):
    system_message: str = (
    def _evidence_schema() -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "claim": {"type": "string"},
                "source_title": {"type": "string"},
                "source_url": {"type": "string"},
                "confidence": {"type": "string"},
                "probability_effect": {
                    "type": "number",
                    "minimum": -1,
                    "maximum": 1,
                "notes": {"type": "string"},
            },
            "required": ["claim", "source_title", "source_url"],
            "additionalProperties": False,
        }
    def build_user_prompt(
        self,
        group: EventMarketGroup,
        *,
        context: PipelineContext,
        runtime: LLMRequestSpec,
    ) -> str:
        return (
            "Prepare a Lexis-style digest focused on verifiable claims. Split the evidence into supporting and "
            "contradicting sets and estimate how the net evidence should shift probability mass.\n\n"
            f"Context:\n{_format_event_context(group)}"
        )

    def build_schema(
        self,
        group: EventMarketGroup,
        *,
        context: PipelineContext,
        runtime: LLMRequestSpec,
    ) -> tuple[str, dict[str, Any]]:
                    "items": self._evidence_schema(),
                    "items": self._evidence_schema(),
        stage_name = _strategy_stage_name(self, "research")
        runtime = resolve_llm_request(
            self,
            context,
            stage=stage_name,
            default_model=self.default_model,
            fallback_model=getattr(context.settings, "openai_research_model", None),
            default_tools=None,
        )
            {"id": "bullish", "model": runtime.overrides.get("bullish_model", "gpt-4.1")},
            {"id": "bearish", "model": runtime.overrides.get("bearish_model", "gpt-4.1-mini")},
            {"id": "neutral", "model": runtime.overrides.get("neutral_model", "gpt-4o-mini")},
        frame_configs: Sequence[Mapping[str, Any]] = runtime.overrides.get("frame_configs", default_frames)
            model = frame_cfg.get("model")
            if not isinstance(model, str) or not model.strip():
            request_kwargs = runtime.merge_options(
                json_mode_kwargs(runtime.client, schema_name=schema_name, schema=schema)
            tools_override = frame_cfg.get("tools") or runtime.overrides.get("tools")
            if isinstance(tools_override, Sequence) and not isinstance(tools_override, (str, bytes)):
                tools_payload = [dict(tool) for tool in tools_override]  # type: ignore[arg-type]
            else:
                tools_payload = [{"type": "web_search"}]
                response = runtime.client.responses.create(
                    tools=tools_payload,

            payload = extract_json(response)
            payload.setdefault("generated_at", iso_timestamp())
                    "usage": usage_dict(response),
                    "provider": runtime.provider,
        aggregator_prompt = (
        aggregator_kwargs = runtime.merge_options(
            json_mode_kwargs(runtime.client, schema_name=schema_name, schema=schema)
            response = runtime.client.responses.create(
                model=runtime.model,
                    {"role": "user", "content": aggregator_prompt},
                **aggregator_kwargs,
        payload = extract_json(response)
        payload.setdefault("generated_at", iso_timestamp())
            "aggregator_model": runtime.model,
            "aggregator_usage": usage_dict(response),
            "provider": runtime.provider,
        artifact_hash = hash_payload(payload)
class HorizonSignalTimeline(StructuredLLMResearchStrategy):
    system_message: str = (
    def build_user_prompt(
        self,
        group: EventMarketGroup,
        *,
        context: PipelineContext,
        runtime: LLMRequestSpec,
    ) -> str:
        return (
            "Construct a timeline that distinguishes past catalysts (already happened) from upcoming catalysts "
            "(future or scheduled). Highlight how each entry could move the market and the confidence level.\n\n"
            f"Context:\n{_format_event_context(group)}"
        )

    def build_schema(
        self,
        group: EventMarketGroup,
        *,
        context: PipelineContext,
        runtime: LLMRequestSpec,
    ) -> tuple[str, dict[str, Any]]:
def _forecast_schema(market: NormalizedMarket) -> tuple[str, dict[str, Any]]:
    outcome_properties: dict[str, Any] = {}
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
    system_message: str = (

        stage_name = _strategy_stage_name(self, "forecast")
        runtime = resolve_llm_request(
            context,
            stage=stage_name,
            default_model=self.default_model,
            fallback_model=getattr(context.settings, "openai_forecast_model", None),
            default_tools=None,
                logger.info("Market %s has no contracts; skipping forecast", market.market_id)
            request_kwargs = runtime.merge_options(
                json_mode_kwargs(runtime.client, schema_name=schema_name, schema=schema)
                response = runtime.client.responses.create(
                    model=runtime.model,
                        {"role": "system", "content": self.system_message},
            forecast_payload = extract_json(response)
                    else f"Forecast generated via {runtime.model}"
            diagnostics = runtime.diagnostics(
                usage=usage_dict(response),
                extra={"confidence": forecast_payload.get("confidence")},
            )
    version = "0.2"
    "AtlasResearchSweep",
    "ScoutChainReflex",
    "LexisDigestStructured",
    "ConsensusMatrixOrchestrator",
    "HorizonSignalTimeline",
