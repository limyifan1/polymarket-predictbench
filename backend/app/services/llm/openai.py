"""OpenAI provider hooks."""

from __future__ import annotations

import inspect
import json
import random
import time
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from http.client import IncompleteRead

import httpx
from openai import APIError, APIStatusError, APITimeoutError, OpenAI
from loguru import logger

from app.core.config import Settings
from app.services.openai_client import get_openai_client
from pipelines.experiments.base import ExperimentExecutionError, ExperimentSkip
from .base import LLMProvider, PipelineContext

_DEFAULT_STAGE_MODELS: dict[str, str] = {
    "research": "gpt-4.1-mini",
    "forecast": "gpt-5",
}

_BACKGROUND_DEFAULT_POLL_INTERVAL_SECONDS = 30.0
_BACKGROUND_DEFAULT_MAX_WAIT_SECONDS = 3600.0  # 1 hour
_STREAM_MAX_ATTEMPTS = 3
_TOTAL_MAX_ATTEMPTS = 5
_RETRY_BASE_SLEEP_SECONDS = 1.5
_RETRY_MAX_SLEEP_SECONDS = 10.0
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _extract_request_id(exc: Exception) -> str | None:
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            request_id = response.headers.get("x-request-id")
            if isinstance(request_id, str) and request_id:
                return request_id
        except Exception:  # noqa: BLE001 - defensive
            pass
    request_id = getattr(exc, "request_id", None)
    if isinstance(request_id, str) and request_id:
        return request_id
    return None


def _status_code_from_exception(exc: Exception) -> int | None:
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    response = getattr(exc, "response", None)
    if response is not None:
        status = getattr(response, "status_code", None)
        if isinstance(status, int):
            return status
    return None


def _should_retry_exception(exc: Exception) -> bool:
    if isinstance(exc, (httpx.RemoteProtocolError, IncompleteRead, APITimeoutError)):
        return True
    if isinstance(exc, APIStatusError):
        return exc.status_code in _RETRYABLE_STATUS_CODES
    if isinstance(exc, APIError):
        status = _status_code_from_exception(exc)
        if status in _RETRYABLE_STATUS_CODES:
            return True
        error_type = getattr(exc, "type", None)
        if isinstance(error_type, str) and error_type.lower() in {
            "api_error",
            "internal_server_error",
            "rate_limit_error",
            "server_error",
        }:
            return True
        message = str(exc)
        if isinstance(message, str) and "retry your request" in message.lower():
            return True
    return False


def _retry_sleep_seconds(attempt: int) -> float:
    backoff = _RETRY_BASE_SLEEP_SECONDS * (2 ** max(attempt - 1, 0))
    backoff = min(backoff, _RETRY_MAX_SLEEP_SECONDS)
    jitter = random.uniform(0.0, 0.75)
    return backoff + jitter


def _exception_summary(exc: Exception, *, request_id: str | None = None) -> str:
    parts = [exc.__class__.__name__]
    status = _status_code_from_exception(exc)
    if isinstance(status, int):
        parts.append(f"status={status}")
    if request_id:
        parts.append(f"request_id={request_id}")
    message = str(exc)
    if message:
        parts.append(message)
    return ": ".join([parts[0], " ".join(parts[1:])]) if len(parts) > 1 else parts[0]


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


def _has_type(schema: Mapping[str, Any], expected: str) -> bool:
    """Return True when a JSON schema declares the expected type."""

    schema_type = schema.get("type")
    if isinstance(schema_type, str):
        return schema_type == expected
    if isinstance(schema_type, Iterable):
        return expected in schema_type  # type: ignore[arg-type]
    return False


def _validate_required_fields(
    schema_name: str,
    schema: Mapping[str, Any],
    *,
    parent_path: str = "",
) -> None:
    """Ensure OpenAI response schemas require every declared property.

    OpenAI rejects schemas where an object lists properties that are missing from
    the ``required`` array at the same nesting level. Validating locally provides
    an actionable error before the request reaches the API.
    """

    if _has_type(schema, "object"):
        properties = schema.get("properties")
        if isinstance(properties, Mapping) and properties:
            required = schema.get("required")
            if isinstance(required, Iterable) and not isinstance(
                required, (str, bytes)
            ):
                required_set = set(required)
            else:
                required_set = set()
            missing = [key for key in properties if key not in required_set]
            if missing:
                location = parent_path or "<root>"
                fields = ", ".join(sorted(missing))
                raise ExperimentExecutionError(
                    f"OpenAI JSON schema '{schema_name}' must mark properties {fields} as required at {location}"
                )
            for key, subschema in properties.items():
                if isinstance(subschema, Mapping):
                    next_path = f"{parent_path}.{key}" if parent_path else key
                    _validate_required_fields(
                        schema_name, subschema, parent_path=next_path
                    )
    if _has_type(schema, "array"):
        items = schema.get("items")
        if isinstance(items, Mapping):
            next_path = f"{parent_path}[]" if parent_path else "[]"
            _validate_required_fields(schema_name, items, parent_path=next_path)


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

    @staticmethod
    def _parse_positive_float(value: Any, default: float) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        if parsed <= 0:
            return default
        return parsed

    def _background_config(self, request) -> tuple[float, float]:
        overrides = getattr(request, "overrides", {}) or {}
        poll_interval = self._parse_positive_float(
            overrides.get("background_poll_interval_seconds"),
            _BACKGROUND_DEFAULT_POLL_INTERVAL_SECONDS,
        )
        max_wait = self._parse_positive_float(
            overrides.get("background_max_wait_seconds"),
            _BACKGROUND_DEFAULT_MAX_WAIT_SECONDS,
        )
        if max_wait < poll_interval:
            max_wait = max(poll_interval * 3, _BACKGROUND_DEFAULT_MAX_WAIT_SECONDS)
        return poll_interval, max_wait

    def _invoke_background(
        self,
        *,
        request,
        payload: Mapping[str, Any],
        record_response_id,
        response_id_holder: Mapping[str, str | None],
    ) -> Any:
        poll_interval, max_wait = self._background_config(request)
        create_kwargs = dict(payload)
        create_kwargs.pop("stream", None)

        try:
            response = request.client.responses.create(**create_kwargs)
        except Exception:  # noqa: BLE001
            logger.exception(
                "Failed to submit OpenAI background response experiment={} strategy={} stage={}",
                request.experiment_name,
                request.strategy_name,
                request.stage,
            )
            raise

        record_response_id(response)
        response_id = response_id_holder.get("id")
        status = getattr(response, "status", None)
        logger.info(
            "OpenAI background response submitted response_id={} experiment={} strategy={} stage={} status={}",
            response_id,
            request.experiment_name,
            request.strategy_name,
            request.stage,
            status,
        )

        if not isinstance(response_id, str):
            raise ExperimentExecutionError(
                "OpenAI background response did not include a response_id"
            )

        if status == "completed":
            return response

        start_time = time.monotonic()
        last_status = status

        while True:
            elapsed = time.monotonic() - start_time
            if elapsed >= max_wait:
                raise ExperimentExecutionError(
                    f"OpenAI background response {response_id} exceeded {max_wait:.1f}s (last status: {status})"
                )

            time.sleep(poll_interval)

            try:
                response = request.client.responses.retrieve(response_id)
            except APITimeoutError:
                logger.warning(
                    "OpenAI background retrieve timed out response_id={} experiment={} strategy={} stage={}",
                    response_id,
                    request.experiment_name,
                    request.strategy_name,
                    request.stage,
                )
                continue
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Failed to retrieve OpenAI background response response_id={} experiment={} strategy={} stage={}",
                    response_id,
                    request.experiment_name,
                    request.strategy_name,
                    request.stage,
                )
                raise

            record_response_id(response)
            status = getattr(response, "status", None)

            if status != last_status:
                logger.info(
                    "OpenAI background response update response_id={} status={} experiment={} strategy={} stage={}",
                    response_id,
                    status,
                    request.experiment_name,
                    request.strategy_name,
                    request.stage,
                )
                last_status = status

            if status == "completed":
                return response

            if status in {"failed", "cancelled"}:
                error_obj = getattr(response, "error", None)
                detail = None
                if error_obj is not None:
                    detail = getattr(error_obj, "message", None) or str(error_obj)
                raise ExperimentExecutionError(
                    f"OpenAI background response {response_id} {status}: {detail or 'no error details provided'}"
                )

            if status == "incomplete":
                incomplete = getattr(response, "incomplete_details", None)
                detail = None
                if incomplete is not None:
                    detail = getattr(incomplete, "reason", None) or str(incomplete)
                raise ExperimentExecutionError(
                    f"OpenAI background response {response_id} incomplete: {detail or 'no details provided'}"
                )

            if status in {"queued", "in_progress"}:
                continue

            if status is None:
                logger.debug(
                    "OpenAI background response missing status response_id={} experiment={} strategy={} stage={}",
                    response_id,
                    request.experiment_name,
                    request.strategy_name,
                    request.stage,
                )
                continue

            logger.warning(
                "OpenAI background response response_id={} unexpected status={} experiment={} strategy={} stage={}",
                response_id,
                status,
                request.experiment_name,
                request.strategy_name,
                request.stage,
            )

    def json_mode_kwargs(
        self,
        client: Any,
        *,
        schema_name: str,
        schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        _validate_required_fields(schema_name, schema)
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

    def _invoke_stream_once(
        self,
        request,
        *,
        payload: Mapping[str, Any],
        response_id_holder: dict[str, str | None],
    ) -> tuple[Any, str | None]:

        def _record_response_id(event: Mapping[str, Any] | Any) -> None:
            response_obj = getattr(event, "response", None)
            response_id = getattr(response_obj, "id", None)
            if not isinstance(response_id, str):
                response_id = getattr(event, "id", None)
            if isinstance(response_id, str):
                response_id_holder["id"] = response_id

        stream_kwargs = dict(payload)

        try:
            with request.client.responses.stream(
                **stream_kwargs,
            ) as stream:
                for event in stream:
                    _record_response_id(event)
                final_response = stream.get_final_response()
                _record_response_id(final_response)
                return final_response, response_id_holder.get("id")
        except APITimeoutError:
            response_id = response_id_holder.get("id")
            if response_id:
                try:
                    logger.warning(
                        "OpenAI stream timed out; retrieving cached response response_id={} experiment={} strategy={} stage={}",
                        response_id,
                        request.experiment_name,
                        request.strategy_name,
                        request.stage,
                    )
                    recovered = request.client.responses.retrieve(response_id)
                    _record_response_id(recovered)
                    return recovered, response_id_holder.get("id")
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "Failed to recover OpenAI response after timeout response_id={} experiment={} strategy={} stage={}",
                        response_id,
                        request.experiment_name,
                        request.strategy_name,
                        request.stage,
                    )
            raise

    def _invoke_nonstream_once(
        self,
        request,
        *,
        payload: Mapping[str, Any],
    ) -> tuple[Any, str | None]:
        result = request.client.responses.create(**dict(payload))
        response_id = getattr(result, "id", None)
        if not isinstance(response_id, str):
            response_obj = getattr(result, "response", None)
            response_id = getattr(response_obj, "id", None)
        if not isinstance(response_id, str):
            response_id = None
        return result, response_id

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

        metadata = dict(payload.get("metadata") or {})
        if request.run_id:
            metadata.setdefault("pipeline_run_id", request.run_id)
        metadata.setdefault("experiment", request.experiment_name)
        metadata.setdefault("strategy", request.strategy_name)
        metadata.setdefault("stage", request.stage)
        payload["metadata"] = {k: v for k, v in metadata.items() if v}

        background_mode = bool(payload.get("background"))
        if background_mode:
            response_id_holder: dict[str, str | None] = {"id": None}

            def _record_response_id(event: Mapping[str, Any] | Any) -> None:
                response_obj = getattr(event, "response", None)
                response_id = getattr(response_obj, "id", None)
                if not isinstance(response_id, str):
                    response_id = getattr(event, "id", None)
                if isinstance(response_id, str):
                    response_id_holder["id"] = response_id

            try:
                return self._invoke_background(
                    request=request,
                    payload=payload,
                    record_response_id=_record_response_id,
                    response_id_holder=response_id_holder,
                )
            except Exception as exc:  # noqa: BLE001
                request_id = response_id_holder.get("id") or _extract_request_id(exc)
                summary = _exception_summary(exc, request_id=request_id)
                raise ExperimentExecutionError(summary) from exc

        total_attempts = max(_TOTAL_MAX_ATTEMPTS, 1)
        attempt = 0
        stream_attempts = 0
        use_stream = True
        last_exc: Exception | None = None
        last_request_id: str | None = None

        while attempt < total_attempts:
            attempt += 1
            transport = "stream" if use_stream else "nonstream"
            response_id_holder: dict[str, str | None] = {"id": None}

            try:
                if use_stream:
                    response, request_id = self._invoke_stream_once(
                        request,
                        payload=payload,
                        response_id_holder=response_id_holder,
                    )
                else:
                    response, request_id = self._invoke_nonstream_once(
                        request,
                        payload=payload,
                    )
                return response
            except Exception as exc:  # noqa: BLE001
                request_id = response_id_holder.get("id") or _extract_request_id(exc)
                retryable = _should_retry_exception(exc) and attempt < total_attempts
                diagnostics: dict[str, Any] = {
                    "error_type": exc.__class__.__name__,
                    "status": getattr(exc, "status_code", None),
                    "request_id": request_id,
                    "attempt": attempt,
                    "transport": transport,
                }
                logger.warning(
                    "OpenAI request failed run={} experiment={} strategy={} stage={} diagnostics={} retryable={}",
                    request.run_id or "n/a",
                    request.experiment_name,
                    request.strategy_name,
                    request.stage,
                    diagnostics,
                    retryable,
                )

                if not retryable:
                    summary = _exception_summary(exc, request_id=request_id)
                    raise ExperimentExecutionError(summary) from exc

                last_exc = exc
                last_request_id = request_id

                if use_stream:
                    stream_attempts += 1
                    if stream_attempts >= _STREAM_MAX_ATTEMPTS:
                        use_stream = False
                        logger.warning(
                            "OpenAI request switching to non-stream mode run={} experiment={} strategy={} stage={} after {} stream attempts",
                            request.run_id or "n/a",
                            request.experiment_name,
                            request.strategy_name,
                            request.stage,
                            stream_attempts,
                        )
                        continue

                sleep_seconds = _retry_sleep_seconds(attempt)
                time.sleep(sleep_seconds)

        if last_exc is not None:
            summary = _exception_summary(last_exc, request_id=last_request_id)
            raise ExperimentExecutionError(summary) from last_exc
        raise ExperimentExecutionError("OpenAI provider failed without raising an exception")

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
            raise ExperimentExecutionError(
                "LLM response did not include a JSON payload"
            )
        try:
            return json.loads(text_candidate)
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive
            raise ExperimentExecutionError(
                "Failed to decode JSON payload from LLM response"
            ) from exc

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
