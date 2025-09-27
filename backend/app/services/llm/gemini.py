"""Google Gemini provider hooks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, MutableMapping, Sequence

import google.generativeai as genai

from pipelines.experiments.base import ExperimentExecutionError, ExperimentSkip

from .base import LLMProvider, PipelineContext

_JSON_KEYS = {"temperature", "top_p", "top_k", "max_output_tokens"}


@dataclass(slots=True)
class _GeminiClient:
    api_key: str
    client_options: Mapping[str, Any] | None = None

    def configure(self) -> None:
        options = dict(self.client_options or {})
        genai.configure(api_key=self.api_key, **options)


@dataclass(slots=True)
class GeminiProvider(LLMProvider):
    name: str = "gemini"
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
        if overrides.get("client") or overrides.get("api_key"):
            return
        if context.settings.gemini_api_key:
            return
        raise ExperimentSkip(
            f"GEMINI_API_KEY is not configured; skipping experiment '{experiment_name}'",
        )

    def build_client(
        self,
        *,
        context: PipelineContext,
        overrides: Mapping[str, Any],
    ) -> Any:
        api_key = overrides.get("api_key") or context.settings.gemini_api_key
        if not api_key:
            raise ExperimentExecutionError("GEMINI_API_KEY is not configured")
        client_options = overrides.get("client_options")
        if client_options is not None and not isinstance(client_options, Mapping):
            raise ExperimentExecutionError("Gemini client_options override must be a mapping")
        return _GeminiClient(api_key=api_key, client_options=client_options)

    def default_model(self, stage: str, *, context: PipelineContext) -> str | None:
        if stage == "forecast":
            return context.settings.gemini_forecast_model
        return context.settings.gemini_research_model

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
        return None

    def json_mode_kwargs(
        self,
        client: Any,
        *,
        schema_name: str,
        schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        return {
            "generation_config": {
                "response_mime_type": "application/json",
                "response_schema": schema,
            }
        }

    def _build_contents(
        self,
        messages: Sequence[Mapping[str, Any]],
    ) -> tuple[str | None, list[MutableMapping[str, Any]]]:
        system_instruction: str | None = None
        contents: list[MutableMapping[str, Any]] = []
        for message in messages:
            role = message.get("role")
            content = message.get("content")
            if role == "system":
                system_instruction = str(content) if content is not None else system_instruction
                continue
            part_text = str(content) if content is not None else ""
            contents.append({"role": role or "user", "parts": [{"text": part_text}]})
        return system_instruction, contents

    def _split_options(
        self,
        options: Mapping[str, Any] | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if not options:
            return {}, {}
        generation_config: dict[str, Any] = {}
        request_options: dict[str, Any] = {}
        for key, value in options.items():
            if key == "generation_config" and isinstance(value, Mapping):
                generation_config.update(value)
            elif key in _JSON_KEYS:
                generation_config[key] = value
            else:
                request_options[key] = value
        return generation_config, request_options

    def invoke(
        self,
        request,
        *,
        messages: Sequence[Mapping[str, Any]],
        options: Mapping[str, Any] | None,
        tools: Sequence[Mapping[str, Any]] | None,
    ) -> Any:
        if tools:
            raise ExperimentExecutionError(
                "Gemini provider does not currently support OpenAI-style tool payloads; override tools to None"
            )
        if not isinstance(request.client, _GeminiClient):
            raise ExperimentExecutionError("Gemini client is not configured correctly")
        request.client.configure()
        system_instruction, contents = self._build_contents(messages)
        generation_config, request_options = self._split_options(options)
        model = genai.GenerativeModel(
            request.model,
            system_instruction=system_instruction,
        )
        response = model.generate_content(
            contents=contents,
            generation_config=generation_config or None,
            **request_options,
        )
        return response

    def extract_json(self, response: Any) -> Mapping[str, Any]:
        text_candidate: str | None = getattr(response, "text", None)
        if text_candidate and text_candidate.strip():
            try:
                return json.loads(text_candidate)
            except json.JSONDecodeError as exc:  # pragma: no cover - defensive
                raise ExperimentExecutionError("Gemini response did not contain valid JSON text") from exc
        candidates = getattr(response, "candidates", None)
        if not candidates:
            raise ExperimentExecutionError("Gemini response missing candidates")
        for candidate in candidates:
            parts = None
            if isinstance(candidate, Mapping):
                parts = candidate.get("content") or candidate.get("parts")
            if parts is None:
                parts = getattr(candidate, "content", None)
            if parts is None:
                parts = getattr(candidate, "parts", None)
            if not parts:
                continue
            part_iterable = getattr(parts, "parts", parts)
            for part in part_iterable:
                text = None
                if isinstance(part, Mapping):
                    text = part.get("text")
                if text is None:
                    text = getattr(part, "text", None)
                if isinstance(text, str) and text.strip():
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError as exc:  # pragma: no cover
                        raise ExperimentExecutionError("Gemini response part was not valid JSON") from exc
        raise ExperimentExecutionError("Gemini response did not include a JSON payload")

    def usage_dict(self, response: Any) -> Mapping[str, Any] | None:
        metadata = getattr(response, "usage_metadata", None)
        if metadata is None:
            return None
        if isinstance(metadata, Mapping):
            return dict(metadata)
        dump = getattr(metadata, "to_dict", None)
        if callable(dump):
            return dump()
        return {
            key: getattr(metadata, key)
            for key in ("prompt_token_count", "candidates_token_count", "total_token_count")
            if hasattr(metadata, key)
        }


__all__ = ["GeminiProvider"]
