"""OpenAI provider hooks."""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from openai import OpenAI

from app.core.config import Settings
from app.services.openai_client import get_openai_client
from pipelines.experiments.base import ExperimentExecutionError, ExperimentSkip
from .base import LLMProvider, PipelineContext

_DEFAULT_STAGE_MODELS: dict[str, str] = {
    "research": "gpt-4.1-mini",
    "forecast": "gpt-5",
}


def _override_openai_client(settings: Settings, overrides: Mapping[str, Any]) -> OpenAI:
    api_key = overrides.get("api_key") or settings.openai_api_key
    if not api_key:
        raise ExperimentExecutionError("OPENAI_API_KEY is not configured")
    kwargs: dict[str, Any] = {"api_key": api_key}
    base_url = overrides.get("api_base") or settings.openai_api_base
    if base_url:
        kwargs["base_url"] = str(base_url)
    organization = overrides.get("organization") or settings.openai_org_id
    if organization:
        kwargs["organization"] = organization
    project = overrides.get("project") or settings.openai_project_id
    if project:
        kwargs["project"] = project
    return OpenAI(**kwargs)


@dataclass(slots=True)
class OpenAIProvider(LLMProvider):
    name: str = "openai"
    require_api_key: bool = True

    def ensure_ready(
        self,
        *,
        context: PipelineContext,
        overrides: Mapping[str, Any],
        experiment_name: str,
    ) -> None:
        if not self.require_api_key:
            return
        if overrides.get("skip_openai_api_key_check"):
            return
        if overrides.get("api_key") or overrides.get("client"):
            return
        if context.settings.openai_api_key:
            return
        raise ExperimentSkip(
            f"OPENAI_API_KEY is not configured; skipping experiment '{experiment_name}'",
        )

    def build_client(
        self,
        *,
        context: PipelineContext,
        overrides: Mapping[str, Any],
    ) -> Any:
        if overrides.get("api_key") or overrides.get("api_base"):
            return _override_openai_client(context.settings, overrides)
        return get_openai_client(context.settings)

    def default_model(self, stage: str, *, context: PipelineContext) -> str | None:
        del context
        return _DEFAULT_STAGE_MODELS.get(stage, _DEFAULT_STAGE_MODELS["research"])

    def default_request_options(
        self,
        stage: str,
        *,
        context: PipelineContext,
    ) -> Mapping[str, Any] | None:
        return None

    def default_tools(
        self,
        stage: str,
        *,
        context: PipelineContext,
    ) -> Sequence[Mapping[str, Any]] | None:
        if stage == "research":
            return ({"type": "web_search"},)
        return None

    def json_mode_kwargs(
        self,
        client: Any,
        *,
        schema_name: str,
        schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        structured = {
            "type": "json_schema",
            "name": schema_name,
            "schema": schema,
        }
        responses_cls = type(getattr(client, "responses"))
        create_signature = inspect.signature(responses_cls.create)
        if "text" in create_signature.parameters:
            return {"text": {"format": structured}}
        return {"response_format": structured}

    def invoke(
        self,
        request,
        *,
        messages: Sequence[Mapping[str, Any]],
        options: Mapping[str, Any] | None,
        tools: Sequence[Mapping[str, Any]] | None,
    ) -> Any:
        payload: dict[str, Any] = {
            "model": request.model,
            "input": list(messages),
        }
        if options:
            payload.update(dict(options))
        if tools is not None:
            payload["tools"] = [dict(tool) for tool in tools]
        return request.client.responses.create(**payload)

    def extract_json(self, response: Any) -> Mapping[str, Any]:
        text_candidate: str | None = None
        output_text = getattr(response, "output_text", None)
        if isinstance(output_text, str) and output_text.strip():
            text_candidate = output_text
        if text_candidate is None:
            dump: Mapping[str, Any]
            if hasattr(response, "model_dump"):
                dump = response.model_dump()
            else:
                dump = dict(response)  # type: ignore[arg-type]
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

    def usage_dict(self, response: Any) -> Mapping[str, Any] | None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return None
        if hasattr(usage, "model_dump"):
            return usage.model_dump()
        try:
            return dict(usage)  # type: ignore[arg-type]
        except Exception:  # noqa: BLE001
            return {"raw": str(usage)}


__all__ = ["OpenAIProvider"]
