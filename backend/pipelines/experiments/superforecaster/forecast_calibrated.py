"""Forecast strategy blending LLM output with base-rate calibration."""

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
    ResearchOutput,
)
from ...context import PipelineContext
from ..llm_support import resolve_llm_request
from ..openai.base import DEFAULT_FORECAST_MODEL, _format_market, _strategy_stage_name


def _forecast_schema(market: NormalizedMarket) -> tuple[str, dict[str, Any]]:
    outcome_properties: dict[str, Any] = {}
    required: list[str] = []
    for contract in market.contracts:
        outcome_properties[contract.name] = {
            "type": "object",
            "properties": {
                "probability": {"type": "number", "minimum": 0, "maximum": 1},
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
                "description": "Narrative explanation grounded in the scenarios and base rate",
            },
            "confidence": {
                "type": "string",
                "description": "Low/Medium/High calibration self-rating",
            },
            "monitoring_plan": {
                "type": "array",
                "items": {"type": "string"},
            },
            "calibration_notes": {"type": "string"},
        },
        "required": ["outcomes", "market_view", "confidence"],
        "additionalProperties": False,
    }
    schema_name = f"SuperforecasterForecast_{market.market_id}"
    return schema_name, schema


def _clamp_probability(value: float | None) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric != numeric:  # NaN check
        return None
    return max(0.0, min(1.0, numeric))


def _base_rate_map(market: NormalizedMarket) -> dict[str, float]:
    contracts = list(market.contracts)
    if not contracts:
        return {}
    explicit = {
        contract.name: _clamp_probability(contract.current_price) for contract in contracts
    }
    if any(value is None for value in explicit.values()):
        fallback = 1.0 / len(contracts)
        return {name: (value if value is not None else fallback) for name, value in explicit.items()}
    return explicit  # type: ignore[return-value]


def _normalize(probabilities: Mapping[str, float]) -> dict[str, float]:
    total = sum(probabilities.values())
    if total <= 0:
        return {name: 1.0 / len(probabilities) for name in probabilities}
    return {name: value / total for name, value in probabilities.items()}


def _format_monitoring(plan: Sequence[str] | None) -> str | None:
    if not plan:
        return None
    lines = "\n".join(f"- {item}" for item in plan if item)
    return lines or None


class SuperforecasterDelphiForecast(ForecastStrategy):
    """Blend structured research with calibrated probability updates."""

    name = "superforecaster_delphi"
    version = "0.1"
    description = "Superforecaster-inspired prompt with base-rate regression"
    requires: Sequence[str] = ("superforecaster_briefing",)
    optional_research: Sequence[str] = (
        "openai_web_search",
        "atlas_research_sweep",
        "horizon_signal_timeline",
    )
    default_model: str | None = DEFAULT_FORECAST_MODEL
    default_request_options: Mapping[str, Any] | None = None
    require_api_key: bool = True
    model_weight: float = 0.6
    base_rate_weight: float = 0.4

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
        briefing_payload: Mapping[str, Any],
        supplemental_research: Sequence[tuple[str, Mapping[str, Any]]],
    ) -> list[dict[str, str]]:
        briefing_json = json.dumps(briefing_payload, indent=2, ensure_ascii=False)
        supplemental_chunks = [
            f"{name}:\n{json.dumps(payload, indent=2, ensure_ascii=False)}"
            for name, payload in supplemental_research
        ]
        supplemental_text = "\n\n".join(supplemental_chunks) if supplemental_chunks else "(none)"
        system = (
            "You are a disciplined superforecaster. Anchor to the base rate, incorporate scenario "
            "analysis, and make explicit, numerically calibrated probability updates."
        )
        user = (
            "Market details:\n"
            f"{_format_market(market)}"
            "\n\nSuperforecaster briefing JSON:\n"
            f"{briefing_json}"
            "\n\nAdditional research artifacts:\n"
            f"{supplemental_text}"
            "\n\nInstructions:\n"
            "1. Start from the base rate in the briefing and adjust using the scenarios.\n"
            "2. Explain how each adjustment changes the odds. Reference evidence or monitoring triggers.\n"
            "3. Output calibrated probabilities (0-1) for every outcome that sum to 1.\n"
            "4. Provide a concise market_view narrative and list key monitoring actions."
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    def _collect_research(
        self,
        research_artifacts: Mapping[str, ResearchOutput],
    ) -> tuple[Mapping[str, Any], list[tuple[str, Mapping[str, Any]]]]:
        briefing_artifact = research_artifacts.get("superforecaster_briefing")
        if not briefing_artifact or briefing_artifact.payload is None:
            raise ExperimentExecutionError(
                "Superforecaster forecast missing required briefing artifact"
            )
        supplemental: list[tuple[str, Mapping[str, Any]]] = []
        for name in self.optional_research:
            artifact = research_artifacts.get(name)
            if artifact and artifact.payload is not None:
                supplemental.append((name, artifact.payload))
        return briefing_artifact.payload, supplemental

    def run(
        self,
        group: EventMarketGroup,
        research_artifacts: Mapping[str, ResearchOutput],
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

        briefing_payload, supplemental = self._collect_research(research_artifacts)

        outputs: list[ForecastOutput] = []
        for market in group.markets:
            if not market.contracts:
                logger.info("Market %s has no contracts; skipping superforecaster forecast", market.market_id)
                continue

            schema_name, schema = _forecast_schema(market)
            request_kwargs = runtime.merge_options(
                runtime.json_mode_kwargs(schema_name=schema_name, schema=schema)
            )
            try:
                response = runtime.invoke(
                    messages=self.build_messages(
                        market=market,
                        briefing_payload=briefing_payload,
                        supplemental_research=supplemental,
                    ),
                    options=request_kwargs,
                    tools=runtime.tools,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("Superforecaster forecast request failed")
                raise ExperimentExecutionError(str(exc)) from exc

            payload = runtime.extract_json(response)
            outcomes_payload = payload.get("outcomes", {})
            raw_probabilities: dict[str, float | None] = {}
            rationales: list[str] = []
            for contract in market.contracts:
                entry = outcomes_payload.get(contract.name, {})
                probability = _clamp_probability(entry.get("probability"))
                raw_probabilities[contract.name] = probability
                rationale = entry.get("rationale")
                if isinstance(rationale, str) and rationale.strip():
                    rationales.append(f"{contract.name}: {rationale.strip()}")

            base_rates = _base_rate_map(market)
            blended: dict[str, float] = {}
            for outcome, base_rate in base_rates.items():
                model_prob = raw_probabilities.get(outcome)
                if model_prob is None:
                    blended[outcome] = base_rate
                else:
                    blended[outcome] = (
                        self.model_weight * model_prob + self.base_rate_weight * base_rate
                    )
            normalized = _normalize(blended) if blended else {}

            monitoring_plan = payload.get("monitoring_plan")
            monitoring_text = _format_monitoring(monitoring_plan if isinstance(monitoring_plan, list) else None)

            reasoning_sections: list[str] = []
            market_view = payload.get("market_view")
            if isinstance(market_view, str) and market_view.strip():
                reasoning_sections.append(market_view.strip())
            if rationales:
                reasoning_sections.append("Key rationales:\n" + "\n".join(rationales))
            if base_rates:
                anchor = ", ".join(f"{name}={value:.2f}" for name, value in base_rates.items())
                reasoning_sections.append(
                    f"Probabilities regressed 40% toward base-rate anchor ({anchor}) to mirror superforecaster calibration."
                )
            calibration_notes = payload.get("calibration_notes")
            if isinstance(calibration_notes, str) and calibration_notes.strip():
                reasoning_sections.append(f"Calibration notes: {calibration_notes.strip()}")
            if monitoring_text:
                reasoning_sections.append("Monitoring plan:\n" + monitoring_text)
            reasoning = "\n\n".join(reasoning_sections) or "Superforecaster-calibrated forecast."

            diagnostics = runtime.diagnostics(
                usage=runtime.usage_dict(response),
                extra={
                    "confidence": payload.get("confidence"),
                    "raw_probabilities": raw_probabilities,
                    "base_rate_probabilities": base_rates,
                    "normalized_probabilities": normalized,
                    "blend_weights": {
                        "model": self.model_weight,
                        "base_rate": self.base_rate_weight,
                    },
                    "monitoring_plan": monitoring_plan,
                },
            )

            outcome_prices = {
                outcome: float(prob) if isinstance(prob, (int, float)) else None
                for outcome, prob in normalized.items()
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


__all__ = ["SuperforecasterDelphiForecast"]
