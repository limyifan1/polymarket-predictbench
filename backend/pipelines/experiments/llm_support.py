"""Reusable helpers for LLM-backed experiment strategies."""

from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import dataclass, field
from datetime import datetime
from importlib import import_module
from typing import Any, Callable, Mapping, Sequence

from app.core.config import Settings
from app.services.openai_client import get_openai_client

from ..context import PipelineContext
from .base import ExperimentExecutionError, ExperimentSkip


@dataclass(slots=True)
class LLMRequestSpec:
    """Resolved runtime configuration for a single LLM request."""

    client: Any
    model: str
    provider: str
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


def _ensure_provider_ready(
    *,
    settings: Settings,
    overrides: Mapping[str, Any],
    provider: str,
    require_api_key: bool,
    experiment_name: str,
) -> None:
    if not require_api_key:
        return
    if provider != "openai":
        return
    if overrides.get("skip_openai_api_key_check") or overrides.get("api_key"):
        return
    if not settings.openai_api_key:
        raise ExperimentSkip(
            f"OPENAI_API_KEY is not configured; skipping experiment '{experiment_name}'"
        )


def _resolve_client(
    *,
    provider: str,
    overrides: Mapping[str, Any],
    context: PipelineContext,
    experiment_name: str,
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

    if provider != "openai":
        raise ExperimentExecutionError(
            f"Experiment '{experiment_name}' specifies provider '{provider}' but no client_factory override"
        )

    return get_openai_client(context.settings)


def _resolve_model(
    *,
    stage: str,
    provider: str,
    overrides: Mapping[str, Any],
    default_model: str | None,
    fallback_model: str | None,
    experiment_name: str,
) -> str:
    candidate_keys: list[str] = []
    if stage:
        candidate_keys.append(f"{stage}_model")
    candidate_keys.extend(["model", f"{provider}_model", "llm_model", "openai_model"])
    for key in candidate_keys:
        value = overrides.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if default_model:
        return default_model
    if fallback_model:
        return fallback_model
    raise ExperimentExecutionError(
        f"No model configured for experiment '{experiment_name}'. Provide an override or fallback model."
    )


def _merge_request_options(
    *,
    stage: str,
    overrides: Mapping[str, Any],
    default_request_options: Mapping[str, Any] | None,
) -> dict[str, Any]:
    merged: dict[str, Any] = dict(default_request_options or {})
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
    default_tools: Sequence[Mapping[str, Any]] | None,
) -> tuple[Mapping[str, Any], ...] | None:
    stage_key = f"{stage}_tools"
    for key in (stage_key, "tools"):
        value = overrides.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            return tuple(value)  # type: ignore[arg-type]
    if default_tools is None:
        return None
    return tuple(default_tools)


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
    default_provider: str = "openai",
    default_client_factory: Callable[[PipelineContext, Mapping[str, Any]], Any] | None = None,
) -> LLMRequestSpec:
    """Resolve runtime inputs for an LLM-backed strategy invocation."""

    experiment_name = getattr(strategy, "_experiment_name", getattr(strategy, "name", "unknown"))
    overrides = context.settings.experiment_config(experiment_name)
    provider = str(overrides.get("provider", default_provider)).lower()

    _ensure_provider_ready(
        settings=context.settings,
        overrides=overrides,
        provider=provider,
        require_api_key=require_api_key,
        experiment_name=experiment_name,
    )

    client = _resolve_client(
        provider=provider,
        overrides=overrides,
        context=context,
        experiment_name=experiment_name,
        default_client_factory=default_client_factory,
    )
    model = _resolve_model(
        stage=stage,
        provider=provider,
        overrides=overrides,
        default_model=default_model,
        fallback_model=fallback_model,
        experiment_name=experiment_name,
    )
    request_options = _merge_request_options(
        stage=stage,
        overrides=overrides,
        default_request_options=default_request_options,
    )
    tools = _resolve_tools(stage=stage, overrides=overrides, default_tools=default_tools)

    return LLMRequestSpec(
        client=client,
        model=model,
        provider=provider,
        request_options=request_options,
        tools=tools,
        overrides=overrides,
    )


def supports_text_config(responses_cls: type[Any]) -> bool:
    signature = inspect.signature(responses_cls.create)
    return "text" in signature.parameters


def json_mode_kwargs(
    client: Any,
    *,
    schema_name: str,
    schema: dict[str, Any],
) -> dict[str, Any]:
    structured = {
        "type": "json_schema",
        "name": schema_name,
        "schema": schema,
    }
    responses_cls = type(getattr(client, "responses"))
    if supports_text_config(responses_cls):
        return {"text": {"format": structured}}
    return {"response_format": structured}


def extract_json(response) -> dict[str, Any]:
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
        raise ExperimentExecutionError("LLM response did not include a JSON payload")
    try:
        return json.loads(text_candidate)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise ExperimentExecutionError("Failed to decode JSON payload from LLM response") from exc


def usage_dict(response) -> dict[str, Any] | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    try:
        return dict(usage)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        return {"raw": str(usage)}


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
    "extract_json",
    "hash_payload",
    "iso_timestamp",
    "json_mode_kwargs",
    "resolve_llm_request",
    "supports_text_config",
    "usage_dict",
]
