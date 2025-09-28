"""Reusable helpers for LLM-backed experiment strategies."""

from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import dataclass, field
from datetime import datetime
from importlib import import_module
from typing import Any, Callable, Mapping, Sequence

from loguru import logger

from app.services.llm import get_provider
from app.services.llm.base import LLMProvider

from ..context import PipelineContext
from .base import ExperimentExecutionError


@dataclass(slots=True)
class LLMRequestSpec:
    """Resolved runtime configuration for a single LLM request."""

    client: Any
    model: str
    provider: str
    provider_impl: LLMProvider
    stage: str
    experiment_name: str
    strategy_name: str
    run_id: str | None = None
    request_options: dict[str, Any] = field(default_factory=dict)
    tools: tuple[Mapping[str, Any], ...] | None = None
    overrides: Mapping[str, Any] = field(default_factory=dict)

    def merge_options(self, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Return request options merged with optional additional values."""

        merged = dict(self.request_options)
        if extra:
            merged.update(extra)
        return merged

    def tools_payload(self) -> Sequence[Mapping[str, Any]] | None:
        """Return tools as a JSON-serializable sequence if configured."""

        if self.tools is None:
            return None
        return [dict(tool) for tool in self.tools]

    def diagnostics(
        self,
        *,
        usage: Mapping[str, Any] | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a diagnostics dictionary with optional additional context."""

        payload: dict[str, Any] = {
            "model": self.model,
            "provider": self.provider,
        }
        if usage:
            payload["usage"] = usage
        if extra:
            payload.update(extra)
        return payload

    def json_mode_kwargs(
        self,
        *,
        schema_name: str,
        schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        return self.provider_impl.json_mode_kwargs(
            self.client,
            schema_name=schema_name,
            schema=schema,
        )

    def invoke(
        self,
        *,
        messages: Sequence[Mapping[str, Any]],
        options: Mapping[str, Any] | None = None,
        tools: Sequence[Mapping[str, Any]] | None = None,
    ) -> Any:
        message_count = len(messages)
        tool_count = len(tools) if tools else 0
        option_keys = sorted(options.keys()) if options else []
        logger.info(
            "Invoking LLM call run={} experiment={} strategy={} stage={} provider={} model={} messages={} tools={} option_keys={}",
            self.run_id or "n/a",
            self.experiment_name,
            self.strategy_name,
            self.stage,
            self.provider,
            self.model,
            message_count,
            tool_count,
            option_keys,
        )
        try:
            response = self.provider_impl.invoke(
                self,
                messages=messages,
                options=options,
                tools=tools,
            )
        except Exception:
            logger.exception(
                "LLM call failed run={} experiment={} strategy={} stage={} provider={} model={}",
                self.run_id or "n/a",
                self.experiment_name,
                self.strategy_name,
                self.stage,
                self.provider,
                self.model,
            )
            raise

        usage_summary: Mapping[str, Any] | None = None
        try:
            usage_summary = self.provider_impl.usage_dict(response)
        except Exception:
            logger.debug(
                "Failed to extract usage for LLM call run={} experiment={} strategy={} stage={}",
                self.run_id or "n/a",
                self.experiment_name,
                self.strategy_name,
                self.stage,
            )

        if usage_summary:
            logger.info(
                "LLM call completed run={} experiment={} strategy={} stage={} usage={}",
                self.run_id or "n/a",
                self.experiment_name,
                self.strategy_name,
                self.stage,
                usage_summary,
            )
        else:
            logger.info(
                "LLM call completed run={} experiment={} strategy={} stage={} (no usage reported)",
                self.run_id or "n/a",
                self.experiment_name,
                self.strategy_name,
                self.stage,
            )

        return response

    def extract_json(self, response: Any) -> Mapping[str, Any]:
        return self.provider_impl.extract_json(response)

    def usage_dict(self, response: Any) -> Mapping[str, Any] | None:
        return self.provider_impl.usage_dict(response)


def _import_callable(path: str):
    module_path, sep, attr = path.partition(":")
    if not attr:
        module_path, _, attr = path.rpartition(".")
    if not module_path or not attr:
        raise ExperimentExecutionError(
            f"Invalid client_factory path '{path}'. Use 'module:callable' or dotted path form."
        )
    module = import_module(module_path)
    candidate = getattr(module, attr, None)
    if not callable(candidate):
        raise ExperimentExecutionError(f"client_factory '{path}' is not callable")
    return candidate


def _invoke_factory(
    factory: Callable[..., Any],
    context: PipelineContext,
    overrides: Mapping[str, Any],
) -> Any:
    signature = inspect.signature(factory)
    kwargs: dict[str, Any] = {}
    if "context" in signature.parameters:
        kwargs["context"] = context
    if "settings" in signature.parameters:
        kwargs["settings"] = context.settings
    if "overrides" in signature.parameters:
        kwargs["overrides"] = overrides
    try:
        return factory(**kwargs)
    except TypeError as exc:  # noqa: BLE001
        raise ExperimentExecutionError(
            f"Failed to call client_factory '{factory.__name__}' with supported signature"
        ) from exc


def _resolve_client(
    *,
    provider: LLMProvider,
    overrides: Mapping[str, Any],
    context: PipelineContext,
    default_client_factory: Callable[[PipelineContext, Mapping[str, Any]], Any] | None,
) -> Any:
    if overrides.get("client") is not None:
        return overrides["client"]

    factory_path = overrides.get("client_factory")
    if factory_path:
        factory = _import_callable(str(factory_path))
        return _invoke_factory(factory, context, overrides)

    if default_client_factory is not None:
        return default_client_factory(context, overrides)

    return provider.build_client(context=context, overrides=overrides)


def _resolve_model(
    *,
    stage: str,
    provider_name: str,
    provider: LLMProvider,
    overrides: Mapping[str, Any],
    default_model: str | None,
    fallback_model: str | None,
    experiment_name: str,
    context: PipelineContext,
) -> str:
    candidate_keys: list[str] = []
    if stage:
        candidate_keys.append(f"{stage}_model")
    candidate_keys.extend(["model", f"{provider_name}_model", "llm_model", "openai_model"])
    for key in candidate_keys:
        value = overrides.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if default_model:
        return default_model
    if fallback_model:
        return fallback_model
    provider_default = provider.default_model(stage, context=context)
    if provider_default:
        return provider_default
    raise ExperimentExecutionError(
        f"No model configured for experiment '{experiment_name}'. Provide an override or fallback model."
    )


def _merge_request_options(
    *,
    stage: str,
    overrides: Mapping[str, Any],
    provider: LLMProvider,
    context: PipelineContext,
    default_request_options: Mapping[str, Any] | None,
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    provider_defaults = provider.default_request_options(stage, context=context)
    if provider_defaults:
        merged.update(provider_defaults)
    if default_request_options:
        merged.update(default_request_options)
    stage_key = f"{stage}_request_options"
    stage_options = overrides.get(stage_key)
    if isinstance(stage_options, Mapping):
        merged.update(stage_options)
    generic = overrides.get("request_options")
    if isinstance(generic, Mapping):
        merged.update(generic)
    return merged


def _resolve_tools(
    *,
    stage: str,
    overrides: Mapping[str, Any],
    provider: LLMProvider,
    context: PipelineContext,
    default_tools: Sequence[Mapping[str, Any]] | None,
) -> tuple[Mapping[str, Any], ...] | None:
    stage_key = f"{stage}_tools"
    for key in (stage_key, "tools"):
        value = overrides.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            return tuple(value)  # type: ignore[arg-type]
    if default_tools is not None:
        return tuple(default_tools)
    provider_tools = provider.default_tools(stage, context=context)
    if provider_tools is None:
        return None
    return tuple(provider_tools)


def resolve_llm_request(
    strategy: Any,
    context: PipelineContext,
    *,
    stage: str,
    default_model: str | None,
    fallback_model: str | None,
    default_tools: Sequence[Mapping[str, Any]] | None = None,
    default_request_options: Mapping[str, Any] | None = None,
    require_api_key: bool = True,
    default_provider: str | None = None,
    default_client_factory: Callable[[PipelineContext, Mapping[str, Any]], Any] | None = None,
) -> LLMRequestSpec:
    """Resolve runtime inputs for an LLM-backed strategy invocation."""

    experiment_name = getattr(strategy, "_experiment_name", getattr(strategy, "name", "unknown"))
    overrides = context.settings.experiment_config(experiment_name)
    provider_name = str(
        overrides.get("provider")
        or default_provider
        or getattr(context.settings, "llm_default_provider", "openai")
    ).lower()
    provider_impl = get_provider(provider_name)
    if require_api_key:
        provider_impl.ensure_ready(
            context=context,
            overrides=overrides,
            experiment_name=experiment_name,
        )

    client = _resolve_client(
        provider=provider_impl,
        overrides=overrides,
        context=context,
        default_client_factory=default_client_factory,
    )
    model = _resolve_model(
        stage=stage,
        provider_name=provider_name,
        provider=provider_impl,
        overrides=overrides,
        default_model=default_model,
        fallback_model=fallback_model,
        experiment_name=experiment_name,
        context=context,
    )
    request_options = _merge_request_options(
        stage=stage,
        overrides=overrides,
        provider=provider_impl,
        context=context,
        default_request_options=default_request_options,
    )
    tools = _resolve_tools(
        stage=stage,
        overrides=overrides,
        provider=provider_impl,
        context=context,
        default_tools=default_tools,
    )

    strategy_name = getattr(strategy, "name", experiment_name) or experiment_name

    return LLMRequestSpec(
        client=client,
        model=model,
        provider=provider_name,
        provider_impl=provider_impl,
        stage=stage,
        experiment_name=experiment_name,
        strategy_name=str(strategy_name),
        run_id=getattr(context, "run_id", None),
        request_options=request_options,
        tools=tools,
        overrides=overrides,
    )
def hash_payload(payload: Mapping[str, Any] | None) -> str | None:
    if not payload:
        return None
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def iso_timestamp() -> str:
    """Return a consistent ISO-8601 timestamp in UTC."""

    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


__all__ = [
    "LLMRequestSpec",
    "hash_payload",
    "iso_timestamp",
    "resolve_llm_request",
]
