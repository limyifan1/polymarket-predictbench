"""Google Gemini provider hooks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, MutableMapping, Sequence

try:  # pragma: no cover - optional dependency
    import google.generativeai as genai
except ModuleNotFoundError:  # pragma: no cover - fallback when SDK missing
    genai = None  # type: ignore[assignment]

from loguru import logger

from pipelines.experiments.base import ExperimentExecutionError, ExperimentSkip

from .base import LLMProvider, PipelineContext

_JSON_KEYS = {"temperature", "top_p", "top_k", "max_output_tokens"}
_UNSUPPORTED_SCHEMA_KEYS = {"additionalProperties", "minimum", "maximum"}


def _prune_schema(value: Any) -> Any:
    """Return a schema with unsupported keys removed recursively."""

    if isinstance(value, Mapping):
        pruned: dict[str, Any] = {}
        for key, inner in value.items():
            if key in _UNSUPPORTED_SCHEMA_KEYS:
                continue
            pruned[key] = _prune_schema(inner)
        return pruned
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_prune_schema(item) for item in value]
    return value


def _is_search_grounding_error(exc: Exception) -> bool:
    message = str(exc)
    return "Search Grounding is not supported" in message


_DEFAULT_STAGE_MODELS: dict[str, str] = {
    "research": "gemini-2.5-flash",
    "forecast": "gemini-2.5-pro",
}


@dataclass(slots=True)
class _GeminiClient:
    api_keys: tuple[str, ...]
    client_options: Mapping[str, Any] | None = None

    def configure(self, api_key: str) -> None:
        if genai is None:
            raise ExperimentExecutionError(
                "google-generativeai is not installed; install the SDK to use Gemini"
            )
        options = dict(self.client_options or {})
        genai.configure(api_key=api_key, **options)


@dataclass(slots=True)
class GeminiProvider(LLMProvider):
    name: str = "gemini"
    require_api_key: bool = True

    def _resolve_api_keys(
        self,
        *,
        context: PipelineContext,
        overrides: Mapping[str, Any],
    ) -> list[str]:
        keys: list[str] = []

        def add_key(candidate: str | None) -> None:
            if not candidate:
                return
            value = candidate.strip()
            if value:
                keys.append(value)

        override_key = overrides.get("api_key")
        if override_key is not None:
            if not isinstance(override_key, str):
                raise ExperimentExecutionError(
                    "Gemini api_key override must be a string"
                )
            add_key(override_key)

        override_keys = overrides.get("api_keys")
        if override_keys is not None:
            if isinstance(override_keys, str):
                add_key(override_keys)
            elif isinstance(override_keys, Iterable) and not isinstance(
                override_keys, (str, bytes)
            ):
                for entry in override_keys:
                    if not isinstance(entry, str):
                        raise ExperimentExecutionError(
                            "Gemini api_keys override must contain only strings"
                        )
                    add_key(entry)
            else:
                raise ExperimentExecutionError(
                    "Gemini api_keys override must be a sequence of strings"
                )

        add_key(getattr(context.settings, "gemini_api_key", None))
        for entry in getattr(context.settings, "gemini_additional_api_keys", []) or []:
            if not isinstance(entry, str):
                raise ExperimentExecutionError(
                    "Gemini additional API keys must be strings"
                )
            add_key(entry)

        deduped: list[str] = []
        seen: set[str] = set()
        for key in keys:
            if key not in seen:
                seen.add(key)
                deduped.append(key)
        return deduped

    def ensure_ready(
        self,
        *,
        context: PipelineContext,
        overrides: Mapping[str, Any],
        experiment_name: str,
    ) -> None:
        if not self.require_api_key:
            return
        if overrides.get("client"):
            return
        if self._resolve_api_keys(context=context, overrides=overrides):
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
        api_keys = self._resolve_api_keys(context=context, overrides=overrides)
        if not api_keys:
            raise ExperimentExecutionError("GEMINI_API_KEY is not configured")
        client_options = overrides.get("client_options")
        if client_options is not None and not isinstance(client_options, Mapping):
            raise ExperimentExecutionError(
                "Gemini client_options override must be a mapping"
            )
        return _GeminiClient(api_keys=tuple(api_keys), client_options=client_options)

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
        del context
        if stage == "research":
            return ({"google_search_retrieval": {}},)
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
                "response_schema": _prune_schema(schema),
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
                system_instruction = (
                    str(content) if content is not None else system_instruction
                )
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

    def _normalise_tool(self, tool: Mapping[str, Any]) -> Mapping[str, Any]:
        tool_map = dict(tool)
        if "google_search" in tool_map:
            value = tool_map["google_search"]
            if value is None:
                value = {}
            elif not isinstance(value, Mapping):
                raise ExperimentExecutionError(
                    "Gemini google_search config must be a mapping"
                )
            return {"google_search_retrieval": dict(value)}
        if "google_search_retrieval" in tool_map:
            value = tool_map["google_search_retrieval"]
            if value is None:
                value = {}
            elif not isinstance(value, Mapping):
                raise ExperimentExecutionError(
                    "Gemini google_search_retrieval config must be a mapping"
                )
            return {"google_search_retrieval": dict(value)}
        tool_type = tool_map.get("type")
        if tool_type == "google_search":
            config = {key: value for key, value in tool_map.items() if key != "type"}
            return {"google_search_retrieval": config}
        if tool_type == "google_search_retrieval":
            config = {key: value for key, value in tool_map.items() if key != "type"}
            return {"google_search_retrieval": config}
        return tool_map

    def _normalise_tools_input(
        self,
        tools: Any,
    ) -> list[Mapping[str, Any]]:
        if tools is None:
            return []
        if isinstance(tools, Mapping):
            return [self._normalise_tool(tools)]
        if isinstance(tools, Iterable) and not isinstance(tools, (str, bytes)):
            normalised: list[Mapping[str, Any]] = []
            for entry in tools:
                if not isinstance(entry, Mapping):
                    raise ExperimentExecutionError(
                        "Gemini tool entries must be mappings"
                    )
                normalised.append(self._normalise_tool(entry))
            return normalised
        raise ExperimentExecutionError(
            "Gemini tools must be provided as a mapping or sequence"
        )

    def _invoke_with_api_key(
        self,
        *,
        request,
        client: _GeminiClient,
        api_key: str,
        attempt_index: int,
        total_attempts: int,
        system_instruction: str | None,
        contents: Sequence[Mapping[str, Any]],
        generation_config: Mapping[str, Any],
        request_options: Mapping[str, Any],
        tool_payload: Sequence[Mapping[str, Any]],
    ) -> Any:
        client.configure(api_key)
        model = genai.GenerativeModel(
            request.model,
            system_instruction=system_instruction,
        )
        try:
            return model.generate_content(
                contents=contents,
                generation_config=generation_config or None,
                tools=tool_payload or None,
                **request_options,
            )
        except Exception as exc:
            if tool_payload and _is_search_grounding_error(exc):
                logger.warning(
                    "Gemini search grounding unavailable; retrying without tools run={} attempt={}/{}",
                    request.run_id or "n/a",
                    attempt_index + 1,
                    total_attempts,
                )
                return model.generate_content(
                    contents=contents,
                    generation_config=generation_config or None,
                    tools=None,
                    **request_options,
                )
            raise

    def invoke(
        self,
        request,
        *,
        messages: Sequence[Mapping[str, Any]],
        options: Mapping[str, Any] | None,
        tools: Sequence[Mapping[str, Any]] | None,
    ) -> Any:
        if not isinstance(request.client, _GeminiClient):
            raise ExperimentExecutionError("Gemini client is not configured correctly")
        system_instruction, contents = self._build_contents(messages)
        generation_config, request_options = self._split_options(options)
        request_tools = request_options.pop("tools", None)
        tool_payload: list[Mapping[str, Any]] = []
        tool_payload.extend(self._normalise_tools_input(request_tools))
        tool_payload.extend(self._normalise_tools_input(tools))
        api_keys = request.client.api_keys
        if not api_keys:
            raise ExperimentExecutionError("GEMINI_API_KEY is not configured")
        last_error: Exception | None = None
        total_attempts = len(api_keys)
        for attempt_index, api_key in enumerate(api_keys):
            try:
                return self._invoke_with_api_key(
                    request=request,
                    client=request.client,
                    api_key=api_key,
                    attempt_index=attempt_index,
                    total_attempts=total_attempts,
                    system_instruction=system_instruction,
                    contents=contents,
                    generation_config=generation_config,
                    request_options=request_options,
                    tool_payload=tool_payload,
                )
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Gemini request failed (attempt {}/{}), run={}, error={}",
                    attempt_index + 1,
                    total_attempts,
                    request.run_id or "n/a",
                    exc,
                )
        if last_error is None:
            raise ExperimentExecutionError(
                "Gemini request failed; no API keys available"
            )
        raise ExperimentExecutionError(
            "Gemini request failed after exhausting all configured API keys"
        ) from last_error

    def extract_json(self, response: Any) -> Mapping[str, Any]:
        text_candidate: str | None = getattr(response, "text", None)
        if text_candidate and text_candidate.strip():
            try:
                return json.loads(text_candidate)
            except json.JSONDecodeError as exc:  # pragma: no cover - defensive
                raise ExperimentExecutionError(
                    "Gemini response did not contain valid JSON text"
                ) from exc
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
                        raise ExperimentExecutionError(
                            "Gemini response part was not valid JSON"
                        ) from exc
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
            for key in (
                "prompt_token_count",
                "candidates_token_count",
                "total_token_count",
            )
            if hasattr(metadata, key)
        }


__all__ = ["GeminiProvider"]
