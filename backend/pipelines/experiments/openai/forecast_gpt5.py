"""Forecast strategy that consumes OpenAI research artifacts."""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from loguru import logger

from app.domain.models import NormalizedMarket

from ..base import (
    EventMarketGroup,
    ExperimentExecutionError,
    ForecastOutput,
    ForecastStrategy,
)
from ...context import PipelineContext
from ..llm_support import resolve_llm_request
from .base import DEFAULT_FORECAST_MODEL, _format_market, _strategy_stage_name


def _forecast_schema(market: NormalizedMarket) -> tuple[str, dict[str, Any]]:
    outcome_properties: dict[str, Any] = {}
    required: list[str] = []
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
                "description": "Narrative explanation for the allocation",
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


class GPT5ForecastStrategy(ForecastStrategy):
    """Simple forecast strategy that consumes research artifacts."""

    name = "gpt5_forecast"
    version = "0.2"
    description = "JSON-mode forecast prompt using GPT-5 preview"
    requires: Sequence[str] = ("openai_web_search",)
    default_model: str | None = DEFAULT_FORECAST_MODEL
    default_request_options: Mapping[str, Any] | None = None
    require_api_key: bool = True

    def resolve_default_model(self, context: PipelineContext) -> str | None:
        del context
        return self.default_model

    def resolve_fallback_model(self, context: PipelineContext) -> str | None:
        del context
        return None

    def build_messages(
        self,
        *,
        market: NormalizedMarket,
        research_payloads: list[tuple[str, dict[str, Any]]],
    ) -> list[dict[str, str]]:
        context_chunks = [
            f"Research ({name}):\n{json.dumps(payload, indent=2, ensure_ascii=False)}"
            for name, payload in research_payloads
        ]
        combined_context = "\n\n".join(context_chunks)
        system = (
            "You are a probabilistic forecaster. Use the provided research to produce calibrated outcome probabilities."
        )
        user = (
            "Produce probabilities that sum to 1 for the market's outcomes. Reference the research evidence in your rationale."
            "\n\nMarket context:\n"
            f"{_format_market(market)}"
            "\n\nResearch context:\n"
            f"{combined_context if combined_context else 'No research supplied.'}"
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    def run(
        self,
        group: EventMarketGroup,
        research_artifacts,
        context: PipelineContext,
    ) -> Sequence[ForecastOutput]:
        stage_name = _strategy_stage_name(self, "forecast")
        runtime = resolve_llm_request(
            self,
            context,
            stage=stage_name,
            default_model=self.resolve_default_model(context),
            fallback_model=self.resolve_fallback_model(context),
            default_tools=None,
            default_request_options=self.default_request_options,
            require_api_key=self.require_api_key,
        )

        outputs: list[ForecastOutput] = []
        for market in group.markets:
            if not market.contracts:
                logger.info("Market %s has no contracts; skipping forecast", market.market_id)
                continue

            schema_name, schema = _forecast_schema(market)
            request_kwargs = runtime.merge_options(
                runtime.json_mode_kwargs(schema_name=schema_name, schema=schema)
            )
            research_payloads: list[tuple[str, dict[str, Any]]] = []
            for name in self.requires:
                artifact = research_artifacts.get(name)
                if not artifact or artifact.payload is None:
                    raise ExperimentExecutionError(
                        f"Forecast '{self.name}' missing required research artifact '{name}'"
                    )
                research_payloads.append((name, artifact.payload))

            try:
                response = runtime.invoke(
                    messages=self.build_messages(
                        market=market,
                        research_payloads=research_payloads,
                    ),
                    options=request_kwargs,
                    tools=runtime.tools,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("LLM forecast request failed")
                raise ExperimentExecutionError(str(exc)) from exc

            forecast_payload = runtime.extract_json(response)
            outcomes_payload = forecast_payload.get("outcomes", {})
            outcome_prices: dict[str, float | None] = {}
            rationales: list[str] = []
            for contract in market.contracts:
                entry = outcomes_payload.get(contract.name, {})
                prob = entry.get("probability")
                rationale = entry.get("rationale")
                outcome_prices[contract.name] = float(prob) if isinstance(prob, (int, float)) else None
                if isinstance(rationale, str) and rationale.strip():
                    rationales.append(f"{contract.name}: {rationale.strip()}")

            reasoning = forecast_payload.get("market_view")
            if not reasoning:
                reasoning = "\n".join(rationales) or f"Forecast generated via {runtime.model}"

            diagnostics = runtime.diagnostics(
                usage=runtime.usage_dict(response),
                extra={"confidence": forecast_payload.get("confidence")},
            )

            outputs.append(
                ForecastOutput(
                    market_id=market.market_id,
                    outcome_prices=outcome_prices,
                    reasoning=reasoning,
                    diagnostics=diagnostics,
                )
            )
        return outputs


__all__ = ["GPT5ForecastStrategy"]
