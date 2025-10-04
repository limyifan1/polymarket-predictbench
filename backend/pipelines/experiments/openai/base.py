"""Shared primitives for OpenAI-powered experiment strategies."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from loguru import logger

from app.domain.models import NormalizedEvent, NormalizedMarket

from ..base import (
    EventMarketGroup,
    ExperimentExecutionError,
    ForecastOutput,
    ForecastStrategy,
    ResearchOutput,
    ResearchStrategy,
)
from ...context import PipelineContext
from ..llm_support import (
    LLMRequestSpec,
    hash_payload,
    iso_timestamp,
    resolve_llm_request,
)

DEFAULT_RESEARCH_MODEL = "gpt-5"
DEFAULT_FORECAST_MODEL = "gpt-5"


__all__ = [
    "DEFAULT_FORECAST_MODEL",
    "DEFAULT_RESEARCH_MODEL",
    "StructuredLLMResearchStrategy",
    "TextLLMResearchStrategy",
    "_format_event_context",
    "_format_market",
    "_strategy_stage_name",
]


def _strategy_stage_name(strategy: Any, default: str = "research") -> str:
    """Return the stage label for a strategy."""

    return getattr(strategy, "stage_name", default)


def _format_event(event: NormalizedEvent | None) -> str:
    if not event:
        return ""
    summary = event.title or event.slug or event.event_id
    details: list[str] = [f"Event: {summary}"]
    if event.start_time:
        details.append(f"Starts: {event.start_time.isoformat()}")
    if event.end_time:
        details.append(f"Ends: {event.end_time.isoformat()}")
    if event.series_title:
        details.append(f"Series: {event.series_title}")
    if event.description:
        details.append(f"Description: {event.description.strip()}"[:400])
    return "\n".join(details)


def _format_market(
    market: NormalizedMarket,
    *,
    include_contract_prices: bool = False,
) -> str:
    lines = [
        f"Market: {market.question}",
        f"Status: {market.status} (closes {market.close_time.isoformat() if market.close_time else 'unknown'})",
    ]
    if market.description:
        lines.append(f"Notes: {market.description.strip()}"[:400])
    if market.contracts:
        lines.append("Outcomes:")
        for contract in market.contracts:
            if include_contract_prices:
                price = (
                    f"{contract.current_price:.2f}"
                    if isinstance(contract.current_price, (int, float))
                    else "unknown"
                )
                lines.append(f"- {contract.name}: price={price}")
            else:
                lines.append(f"- {contract.name}")
    return "\n".join(lines)


def _format_event_context(group: EventMarketGroup) -> str:
    sections: list[str] = []
    event_block = _format_event(group.event)
    if event_block:
        sections.append(event_block)
    for market in group.markets:
        sections.append(_format_market(market))
    return "\n\n".join(sections)


def _extract_textual_response(response: Any) -> str:
    """Extract a plain-text body from an LLM response."""

    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    dump: Mapping[str, Any]
    if hasattr(response, "model_dump"):
        dump = response.model_dump()
    else:
        dump = dict(response)  # type: ignore[arg-type]

    for item in dump.get("output", []):
        if not isinstance(item, Mapping):
            continue
        for content in item.get("content", []):
            if isinstance(content, Mapping):
                text_candidate = content.get("text") or content.get("output_text")
                if isinstance(text_candidate, str) and text_candidate.strip():
                    return text_candidate.strip()

    raise ExperimentExecutionError("LLM response did not include textual content")


class TextLLMResearchStrategy(ResearchStrategy):
    """Base strategy for long-form, unstructured LLM research outputs."""

    name: str = ""
    version: str = "1.0"
    description: str | None = None
    shared_identity: str | None = None

    system_message: str = ""
    default_model: str | None = DEFAULT_RESEARCH_MODEL
    default_tools: tuple[Mapping[str, Any], ...] | None = None
    default_request_options: Mapping[str, Any] | None = None
    require_api_key: bool = True
    default_provider: str | None = None
    content_format: str = "markdown"
    error_label: str = "LLM research request failed"

    def resolve_default_model(self, context: PipelineContext) -> str | None:
        del context
        return self.default_model

    def resolve_fallback_model(self, context: PipelineContext) -> str | None:
        del context
        return None

    def system_prompt(
        self,
        *,
        group: EventMarketGroup,
        context: PipelineContext,
        runtime: LLMRequestSpec,
    ) -> str:
        del group, context, runtime
        return self.system_message

    def build_user_prompt(
        self,
        group: EventMarketGroup,
        *,
        context: PipelineContext,
        runtime: LLMRequestSpec,
    ) -> str:
        raise NotImplementedError

    def extra_request_options(
        self,
        group: EventMarketGroup,
        *,
        context: PipelineContext,
        runtime: LLMRequestSpec,
    ) -> Mapping[str, Any] | None:
        return None

    def postprocess_text_output(
        self,
        content: str,
        *,
        group: EventMarketGroup,
        context: PipelineContext,
        runtime: LLMRequestSpec,
        response: Any,
    ) -> dict[str, Any]:
        return {
            "content": content,
            "content_format": self.content_format,
            "generated_at": iso_timestamp(),
        }

    def extra_diagnostics(
        self,
        *,
        group: EventMarketGroup,
        context: PipelineContext,
        runtime: LLMRequestSpec,
        response: Any,
    ) -> Mapping[str, Any] | None:
        return None

    def run(
        self,
        group: EventMarketGroup,
        context: PipelineContext,
    ) -> ResearchOutput:
        stage_name = _strategy_stage_name(self, "research")
        runtime = resolve_llm_request(
            self,
            context,
            stage=stage_name,
            default_model=self.resolve_default_model(context),
            fallback_model=self.resolve_fallback_model(context),
            default_tools=self.default_tools,
            default_request_options=self.default_request_options,
            require_api_key=self.require_api_key,
            default_provider=self.default_provider,
        )

        request_kwargs = runtime.merge_options()
        messages = [
            {
                "role": "system",
                "content": self.system_prompt(
                    group=group, context=context, runtime=runtime
                ),
            },
            {
                "role": "user",
                "content": self.build_user_prompt(
                    group, context=context, runtime=runtime
                ),
            },
        ]
        options = dict(request_kwargs)
        extra_options = self.extra_request_options(
            group, context=context, runtime=runtime
        )
        if extra_options:
            options.update(extra_options)

        try:
            response = runtime.invoke(
                messages=messages,
                options=options,
                tools=runtime.tools,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(self.error_label)
            raise ExperimentExecutionError(str(exc)) from exc

        content = _extract_textual_response(response)
        payload = self.postprocess_text_output(
            content,
            group=group,
            context=context,
            runtime=runtime,
            response=response,
        )
        diagnostics = runtime.diagnostics(
            usage=runtime.usage_dict(response),
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


class StructuredLLMResearchStrategy(ResearchStrategy):
    """Base class that handles LLM request lifecycle for research strategies."""

    name: str = ""
    version: str = "1.0"
    description: str | None = None
    shared_identity: str | None = None

    system_message: str = ""
    default_model: str | None = DEFAULT_RESEARCH_MODEL
    default_tools: tuple[Mapping[str, Any], ...] | None = None
    default_request_options: Mapping[str, Any] | None = None
    require_api_key: bool = True
    default_provider: str | None = None
    error_label: str = "LLM research request failed"

    def resolve_default_model(self, context: PipelineContext) -> str | None:
        del context
        return self.default_model

    def resolve_fallback_model(self, context: PipelineContext) -> str | None:
        del context
        return None

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

    def run(
        self,
        group: EventMarketGroup,
        context: PipelineContext,
    ) -> ResearchOutput:
        stage_name = _strategy_stage_name(self, "research")
        runtime = resolve_llm_request(
            self,
            context,
            stage=stage_name,
            default_model=self.resolve_default_model(context),
            fallback_model=self.resolve_fallback_model(context),
            default_tools=self.default_tools,
            default_request_options=self.default_request_options,
            require_api_key=self.require_api_key,
            default_provider=self.default_provider,
        )

        schema_name, schema = self.build_schema(group, context=context, runtime=runtime)
        request_kwargs = runtime.merge_options(
            runtime.json_mode_kwargs(schema_name=schema_name, schema=schema)
        )

        messages = [
            {
                "role": "system",
                "content": self.system_prompt(
                    group=group, context=context, runtime=runtime
                ),
            },
            {
                "role": "user",
                "content": self.build_user_prompt(
                    group, context=context, runtime=runtime
                ),
            },
        ]
        options = dict(request_kwargs)
        extra_options = self.extra_request_options(
            group, context=context, runtime=runtime
        )
        if extra_options:
            options.update(extra_options)

        try:
            response = runtime.invoke(
                messages=messages,
                options=options,
                tools=runtime.tools,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(self.error_label)
            raise ExperimentExecutionError(str(exc)) from exc

        artifact = runtime.extract_json(response)
        artifact = self.postprocess_payload(
            artifact,
            group=group,
            context=context,
            runtime=runtime,
            response=response,
        )
        diagnostics = runtime.diagnostics(
            usage=runtime.usage_dict(response),
            extra=self.extra_diagnostics(
                group=group,
                context=context,
                runtime=runtime,
                response=response,
            ),
        )
        artifact_hash = hash_payload(artifact)
        return ResearchOutput(
            payload=artifact, artifact_hash=artifact_hash, diagnostics=diagnostics
        )
