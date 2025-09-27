"""Provider contracts for LLM integrations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping, Protocol, Sequence

if TYPE_CHECKING:
    from pipelines.context import PipelineContext
    from pipelines.experiments.llm_support import LLMRequestSpec
else:  # pragma: no cover - runtime import cycle guard
    PipelineContext = Any  # type: ignore[assignment]
    LLMRequestSpec = Any  # type: ignore[assignment]


class LLMProvider(Protocol):
    """Interface implemented by provider adapters."""

    name: str
    require_api_key: bool

    def ensure_ready(
        self,
        *,
        context: PipelineContext,
        overrides: Mapping[str, Any],
        experiment_name: str,
    ) -> None:
        """Validate credentials or raise :class:`ExperimentSkip`."""

    def build_client(
        self,
        *,
        context: PipelineContext,
        overrides: Mapping[str, Any],
    ) -> Any:
        """Return a provider client for the resolved settings."""

    def default_model(self, stage: str, *, context: PipelineContext) -> str | None:
        """Return provider fallback model for the supplied stage."""

    def default_request_options(
        self,
        stage: str,
        *,
        context: PipelineContext,
    ) -> Mapping[str, Any] | None:
        """Return provider-specific default request options."""

    def default_tools(
        self,
        stage: str,
        *,
        context: PipelineContext,
    ) -> Sequence[Mapping[str, Any]] | None:
        """Return provider-default tool declarations for the stage."""

    def json_mode_kwargs(
        self,
        client: Any,
        *,
        schema_name: str,
        schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """Return structured-output kwargs for the provider."""

    def invoke(
        self,
        request: LLMRequestSpec,
        *,
        messages: Sequence[Mapping[str, Any]],
        options: Mapping[str, Any] | None,
        tools: Sequence[Mapping[str, Any]] | None,
    ) -> Any:
        """Execute the model call and return the raw response."""

    def extract_json(self, response: Any) -> Mapping[str, Any]:
        """Extract structured payload from provider response."""

    def usage_dict(self, response: Any) -> Mapping[str, Any] | None:
        """Return usage metadata from provider response."""


__all__ = ["LLMProvider"]
