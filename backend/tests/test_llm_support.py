from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
import sys

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from app.services.llm.gemini import (
    GeminiProvider,
    _DEFAULT_SEARCH_TOOL_KEY,
    _SUPPORTS_GOOGLE_SEARCH_TOOL,
)
from pipelines.context import PipelineContext
from pipelines.experiments.llm_support import resolve_llm_request


@dataclass
class DummyStrategy:
    name: str = "dummy"


class DummySettings:
    def __init__(self, overrides: dict[str, dict[str, object]] | None = None):
        self.llm_default_provider = "openai"
        self.openai_api_key = "sk-openai"
        self.gemini_api_key = "sk-gemini"
        self._overrides = overrides or {}

    def experiment_config(self, name: str) -> dict[str, object]:
        return dict(self._overrides.get(name, {}))


def build_context(
    overrides: dict[str, dict[str, object]] | None = None,
) -> PipelineContext:
    settings = DummySettings(overrides)
    return PipelineContext(
        run_id="test",
        run_date=date.today(),
        target_date=date.today(),
        window_days=0,
        settings=settings,  # type: ignore[arg-type]
        db_session=None,  # type: ignore[arg-type]
        dry_run=True,
    )


def test_resolve_llm_request_selects_gemini_provider() -> None:
    context = build_context({"dummy": {"provider": "gemini"}})
    runtime = resolve_llm_request(
        DummyStrategy(),
        context,
        stage="research",
        default_model=None,
        fallback_model=None,
        default_tools=None,
        default_request_options=None,
    )
    assert runtime.provider == "gemini"
    assert runtime.model == "gemini-2.5-flash"
    assert isinstance(runtime.provider_impl, GeminiProvider)


class _GeminiResponse:
    def __init__(self, text: str | None = None):
        self.text = text
        self.candidates = []
        self.usage_metadata = {"prompt_token_count": 10, "total_token_count": 20}


@pytest.mark.parametrize("payload", ['{"value": 1}', '\n  {"value": 1}\n'])
def test_gemini_extract_json_parses_payload(payload: str) -> None:
    provider = GeminiProvider()
    response = _GeminiResponse(text=payload)
    parsed = provider.extract_json(response)
    assert parsed == {"value": 1}
    usage = provider.usage_dict(response)
    assert usage["prompt_token_count"] == 10


def test_gemini_default_tools_include_search_tool() -> None:
    context = build_context({"dummy": {"provider": "gemini"}})
    runtime = resolve_llm_request(
        DummyStrategy(),
        context,
        stage="research",
        default_model=None,
        fallback_model=None,
        default_tools=None,
        default_request_options=None,
    )
    assert runtime.tools is not None
    assert {_DEFAULT_SEARCH_TOOL_KEY: {}} in runtime.tools


def test_gemini_search_tool_remaps_to_legacy_for_1_x_models() -> None:
    provider = GeminiProvider()
    remapped = provider._remap_search_tools_for_model(  # type: ignore[attr-defined]
        model="gemini-2.5-flash",
        tools=[{"google_search": {}}],
    )
    assert remapped == [{"google_search_retrieval": {}}]


def test_gemini_search_tool_remaps_legacy_payload_for_2_x_models() -> None:
    provider = GeminiProvider()
    remapped = provider._remap_search_tools_for_model(  # type: ignore[attr-defined]
        model="gemini-2.5-pro",
        tools=[{"google_search_retrieval": {}}],
    )
    expected_key = (
        "google_search" if _SUPPORTS_GOOGLE_SEARCH_TOOL else "google_search_retrieval"
    )
    assert remapped == [{expected_key: {}}]
