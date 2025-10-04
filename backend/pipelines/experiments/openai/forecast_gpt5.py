"""Forecast strategy that consumes OpenAI research artifacts."""

from __future__ import annotations

import json
from datetime import date, datetime
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


def _extract_research_date(payload: Mapping[str, Any] | None) -> date | None:
    if not isinstance(payload, Mapping):
        return None
    generated_at = payload.get("generated_at")
    if not isinstance(generated_at, str):
        return None
    candidate = generated_at.strip()
    if not candidate:
        return None
    try:
        timestamp = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError:
        return None
    return timestamp.date()


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
    default_model: str | None = DEFAULT_FORECAST_MODEL
    default_request_options: Mapping[str, Any] | None = None
    require_api_key: bool = True

    def __init__(self, *, requires: Sequence[str]) -> None:
        if not requires:
            raise ValueError("GPT5ForecastStrategy requires at least one research dependency")
        self.requires = tuple(str(dep) for dep in requires)
    default_provider: str | None = None

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
        research_date: date,
    ) -> list[dict[str, str]]:
        context_chunks = [
            f"Research ({name}):\n{json.dumps(payload, indent=2, ensure_ascii=False)}"
            for name, payload in research_payloads
        ]
        combined_context = "\n\n".join(context_chunks)
        generated_on = research_date.isoformat()
        system = (
            "You are a probabilistic forecaster. Use the provided research to produce calibrated outcome probabilities."
        )
        user = (
            f"The latest research artifacts were generated on {generated_on}."
            "\n\nProduce probabilities that sum to 1 for the market's outcomes. Reference the research evidence in your rationale."
            "\n\nMarket context:\n"
            f"{_format_market(market, include_contract_prices=False)}"
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
            default_provider=self.default_provider,
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
            research_dates: list[date] = []
            for name in self.requires:
                artifact = research_artifacts.get(name)
                if not artifact or artifact.payload is None:
                    raise ExperimentExecutionError(
                        f"Forecast '{self.name}' missing required research artifact '{name}'"
                    )
                research_payloads.append((name, artifact.payload))
                generated_at = _extract_research_date(artifact.payload)
                if generated_at is not None:
                    research_dates.append(generated_at)

            research_date = max(research_dates) if research_dates else context.run_date

            try:
                response = runtime.invoke(
                    messages=self.build_messages(
                        market=market,
                        research_payloads=research_payloads,
                        research_date=research_date,
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
